"""P13 unit tests: the priority formula, the SLA state evaluation and
the transition map's structural invariants (no DB needed)."""

import datetime as dt

import pytest

from app.models import AssetCriticality, EventSeverity, TicketStatus
from app.tickets import (
    AT_RISK_FRACTION,
    P1_MIN,
    P2_MIN,
    P3_MIN,
    SEVERITY_POINTS,
    compute_priority,
    confidence_points,
    evaluate_sla_state,
    TICKET_TRANSITIONS,
)

UTC = dt.timezone.utc


def ts(minutes: int) -> dt.datetime:
    return dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC) + dt.timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Priority formula (documented weights; boundaries pinned).
# ---------------------------------------------------------------------------


class TestPriorityFormula:
    def test_max_score_is_p1(self):
        assert compute_priority(EventSeverity.critical, AssetCriticality.critical, 0.99) == "P1"

    def test_exact_p1_boundary(self):
        # critical(40) + critical(30) + >=0.9 confidence(10) = 80
        assert compute_priority(EventSeverity.critical, AssetCriticality.critical, 0.9) == "P1"

    def test_just_below_p1(self):
        # high(30) + critical(30) + high confidence(10) = 70 -> P2
        assert compute_priority(EventSeverity.high, AssetCriticality.critical, 0.9) == "P2"

    def test_exact_p2_boundary(self):
        # high(30) + high(22) + high(10) = 62 -> P2; 60 exactly: medium(20)+critical(30)+high(10)
        assert compute_priority(EventSeverity.medium, AssetCriticality.critical, 0.9) == "P2"

    def test_just_below_p2(self):
        # high(30) + high(22) + mid(5) = 57 -> P3
        assert compute_priority(EventSeverity.high, AssetCriticality.high, 0.7) == "P3"

    def test_exact_p3_boundary(self):
        # medium(20) + medium(12) + mid(5) = 37; 35 exactly: medium(20)+high(22)... not reachable,
        # use low(10)+critical(30) minus... 10+22+5=37 too. 35 = medium(20)+low(5)+mid(10)?
        # 20+5+10=35 -> P3 exactly.
        assert compute_priority(EventSeverity.medium, AssetCriticality.low, 0.9) == "P3"

    def test_just_below_p3(self):
        # medium(20) + medium(12) = 32, no confidence -> P4
        assert compute_priority(EventSeverity.medium, AssetCriticality.medium, None) == "P4"

    def test_no_asset_no_confidence(self):
        assert compute_priority(EventSeverity.medium, None, None) == "P4"

    def test_info_is_lowest(self):
        assert compute_priority(EventSeverity.info, AssetCriticality.low, None) == "P4"

    def test_confidence_none_scores_zero(self):
        assert confidence_points(None) == 0

    def test_confidence_bands(self):
        assert confidence_points(0.89) == 5
        assert confidence_points(0.9) == 10
        assert confidence_points(0.69) == 0
        assert confidence_points(0.7) == 5

    def test_severity_ordering_is_monotonic(self):
        order = [EventSeverity.info, EventSeverity.low, EventSeverity.medium, EventSeverity.high, EventSeverity.critical]
        points = [SEVERITY_POINTS[s] for s in order]
        assert points == sorted(points)


# ---------------------------------------------------------------------------
# SLA state evaluation (controllable clock).
# ---------------------------------------------------------------------------


class TestSlaState:
    def _evaluate(self, **overrides):
        kwargs = dict(
            created_at=ts(0),
            acknowledged_at=None,
            ack_due_at=ts(60),
            resolve_due_at=ts(240),
            resolved_at=None,
            now=ts(0),
        )
        kwargs.update(overrides)
        return evaluate_sla_state(**kwargs)

    def test_fresh_ticket_is_on_track(self):
        assert self._evaluate(now=ts(10)) == (False, False)

    def test_at_risk_at_80_percent_of_ack_window(self):
        # ack window 0..60; 80% = minute 48
        at_risk, breached = self._evaluate(now=ts(48))
        assert at_risk is True and breached is False

    def test_not_at_risk_before_80_percent(self):
        at_risk, breached = self._evaluate(now=ts(47))
        assert at_risk is False and breached is False

    def test_breach_after_resolve_deadline(self):
        at_risk, breached = self._evaluate(now=ts(241))
        assert at_risk is True and breached is True

    def test_resolve_window_uses_ack_time_as_start(self):
        # acknowledged at minute 30 -> resolve window 30..240 (210 min);
        # 80% of that is minute 30 + 168 = 198
        at_risk, _ = self._evaluate(acknowledged_at=ts(30), now=ts(197))
        assert at_risk is False
        at_risk, _ = self._evaluate(acknowledged_at=ts(30), now=ts(198))
        assert at_risk is True

    def test_resolved_tickets_never_marked(self):
        assert self._evaluate(resolved_at=ts(10), now=ts(300)) == (False, False)

    def test_no_deadlines_never_marked(self):
        assert self._evaluate(ack_due_at=None, resolve_due_at=None, now=ts(100)) == (False, False)

    def test_breach_implies_at_risk(self):
        at_risk, breached = self._evaluate(now=ts(300))
        assert at_risk is True and breached is True


# ---------------------------------------------------------------------------
# Transition map structural invariants.
# ---------------------------------------------------------------------------


class TestTransitionMap:
    def test_all_nine_statuses_present(self):
        assert len(TicketStatus) == 9
        assert set(TICKET_TRANSITIONS.keys()) == set(TicketStatus)

    def test_closed_is_the_only_close_target(self):
        for current, targets in TICKET_TRANSITIONS.items():
            if TicketStatus.closed in targets:
                assert current == TicketStatus.resolved

    def test_only_resolved_and_closed_reopen(self):
        for current, targets in TICKET_TRANSITIONS.items():
            if TicketStatus.open in targets and current != TicketStatus.open:
                assert current in {TicketStatus.verification, TicketStatus.resolved, TicketStatus.closed}

    def test_it_ladder_exists(self):
        # OPEN -> ... -> INVESTIGATING -> REMEDIATION -> VERIFICATION reachable
        ladder = [
            TicketStatus.open,
            TicketStatus.investigating,
            TicketStatus.remediation,
            TicketStatus.verification,
        ]
        for step, nxt in zip(ladder, ladder[1:]):
            assert nxt in TICKET_TRANSITIONS[step]

    def test_verification_cannot_go_to_remediation_directly(self):
        assert TicketStatus.remediation not in TICKET_TRANSITIONS[TicketStatus.verification]
