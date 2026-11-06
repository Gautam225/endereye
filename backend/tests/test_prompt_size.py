"""The model's prompt stays small however long the earlier answers were."""

from app.chat.pipeline import HISTORY_ANSWER_CHARS, outcome_text
from app.chat.prompts import Context, Turn, sql_messages
from app.db.models import Message
from app.llm.gateway import estimate_tokens

GROQ_LIMIT = 6000  # tokens; the default of GROQ_MAX_PROMPT_TOKENS


def test_a_long_earlier_answer_is_cut_short_in_the_history() -> None:
    message = Message(status="answer", answer="Silverline guarantees 98 percent. " * 300)

    text = outcome_text(message)

    assert text.startswith("answered from documents: Silverline guarantees")
    assert len(text) < HISTORY_ANSWER_CHARS + 60 and text.endswith("…")


def test_a_chat_with_long_answers_and_full_documents_fits_the_smallest_model_limit() -> None:
    context = Context(documents=[(f"doc{i} > Section", "x" * 1500) for i in range(4)])
    long_answer = outcome_text(Message(status="answer", answer="word " * 2000))
    history = [Turn(f"question {i}", None, None, long_answer) for i in range(10)]

    messages = sql_messages(context, history, "compare both documents", general=True)

    assert estimate_tokens(messages) < GROQ_LIMIT // 2
