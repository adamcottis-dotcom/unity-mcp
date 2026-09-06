"""Durable activity, approval, and economics ledger for the overseer dashboard.

The ledger deliberately stores facts rather than provider-specific objects. Connectors
for a CRM, billing provider, or model runtime can translate their callbacks into events.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Iterable
from uuid import uuid4


@dataclass(frozen=True)
class LedgerEvent:
    id: str
    category: str
    event_type: str
    team_id: str
    agent_id: str
    task_id: str | None
    amount: float
    currency: str
    requires_approval: bool
    approved_by: str | None
    metadata: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class TeamSummary:
    team_id: str
    revenue: float
    costs: float
    profit: float
    activity_count: int
    pending_approvals: int


class EventLedger:
    """SQLite-backed ledger suitable for simulation and a later API adapter."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger_events (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL CHECK (category IN ('activity', 'revenue', 'cost')),
                event_type TEXT NOT NULL,
                team_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                task_id TEXT,
                amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL,
                requires_approval INTEGER NOT NULL DEFAULT 0,
                approved_by TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ledger_events_team
                ON ledger_events(team_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_ledger_events_approval
                ON ledger_events(requires_approval, approved_by);
            """
        )
        self._connection.commit()

    def record(
        self,
        *,
        category: str,
        event_type: str,
        team_id: str,
        agent_id: str,
        task_id: str | None = None,
        amount: float = 0,
        currency: str = "USD",
        requires_approval: bool = False,
        approved_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> LedgerEvent:
        if category not in {"activity", "revenue", "cost"}:
            raise ValueError("category must be activity, revenue, or cost")
        if not team_id or not agent_id or not event_type:
            raise ValueError("team_id, agent_id, and event_type are required")
        if requires_approval and approved_by is not None:
            raise ValueError("an event cannot require approval and already be approved")
        if amount < 0:
            raise ValueError("amount must be non-negative; use category to distinguish revenue and cost")

        event = LedgerEvent(
            id=str(uuid4()),
            category=category,
            event_type=event_type,
            team_id=team_id,
            agent_id=agent_id,
            task_id=task_id,
            amount=amount,
            currency=currency.upper(),
            requires_approval=requires_approval,
            approved_by=approved_by,
            metadata=metadata or {},
            created_at=(created_at or datetime.now(timezone.utc)).isoformat(),
        )
        self._connection.execute(
            """
            INSERT INTO ledger_events
            (id, category, event_type, team_id, agent_id, task_id, amount, currency,
             requires_approval, approved_by, metadata_json, created_at)
            VALUES (:id, :category, :event_type, :team_id, :agent_id, :task_id, :amount,
                    :currency, :requires_approval, :approved_by, :metadata_json, :created_at)
            """,
            {**asdict(event), "requires_approval": int(event.requires_approval),
             "metadata_json": json.dumps(event.metadata, sort_keys=True)},
        )
        self._connection.commit()
        return event

    def approve(self, event_id: str, approver_id: str) -> LedgerEvent:
        if not approver_id:
            raise ValueError("approver_id is required")
        cursor = self._connection.execute(
            """
            UPDATE ledger_events
            SET requires_approval = 0, approved_by = ?
            WHERE id = ? AND requires_approval = 1 AND approved_by IS NULL
            """,
            (approver_id, event_id),
        )
        if cursor.rowcount != 1:
            raise LookupError("pending approval not found")
        self._connection.commit()
        return self.get(event_id)

    def get(self, event_id: str) -> LedgerEvent:
        row = self._connection.execute(
            "SELECT * FROM ledger_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise LookupError("ledger event not found")
        return self._row_to_event(row)

    def list_events(self, team_id: str | None = None) -> list[LedgerEvent]:
        if team_id is None:
            rows = self._connection.execute(
                "SELECT * FROM ledger_events ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM ledger_events WHERE team_id = ? ORDER BY created_at DESC",
                (team_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def summarize(self, team_id: str | None = None) -> list[TeamSummary]:
        where = "" if team_id is None else "WHERE team_id = ?"
        params: Iterable[str] = () if team_id is None else (team_id,)
        rows = self._connection.execute(
            f"""
            SELECT team_id,
                   COALESCE(SUM(CASE WHEN category = 'revenue' THEN amount ELSE 0 END), 0) AS revenue,
                   COALESCE(SUM(CASE WHEN category = 'cost' THEN amount ELSE 0 END), 0) AS costs,
                   COUNT(*) AS activity_count,
                   COALESCE(SUM(CASE WHEN requires_approval = 1 THEN 1 ELSE 0 END), 0)
                       AS pending_approvals
            FROM ledger_events {where}
            GROUP BY team_id
            ORDER BY team_id
            """,
            tuple(params),
        ).fetchall()
        return [
            TeamSummary(
                team_id=row["team_id"],
                revenue=row["revenue"],
                costs=row["costs"],
                profit=row["revenue"] - row["costs"],
                activity_count=row["activity_count"],
                pending_approvals=row["pending_approvals"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> LedgerEvent:
        return LedgerEvent(
            id=row["id"],
            category=row["category"],
            event_type=row["event_type"],
            team_id=row["team_id"],
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            amount=row["amount"],
            currency=row["currency"],
            requires_approval=bool(row["requires_approval"]),
            approved_by=row["approved_by"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
        )
