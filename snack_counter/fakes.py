"""Simulated stand-ins for everything outside our control.

The service only uses the small method surface shown here, so a real chat bot,
HR client or calendar integration can replace each class without touching the rules.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional


class FakeClock:
    """Time is injected so timeouts can be tested without sleeping."""

    def __init__(self, start: datetime):
        assert start.tzinfo is not None, "use timezone-aware datetimes"
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class FakeChat:
    """Chat tool: records every message so tests can assert who was told what."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []   # (recipient or channel, text)

    def send(self, to: str, text: str) -> None:
        self.messages.append((to, text))

    def sent_to(self, to: str) -> list[str]:
        return [text for recipient, text in self.messages if recipient == to]


class HRUnavailable(Exception):
    pass


class FakeHR:
    """External HR system. Accepts exactly the five fields the brief lists."""

    def __init__(self):
        self.claims: dict[str, dict] = {}
        self.down = False

    def create_claim(self, amount: Decimal, currency: str, description: str,
                     receipt_image: bytes, employee_id: str) -> str:
        if self.down:
            raise HRUnavailable("HR system did not respond")
        claim_id = f"HR-{len(self.claims) + 1}"
        self.claims[claim_id] = dict(amount=amount, currency=currency, description=description,
                                     receipt_image=receipt_image, employee_id=employee_id,
                                     status="pending")
        return claim_id

    def status(self, claim_id: str) -> str:
        if self.down:
            raise HRUnavailable("HR system did not respond")
        return self.claims[claim_id]["status"]

    # --- test/demo controls: what the HR team would do on their side ---
    def approve(self, claim_id: str) -> None:
        self.claims[claim_id]["status"] = "approved"

    def reject(self, claim_id: str) -> None:
        self.claims[claim_id]["status"] = "rejected"


class FakePresence:
    """Where is an employee today? Defaults to their home office.

    Real sources would be the desk-booking tool, calendar or chat status. It is
    only a hint: the offer timeout is what actually protects against a wrong answer.
    """

    def __init__(self, employees: dict):
        self._employees = employees
        self._overrides: dict[tuple[str, date], Optional[str]] = {}

    def set(self, employee_id: str, day: date, location: Optional[str]) -> None:
        """location: an office code, or None for home / holiday."""
        self._overrides[(employee_id, day)] = location

    def office_on(self, employee_id: str, day: date) -> Optional[str]:
        if (employee_id, day) in self._overrides:
            return self._overrides[(employee_id, day)]
        return self._employees[employee_id].home_office


UTC = timezone.utc
