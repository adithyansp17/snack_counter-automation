"""Data the snack counter keeps. No behaviour lives here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class State(str, Enum):
    OPEN = "open"                      # reported empty, nobody holds it right now
    OFFERED = "offered"                # one volunteer has been asked and has a deadline
    COMMITTED = "committed"            # one volunteer said "I'll buy" and has a deadline
    NEEDS_APPROVAL = "needs_approval"  # bought, but over the remaining budget: admin decides
    PURCHASED = "purchased"            # receipt recorded, claim not yet filed in HR
    CLAIMED = "claimed"                # claim filed in HR, waiting for approval
    REIMBURSED = "reimbursed"          # HR approved: done
    REJECTED = "rejected"              # admin or HR said no: not company spend
    BLOCKED_BUDGET = "blocked_budget"  # month's budget cannot cover a typical purchase


# A refill in one of these states "owns" the office's counter: no second refill can start.
ACTIVE = {State.OPEN, State.OFFERED, State.COMMITTED, State.BLOCKED_BUDGET}
# States whose amount counts against the office's monthly budget.
COUNTS_AS_SPEND = {State.NEEDS_APPROVAL, State.PURCHASED, State.CLAIMED, State.REIMBURSED}
# States where the buyer is still out of pocket.
AWAITING_MONEY = {State.NEEDS_APPROVAL, State.PURCHASED, State.CLAIMED}


@dataclass(frozen=True)
class Office:
    code: str                # "OSL", "BLR"
    currency: str            # budget and purchases at this counter are in this currency
    monthly_budget: Decimal
    min_purchase: Decimal    # below this remaining budget, a shopping trip is not worth asking for
    max_purchase: Decimal    # cap suggested to the buyer for one trip
    timezone: str            # month boundaries follow the office's local time
    channel: str             # office snack channel in the chat tool
    admin_id: str            # approves over-budget purchases, hears about escalations


@dataclass(frozen=True)
class Employee:
    id: str
    name: str
    home_office: str
    is_volunteer: bool = False


@dataclass
class Refill:
    id: str
    office: str
    reported_by: str
    reported_at: datetime
    state: State = State.OPEN
    # assignment
    offered_to: Optional[str] = None
    offer_expires_at: Optional[datetime] = None
    committed_by: Optional[str] = None
    purchase_deadline: Optional[datetime] = None
    passed: set = field(default_factory=set)   # declined / timed out on this refill
    retry_at: Optional[datetime] = None         # when OPEN: next attempt to find a buyer
    cap: Optional[Decimal] = None               # spending limit told to the buyer
    # purchase
    buyer: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    receipt_image: Optional[bytes] = None
    items: tuple = ()
    purchased_at: Optional[datetime] = None
    # reimbursement
    claim_id: Optional[str] = None
    claimed_at: Optional[datetime] = None
    reimbursed_at: Optional[datetime] = None
    overdue_flagged: bool = False
    history: list = field(default_factory=list)  # (time, state, note) audit trail


class SnackError(Exception):
    """Base class for rule violations."""


class AlreadyCommitted(SnackError):
    pass


class NotEligible(SnackError):
    pass


class InvalidTransition(SnackError):
    pass
