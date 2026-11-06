"""One chat turn, start to finish, as a stream of events.

    understand  rewrite a follow-up so it stands alone             (fast model, only in a thread)
    retrieve    the right tables, rules, examples, values, documents
    write SQL   in DuckDB dialect, or answer / ask / decline         (smart model)
    check       the SQL guard: one read-only query over this space's tables only
    run         with a time limit and a row limit
    repair      on an error, send it back to the model (at most 3 tries in all)
    answer      a short explanation grounded in the real result

Every stage is saved on the message as it happens, so a refresh or a dropped connection never
loses what was done. Nothing here is shared between conversations: the only history used is
the earlier turns of this same conversation.
"""

import asyncio
import logging
import math
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat import grounding, measures
from app.chat.answer import write_answer
from app.chat.charts import is_numeric, result_roles, suggest_chart, wants_combined
from app.chat.context import BuiltContext, build_context, normalise_sql
from app.chat.figures import clean_charts, lift_charts, tidy_reply
from app.chat.measures import Shape
from app.chat.prompts import (
    NO_TABLES_REPLY,
    Rewrite,
    ShownFigure,
    SqlPlan,
    TableContext,
    Turn,
    chart_repair_messages,
    repair_messages,
    rewrite_messages,
    sql_messages,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.core.rowcount import rows_text
from app.db.models import (
    FINISHED_WITH_CONTEXT,
    Conversation,
    Message,
    MessageStatus,
    Space,
    User,
)
from app.engine import duckdb_engine
from app.engine.duckdb_engine import CancelToken, QueryCancelledError, QueryFailedError
from app.engine.sql_guard import SqlNotAllowedError
from app.llm.errors import LLMError
from app.llm.gateway import LLMGateway
from app.llm.types import LLMResult
from app.schemas.chat import MessageOut
from app.services import engines, indexing, notifications
from app.services.conversations import NEW_CHAT, title_from

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
HISTORY_TURNS = 4
HISTORY_ANSWER_CHARS = 400  # earlier answers are reminders for the model, not its input
PREVIEW_ROWS = 200
MAX_ERROR_CHARS = 500

Event = tuple[str, dict[str, Any]]

STAGE_TEXT = {
    "understanding": "Understanding your question",
    "retrieving": "Finding the right tables and rules",
    "writing_sql": "Writing the query",
    "running": "Running the query",
    "repairing": "Fixing the query",
    "explaining": "Writing the answer",
}


class Progress:
    """Timings, models used and saving for one run of a turn."""

    def __init__(self, session: AsyncSession, message_id: uuid.UUID) -> None:
        self.session, self.message_id = session, message_id
        self.timings: dict[str, int] = {}
        self.models: list[str] = []
        self.thoughts: list[dict[str, str]] = []
        self._started = time.perf_counter()
        self._lap = self._started

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.timings[name] = self.timings.get(name, 0) + round((now - self._lap) * 1000)
        self._lap = now

    def think(self, text: str, kind: str = "step") -> Event:
        """A line of the thought process: shown while the answer is written, and saved with it."""
        thought = {"kind": kind, "text": text}
        self.thoughts.append(thought)
        return "thought", thought

    def note(self, result: LLMResult) -> None:
        label = f"{result.provider}/{result.model}"
        if label not in self.models:
            self.models.append(label)

    async def save(self, **fields: Any) -> None:
        await self.session.execute(
            update(Message).where(Message.id == self.message_id).values(**fields)
        )
        await self.session.commit()

    async def finish(self, status: MessageStatus, **fields: Any) -> None:
        self.timings["total"] = round((time.perf_counter() - self._started) * 1000)
        if isinstance(fields.get("error"), str):  # a database message can quote a data value
            fields["error"] = fields["error"][:MAX_ERROR_CHARS]
        await self.save(
            status=status.value,
            timings=self.timings,
            models=self.models,
            thoughts=self.thoughts,
            finished_at=datetime.now(UTC),
            **fields,
        )


# [S1], [S1, S2] or the full-width 【S1】 that some models write
CITED = re.compile(r"[\[【]\s*(S\d{1,2}(?:\s*[,;、]\s*S\d{1,2})*)\s*[\]】]")
TAG = re.compile(r"S\d{1,2}")


def _citations(built: BuiltContext, answer: str) -> list[dict[str, Any]]:
    """The passages the answer cites ([S1]...), as shown to the AI. When it cited none, the
    passages it was given are kept, marked as not cited, so the person can still look."""
    if not built.citations:
        return []
    used = {tag for group in CITED.findall(answer) for tag in TAG.findall(group)}
    cited = [{**c, "cited": True} for c in built.citations if c["tag"] in used]
    return cited or [{**c, "cited": False} for c in built.citations]


async def _history(
    session: AsyncSession, message: Message, share_answers: bool = True
) -> list[Turn]:
    rows = await session.scalars(
        select(Message)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.seq < message.seq,
            Message.status.in_([s.value for s in FINISHED_WITH_CONTEXT]),
        )
        .order_by(Message.seq.desc())
        .limit(HISTORY_TURNS)
    )
    return [
        Turn(m.question, m.standalone_question, m.sql, outcome_text(m, share_answers))
        for m in reversed(list(rows))
    ]


