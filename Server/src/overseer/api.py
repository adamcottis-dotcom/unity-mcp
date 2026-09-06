"""Read-only HTTP view of the overseer ledger."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, Query

from .ledger import EventLedger


def create_overseer_app(ledger: EventLedger) -> FastAPI:
    """Create a dashboard-friendly API backed by an existing ledger."""
    app = FastAPI(title="Overseer Control Plane", version="1.0")

    @app.get("/events")
    def events(
        team_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict]:
        return [asdict(event) for event in ledger.list_events(team_id)[:limit]]

    @app.get("/summaries")
    def summaries(team_id: str | None = Query(default=None)) -> list[dict]:
        return [asdict(summary) for summary in ledger.summarize(team_id)]

    @app.get("/approvals")
    def pending_approvals(
        team_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict]:
        pending = [
            event
            for event in ledger.list_events(team_id)
            if event.requires_approval
        ]
        return [asdict(event) for event in pending[:limit]]

    return app
