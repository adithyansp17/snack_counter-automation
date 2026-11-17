"""Choosing who buys: only people who are there, and not the same people every time."""
from snack_counter import State


def today(w):
    return w.clock().date()


def test_people_at_home_or_on_holiday_are_not_asked(w):
    w.presence.set("kari", today(w), None)
    w.presence.set("nils", today(w), None)
    refill = w.svc.report_empty("OSL", "guest")
    assert refill.offered_to == "ola"


def test_nobody_in_the_office_goes_to_the_channel_then_retries_next_day(w):
    for person in ("kari", "nils", "ola"):
        w.presence.set(person, today(w), None)
    refill = w.svc.report_empty("OSL", "guest")
    assert refill.state is State.OPEN
    assert w.chat.sent_to("#snacks-oslo")

    w.clock.advance(days=1)                           # everyone is back
    w.svc.tick()
    assert refill.state is State.OFFERED


def test_visiting_volunteer_is_asked_at_the_office_they_are_in(w):
    for person in ("kari", "nils", "ola"):
        w.presence.set(person, today(w), None)
    w.presence.set("asha", today(w), "OSL")           # Bengaluru volunteer visiting Oslo

    oslo = w.svc.report_empty("OSL", "guest")
    assert oslo.offered_to == "asha"

    blr = w.svc.report_empty("BLR", "ravi")
    assert blr.offered_to != "asha"                   # and not asked about Bengaluru meanwhile


def test_visitor_buys_in_local_currency_and_claims_under_their_own_id(w):
    for person in ("kari", "nils", "ola"):
        w.presence.set(person, today(w), None)
    w.presence.set("asha", today(w), "OSL")
    refill = w.buy("OSL", "400")
    claim = w.hr.claims[refill.claim_id]
    assert (claim["currency"], claim["employee_id"]) == ("NOK", "asha")
    report = w.svc.monthly_report(2026, 11, "NOK", {"INR": 1})
    assert report["offices"]["OSL"]["spent"] == 400   # charged to the counter that was filled
    assert report["offices"]["BLR"]["spent"] == 0


def test_refills_rotate_instead_of_landing_on_the_same_person(w):
    buyers = [w.buy("OSL", "400").buyer for _ in range(3)]
    assert sorted(buyers) == ["kari", "nils", "ola"]


def test_someone_still_waiting_for_money_is_asked_last(w):
    first = w.buy("OSL", "400")                       # claim pending in HR
    w.clock.advance(days=40)                          # outside the 30-day fairness window
    for other in ("kari", "nils", "ola"):
        if other != first.buyer:
            done = w.buy("OSL", "400")
            w.hr.approve(done.claim_id)
    w.svc.tick()                                      # the other two are reimbursed

    refill = w.svc.report_empty("OSL", "guest")
    assert refill.offered_to != first.buyer           # although their last refill is the oldest


def test_recent_buyers_go_behind_those_who_have_not_bought_lately(w):
    done = w.buy("OSL", "400")
    w.hr.approve(done.claim_id)
    w.svc.tick()
    refill = w.svc.report_empty("OSL", "guest")
    assert refill.offered_to != done.buyer
