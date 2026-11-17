"""Budget check and the monthly report. Pure functions over the refill records.

Money is Decimal, never float. Each office's budget is checked in its own
currency; currencies are only converted in the management report.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from .models import AWAITING_MONEY, COUNTS_AS_SPEND, Office

CENT = Decimal("0.01")


def local_month(office: Office, moment: datetime) -> tuple:
    """The (year, month) a moment falls in at the office. 30 Nov 19:00 UTC is
    still November in Oslo, but already 1 December in Bengaluru."""
    local = moment.astimezone(ZoneInfo(office.timezone))
    return local.year, local.month


def _purchases(office: Office, year: int, month: int, refills):
    return [r for r in refills
            if r.office == office.code and r.state in COUNTS_AS_SPEND
            and local_month(office, r.purchased_at) == (year, month)]


def spent(office: Office, year: int, month: int, refills) -> Decimal:
    return sum((r.amount for r in _purchases(office, year, month, refills)), Decimal("0"))


def remaining(office: Office, year: int, month: int, refills) -> Decimal:
    return office.monthly_budget - spent(office, year, month, refills)


def monthly_report(offices: dict, refills, year: int, month: int,
                   reporting_currency: str, rates: dict) -> dict:
    """One report for management: per office in local currency, plus one total.

    rates maps currency -> value of 1 unit in the reporting currency,
    e.g. {"INR": Decimal("0.12")} when reporting in NOK. A missing rate is an
    error, never a silent zero.
    """
    refills = list(refills)
    report = {"month": f"{year}-{month:02d}", "reporting_currency": reporting_currency,
              "offices": {}, "total": Decimal("0")}
    for office in offices.values():
        purchases = _purchases(office, year, month, refills)
        total = sum((r.amount for r in purchases), Decimal("0"))
        if office.currency == reporting_currency:
            rate = Decimal("1")
        elif office.currency in rates:
            rate = rates[office.currency]
        else:
            raise ValueError(f"no exchange rate for {office.currency} -> {reporting_currency}")
        converted = (total * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        report["offices"][office.code] = {
            "currency": office.currency,
            "budget": office.monthly_budget,
            "spent": total,
            "remaining": office.monthly_budget - total,
            "refills": len(purchases),
            "awaiting_reimbursement": sum(
                (r.amount for r in purchases if r.state in AWAITING_MONEY), Decimal("0")),
            "spent_in_reporting_currency": converted,
        }
        # Sum the rounded lines so the total always equals what the reader adds up.
        report["total"] += converted
    return report
