"""Notifications: pop-ups for things that happen while a person is in the app (needs the test
database). Each producer (a report finishing, an alert firing, a person added to a space) is run for
real; the mail server and the AI service are scripted."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_alerts import always_configured, orders_metric
from test_chat import (
    REVENUE_SQL,
    FakeLLM,
    ask,
    conversation,
    events,
    final,
    small_space,
    sql_plan,
    use,
)
from test_dashboards import answered, pin
from test_knowledge import POLICY
from test_spaces import Person, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.llm.errors import LLMUnavailableError
from app.services import mail_config, mailer
from app.services import notifications as service

pytestmark = pytest.mark.db


def waiting(who: Person) -> list[dict[str, Any]]:
    return who.get("/notifications/pending").json()


def waiting_for(
    who: Person, prefix: str, count: int = 1, seconds: float = 20
) -> list[dict[str, Any]]:
    """Notifications whose kind starts with `prefix`, once `count` of them have arrived: the thing
    they announce is saved a moment before the announcement is written."""
    found: list[dict[str, Any]] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found += [n for n in waiting(who) if n["kind"].startswith(prefix)]
        if len(found) >= count:
            break
        time.sleep(0.2)
    return found


def kinds(items: list[dict[str, Any]]) -> list[str]:
    return [n["kind"] for n in items]


def test_each_notification_is_handed_over_once_and_only_to_its_person(
    api: TestClient, sql: Any
) -> None:
    boss = admin(api)
    other = person(api, boss, "other@example.com", "editor")
    for n in range(3):
        sql(
            "INSERT INTO notifications (id, user_id, kind, level, title) "
            "VALUES (gen_random_uuid(), :u, :k, 'info', :t)",
            {"u": boss.id, "k": f"k{n}", "t": f"Title {n}"},
        )

    first = waiting(boss)
    again = waiting(boss)

    assert [n["title"] for n in first] == ["Title 0", "Title 1", "Title 2"]  # oldest first
    assert {"id", "kind", "level", "title", "body", "link", "action", "quiet_when_here"} <= set(
        first[0]
    )
    assert again == [] and waiting(other) == []


def test_old_notifications_are_not_news_and_a_wall_of_them_comes_in_pieces(
    api: TestClient, sql: Any
) -> None:
    boss = admin(api)
    sql(
        "INSERT INTO notifications (id, user_id, kind, level, title, created_at) "
        "VALUES (gen_random_uuid(), :u, 'old', 'info', 'Yesterday', now() - interval '2 days')",
        {"u": boss.id},
    )
    for n in range(14):
        sql(
            "INSERT INTO notifications (id, user_id, kind, level, title) "
            "VALUES (gen_random_uuid(), :u, 'new', 'info', :t)",
            {"u": boss.id, "t": f"N{n}"},
        )

    first, second = waiting(boss), waiting(boss)

    assert len(first) == service.DELIVER_AT_ONCE and len(second) == 4
    assert "Yesterday" not in [n["title"] for n in first + second]
    assert waiting(boss) == []


def test_the_same_problem_is_announced_once_within_the_window(
    settings: Any, api: TestClient
) -> None:
    import asyncio

    from app.db.session import create_engine, create_sessionmaker

    boss = admin(api)

    async def tell() -> tuple[int, int, int]:
        engine = create_engine(settings)
        try:
            async with create_sessionmaker(engine)() as session:
                fields: dict[str, Any] = {
                    "kind": "x",
                    "level": "error",
                    "title": "Boom",
                    "dedupe_key": "boom",
                    "dedupe_minutes": 60,
                }
                a = await service.notify(session, [boss.id], **fields)
                b = await service.notify(session, [boss.id], **fields)
                c = await service.notify(
                    session, [None, boss.id], **{**fields, "dedupe_key": "other"}
                )
                return a, b, c
        finally:
            await engine.dispose()

    assert asyncio.run(tell()) == (1, 0, 1)
    assert len(waiting(boss)) == 2


def test_a_document_that_finishes_is_announced_to_its_uploader(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    waiting(boss)

    boss.post(f"/spaces/{space_id}/documents", files={"file": ("policy.md", POLICY.encode())})
    done = waiting_for(boss, "document_")

    assert [(n["kind"], n["level"]) for n in done] == [("document_ready", "success")]
    assert done[0]["title"] == "policy.md is ready"
    assert done[0]["link"] == f"/spaces/{space_id}?tab=library"


def test_a_chat_document_links_to_its_chat_and_a_bad_one_says_why(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    waiting(boss)

    boss.post(
        f"/spaces/{space_id}/conversations/{cid}/documents",
        files={"file": ("notes.md", POLICY.encode())},
    )
    boss.post(
        f"/spaces/{space_id}/conversations/{cid}/documents",
        files={"file": ("blank.md", b"   \n  \n")},
    )
    found = {n["title"]: n for n in waiting_for(boss, "document_", count=2)}

    assert found["notes.md is ready"]["link"] == f"/spaces/{space_id}/chat/{cid}"
    bad = found["blank.md could not be read"]
    assert (bad["level"], bad["kind"]) == ("error", "document_failed") and bad["body"]


def test_a_finished_chat_answer_is_announced_but_quiet_on_its_own_page(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)]))
    waiting(boss)

    final(events(ask(boss, space_id, cid, "Revenue by region?")))
    (ready,) = [n for n in waiting(boss) if n["kind"] == "answer_ready"]

    assert ready["level"] == "success" and ready["quiet_when_here"] is True
    assert (
        ready["link"] == f"/spaces/{space_id}/chat/{cid}" and "Revenue by region" in ready["body"]
    )


def test_an_answer_that_fails_is_an_error_and_a_down_ai_service_warns_administrators(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    other_admin = person(api, boss, "admin2@example.com", "admin")
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[LLMUnavailableError("All AI keys are resting.", retry_after=30)]))
    waiting(boss), waiting(other_admin)

    ask(boss, space_id, cid, "Anything?")
    mine = waiting(boss)
    theirs = waiting(other_admin)

    assert "answer_failed" in kinds(mine) and "ai_problem" in kinds(mine)
    assert kinds(theirs) == ["ai_problem"]
    ask(boss, space_id, conversation(boss, space_id), "Again?")
    assert "ai_problem" not in kinds(waiting(boss))  # said once, not for every question


def test_a_report_that_finishes_offers_the_file_to_download(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()["id"]
    report = boss.post(
        f"/spaces/{space_id}/reports", json={"name": "Weekly", "item_ids": [item]}
    ).json()
    waiting(boss)

    boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
    for _ in range(200):
        got = [n for n in waiting(boss) if n["kind"].startswith("report_")]
        if got:
            break
        time.sleep(0.2)

    (ready,) = got
    assert (ready["kind"], ready["level"]) == ("report_ready", "success")
    assert ready["link"] == f"/spaces/{space_id}/reports?report={report['id']}"
    action = ready["action"]
    assert action["type"] == "download" and action["label"] == "Download PDF"
    file = boss.get(action["path"])  # the path is one the person may really fetch
    assert file.status_code == 200 and file.content.startswith(b"%PDF")


def test_a_report_that_fails_says_why(api: TestClient, sql: Any) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()["id"]
    sql("UPDATE dashboard_items SET sql = 'SELECT nope FROM sales' WHERE id = :i", {"i": item})
    report = boss.post(
        f"/spaces/{space_id}/reports", json={"name": "Broken", "item_ids": [item]}
    ).json()
    waiting(boss)

    boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
    for _ in range(200):
        got = [n for n in waiting(boss) if n["kind"].startswith("report_")]
        if got:
            break
        time.sleep(0.2)

    (failed,) = got
    assert (failed["kind"], failed["level"]) == ("report_failed", "error")
    assert failed["title"] == "Broken failed" and failed["body"]


def test_email_trouble_warns_the_administrators_once(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(*args: Any, **kwargs: Any) -> None:
        raise mailer.MailError("The mail server refused the sign-in.")

    boss = admin(api)
    second = person(api, boss, "admin2@example.com", "admin")
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()["id"]
    monkeypatch.setattr(mail_config, "is_configured", always_configured)
    monkeypatch.setattr(mailer, "send", refuse)
    report = boss.post(
        f"/spaces/{space_id}/reports",
        json={"name": "Weekly", "item_ids": [item], "recipients": ["a@b.org"]},
    ).json()
    waiting(boss), waiting(second)

    for _ in range(2):
        boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
        time.sleep(1.5)

    problems = [n for n in waiting(second) if n["kind"] == "email_problem"]
    assert len(problems) == 1 and problems[0]["link"] == "/email?tab=account"
    assert problems[0]["level"] == "error"


def test_an_alert_that_goes_off_and_recovers_is_announced(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    metric = orders_metric(boss, space_id)
    waiting(boss)

    alert = boss.post(
        f"/spaces/{space_id}/alerts",
        json={
            "name": "Too many orders",
            "source_type": "metric",
            "expression_id": metric,
            "operator": "gt",
            "threshold": 10,
        },
    ).json()
    (fired,) = [n for n in waiting(boss) if n["kind"] == "alert_fired"]
    boss.patch(f"/spaces/{space_id}/alerts/{alert['id']}", json={"threshold": 1000})
    boss.post(f"/spaces/{space_id}/alerts/{alert['id']}/check")
    (back,) = [n for n in waiting(boss) if n["kind"] == "alert_recovered"]

    assert (fired["level"], fired["title"]) == ("warning", "Too many orders went off")
    assert "60" in fired["body"]
    assert fired["link"] == f"/spaces/{space_id}/alerts?alert={alert['id']}"
    assert (back["level"], back["title"]) == ("success", "Too many orders is back to normal")


def test_people_hear_when_they_are_added_moved_or_removed_from_a_space(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    ann = person(api, boss, "ann@example.com", "editor")
    waiting(ann)

    boss.put(f"/spaces/{space_id}/members/{ann.id}", json={"role": "viewer"})
    boss.put(f"/spaces/{space_id}/members/{ann.id}", json={"role": "viewer"})  # nothing changed
    boss.put(f"/spaces/{space_id}/members/{ann.id}", json={"role": "editor"})
    boss.delete(f"/spaces/{space_id}/members/{ann.id}")
    got = waiting(ann)

    assert kinds(got) == ["space_added", "space_role", "space_removed"]
    assert got[0]["link"] == f"/spaces/{space_id}" and got[2]["link"] == "/spaces"
    assert got[2]["level"] == "warning"
    assert not [n for n in waiting(boss) if n["kind"].startswith("space_")]  # not the actor


def test_administrators_hear_about_account_changes_except_their_own(api: TestClient) -> None:
    boss = admin(api)
    second = person(api, boss, "admin2@example.com", "admin")
    waiting(boss), waiting(second)

    new = person(api, boss, "new@example.com", "viewer")
    boss.patch(f"/users/{new.id}", json={"role": "editor"})
    boss.patch(f"/users/{new.id}", json={"is_active": False})

    got = waiting(second)
    assert kinds(got) == ["user_added", "user_changed", "user_changed"]
    assert (
        got[2]["title"].endswith("account was turned off")
        and got[1]["body"] == "They are now editor."
    )
    assert all(n["link"] == "/users" for n in got)
    assert [n for n in waiting(boss) if n["kind"].startswith("user_")] == []


def test_a_person_is_told_when_their_role_changes(api: TestClient) -> None:
    boss = admin(api)
    ann = person(api, boss, "ann@example.com", "viewer")
    waiting(ann)

    boss.patch(f"/users/{ann.id}", json={"role": "editor"})

    (told,) = waiting(ann)
    assert (told["kind"], told["link"], told["body"]) == (
        "role_changed",
        "/account",
        "You are now editor.",
    )


# ── Choosing what to hear about ──────────────────────────────────────────────


def prefs(who: Person) -> dict[str, Any]:
    return who.get("/notifications/preferences").json()


def put(who: Person, **body: Any) -> Any:
    return who.put("/notifications/preferences", json=body)


def test_everything_is_on_by_default_and_admins_see_two_more_groups(api: TestClient) -> None:
    boss = admin(api)
    viewer = person(api, boss, "vi@example.com", "viewer")

    mine = prefs(viewer)
    theirs = prefs(boss)

    assert mine["enabled"] is True and mine["paused_until"] is None
    assert [c["id"] for c in mine["categories"]] == [
        "reports",
        "alerts",
        "answers",
        "documents",
        "sharing",
        "benchmarks",
        "access",
        "connection",
    ]
    assert all(c["enabled"] for c in mine["categories"] + theirs["categories"])
    assert [c["id"] for c in theirs["categories"]][-2:] == ["system", "people"]
    assert {"title", "description", "group", "client_only"} <= set(mine["categories"][0])


def test_a_category_can_be_turned_off_and_on_and_only_that_kind_is_skipped(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    metric = orders_metric(boss, space_id)
    waiting(boss)

    off = put(boss, categories={"alerts": False})
    assert {c["id"]: c["enabled"] for c in off.json()["categories"]}["alerts"] is False
    boss.post(
        f"/spaces/{space_id}/alerts",
        json={
            "name": "Quiet",
            "source_type": "metric",
            "expression_id": metric,
            "operator": "gt",
            "threshold": 10,
        },
    )
    boss.post(f"/spaces/{space_id}/documents", files={"file": ("policy.md", POLICY.encode())})
    got = kinds(waiting(boss))

    assert "alert_fired" not in got and "document_ready" in got  # only alerts were muted
    on = put(boss, categories={"alerts": True}).json()
    assert {c["id"]: c["enabled"] for c in on["categories"]}["alerts"] is True


def test_turning_everything_off_or_pausing_stops_notifications_until_resumed(
    api: TestClient,
) -> None:
    from datetime import UTC, datetime, timedelta

    boss = admin(api)
    ann = person(api, boss, "ann@example.com", "editor")
    space_id = new_space(boss)
    waiting(ann)

    put(ann, enabled=False)
    boss.put(f"/spaces/{space_id}/members/{ann.id}", json={"role": "viewer"})
    assert waiting(ann) == []
    assert prefs(ann)["enabled"] is False

    put(ann, enabled=True)
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    paused = put(ann, paused_until=later).json()
    boss.put(f"/spaces/{space_id}/members/{ann.id}", json={"role": "editor"})
    assert paused["paused_until"] is not None and waiting(ann) == []

    resumed = put(ann, clear_pause=True).json()
    boss.put(f"/spaces/{space_id}/members/{ann.id}", json={"role": "viewer"})
    assert resumed["paused_until"] is None and kinds(waiting(ann)) == ["space_role"]


def test_a_pause_must_end_in_the_future_and_unknown_choices_are_refused(api: TestClient) -> None:
    from datetime import UTC, datetime, timedelta

    boss = admin(api)
    viewer = person(api, boss, "vi@example.com", "viewer")
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    assert put(boss, paused_until=past).status_code == 400
    assert put(boss, categories={"nonsense": False}).status_code == 400
    assert put(viewer, categories={"system": False}).status_code == 400  # not theirs to set


def test_an_administrator_can_mute_system_problems_and_others_still_hear_them(
    api: TestClient, sql: Any
) -> None:
    import asyncio

    from app.core.config import load_settings
    from app.db.session import create_engine, create_sessionmaker

    boss = admin(api)
    second = person(api, boss, "admin2@example.com", "admin")
    put(boss, categories={"system": False})
    waiting(boss), waiting(second)

    async def tell() -> None:
        engine = create_engine(load_settings())
        try:
            async with create_sessionmaker(engine)() as session:
                await service.email_problem(session, "refused")
        finally:
            await engine.dispose()

    asyncio.run(tell())

    assert waiting(boss) == []
    assert kinds(waiting(second)) == ["email_problem"]


def test_a_test_notification_shows_even_when_everything_is_paused(api: TestClient) -> None:
    boss = admin(api)
    put(boss, enabled=False)
    waiting(boss)

    sent = boss.post("/notifications/test")
    got = waiting(boss)

    assert sent.status_code == 202 and sent.json() == {"sent": True}
    assert kinds(got) == ["test"] and got[0]["link"] == "/account?section=notifications"


def test_resetting_puts_every_choice_back_to_the_default(api: TestClient) -> None:
    boss = admin(api)
    put(boss, enabled=False, categories={"reports": False, "alerts": False})

    back = boss.delete("/notifications/preferences").json()

    assert back["enabled"] is True and back["paused_until"] is None
    assert all(c["enabled"] for c in back["categories"])
