"""Which database migration this code expects, so we can tell when `alembic upgrade head`
still needs to run."""

from functools import lru_cache
from pathlib import Path

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@lru_cache
def expected_revision() -> str | None:
    """The newest migration in alembic/versions, or None if the files aren't available."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    except Exception:
        return None
