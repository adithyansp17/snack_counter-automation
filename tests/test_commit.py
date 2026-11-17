"""Rule: two people cannot both commit to the same refill."""
import threading
from decimal import Decimal

import pytest

from snack_counter import AlreadyCommitted, InvalidTransition, NotEligible, State

from conftest import RECEIPT


def test_second_commit_is_refused(w):
    refill = w.svc.report_empty("OSL", "guest")
    w.svc.commit(refill.id, "kari")
    with pytest.raises(AlreadyCommitted):
        w.svc.commit(refill.id, "ola")
    assert refill.committed_by == "kari"


def test_simultaneous_commits_have_exactly_one_winner(w):
    refill = w.svc.report_empty("OSL", "guest")
    racers = ["kari", "nils", "ola"] * 10
    start = threading.Barrier(len(racers))
    won, lost = [], []

    def race(person):
        start.wait()
        try:
            w.svc.commit(refill.id, person)
            won.append(person)
        except AlreadyCommitted:
            lost.append(person)

    threads = [threading.Thread(target=race, args=(p,)) for p in racers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(won) == 1 and len(lost) == len(racers) - 1
    assert refill.committed_by == won[0]


def test_another_volunteer_may_step_in_before_the_asked_person_answers(w):
    refill = w.svc.report_empty("OSL", "guest")
    asked = refill.offered_to
    helper = next(p for p in ("kari", "nils", "ola") if p != asked)
    w.svc.commit(refill.id, helper)
    assert refill.committed_by == helper
    assert "No need to buy" in w.chat.sent_to(asked)[-1]      # the asked person is stood down


def test_only_volunteers_present_at_that_office_can_commit(w):
    refill = w.svc.report_empty("OSL", "guest")
    with pytest.raises(NotEligible):
        w.svc.commit(refill.id, "guest")                      # not a volunteer
    with pytest.raises(NotEligible):
        w.svc.commit(refill.id, "asha")                       # volunteer, but in Bengaluru
    assert refill.state is State.OFFERED


def test_only_the_committed_buyer_can_submit_the_receipt(w):
    refill = w.svc.report_empty("OSL", "guest")
    w.svc.commit(refill.id, "kari")
    with pytest.raises(InvalidTransition):
        w.svc.record_purchase(refill.id, "ola", Decimal("500"), RECEIPT)
    assert w.hr.claims == {}


def test_a_receipt_is_required(w):
    refill = w.svc.report_empty("OSL", "guest")
    w.svc.commit(refill.id, "kari")
    with pytest.raises(ValueError):
        w.svc.record_purchase(refill.id, "kari", Decimal("500"), b"")
    assert refill.state is State.COMMITTED
