"""A refill's path from "empty" to "reimbursed", and what happens when HR misbehaves."""
from decimal import Decimal

from snack_counter import State

from conftest import RECEIPT


def test_refill_goes_from_empty_to_reimbursed(w):
    refill = w.svc.report_empty("OSL", "guest")
    assert refill.state is State.OFFERED
    buyer = refill.offered_to
    assert len(w.chat.sent_to(buyer)) == 1            # exactly one person is asked

    w.svc.commit(refill.id, buyer)
    assert refill.state is State.COMMITTED

    w.svc.record_purchase(refill.id, buyer, Decimal("850.50"), RECEIPT, items=["fruit", "nuts"])
    assert refill.state is State.CLAIMED              # claim filed without the buyer doing anything
    claim = w.hr.claims[refill.claim_id]
    assert (claim["amount"], claim["currency"], claim["employee_id"], claim["receipt_image"]) == \
           (Decimal("850.50"), "NOK", buyer, RECEIPT)

    w.clock.advance(days=3)
    w.hr.approve(refill.claim_id)
    w.svc.tick()
    assert refill.state is State.REIMBURSED


def test_second_empty_report_joins_the_refill_in_progress(w):
    first = w.svc.report_empty("OSL", "guest")
    second = w.svc.report_empty("OSL", "ola")
    assert second is first
    assert len(w.svc.refills) == 1
    offers = [m for m in w.chat.messages if "your turn" in m[1]]
    assert len(offers) == 1                           # still only one person asked


def test_each_office_has_its_own_refill(w):
    assert w.svc.report_empty("OSL", "guest") is not w.svc.report_empty("BLR", "asha")


def test_box_can_be_reported_empty_again_after_a_purchase(w):
    first = w.buy("OSL", "500")
    second = w.svc.report_empty("OSL", "guest")
    assert second is not first


def test_hr_outage_keeps_the_receipt_and_files_exactly_one_claim_later(w):
    w.hr.down = True
    refill = w.buy("OSL", "500")
    assert refill.state is State.PURCHASED and refill.receipt_image == RECEIPT
    w.svc.tick()
    assert w.hr.claims == {}

    w.hr.down = False
    w.svc.tick()
    w.svc.tick()
    assert refill.state is State.CLAIMED
    assert len(w.hr.claims) == 1


def test_hr_rejection_is_surfaced_and_is_not_company_spend(w):
    refill = w.buy("OSL", "500")
    w.hr.reject(refill.claim_id)
    w.svc.tick()
    assert refill.state is State.REJECTED
    assert w.chat.sent_to(refill.buyer)[-1].startswith("HR rejected")
    assert w.svc.monthly_report(2026, 11, "NOK", {"INR": Decimal("0.12")})["offices"]["OSL"]["spent"] == 0


def test_claim_waiting_more_than_ten_days_is_chased_once(w):
    refill = w.buy("OSL", "500")
    w.clock.advance(days=11)
    w.svc.tick()
    w.svc.tick()
    chasers = [m for m in w.chat.sent_to("osl-admin") if "more than 10 days" in m]
    assert len(chasers) == 1
    assert refill.state is State.CLAIMED