def _draw_charts(
    plan: SqlPlan, documents: list[str], question: str
) -> tuple[SqlPlan, list[dict[str, Any]], list[str], int]:
    """The plan with chart data taken out of its text, the charts that can be shown, why the
    others cannot, and how many written-in charts were unreadable."""
    text, charts, unusable = lift_charts(plan.answer or "", plan.charts)
    answer = tidy_reply(text) if text else plan.answer
    plan = plan.model_copy(update={"answer": answer, "charts": charts})
    figures, notes = clean_charts(charts, documents, question)
    return plan, figures, notes, unusable


MAX_OPTIONS = 5
MAX_OPTION_CHARS = 120


def clean_options(options: list[str], question: str = "") -> list[str]:
    """The answers offered with a question: trimmed, different from each other and from the
    question, short, and at most five. One option alone is not a choice, so it is dropped."""
    cleaned: list[str] = []
    seen = {" ".join(question.lower().split())}
    for option in options:
        text = " ".join(str(option).split())
        key = text.lower()
        if text and len(text) <= MAX_OPTION_CHARS and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned[:MAX_OPTIONS] if len(cleaned) >= 2 else []


COMBINE_PROBLEM = (
    "The question asks for the analyses combined in one chart, but this result stacks separate "
    "breakdowns one under another. Write ONE query that groups by both things together (one row "
    "per combination, for example birth_year, gender and the count), so each value of the first "
    "gets one bar per value of the second."
)


def _stacked_but_combined_asked(
    question: str, outcome: duckdb_engine.QueryResult, attempt: int, shape: Shape | None = None
) -> str | None:
    """When the person asked for a combined chart but the result stacks separate analyses, the
    problem to send back for one redo (the query ran; it is just not what was asked)."""
    if attempt >= MAX_ATTEMPTS or not wants_combined(question):
        return None
    columns = [{"name": c.name, "type": c.type} for c in outcome.columns]
    spec = suggest_chart(columns, outcome.rows[:PREVIEW_ROWS], shape)
    return COMBINE_PROBLEM if spec and spec.get("facet") and spec.get("panels") else None


EMPTY_PREFIX = "The query ran but found nothing"


def _empty_problem(
    sql: str, outcome: duckdb_engine.QueryResult, attempt: int, built: BuiltContext
) -> str | None:
    """A filtered query that returns no rows, or only empty figures, is more often a wrong filter
    value or a date outside the data than a true "none". One redo with the real ranges beside it;
    a second empty result is then reported as it is."""
    if attempt >= MAX_ATTEMPTS:
        return None
    nothing = not outcome.rows
    if not nothing and len(outcome.rows) == 1:
        numbers = [
            i for i, c in enumerate(outcome.columns) if is_numeric(c.type)
        ]  # SUM() of no rows is a single NULL row
        nothing = bool(numbers) and all(outcome.rows[0][i] is None for i in numbers)
    if not nothing:
        return None
    shape = measures.analyse(sql)
    if shape.known and not shape.filtered:
        return None  # nothing was filtered, so the table itself is empty: that is the answer
    ranges = [
        f"{table.name}.{column.name}: {column.value_range[0]} to {column.value_range[1]}"
        for table in built.context.tables
        for column in table.columns
        if column.value_range
    ][:8]
    seen = f" The data's date ranges: {'; '.join(ranges)}." if ranges else ""
    return (
        f"{EMPTY_PREFIX} (no rows, or only empty values).{seen} Check that every filter value "
        "exists in the data (use the listed example values and their exact spelling), that the "
        "dates fall inside the data's range, and that the joins do not lose rows. Relax any "
        "filter the question did not ask for, and say what you changed in assumptions."
    )


