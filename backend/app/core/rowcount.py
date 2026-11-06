"""How many rows a table has, as far as anyone knows.

For files the count is exact. For a table of an external database it is only the server's own
estimate, and often there is none (PostgreSQL knows a table's size only after it has been
analysed). An unknown size is stored as -1 and is never written as a number: a made-up "0 rows"
once made the assistant decide that a table with data was empty.
"""

UNKNOWN = -1


def rows_text(count: int, approximate: bool = False) -> str | None:
    """ "1,234 rows", "about 1,234 rows" for an estimate, or None when the size is not known."""
    if count < 0:
        return None
    noun = "row" if count == 1 else "rows"
    return f"{'about ' if approximate else ''}{count:,} {noun}"
