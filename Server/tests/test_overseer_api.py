import sqlite3

from fastapi.testclient import TestClient

from overseer import EventLedger, create_overseer_app, run_support_ticket_simulation


def test_api_exposes_simulation_events_and_financial_summary():
    ledger = EventLedger(sqlite3.connect(":memory:", check_same_thread=False))
    run_support_ticket_simulation(ledger, ticket_id="T-42")
    client = TestClient(create_overseer_app(ledger))

    events = client.get("/events?team_id=support").json()
    summary = client.get("/summaries?team_id=support").json()

    assert len(events) == 4
    assert summary == [
        {
            "team_id": "support",
            "revenue": 499,
            "costs": 31.25,
            "profit": 467.75,
            "activity_count": 4,
            "pending_approvals": 0,
        }
    ]


def test_api_only_returns_pending_approvals():
    ledger = EventLedger(sqlite3.connect(":memory:", check_same_thread=False))
    pending = ledger.record(
        category="cost",
        event_type="refund_requested",
        team_id="support",
        agent_id="billing-agent",
        amount=50,
        requires_approval=True,
    )
    ledger.record(
        category="activity",
        event_type="ticket_resolved",
        team_id="support",
        agent_id="support-agent",
    )
    client = TestClient(create_overseer_app(ledger))

    approvals = client.get("/approvals").json()

    assert len(approvals) == 1
    assert approvals[0]["id"] == pending.id
