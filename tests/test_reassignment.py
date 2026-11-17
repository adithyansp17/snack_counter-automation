"""Rule: a refill nobody completes is handed to someone else."""
from decimal import Decimal

import pytest

from snack_counter import InvalidTransition, State

from conftest import RECEIPT


def test_unanswered_offer_moves_to_the_next_volunteer(w):
    refill = w.svc.report_empty("OSL", "guest")
    first = refill.offered_to

    w.clock.advance(hours=1, minutes=59)
    w.svc.tick()
    assert refill.offered_to == first                 # still inside the 2 hours

    w.clock.advance(minutes=1)
    w.svc.tick()
    assert refill.state is State.OFFERED
    assert refill.offered_to not in (None, first)


def test_decline_moves_on_immediately(w):
    refill = w.svc.report_empty("OSL", "guest")
    first = refill.offered_to
    w.svc.decline(refill.id, first)
    assert refill.offered_to not in (None, first)


def test_committed_but_never_bought_is_handed_to_someone_else(w):
    refill = w.svc.report_empty("OSL", "guest")
    flaky = refill.offered_to
    w.svc.commit(refill.id, flaky)

    w.clock.advance(hours=24)
    w.svc.tick()

    assert refill.state is State.OFFERED
    assert refill.committed_by is None
    assert refill.offered_to != flaky
    with pytest.raises(InvalidTransition):            # the old holder can no longer claim for it
        w.svc.record_purchase(refill.id, flaky, Decimal("500"), RECEIPT)

    w.svc.commit(refill.id, refill.offered_to)        # and the new person can finish it
    assert refill.state is State.COMMITTED


def test_committed_volunteer_can_back_out(w):
    refill = w.svc.report_empty("OSL", "guest")
    first = refill.offered_to
    w.svc.commit(refill.id, first)
    w.svc.decline(refill.id, first)
    assert refill.state is State.OFFERED and refill.offered_to != first


def test_when_everyone_passes_the_office_is_told_and_the_rotation_restarts(w):
    refill = w.svc.report_empty("OSL", "guest")
    asked = []
    for _ in range(3):
        asked.append(refill.offered_to)
        w.svc.decline(refill.id, refill.offered_to)

    assert sorted(asked) == ["kari", "nils", "ola"]   # each asked once, nobody twice
    assert refill.state is State.OPEN
    assert "no volunteer could take it" in w.chat.sent_to("#snacks-oslo")[-1]

    w.clock.advance(hours=4)
    w.svc.tick()
    assert refill.state is State.OFFERED              # it never silently dies


def test_open_refill_can_be_claimed_by_any_volunteer_in_the_office(w):
    refill = w.svc.report_empty("OSL", "guest")
    for _ in range(3):
        w.svc.decline(refill.id, refill.offered_to)
    w.svc.commit(refill.id, "nils")
    assert refill.committed_by == "nils"
