"""Choosing who buys. Pure functions: same inputs, same answer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import AWAITING_MONEY, Office

FAIRNESS_WINDOW = timedelta(days=30)
_NEVER = datetime.min.replace(tzinfo=timezone.utc)


def is_eligible(employee, office: Office, today, presence) -> bool:
    """A volunteer who is physically at this office today.

    Home office does not matter: a Bengaluru volunteer visiting Oslo can refill
    the Oslo counter, and is not asked about Bengaluru while away.
    """
    return employee.is_volunteer and presence.office_on(employee.id, today) == office.code


def rank_candidates(office: Office, today, now: datetime, employees, presence,
                    refills, exclude=()) -> list:
    """Eligible volunteers, best candidate first.

    Order, most important first:
      1. fewest purchases still waiting for money  (don't pile debt on one person)
      2. fewest refills in the last 30 days        (spread the work)
      3. longest time since their last refill      (round-robin among equals)
      4. employee id                               (deterministic tie-break)
    Counts are per person across both offices, so nothing is compared across currencies.
    """
    refills = list(refills)

    def load(employee_id: str):
        mine = [r for r in refills if r.buyer == employee_id]
        waiting = sum(1 for r in mine if r.state in AWAITING_MONEY)
        recent = sum(1 for r in mine if now - r.purchased_at <= FAIRNESS_WINDOW)
        last = max((r.purchased_at for r in mine), default=_NEVER)
        return (waiting, recent, last, employee_id)

    eligible = [e.id for e in employees.values()
                if e.id not in exclude and is_eligible(e, office, today, presence)]
    return sorted(eligible, key=load)