MISSING_PREFIX = "The question asks to show "


def _missing_figures(plan: SqlPlan, outcome: duckdb_engine.QueryResult) -> list[ShownFigure]:
    """The figures the plan says the question asks for whose column the result does not have.
    Names are compared without regard to case, since a database may fold an alias to lower case."""
    have = {c.name.lower() for c in outcome.columns}
    return [
        figure
        for figure in plan.shows
        if figure.column.strip() and figure.column.strip().lower() not in have
    ]


def _missing_problem(
    missing: list[ShownFigure], outcome: duckdb_engine.QueryResult, attempt: int
) -> str | None:
    """The query ran but left out a figure that was asked for: one redo, never a silent gap."""
    if not missing or attempt >= MAX_ATTEMPTS:
        return None
    wanted = "; ".join(f"{figure.ask} (column {figure.column})" for figure in missing)
    have = ", ".join(c.name for c in outcome.columns)
    return (
        f"{MISSING_PREFIX}{wanted}, but the result has no such column. It returned: {have}. "
        "Write the query again so that every figure asked for comes back as its own column with "
        "that alias, even when the figures are very different in size."
    )


async def _overall_figures(
    session: AsyncSession,
    engine: engines.SpaceEngine,
    built: BuiltContext,
    shape: Shape,
    outcome: duckdb_engine.QueryResult,
    settings: Settings,
    cancel: CancelToken,
) -> dict[str, float]:
    """The overall figures of a grouped result, asked of the database as the same query without
    its grouping, because adding up the rows is wrong for an average or a distinct count. It is
    asked for results that compare several measures (one measure is already its own answer), and it
    never fails the answer: when it cannot be done there are simply no overall figures."""
    if shape.totals_sql is None or len(outcome.rows) < 2 or outcome.truncated:
        return {}
    columns = [{"name": c.name, "type": c.type} for c in outcome.columns]
    if len(result_roles(columns, outcome.rows)["measure"]) < 2:
        return {}
    if shape.limit is not None and len(outcome.rows) >= shape.limit:
        return {}  # the LIMIT may have cut groups off, so the overall query would not match
    try:
        checked = engine.check(shape.totals_sql, set(built.table_names))
        result = await engine.run(
            session,
            checked,
            max_rows=1,
            timeout_seconds=settings.query_timeout_seconds,
            cancel=cancel,
        )
    except QueryCancelledError:
        raise
    except AppError as exc:
        logger.info("Overall figures skipped: %s", exc.message)
        return {}
    if not result.rows:
        return {}
    named = {c.name.lower(): c.name for c in outcome.columns}
    totals: dict[str, float] = {}
    for alias, value in zip(shape.totals_names, result.rows[0], strict=False):
        name = named.get(alias.lower())
        if (
            name
            and isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            totals[name] = float(value)
    return totals


def _chart_for(
    columns: list[dict[str, Any]],
    preview: list[list[Any]],
    shape: Shape,
    totals: dict[str, float],
    count: int,
    truncated: bool,
) -> dict[str, Any] | None:
    """The chart spec for a result, with the overall figures to show above it."""
    chart = suggest_chart(columns, preview, shape)
    if chart is None:
        return None
    chart["partial"] = count > len(preview) or truncated
    if chart.get("facet") and chart.get("panels"):
        grounding.annotate_panels(columns, preview, chart)
    tiles = [
        {
            "name": column["name"],
            "kind": shape.kind_of(column["name"]) or "other",
            "value": totals[column["name"]],
        }
        for column in columns
        if column["name"] in totals
    ]
    if tiles:
        chart["totals"] = tiles
    return chart


def _table_summary(table: TableContext) -> str:
    size = rows_text(table.row_count, table.approximate)
    return f"{table.name} ({size})" if size else table.name


def _brief(text: str | None) -> str:
    """The start of an earlier answer: long ones would fill the model's prompt."""
    text = " ".join((text or "").split())
    return text if len(text) <= HISTORY_ANSWER_CHARS else text[:HISTORY_ANSWER_CHARS] + "…"


def outcome_text(message: Message, share_answers: bool = True) -> str:
    """What an earlier turn came to, for the next prompt. When results must not go to the AI
    service, an answer that quotes the data is left out (the shape of the result stays)."""
    match message.status:
        case MessageStatus.OK.value:
            names = ", ".join(c["name"] for c in (message.columns or [])[:12])
            text = f"returned {message.row_count} rows with columns {names}"
            if message.answer and share_answers:
                return f"{text}. {_brief(message.answer)}"
            return text
        case MessageStatus.EMPTY.value:
            return "the query returned no rows"
        case MessageStatus.CLARIFY.value:
            return f"asked the user: {_brief(message.answer)}"
        case MessageStatus.DECLINED.value:
            return f"could not answer: {_brief(message.answer)}"
        case MessageStatus.ANSWER.value:
            return f"answered from documents: {_brief(message.answer)}"
    return message.status


def _check_cancel(cancel: CancelToken) -> None:
    if cancel.cancelled:
        raise QueryCancelledError("Stopped.")


def _friendly(exc: AppError) -> tuple[str, str]:
    return exc.code, exc.message


async def run_turn(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    llm: LLMGateway,
    space_id: uuid.UUID,
    message_id: uuid.UUID,
    cancel: CancelToken,
) -> AsyncIterator[Event]:
    async with sessionmaker() as session:
        message = await session.get(Message, message_id)
        if message is None:
            return
        turn = Progress(session, message_id)
        try:
            async for event in _run(session, turn, message, settings, llm, space_id, cancel):
                yield event
        except asyncio.CancelledError:
            await asyncio.shield(_mark_cancelled(session, turn))
            raise
        except QueryCancelledError:
            await _mark_cancelled(session, turn)
            yield "error", {"code": "cancelled", "message": "Stopped."}
        except AppError as exc:
            code, text = _friendly(exc)
            await turn.finish(MessageStatus.FAILED, error_code=code, error=text)
            await _announce(session, message_id)
            if code in ("llm_unavailable", "llm_not_configured"):
                await _tell_admins_about_ai(session, text)
            yield "error", {"code": code, "message": text}
        except Exception:
            logger.exception("Chat turn failed")
            text = "Something went wrong on our side. Please try again."
            await turn.finish(MessageStatus.FAILED, error_code="internal_error", error=text)
            await _announce(session, message_id)
            yield "error", {"code": "internal_error", "message": text}
        else:
            await _announce(session, message_id)
            return
        # An error path: still tell the client how the message ended.
        await session.refresh(message)
        yield "done", MessageOut.model_validate(message).model_dump(mode="json")


async def _announce(session: AsyncSession, message_id: uuid.UUID) -> None:
    """Tell the person their answer is ready (or failed): they may be on another page by now. The
    app stays quiet about it when they are looking at that very chat."""
    try:
        message = await session.get(Message, message_id)
        if message is None or message.status == MessageStatus.CANCELLED.value:
            return
        await session.refresh(message)
        conversation = await session.get(Conversation, message.conversation_id)
        if conversation is None:
            return
        failed = message.status == MessageStatus.FAILED.value
        question = " ".join(message.question.split())
        await notifications.notify(
            session,
            [conversation.user_id],
            kind="answer_failed" if failed else "answer_ready",
            level="error" if failed else "success",
            title="Your answer could not be made" if failed else "Your answer is ready",
            body=(message.error if failed and message.error else question)[:200],
            link=f"/spaces/{conversation.space_id}/chat/{conversation.id}",
            quiet_when_here=True,
        )
    except Exception:
        logger.warning("Could not announce a finished answer", exc_info=True)


async def _tell_admins_about_ai(session: AsyncSession, reason: str) -> None:
    """The AI service is down or not set up: every question is affected, so administrators hear
    about it (once every 30 minutes, not once per failed question)."""
    await notifications.notify_admins(
        session,
        kind="ai_problem",
        level="error",
        title="The AI service is not answering",
        body=f"Questions cannot be answered right now. {reason}"[:400],
        link="/monitoring",
        dedupe_key="ai_problem",
        dedupe_minutes=30,
    )


async def _mark_cancelled(session: AsyncSession, turn: Progress) -> None:
    try:
        await session.rollback()
        await turn.finish(MessageStatus.CANCELLED, error_code="cancelled", error="Stopped.")
    except Exception:
        logger.exception("Could not mark a chat turn as stopped")


async def _run(
    session: AsyncSession,
    turn: Progress,
    message: Message,
    settings: Settings,
    llm: LLMGateway,
    space_id: uuid.UUID,
    cancel: CancelToken,
) -> AsyncIterator[Event]:
    def stage(name: str) -> Event:
        text = STAGE_TEXT[name]
        if name == "retrieving" and personal:
            text = "Searching your documents"
        return "status", {"stage": name, "message": text}

    question = message.question
    personal = bool(await session.scalar(select(Space.is_personal).where(Space.id == space_id)))
    owner = await session.scalar(
        select(User)
        .join(Conversation, Conversation.user_id == User.id)
        .where(Conversation.id == message.conversation_id)
    )
    engine = await engines.for_space(session, space_id, settings, owner)
    history = await _history(session, message, engine.shares_results)

    # 1. Understand: a follow-up is rewritten so it stands alone.
    standalone = question
    if history:
        yield stage("understanding")
        try:
            rewrite, result = await llm.complete_json(
                rewrite_messages(history, question), Rewrite, purpose="chat_rewrite", tier="fast"
            )
            turn.note(result)
            standalone = rewrite.standalone_question.strip() or question
        except LLMError:
            logger.info("Rewrite failed; using the question as asked")
        turn.lap("understand")
        await turn.save(standalone_question=standalone)
        if standalone != question:
            yield turn.think(f"Read your follow-up as: {standalone}")

    # 2. Retrieve.
    yield stage("retrieving")
    embedder = await indexing.load_embedder(settings)
    reranker = await indexing.load_reranker(settings)
    built = await build_context(
        session,
        space_id,
        standalone,
        embedder=embedder,
        reranker=reranker,
        settings=settings,
        conversation_id=message.conversation_id,
        mentions=message.mentions,
        restrictions=engine.restrictions,
    )
    turn.lap("retrieve")
    await turn.save(sources=built.sources)
    _check_cancel(cancel)
    for kind, what in (("document", "documents"), ("table", "tables")):
        pointed = [m for m in message.mentions if m.get("kind", "document") == kind]
        if pointed:
            names = ", ".join(f"@{m['name']}" for m in pointed)
            yield turn.think(f"Using only the {what} you mentioned: {names}")
    if not personal or built.sources:
        yield turn.think(_found_text(built, personal))

    # A bigger request, in deep mode, is planned as a few analyses that are solved one by one.
    quick = message.mode == "quick"  # fewer AI calls: a faster model, the answer written here
    if message.mode == "deep" and not personal:
        from app.chat import deep

        yield stage("writing_sql")
        deep_plan, planned = await deep.make_plan(llm, built.context, history, standalone)
        if planned is not None:
            turn.note(planned)
        turn.lap("write_sql")
        _check_cancel(cancel)
        if deep_plan is not None:
            async for event in deep.run(
                session, turn, message, llm, built, engine, settings, cancel, deep_plan
            ):
                yield event
            return
        yield turn.think("This fits in one query, so I'm answering it directly.", "note")

    # 3-5. Write, check, run, repair.
    yield stage("writing_sql")
    base = sql_messages(
        built.context, history, standalone, general=personal, dialect=engine.dialect
    )
    sql_tier = "fast" if quick else "smart"
    plan, result = await llm.complete_json(base, SqlPlan, purpose="chat_sql", tier=sql_tier)
    turn.note(result)
    turn.lap("write_sql")
    _check_cancel(cancel)
    if personal and plan.action in {"sql", "describe", "clarify"}:
        # The General chat has no tables, whatever the AI chose: it can only talk.
        said = plan.clarification if plan.action == "clarify" else None
        plan.answer = said or plan.answer or NO_TABLES_REPLY
        plan.action = "chat"
    if plan.plan:
        yield turn.think(plan.plan, "plan")
    if plan.assumptions:
        yield turn.think("Assuming: " + "; ".join(plan.assumptions), "plan")

    last_error = ""
    last_sql: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if plan.action != "sql":
            break
        sql = (plan.sql or "").strip()
        last_sql = sql or last_sql
        problem: str | None = None
        checked = None
        missing: list[ShownFigure] = []
        try:
            checked = engine.check(sql, set(built.table_names))
        except SqlNotAllowedError as exc:
            problem = exc.message
        if checked is not None:
            _check_cancel(cancel)
            await turn.save(sql=checked.display, attempts=attempt)
            yield "sql", {"sql": checked.display, "attempt": attempt}
            yield stage("running")
            try:
                outcome = await engine.run(
                    session,
                    checked,
                    max_rows=settings.query_max_rows,
                    timeout_seconds=settings.query_timeout_seconds,
                    cancel=cancel,
                )
            except QueryFailedError as exc:
                problem = exc.message
            else:
                turn.lap("execute")
                shape = measures.analyse(checked.display, engine.dialect)
                missing = _missing_figures(plan, outcome)
                # The query ran, but it may not be what was asked: a combined chart, or every
                # figure the question names. Each gets one redo.
                problem = (
                    _stacked_but_combined_asked(standalone, outcome, attempt, shape)
                    or _missing_problem(missing, outcome, attempt)
                    or _empty_problem(checked.display, outcome, attempt, built)
                )
                if problem is None:
                    overall = (
                        {}
                        if quick
                        else await _overall_figures(
                            session, engine, built, shape, outcome, settings, cancel
                        )
                    )
                    turn.lap("overall")
                    if overall:
                        yield turn.think(
                            "Asked the database for the overall figures too: the same query "
                            "without its grouping."
                        )
                    async for event in _finish_with_rows(
                        session,
                        turn,
                        message,
                        llm,
                        built,
                        standalone,
                        plan,
                        checked.display,
                        outcome,
                        attempt,
                        engine.shares_results and not quick,
                        shape,
                        overall,
                        missing,
                    ):
                        yield event
                    return
        last_error = problem
        turn.lap("execute")
        if attempt == MAX_ATTEMPTS:
            break
        if problem == COMBINE_PROBLEM:
            yield turn.think(
                "You asked for the analyses combined in one chart, so the query is being redone "
                "to group by both.",
                "note",
            )
        elif problem.startswith(EMPTY_PREFIX):
            yield turn.think(
                "The query found nothing, so the filters are being checked against the data.",
                "note",
            )
        elif problem.startswith(MISSING_PREFIX):
            yield turn.think(
                "The result left out "
                + ", ".join(figure.ask for figure in missing)
                + ", so the query is being redone to include it.",
                "note",
            )
        else:
            yield turn.think(
                f"That query did not work ({problem[:160]}). Asking for a fix.", "note"
            )
        yield stage("repairing")
        plan, result = await llm.complete_json(
            repair_messages(base, plan, problem), SqlPlan, purpose="chat_repair", tier=sql_tier
        )
        turn.note(result)
        turn.lap("repair")

    # The model chose not to write SQL, or ran out of tries.
    # A chart the model pasted into its text as JSON becomes a real chart, not a block of code.
    documents = [text for _, text in built.context.documents]
    plan, figures, figure_notes, unusable = _draw_charts(plan, documents, standalone)
    if unusable:
        yield turn.think("Could not read a chart the assistant wrote, so it was left out.", "note")
    for note in figure_notes:
        yield turn.think(note, "note")
    if plan.charts and not figures and documents and plan.action in {"answer", "chat"}:
        # The chart was refused: ask once for a corrected one before giving up on it.
        yield turn.think("Asking the assistant to redraw the chart from the documents' numbers.")
        yield stage("repairing")
        try:
            again, result = await llm.complete_json(
                chart_repair_messages(base, plan, figure_notes),
                SqlPlan,
                purpose="chat_repair",
                tier="smart",
            )
        except LLMError:
            again = None
        else:
            turn.note(result)
            turn.lap("repair")
        if again is not None:
            again, figures_again, notes_again, _ = _draw_charts(again, documents, standalone)
            if figures_again:
                plan, figures, figure_notes = again, figures_again, []
            else:
                for note in notes_again:
                    yield turn.think(note, "note")
                figure_notes = notes_again or figure_notes
    if plan.charts and not figures and figure_notes:
        # Say it in the answer too, where it can be seen, instead of leaving a gap.
        reason = figure_notes[0].replace("Left out the chart", "I couldn't draw the chart", 1)
        plan.answer = f"{plan.answer or ''}\n\n> {reason}".strip()
    reply = (plan.answer or "").strip()
    document_sources = [s for s in built.sources if s["type"] == "document"]
    if personal and plan.action in {"chat", "answer", "decline"} and reply:
        await turn.finish(
            MessageStatus.ANSWER,
            answer=reply,
            figures=figures,
            assumptions=plan.assumptions,
            sources=document_sources,
            citations=_citations(built, reply),
        )
        async for event in _answer_events(reply):
            yield event
        for figure in figures:
            yield "figure", figure
    elif plan.action == "clarify":
        text = plan.clarification or plan.answer or "Could you tell me a bit more?"
        options = clean_options(plan.options, text)
        await turn.finish(
            MessageStatus.CLARIFY, answer=text, assumptions=plan.assumptions, options=options
        )
        async for event in _answer_events(text):
            yield event
        if options:
            yield "options", {"options": options}
    elif plan.action == "describe" and built.context.tables:
        text = (
            plan.answer
            or "This space has: " + "; ".join(_table_summary(t) for t in built.context.tables) + "."
        )
        await turn.finish(
            MessageStatus.ANSWER,
            answer=text,
            assumptions=plan.assumptions,
            sources=[{"type": "table", "header": t.name} for t in built.context.tables],
        )
        async for event in _answer_events(text):
            yield event
    elif plan.action == "answer" and built.context.documents:
        text = plan.answer or ""
        await turn.finish(
            MessageStatus.ANSWER,
            answer=text,
            figures=figures,
            assumptions=plan.assumptions,
            sources=document_sources,
            citations=_citations(built, text),
        )
        async for event in _answer_events(text):
            yield event
        for figure in figures:
            yield "figure", figure
    elif plan.action in {"answer", "decline", "chat"}:
        text = (
            plan.answer
            if plan.action == "decline" and plan.answer
            else "I can only answer from this space's data and documents. Open the general chat "
            "(the switcher at the top) for other questions."
            if plan.action == "chat"
            else "I couldn't find that in this space's data or documents."
        )
        await turn.finish(MessageStatus.DECLINED, answer=text, assumptions=plan.assumptions)
        async for event in _answer_events(text):
            yield event
    else:  # sql, but nothing worked
        text = (
            "I couldn't write a query that runs for this question. "
            "Try rephrasing it, or ask an editor to add an example for it."
        )
        await turn.finish(
            MessageStatus.FAILED,
            sql=last_sql,
            attempts=MAX_ATTEMPTS,
            error_code="sql_failed",
            error=f"{text} Last problem: {last_error}",
        )
        yield "error", {"code": "sql_failed", "message": text, "detail": last_error}
    async for event in _done(session, turn):
        yield event


async def _finish_with_rows(
    session: AsyncSession,
    turn: Progress,
    message: Message,
    llm: LLMGateway,
    built: BuiltContext,
    question: str,
    plan: SqlPlan,
    sql: str,
    outcome: duckdb_engine.QueryResult,
    attempt: int,
    share_results: bool = True,
    shape: Shape | None = None,
    overall: dict[str, float] | None = None,
    missing: list[ShownFigure] | None = None,
) -> AsyncIterator[Event]:
    shape, overall = shape or Shape(), overall or {}
    columns = [{"name": c.name, "type": c.type} for c in outcome.columns]
    preview = outcome.rows[:PREVIEW_ROWS]
    count = len(outcome.rows)
    trusted = normalise_sql(sql) in built.trusted_sql
    yield turn.think(
        f"The query returned {count:,} row{'s' if count != 1 else ''} in {outcome.elapsed_ms} ms."
    )
    yield (
        "rows",
        {
            "columns": columns,
            "rows": preview,
            "row_count": count,
            "truncated": outcome.truncated,
            "elapsed_ms": outcome.elapsed_ms,
        },
    )

    chart: dict[str, Any] | None = None
    suggestions: list[str] = []
    title = ""
    if count == 0:
        answer = grounding.fallback_summary(columns, [])
    elif not share_results:
        # This connection keeps its rows from the AI service: the summary is written here, from
        # the rows, and every number in it is read from them.
        yield turn.think(
            "Wrote the summary here without the AI service: this connection does not share "
            "results with it."
        )
        answer = grounding.fallback_summary(
            columns, outcome.rows, outcome.truncated, shape, overall
        )
        chart = _chart_for(columns, preview, shape, overall, count, outcome.truncated)
    else:
        yield "status", {"stage": "explaining", "message": STAGE_TEXT["explaining"]}
        written = await write_answer(
            llm,
            question=question,
            columns=columns,
            rows=outcome.rows,
            row_count=count,
            truncated=outcome.truncated,
            tables=built.context.tables,
            overall=overall,
            shape=shape,
        )
        turn.lap("explain")
        if written.model is not None:
            turn.note(written.model)
        answer, suggestions, title = written.summary, written.follow_ups, written.title
        chart = _chart_for(columns, preview, shape, overall, count, outcome.truncated)

    if missing:
        # A figure that was asked for and could not be returned is said so, never left as a gap.
        left_out = ", ".join(figure.ask for figure in missing)
        note = f"The result does not include {left_out}: the query would not return it."
        yield turn.think(note, "note")
        answer = f"{answer}\n\n> {note}"

    async for event in _answer_events(answer):
        yield event
    if chart is not None:
        yield "chart", chart
    if suggestions:
        yield "suggestions", {"questions": suggestions}
    if title and await _retitle(session, message, title):
        yield "title", {"title": title}

    await turn.finish(
        MessageStatus.OK if count else MessageStatus.EMPTY,
        sql=sql,
        trusted=trusted,
        answer=answer,
        assumptions=plan.assumptions,
        columns=columns,
        rows=preview,
        row_count=count,
        truncated=outcome.truncated,
        chart=chart,
        suggestions=suggestions,
        attempts=attempt,
    )
    async for event in _done(session, turn):
        yield event


async def _retitle(session: AsyncSession, message: Message, title: str) -> bool:
    """Give the thread a better title after its first answer, unless someone renamed it."""
    result = await session.execute(
        update(Conversation)
        .where(
            Conversation.id == message.conversation_id,
            Conversation.title.in_([title_from(message.question), NEW_CHAT]),
        )
        .values(title=title)
    )
    await session.commit()
    return bool(result.rowcount) and message.seq == 1


def _found_text(built: BuiltContext, personal: bool = False) -> str:
    """What retrieval found, in a line a person can read."""
    counts: dict[str, int] = {}
    for source in built.sources:
        counts[source["type"]] = counts.get(source["type"], 0) + source.get("passages", 1)
    parts = []
    if built.context.tables:
        parts.append("tables " + ", ".join(t.name for t in built.context.tables))
    labels = {
        "instruction": "rule",
        "clarification": "rule",
        "glossary": "business term",
        "example_sql": "example query",
        "expression": "definition",
        "document": "document passage",
    }
    for kind, label in labels.items():
        if counts.get(kind):
            parts.append(f"{counts[kind]} {label}{'s' if counts[kind] != 1 else ''}")
    where = "your documents" if personal else "your space"
    return f"Looked through {where} and found " + (" · ".join(parts) or "nothing relevant") + "."


async def _answer_events(text: str) -> AsyncIterator[Event]:
    """The answer, a few words at a time (so it reads as it is written), then in full.

    The text is only shown once it has been checked, so a number that is not in the data is
    never on screen; that is why this follows the check instead of streaming the model."""
    words = text.split(" ")
    size = max(2, -(-len(words) // 60))  # at most about 60 pieces
    for start in range(0, len(words), size):
        piece = " ".join(words[start : start + size])
        yield "answer.delta", {"text": piece if start == 0 else " " + piece}
        await asyncio.sleep(0.012)
    yield "answer", {"text": text}


async def _done(session: AsyncSession, turn: Progress) -> AsyncIterator[Event]:
    message = await session.get(Message, turn.message_id)
    if message is not None:
        await session.refresh(message)
        yield "done", MessageOut.model_validate(message).model_dump(mode="json")
