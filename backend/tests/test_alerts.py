"""Alerts: when a number crosses a threshold, who is told, and when they are not told again
(needs the test database). The mail server is scripted; everything else is real."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import small_space
from test_dashboards import answered, pin
from test_spaces import Person, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.services import mail_config, mailer
from app.services.alerts import holds

pytestmark = pytest.mark.db


async def always_configured(session: Any, settings: Any) -> bool:
    return True


def test_a_threshold_is_crossed_by_the_operator_chosen() -> None:
    assert holds(3.1, "gt", 3) and not holds(3, "gt", 3)
    assert holds(3, "gte", 3) and not holds(2.9, "gte", 3)
    assert holds(2.9, "lt", 3) and not holds(3, "lt", 3)
    assert holds(3, "lte", 3) and not holds(3.1, "lte", 3)


class Outbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, settings: Any, to: list[str], subject: str, body: str, files: Any) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(mail_config, "is_configured", always_configured)
    monkeypatch.setattr(mailer, "send", box.send)
    return box


def orders_metric(boss: Person, space_id: str) -> str:
    """The shared metric "Orders" (a row count), made the first time it is asked for."""
    found = [e for e in boss.get(f"/spaces/{space_id}/expressions").json() if e["name"] == "Orders"]
    if found:
        return found[0]["id"]
    made = boss.post(
        f"/spaces/{space_id}/expressions",
        json={"name": "Orders", "type": "measure", "expression": "count(*)", "table_name": "sales"},
    )
    return made.json()["id"]


def watch(boss: Person, space_id: str, **extra: Any) -> Any:
    body = {
        "name": "Too many orders",
        "source_type": "metric",
        "expression_id": orders_metric(boss, space_id),
        "operator": "gt",
        "threshold": 10,
    }
    return boss.post(f"/spaces/{space_id}/alerts", json={**body, **extra})


def events(boss: Person, space_id: str, alert_id: str) -> list[dict[str, Any]]:
    return boss.get(f"/spaces/{space_id}/alerts/{alert_id}/events").json()


def test_an_alert_on_a_metric_goes_off_when_created_above_its_threshold(
    api: TestClient, outbox: Outbox
) -> None:
    boss = admin(api)
    space_id = small_space(boss)

    made = watch(boss, space_id, recipients=["Team@Example.com"])

    assert made.status_code == 201, made.text
    alert = made.json()
    assert (alert["state"], alert["last_value"]) == ("triggered", 60)
    assert alert["expression_name"] == "Orders" and alert["next_check_at"] is not None
    (event,) = events(boss, space_id, alert["id"])
    assert event["kind"] == "triggered" and event["value"] == 60
    assert len(outbox.sent) == 1
    assert "team@example.com" in outbox.sent[0]["to"] and len(outbox.sent[0]["to"]) == 2
    assert "Too many orders" in outbox.sent[0]["subject"] and "60" in outbox.sent[0]["body"]


def test_people_are_told_once_while_it_holds_and_again_when_it_ends(
    api: TestClient, outbox: Outbox
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    alert = watch(boss, space_id, renotify_hours=0).json()
    base = f"/spaces/{space_id}/alerts/{alert['id']}"

    boss.post(f"{base}/check")
    boss.post(f"{base}/check")
    assert [e["kind"] for e in events(boss, space_id, alert["id"])] == ["triggered"]
    assert len(outbox.sent) == 1  # still above: not told again

    back = boss.patch(base, json={"threshold": 1000}).json()
    assert back["state"] == "triggered"  # not checked yet
    ok = boss.post(f"{base}/check").json()

    assert ok["state"] == "ok" and ok["last_value"] == 60
    assert [e["kind"] for e in events(boss, space_id, alert["id"])] == ["recovered", "triggered"]
    assert len(outbox.sent) == 2 and outbox.sent[1]["subject"].startswith("Back to normal")


def test_a_lingering_alert_repeats_only_after_the_renotify_time(
    api: TestClient, outbox: Outbox, sql: Any
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    alert = watch(boss, space_id, renotify_hours=2).json()
    base = f"/spaces/{space_id}/alerts/{alert['id']}"

    boss.post(f"{base}/check")
    assert len(outbox.sent) == 1
    sql(
        "UPDATE alerts SET last_notified_at = now() - interval '3 hours' WHERE id = :i",
        {"i": alert["id"]},
    )
    boss.post(f"{base}/check")

    assert len(outbox.sent) == 2
    assert [e["kind"] for e in events(boss, space_id, alert["id"])] == ["triggered", "triggered"]


def test_recovery_can_be_left_unannounced(api: TestClient, outbox: Outbox) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    alert = watch(boss, space_id, notify_on_recovery=False).json()
    base = f"/spaces/{space_id}/alerts/{alert['id']}"

    boss.patch(base, json={"threshold": 1000})
    boss.post(f"{base}/check")

    assert [e["kind"] for e in events(boss, space_id, alert["id"])] == ["triggered"]
    assert len(outbox.sent) == 1


def test_without_mail_the_alert_still_works_and_the_event_says_it_was_not_sent(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)

    alert = watch(boss, space_id).json()

    (event,) = events(boss, space_id, alert["id"])
    assert event["emailed_to"] == [] and "Not emailed" in event["message"]


def test_an_alert_that_cannot_read_its_number_is_refused(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)

    broken = watch(boss, space_id, where_sql="nope = 1")
    other_space = watch(boss, space_id, expression_id="00000000-0000-0000-0000-000000000000")
    nothing_chosen = boss.post(
        f"/spaces/{space_id}/alerts",
        json={"name": "x", "source_type": "item", "operator": "gt", "threshold": 1},
    )

    assert broken.status_code == 400
    assert other_space.status_code == 404
    assert nothing_chosen.status_code == 422
    assert boss.get(f"/spaces/{space_id}/alerts").json() == []


def test_an_alert_can_watch_the_first_number_of_a_kept_answer(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()

    made = boss.post(
        f"/spaces/{space_id}/alerts",
        json={
            "name": "Revenue",
            "source_type": "item",
            "item_id": item["id"],
            "operator": "gt",
            "threshold": 0,
        },
    )
    named = boss.post(
        f"/spaces/{space_id}/alerts",
        json={
            "name": "Missing column",
            "source_type": "item",
            "item_id": item["id"],
            "value_column": "nope",
            "operator": "gt",
            "threshold": 0,
        },
    )

    assert made.status_code == 201 and made.json()["state"] == "triggered"
    assert made.json()["item_title"] and made.json()["last_value"] > 0
    assert named.status_code == 400


def test_an_alert_is_private_and_uses_only_the_owners_kept_answers(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    alert = watch(boss, space_id).json()
    other = person(api, boss, "other@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{other.id}", json={"role": "editor"})
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()
    base = f"/spaces/{space_id}/alerts/{alert['id']}"

    assert other.get(f"/spaces/{space_id}/alerts").json() == []
    for call in (other.post(f"{base}/check"), other.patch(base, json={"threshold": 1})):
        assert call.status_code == 404
    assert other.delete(base).status_code == 404
    assert other.get(f"{base}/events").status_code == 404
    stolen = other.post(
        f"/spaces/{space_id}/alerts",
        json={
            "name": "Peek",
            "source_type": "item",
            "item_id": item["id"],
            "operator": "gt",
            "threshold": 0,
        },
    )
    assert stolen.status_code == 404


def test_an_alert_can_be_changed_paused_and_deleted(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    alert = watch(boss, space_id, interval_minutes=15).json()
    base = f"/spaces/{space_id}/alerts/{alert['id']}"

    assert watch(boss, space_id, interval_minutes=7).status_code == 422
    paused = boss.patch(base, json={"enabled": False}).json()
    assert paused["enabled"] is False and paused["next_check_at"] is None
    resumed = boss.patch(base, json={"enabled": True, "name": "Renamed"}).json()
    assert resumed["next_check_at"] is not None and resumed["name"] == "Renamed"
    assert boss.delete(base).status_code == 204
    assert boss.get(f"/spaces/{space_id}/alerts").json() == []


def test_the_scheduler_checks_an_alert_that_is_due_and_sets_the_next_time(
    settings: Any, clean_db: None, data_dir: Any, sql: Any, outbox: Outbox
) -> None:
    from app.main import create_app

    custom = settings.model_copy(
        update={"data_dir": data_dir, "report_poll_seconds": 1, "report_scheduler": True}
    )
    with TestClient(create_app(custom)) as client:
        boss = admin(client)
        space_id = small_space(boss)
        alert = watch(boss, space_id, threshold=1000).json()  # fine now
        sql(
            "UPDATE alerts SET next_check_at = now() - interval '1 minute', last_value = -1 "
            "WHERE id = :i",
            {"i": alert["id"]},
        )

        for _ in range(100):
            seen = sql("SELECT last_value FROM alerts WHERE id = :i", {"i": alert["id"]})[0][0]
            if seen == 60:
                break
            time.sleep(0.2)

        assert seen == 60
        later = boss.get(f"/spaces/{space_id}/alerts").json()[0]
        assert later["state"] == "ok" and later["next_check_at"] > later["last_checked_at"]
        assert outbox.sent == []  # nothing to say


def test_an_alert_whose_owner_lost_access_is_switched_off(
    settings: Any, clean_db: None, data_dir: Any, sql: Any
) -> None:
    from app.main import create_app

    custom = settings.model_copy(
        update={"data_dir": data_dir, "report_poll_seconds": 1, "report_scheduler": True}
    )
    with TestClient(create_app(custom)) as client:
        boss = admin(client)
        space_id = small_space(boss)
        other = person(client, boss, "other@example.com", "editor")
        boss.put(f"/spaces/{space_id}/members/{other.id}", json={"role": "editor"})
        alert = other.post(
            f"/spaces/{space_id}/alerts",
            json={
                "name": "Mine",
                "source_type": "metric",
                "expression_id": orders_metric(boss, space_id),
                "operator": "gt",
                "threshold": 1000,
            },
        ).json()
        assert boss.delete(f"/spaces/{space_id}/members/{other.id}").status_code == 204
        sql(
            "UPDATE alerts SET next_check_at = now() - interval '1 minute' WHERE id = :i",
            {"i": alert["id"]},
        )

        for _ in range(150):
            row = sql(
                "SELECT enabled, state, last_error FROM alerts WHERE id = :i", {"i": alert["id"]}
            )[0]
            if not row[0]:
                break
            time.sleep(0.2)

        assert row[0] is False and row[1] == "error" and "no longer has access" in row[2]
