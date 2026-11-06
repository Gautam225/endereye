"""Reading what an external PostgreSQL database contains: tables, columns, keys, descriptions.

Only the catalogs are read (pg_class, pg_attribute, pg_constraint, comments). No table is ever
read, not even a sample, so discovery cannot expose or load data. What the login may not see is
not listed: a table it cannot SELECT from, a column it cannot SELECT, or a schema it cannot use
does not appear, so the database's own permissions decide what can ever be offered.

Relationships are only the foreign keys the database itself declares. Nothing is guessed from
column names. A foreign key over several columns can't be stored as a join (a join here is one
column to one column), so it is reported as skipped instead of being cut down.
"""

from dataclasses import dataclass, field
from typing import Any

import asyncpg

MAX_TABLES = 500
KIND_NAMES = {
    "r": "table",
    "p": "table",
    "v": "view",
    "m": "materialized view",
    "f": "foreign table",
}
SYSTEM_SCHEMAS = "n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'"


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    type: str
    position: int
    nullable: bool
    primary_key: bool = False
    comment: str = ""


@dataclass(frozen=True, slots=True)
class ForeignKey:
    name: str
    columns: tuple[str, ...]
    ref_schema: str
    ref_table: str
    ref_columns: tuple[str, ...]

    @property
    def single_column(self) -> bool:
        return len(self.columns) == 1 and len(self.ref_columns) == 1


@dataclass(slots=True)
class TableInfo:
    schema: str
    name: str
    kind: str  # table, view, materialized view, foreign table
    comment: str
    estimated_rows: int | None  # the server's estimate; None when it has none (or says 0)
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    oid: int = 0

    @property
    def ref(self) -> str:
        return f"{self.schema}.{self.name}"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def discover(conn: asyncpg.Connection, limit: int = MAX_TABLES) -> list[TableInfo]:
    """Every table and view this login can read, with its readable columns and foreign keys.
    Run inside a read-only transaction."""
    rows = await conn.fetch(
        f"""
        SELECT c.oid::bigint AS oid, n.nspname AS schema, c.relname AS name,
               c.relkind::text AS kind,
               obj_description(c.oid, 'pg_class') AS comment,
               c.reltuples::float8 AS reltuples
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND NOT c.relispartition
          AND {SYSTEM_SCHEMAS}
          AND has_schema_privilege(current_user, n.oid, 'USAGE')
          AND (has_table_privilege(current_user, c.oid, 'SELECT')
               OR has_any_column_privilege(current_user, c.oid, 'SELECT'))
        ORDER BY n.nspname, c.relname
        LIMIT $1
        """,
        limit,
    )
    tables = {
        r["oid"]: TableInfo(
            r["schema"],
            r["name"],
            KIND_NAMES.get(r["kind"], "table"),
            (r["comment"] or "").strip(),
            # -1 means never analysed; 0 can mean the same on older servers, or a stale count of
            # a table that has since been filled. Neither is a size worth stating.
            int(r["reltuples"]) if r["reltuples"] > 0 else None,
            oid=r["oid"],
        )
        for r in rows
    }
    if not tables:
        return []
    oids = list(tables)

    primary = await _primary_keys(conn, oids)
    for r in await conn.fetch(
        """
        SELECT a.attrelid::bigint AS oid, a.attname AS name, a.attnum AS position,
               format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable,
               col_description(a.attrelid, a.attnum) AS comment
        FROM pg_attribute a
        WHERE a.attrelid = ANY($1::oid[]) AND a.attnum > 0 AND NOT a.attisdropped
          AND has_column_privilege(current_user, a.attrelid, a.attnum, 'SELECT')
        ORDER BY a.attrelid, a.attnum
        """,
        oids,
    ):
        tables[r["oid"]].columns.append(
            ColumnInfo(
                r["name"],
                r["type"],
                r["position"],
                bool(r["nullable"]),
                r["name"] in primary.get(r["oid"], ()),
                (r["comment"] or "").strip(),
            )
        )

    visible = {t.oid: t for t in tables.values()}
    for r in await conn.fetch(
        """
        SELECT con.conname AS name, con.conrelid::bigint AS oid, con.confrelid::bigint AS ref_oid,
          (SELECT array_agg(a.attname ORDER BY k.ord)
             FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS columns,
          (SELECT array_agg(a.attname ORDER BY k.ord)
             FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum)
            AS ref_columns
        FROM pg_constraint con
        WHERE con.contype = 'f' AND con.conrelid = ANY($1::oid[])
        ORDER BY con.conrelid, con.conname
        """,
        oids,
    ):
        parent = visible.get(r["ref_oid"])
        if parent is None:  # points at a table this login can't read: not usable
            continue
        tables[r["oid"]].foreign_keys.append(
            ForeignKey(
                r["name"],
                tuple(r["columns"] or ()),
                parent.schema,
                parent.name,
                tuple(r["ref_columns"] or ()),
            )
        )
    return list(tables.values())


async def _primary_keys(conn: asyncpg.Connection, oids: list[int]) -> dict[int, set[str]]:
    found: dict[int, set[str]] = {}
    for r in await conn.fetch(
        """
        SELECT con.conrelid::bigint AS oid, a.attname AS name
        FROM pg_constraint con
        JOIN LATERAL unnest(con.conkey) AS k(attnum) ON true
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
        WHERE con.contype = 'p' AND con.conrelid = ANY($1::oid[])
        """,
        oids,
    ):
        found.setdefault(r["oid"], set()).add(r["name"])
    return found


def to_json(columns: list[ColumnInfo]) -> list[dict[str, Any]]:
    """What is saved in space_tables.columns (name and type are what the rest of the app reads)."""
    return [
        {"name": c.name, "type": c.type, "nullable": c.nullable, "primary_key": c.primary_key}
        for c in columns
    ]
