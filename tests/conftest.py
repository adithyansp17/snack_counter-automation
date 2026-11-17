"""Test world: the sample company plus the simulated chat, HR, presence and clock."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from snack_counter import RefillService
from snack_counter.fakes import UTC, FakeChat, FakeClock, FakeHR, FakePresence
from snack_counter.sample import make_employees, make_offices

RECEIPT = b"receipt-photo"


@pytest.fixture
def w():
    """The world: service plus its fakes. Starts Tue 10 Nov 2026, 09:00 UTC."""
    employees = make_employees()
    world = SimpleNamespace(
        clock=FakeClock(datetime(2026, 11, 10, 9, 0, tzinfo=UTC)),
        chat=FakeChat(), hr=FakeHR(), presence=FakePresence(employees),
        offices=make_offices(), employees=employees)
    world.svc = RefillService(world.offices, employees, world.presence,
                              world.chat, world.hr, world.clock)

    def buy(office, amount, reporter="guest"):
        """Shortcut: run one refill up to the filed claim. Returns the refill."""
        refill = world.svc.report_empty(office, reporter)
        buyer = refill.offered_to
        world.svc.commit(refill.id, buyer)
        return world.svc.record_purchase(refill.id, buyer, Decimal(amount), RECEIPT)

    world.buy = buy
    return world
