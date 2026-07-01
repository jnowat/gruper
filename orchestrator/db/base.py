"""
Backend-agnostic async database handle.

`Database` mirrors the subset of asyncpg.Pool's surface the orchestrator
already uses (execute / fetch / fetchrow / fetchval), so `PostgresDatabase`
wraps asyncpg almost transparently. `SQLiteDatabase` adapts SQL text and
argument binding to reach behavioural parity with the Postgres path — see
`db/sqlite.py` for exactly what that adaptation covers.

This is deliberately NOT an ORM: application code still writes raw SQL.
The abstraction only standardises the calling convention and result shape
across the two drivers so the rest of the codebase doesn't need to know
which one is active.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class Row(Mapping[str, Any]):
    """Read-only mapping over a single result row (`row["col"]`, `dict(row)`)."""

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data = dict(data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:  # pragma: no cover — debugging aid only
        return f"Row({self._data!r})"


class Database(ABC):
    """Async database handle. One concrete subclass per backend."""

    dialect: str  # "postgres" | "sqlite"

    @abstractmethod
    async def execute(self, query: str, *args: Any) -> None: ...

    @abstractmethod
    async def fetch(self, query: str, *args: Any) -> list[Row]: ...

    @abstractmethod
    async def fetchrow(self, query: str, *args: Any) -> Row | None: ...

    @abstractmethod
    async def fetchval(self, query: str, *args: Any) -> Any: ...

    @abstractmethod
    async def close(self) -> None: ...

    def q(self, *, pg: str, lite: str) -> str:
        """Pick dialect-specific SQL text.

        Use only where the two engines genuinely need different SQL (e.g.
        the PostgreSQL SKIP LOCKED dispatch query, which has no SQLite
        equivalent). Everywhere else, write one PostgreSQL-style query —
        `$1`-style parameters and `::type` casts — and let the active
        backend adapt it. `PostgresDatabase` runs it unchanged; `SQLiteDatabase`
        rewrites placeholders/casts. Explicit dual text like this is
        preferred over cleverer regex rewriting when the queries are
        genuinely structurally different, so both variants stay visible
        and reviewable side by side.
        """
        return pg if self.dialect == "postgres" else lite
