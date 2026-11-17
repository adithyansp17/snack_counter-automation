"""Rule: budgets and totals are correct across both currencies."""
from datetime import datetime
from decimal import Decimal

import pytest

from snack_counter import NotEligible, State
from snack_counter.fakes import UTC

RATES = {"INR": Decimal("0.1234")}                    # 1 INR = 0.1234 NOK


def report(w, month=11):
    return w.svc.monthly_report(2026, month, "NOK", RATES)


def test_each_office_is_checked_against_its_own_budget_in_its_own_currency(w):
    w.buy("OSL", "1000")
    w.buy("BLR", "2500")
    offices = report(w)["offices"]
    assert (offices["OSL"]["spent"], offices["OSL"]["remaining"]) == (Decimal("1000"), Decimal("5000"))
    assert (offices["BLR"]["spent"], offices["BLR"]["remaining"]) == (Decimal("2500"), Decimal("12500"))


def test_report_total_converts_to_one_currency_and_adds_up(w):
    w.buy("OSL", "1000.50")
    w.buy("BLR", "2500")
    w.buy("BLR", "333.33")
    r = report(w)
    # 2833.33 INR * 0.1234 = 349.632922 -> 349.63 NOK
    assert r["offices"]["BLR"]["spent_in_reporting_currency"] == Decimal("349.63")
    assert r["total"] == Decimal("1350.13")
    assert r["total"] == sum(o["spent_in_reporting_currency"] for o in r["offices"].values())
    assert r["offices"]["BLR"]["refills"] == 2


def test_missing_exchange_rate_is_an_error_not_a_zero(w):
    w.buy("BLR", "2500")
    with pytest.raises(ValueError):
        w.svc.monthly_report(2026, 11, "NOK", {})


def test_buyer_is_told_a_cap_that_fits_the_remaining_budget(w):
    assert w.svc.report_empty("OSL", "guest").cap == Decimal("1200")      # typical maximum
    w.svc.commit("R1", "kari")
    w.svc.record_purchase("R1", "kari", Decimal("1200"), b"r")
    for _ in range(3):
        w.buy("OSL", "1200")
    w.buy("OSL", "600")                                                   # 5400 spent
    assert w.svc.report_empty("OSL", "guest").cap == Decimal("600")       # what is left


def test_nobody_is_sent_shopping_when_the_budget_is_used_up(w):
    for _ in range(4):
        w.buy("OSL", "1200")
    w.buy("OSL", "1000")                              # 5800 of 6000 spent, 200 left < 300 minimum
    before = len(w.chat.messages)

    refill = w.svc.report_empty("OSL", "guest")
    assert refill.state is State.BLOCKED_BUDGET and refill.offered_to is None
    told = {to for to, _ in w.chat.messages[before:]}
    assert told == {"#snacks-oslo", "osl-admin"}      # office and admin know why; no volunteer asked

    assert w.svc.report_empty("BLR", "ravi").state is State.OFFERED       # Bengaluru unaffected


def test_blocked_refill_resumes_when_the_new_month_starts(w):
    for _ in range(5):
        w.buy("OSL", "1200")
    refill = w.svc.report_empty("OSL", "guest")
    assert refill.state is State.BLOCKED_BUDGET

    w.clock.now = datetime(2026, 12, 1, 8, 0, tzinfo=UTC)
    w.svc.tick()
    assert refill.state is State.OFFERED


def test_purchase_over_the_remaining_budget_waits_for_the_admin(w):
    for _ in range(4):
        w.buy("OSL", "1200")                          # 4800 spent, 1200 left
    claims_before = len(w.hr.claims)
    refill = w.buy("OSL", "1500")

    assert refill.state is State.NEEDS_APPROVAL
    assert len(w.hr.claims) == claims_before          # nothing filed yet
    assert report(w)["offices"]["OSL"]["remaining"] == Decimal("-300")    # but visible in the numbers

    with pytest.raises(NotEligible):
        w.svc.approve_overage(refill.id, "kari")      # only the office admin decides
    w.svc.approve_overage(refill.id, "osl-admin")
    assert refill.state is State.CLAIMED


def test_rejected_overage_does_not_count_as_spend(w):
    for _ in range(4):
        w.buy("OSL", "1200")
    refill = w.buy("OSL", "1500")
    w.svc.reject_overage(refill.id, "osl-admin")
    assert refill.state is State.REJECTED
    assert report(w)["offices"]["OSL"]["spent"] == Decimal("4800")


def test_month_is_decided_by_the_office_clock_not_utc(w):
    # 30 Nov 19:00 UTC is 20:00 in Oslo (November) but 1 Dec 00:30 in Bengaluru (December).
    w.clock.now = datetime(2026, 11, 30, 19, 0, tzinfo=UTC)
    w.buy("OSL", "500")
    w.buy("BLR", "900")
    assert report(w, 11)["offices"]["OSL"]["spent"] == Decimal("500")
    assert report(w, 11)["offices"]["BLR"]["spent"] == Decimal("0")
    assert report(w, 12)["offices"]["BLR"]["spent"] == Decimal("900")


def test_report_shows_money_volunteers_are_still_waiting_for(w):
    paid = w.buy("OSL", "500")
    w.buy("OSL", "700")
    w.hr.approve(paid.claim_id)
    w.svc.tick()
    assert report(w)["offices"]["OSL"]["awaiting_reimbursement"] == Decimal("700")
