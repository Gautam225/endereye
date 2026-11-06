"""Scheduled reports: when they are due, the files they make, the email, and the API (the API
tests need the test database). The mail server is scripted; everything else is real."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import io
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from test_chat import small_space
from test_dashboards import answered, pin
from test_spaces import Person, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.services import mail_config, mailer
from app.services.report_files import Section, build_pdf, build_xlsx
from app.services.schedule import next_run


async def always_configured(session: Any, settings: Any) -> bool:
    return True


NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)  # a Wednesday


def due(frequency: str, **kwargs: Any) -> datetime:
    base = {"hour": 8, "weekdays": [0], "day_of_month": 1, "timezone": "UTC", "after": NOW}
    return next_run(frequency, **{**base, **kwargs})


# ── When a report is due ─────────────────────────────────────────────────────


def test_a_daily_report_is_due_at_its_hour_today_or_tomorrow() -> None:
    assert due("daily", hour=12) == datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    assert due("daily", hour=8) == datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    assert due("daily", hour=10) == datetime(2026, 11, 12, 10, 0, tzinfo=UTC)  # strictly after


def test_a_weekly_report_waits_for_its_weekday() -> None:
    assert due("weekly", weekdays=[0]) == datetime(2026, 11, 16, 8, 0, tzinfo=UTC)  # Monday
    assert due("weekly", weekdays=[2], hour=12) == datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    assert due("weekly", weekdays=[2], hour=8) == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)


def test_a_weekly_report_can_run_on_several_days_and_at_any_minute() -> None:
    friday_and_saturday = [4, 5]
    assert due("weekly", weekdays=friday_and_saturday) == datetime(2026, 11, 13, 8, 0, tzinfo=UTC)
    after_friday = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
    assert due("weekly", weekdays=friday_and_saturday, after=after_friday) == datetime(
        2026, 11, 14, 8, 0, tzinfo=UTC
    )
    after_saturday = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    assert due("weekly", weekdays=friday_and_saturday, after=after_saturday) == datetime(
        2026, 11, 20, 8, 0, tzinfo=UTC
    )  # the following Friday
    assert due("weekly", weekdays=[2], hour=10, minute=45) == datetime(
        2026, 11, 11, 10, 45, tzinfo=UTC
    )
    assert due("daily", hour=10, minute=1) == datetime(2026, 11, 11, 10, 1, tzinfo=UTC)
    assert due("daily", hour=10, minute=0) == datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def test_a_monthly_report_uses_this_months_day_or_next_months() -> None:
    assert due("monthly", day_of_month=20) == datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    assert due("monthly", day_of_month=1) == datetime(2026, 12, 1, 8, 0, tzinfo=UTC)
    december = datetime(2026, 12, 28, 9, 0, tzinfo=UTC)
    assert due("monthly", day_of_month=28, after=december) == datetime(
        2027, 1, 28, 8, 0, tzinfo=UTC
    )


def test_the_hour_is_local_to_the_reports_time_zone_across_daylight_saving() -> None:
    summer = due("daily", timezone="Europe/London", after=datetime(2026, 7, 1, 12, 0, tzinfo=UTC))
    winter = due("daily", timezone="Europe/London", after=datetime(2026, 12, 1, 12, 0, tzinfo=UTC))
    assert summer == datetime(2026, 7, 2, 7, 0, tzinfo=UTC)  # 8:00 BST
    assert winter == datetime(2026, 12, 2, 8, 0, tzinfo=UTC)  # 8:00 GMT
    kolkata = due("daily", timezone="Asia/Kolkata", hour=8)
    assert kolkata == datetime(2026, 11, 12, 2, 30, tzinfo=UTC)
    nepal = due("daily", timezone="Asia/Kathmandu", hour=8, minute=15)
    assert nepal == datetime(2026, 11, 12, 2, 30, tzinfo=UTC)  # UTC+5:45


# ── The files ────────────────────────────────────────────────────────────────

SECTIONS = [
    Section(
        title="Revenue <b>by</b> region",
        question="Revenue by region?",
        columns=["region", "revenue"],
        rows=[["North", 1234.5], ["=cmd|calc", 10]],
        row_count=2,
    ),
    Section(title="Revenue by region", question="Again?", error="The table was removed."),
]


def test_the_pdf_is_a_real_pdf_and_text_is_never_read_as_markup() -> None:
    pdf = build_pdf("Weekly <i>sales</i>", SECTIONS, NOW, max_rows=10)

    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_the_workbook_has_a_summary_and_a_sheet_per_answer_with_formulas_neutralised() -> None:
    book = load_workbook(io.BytesIO(build_xlsx("Weekly sales", SECTIONS, NOW)))

    assert len(book.sheetnames) == 3 and book.sheetnames[0] == "Summary"
    first = book[book.sheetnames[1]]
    assert [c.value for c in first[1]] == ["region", "revenue"]
    assert first["A3"].value == "'=cmd|calc"
    assert "could not be refreshed" in str(book[book.sheetnames[2]]["A1"].value)
    assert book.sheetnames[1].lower() != book.sheetnames[2].lower()  # same title, own sheet


# ── Email ────────────────────────────────────────────────────────────────────


def test_an_email_header_can_never_carry_a_line_break() -> None:
    config = mailer.MailConfig(host="mail.example.com", from_address="a@b.com")

    message = mailer.build_message(
        config,
        ["x@example.com"],
        "Sales\r\nBcc: spy@evil.com",
        "Hello",
        [mailer.Attachment("report.pdf", b"%PDF")],
    )

    assert "\n" not in message["Subject"] and message["Bcc"] is None
    assert [p.get_filename() for p in message.iter_attachments()] == ["report.pdf"]


# ── The API ──────────────────────────────────────────────────────────────────


class Outbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, settings: Any, to: list[str], subject: str, body: str, attachments: Any):
        self.sent.append({"to": to, "subject": subject, "files": [a.filename for a in attachments]})


def kept_item(boss: Person, space_id: str) -> str:
    cid, mid = answered(boss, space_id)
    return pin(boss, space_id, cid, mid).json()["id"]


def make_report(boss: Person, space_id: str, item_id: str, **extra: Any) -> Any:
    return boss.post(
        f"/spaces/{space_id}/reports",
        json={"name": "Weekly sales", "item_ids": [item_id], **extra},
    )


def finished_run(
    boss: Person, space_id: str, report_id: str, seconds: float = 60
) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        runs = boss.get(f"/spaces/{space_id}/reports/{report_id}/runs").json()
        if runs and runs[0]["status"] != "running":
            return runs[0]
        time.sleep(0.1)
    raise AssertionError("the report did not finish")


@pytest.mark.db
def test_a_report_is_made_on_demand_and_its_files_can_be_downloaded(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item_id = kept_item(boss, space_id)
    report = make_report(boss, space_id, item_id, format="both").json()
    assert report["next_run_at"] is not None and report["last_run"] is None

    started = boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
    assert started.status_code == 202, started.text
    run = finished_run(boss, space_id, report["id"])

    assert run["status"] == "ok" and run["trigger"] == "manual"
    assert sorted(f.rsplit(".", 1)[1] for f in run["files"]) == ["pdf", "xlsx"]
    base = f"/spaces/{space_id}/reports/{report['id']}/runs/{run['id']}/files"
    pdf = boss.get(f"{base}/{next(f for f in run['files'] if f.endswith('.pdf'))}")
    xlsx = boss.get(f"{base}/{next(f for f in run['files'] if f.endswith('.xlsx'))}")
    assert pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    sheet = load_workbook(io.BytesIO(xlsx.content))
    assert sheet[sheet.sheetnames[1]]["A1"].value == "region"
    assert boss.get(f"{base}/..%2Fsecret.pdf").status_code == 404
    assert boss.get(f"{base}/other.pdf").status_code == 404


@pytest.mark.db
def test_a_report_is_emailed_to_its_recipients_when_mail_is_set_up(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item_id = kept_item(boss, space_id)
    outbox = Outbox()
    monkeypatch.setattr(mail_config, "is_configured", always_configured)
    monkeypatch.setattr(mailer, "send", outbox.send)
    report = make_report(
        boss, space_id, item_id, recipients=["Boss@Example.com", "boss@example.com", "b@x.org"]
    ).json()
    assert report["recipients"] == ["boss@example.com", "b@x.org"]

    boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
    run = finished_run(boss, space_id, report["id"])

    assert run["status"] == "ok" and run["emailed_to"] == ["boss@example.com", "b@x.org"]
    assert len(outbox.sent) == 1 and outbox.sent[0]["files"][0].endswith(".pdf")


@pytest.mark.db
def test_without_mail_the_report_is_still_made_and_says_it_was_not_sent(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    report = make_report(boss, space_id, kept_item(boss, space_id), recipients=["a@b.org"]).json()

    boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
    run = finished_run(boss, space_id, report["id"])

    assert run["status"] == "ok" and run["emailed_to"] == [] and "Not emailed" in run["error"]
    assert boss.get(f"/spaces/{space_id}/reports/options").json()["email_configured"] is False


@pytest.mark.db
def test_a_mail_failure_is_recorded_and_the_files_are_kept(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(*args: Any, **kwargs: Any) -> None:
        raise mailer.MailError("The mail server refused the sign-in.")

    boss = admin(api)
    space_id = small_space(boss)
    monkeypatch.setattr(mail_config, "is_configured", always_configured)
    monkeypatch.setattr(mailer, "send", refuse)
    report = make_report(boss, space_id, kept_item(boss, space_id), recipients=["a@b.org"]).json()

    boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
    run = finished_run(boss, space_id, report["id"])

    assert run["status"] == "failed" and "Email failed" in run["error"] and run["files"]


@pytest.mark.db
def test_a_report_only_uses_the_owners_own_kept_answers_and_is_private(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item_id = kept_item(boss, space_id)
    other = person(api, boss, "other@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{other.id}", json={"role": "viewer"})
    report = make_report(boss, space_id, item_id).json()

    assert make_report(other, space_id, item_id).status_code == 404  # not their kept answer
    assert other.get(f"/spaces/{space_id}/reports").json() == []
    base = f"/spaces/{space_id}/reports/{report['id']}"
    assert other.post(f"{base}/run").status_code == 404
    assert other.patch(base, json={"name": "mine"}).status_code == 404
    assert other.delete(base).status_code == 404
    assert make_report(boss, space_id, "00000000-0000-0000-0000-000000000000").status_code == 404


@pytest.mark.db
def test_a_report_is_validated_and_can_be_changed_and_deleted(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item_id = kept_item(boss, space_id)

    assert make_report(boss, space_id, item_id, timezone="Mars/Base").status_code == 422
    assert make_report(boss, space_id, item_id, recipients=["not-an-email"]).status_code == 422
    assert make_report(boss, space_id, item_id, hour=24).status_code == 422
    assert make_report(boss, space_id, item_id, day_of_month=31).status_code == 422
    assert make_report(boss, space_id, item_id, minute=60).status_code == 422
    assert make_report(boss, space_id, item_id, weekdays=[]).status_code == 422
    assert make_report(boss, space_id, item_id, weekdays=[7]).status_code == 422

    report = make_report(boss, space_id, item_id, frequency="daily").json()
    off = boss.patch(f"/spaces/{space_id}/reports/{report['id']}", json={"enabled": False}).json()
    assert off["enabled"] is False and off["next_run_at"] is None
    on = boss.patch(
        f"/spaces/{space_id}/reports/{report['id']}",
        json={
            "enabled": True,
            "frequency": "monthly",
            "day_of_month": 5,
            "timezone": "Asia/Kolkata",
        },
    ).json()
    assert on["next_run_at"] is not None and on["frequency"] == "monthly"
    assert boss.delete(f"/spaces/{space_id}/reports/{report['id']}").status_code == 204
    assert boss.get(f"/spaces/{space_id}/reports").json() == []


@pytest.mark.db
def test_reports_can_only_go_to_allowed_domains_and_to_a_limited_number_of_people(
    settings: Any, clean_db: None, data_dir: Any
) -> None:
    from app.main import create_app

    custom = settings.model_copy(
        update={
            "data_dir": data_dir,
            "report_allowed_email_domains": ["example.com"],
            "report_max_recipients": 2,
            "report_scheduler": False,
        }
    )
    with TestClient(create_app(custom)) as client:
        boss = admin(client)
        space_id = small_space(boss)
        item_id = kept_item(boss, space_id)

        outside = make_report(boss, space_id, item_id, recipients=["a@evil.org"])
        too_many = make_report(
            boss, space_id, item_id, recipients=["a@example.com", "b@example.com", "c@example.com"]
        )
        fine = make_report(boss, space_id, item_id, recipients=["a@example.com"])

        assert outside.status_code == 400 and "example.com" in outside.text
        assert too_many.status_code == 400 and "at most 2" in too_many.text
        assert fine.status_code == 201


@pytest.mark.db
def test_the_scheduler_starts_a_report_that_is_due_and_sets_the_next_time(
    settings: Any, clean_db: None, data_dir: Any, sql: Any
) -> None:
    from app.main import create_app

    custom = settings.model_copy(
        update={"data_dir": data_dir, "report_poll_seconds": 1, "report_scheduler": True}
    )
    with TestClient(create_app(custom)) as client:
        boss = admin(client)
        space_id = small_space(boss)
        report = make_report(boss, space_id, kept_item(boss, space_id), frequency="daily").json()
        sql(
            "UPDATE reports SET next_run_at = now() - interval '1 minute' WHERE id = :i",
            {"i": report["id"]},
        )

        run = finished_run(boss, space_id, report["id"], seconds=30)

        assert run["status"] == "ok" and run["trigger"] == "schedule"
        later = boss.get(f"/spaces/{space_id}/reports").json()[0]
        assert datetime.fromisoformat(later["next_run_at"]) > datetime.now(UTC)
        assert len(boss.get(f"/spaces/{space_id}/reports/{report['id']}/runs").json()) == 1


@pytest.mark.db
def test_a_report_whose_owner_lost_access_is_switched_off_not_run(
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
        cid, mid = answered(other, space_id)
        item_id = pin(other, space_id, cid, mid).json()["id"]
        report = make_report(other, space_id, item_id).json()
        assert boss.delete(f"/spaces/{space_id}/members/{other.id}").status_code == 204
        sql(
            "UPDATE reports SET next_run_at = now() - interval '1 minute' WHERE id = :i",
            {"i": report["id"]},
        )

        for _ in range(300):
            runs = sql(
                "SELECT status, error FROM report_runs WHERE report_id = :i", {"i": report["id"]}
            )
            if runs and runs[0][0] != "running":
                break
            time.sleep(0.1)

        assert runs[0][0] == "failed" and "no longer has access" in runs[0][1]
        enabled, next_run = sql(
            "SELECT enabled, next_run_at FROM reports WHERE id = :i", {"i": report["id"]}
        )[0]
        assert enabled is False and next_run is None


@pytest.mark.db
def test_a_report_keeps_several_weekdays_and_the_minute_and_names_its_answers(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item_id = kept_item(boss, space_id)

    made = make_report(boss, space_id, item_id, weekdays=[5, 4, 5], hour=9, minute=45).json()

    assert (made["weekdays"], made["hour"], made["minute"]) == ([4, 5], 9, 45)
    assert [i["id"] for i in made["items"]] == [item_id] and made["items"][0]["title"]
    first = datetime.fromisoformat(made["next_run_at"])
    assert first.astimezone(UTC).minute == 45 and first.astimezone(UTC).weekday() in (4, 5)
    changed = boss.patch(
        f"/spaces/{space_id}/reports/{made['id']}", json={"weekdays": [0, 2], "minute": 5}
    ).json()
    assert (changed["weekdays"], changed["minute"]) == ([0, 2], 5)
    assert boss.get(f"/spaces/{space_id}/reports").json()[0]["weekdays"] == [0, 2]
