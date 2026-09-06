import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from overseer import EventLedger


@pytest.fixture
def ledger():
    return EventLedger(sqlite3.connect(":memory:"))


def test_records_activity_and_summarizes_revenue_cost_and_profit(ledger):
    ledger.record(
        category="revenue",
        event_type="subscription_paid",
        team_id="support",
        agent_id="billing-agent",
        amount=500,
        currency="usd",
    )
    ledger.record(
        category="cost",
        event_type="model_usage",
        team_id="support",
        agent_id="support-agent",
        amount=125,
        currency="USD",
    )
    ledger.record(
        category="activity",
        event_type="ticket_resolved",
        team_id="support",
        agent_id="support-agent",
        metadata={"ticket_id": "T-1"},
    )

    summary = ledger.summarize()[0]
    assert summary.team_id == "support"
    assert summary.revenue == 500
    assert summary.costs == 125
    assert summary.profit == 375
    assert summary.activity_count == 3


def test_exact_money_is_currency_aware_and_pending_amounts_are_excluded(ledger):
    ledger.record(
        category="revenue",
        event_type="paid",
        team_id="support",
        agent_id="billing",
        amount="0.10",
        currency="usd",
    )
    ledger.record(
        category="revenue",
        event_type="paid",
        team_id="support",
        agent_id="billing",
        amount="0.20",
        currency="usd",
    )
    ledger.record(
        category="revenue",
        event_type="pending",
        team_id="support",
        agent_id="billing",
        amount="100",
        currency="eur",
        requires_approval=True,
    )

    summaries = ledger.summarize()
    by_currency = {summary.currency: summary for summary in summaries}
    assert by_currency["USD"].revenue == Decimal("0.30")
    assert by_currency["EUR"].revenue == Decimal("0")
    assert by_currency["EUR"].pending_approvals == 1


def test_rejects_non_finite_or_naive_timestamps(ledger):
    with pytest.raises(ValueError, match="finite"):
        ledger.record(category="cost", event_type="x", team_id="t", agent_id="a", amount=float("nan"))
    with pytest.raises(ValueError, match="timezone-aware"):
        ledger.record(
            category="activity",
            event_type="x",
            team_id="t",
            agent_id="a",
            created_at=datetime(2025, 1, 1),
        )

    event = ledger.record(
        category="activity",
        event_type="x",
        team_id="t",
        agent_id="a",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    assert event.created_at.endswith("+00:00")


def test_requires_approval_is_visible_and_can_be_approved(ledger):
    event = ledger.record(
        category="cost",
        event_type="refund_requested",
        team_id="support",
        agent_id="support-agent",
        amount=50,
        requires_approval=True,
    )

    assert ledger.summarize()[0].pending_approvals == 1
    approved = ledger.approve(event.id, "operator-1")
    assert approved.approved_by == "operator-1"
    assert not approved.requires_approval
    assert ledger.summarize()[0].pending_approvals == 0


def test_rejects_unsafe_or_ambiguous_events(ledger):
    with pytest.raises(ValueError, match="category"):
        ledger.record(
            category="unknown",
            event_type="x",
            team_id="support",
            agent_id="agent",
        )
    with pytest.raises(ValueError, match="non-negative"):
        ledger.record(
            category="cost",
            event_type="x",
            team_id="support",
            agent_id="agent",
            amount=-1,
        )
    with pytest.raises(ValueError, match="already be approved"):
        ledger.record(
            category="activity",
            event_type="x",
            team_id="support",
            agent_id="agent",
            requires_approval=True,
            approved_by="operator",
        )
