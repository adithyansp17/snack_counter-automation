"""The refill lifecycle: the only place that changes a refill's state.

    report_empty -> OFFERED -> COMMITTED -> PURCHASED -> CLAIMED -> REIMBURSED
                      |  ^         |            ^
              timeout/decline   timeout     NEEDS_APPROVAL (over budget, admin decides)
                      v  |         v
                  next volunteer, or OPEN + channel broadcast if nobody is in

Chat commands and a scheduler would call the public methods; `tick()` is the
scheduler entry point (run every few minutes).
"""
from __future__ import annotations

import threading
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from . import budget
from .models import (ACTIVE, AlreadyCommitted, InvalidTransition, NotEligible, Refill, State)
from .selection import is_eligible, rank_candidates

OFFER_TIMEOUT = timedelta(hours=2)      # time to answer "can you buy?"
PURCHASE_TIMEOUT = timedelta(hours=24)  # time to buy after saying yes
RETRY_INTERVAL = timedelta(hours=4)     # when nobody is available, ask again after this
CLAIM_OVERDUE = timedelta(days=10)      # HR's stated maximum; after this we chase


class RefillService:
    def __init__(self, offices: dict, employees: dict, presence, chat, hr, clock):
        self.offices = offices
        self.employees = employees
        self.presence = presence
        self.chat = chat
        self.hr = hr
        self.clock = clock
        self.refills = {}   # refill id -> Refill
        # One lock makes every transition atomic in this single process. With a
        # database this becomes a conditional update ("... WHERE state = 'offered'")
        # plus a unique index on (office) for active refills.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ reporting

    def report_empty(self, office_code: str, reporter_id: str) -> Refill:
        """Anyone at the office can say the box is empty. A second report while a
        refill is already in progress joins it instead of starting another."""
        with self._lock:
            existing = self.active_refill(office_code)
            if existing:
                self.chat.send(reporter_id, f"Thanks - already on it ({self._who_has(existing)}).")
                return existing
            refill = Refill(id=f"R{len(self.refills) + 1}", office=office_code,
                            reported_by=reporter_id, reported_at=self.clock())
            refill.history.append((self.clock(), State.OPEN, f"reported by {reporter_id}"))
            self.refills[refill.id] = refill
            self._assign(refill)
            return refill

    def active_refill(self, office_code: str):
        return next((r for r in self.refills.values()
                     if r.office == office_code and r.state in ACTIVE), None)

    # ------------------------------------------------------------------ volunteers

    def commit(self, refill_id: str, employee_id: str) -> Refill:
        """"I'll buy." First commit wins; everyone after gets AlreadyCommitted.

        The person who was asked has no exclusive right: any eligible volunteer
        may step in while nobody has committed yet.
        """
        with self._lock:
            refill = self.refills[refill_id]
            office = self.offices[refill.office]
            if refill.state is State.COMMITTED:
                raise AlreadyCommitted(f"{refill.committed_by} is already buying for {refill.office}")
            if refill.state not in (State.OPEN, State.OFFERED):
                raise InvalidTransition(f"refill {refill.id} is {refill.state.value}")
            if not is_eligible(self.employees[employee_id], office, self._today(office), self.presence):
                raise NotEligible(f"{employee_id} is not a volunteer at {office.code} today")
            if refill.offered_to and refill.offered_to != employee_id:
                self.chat.send(refill.offered_to, f"No need to buy snacks: {employee_id} has it.")
            refill.offered_to = refill.offer_expires_at = refill.retry_at = None
            refill.committed_by = employee_id
            refill.purchase_deadline = self.clock() + PURCHASE_TIMEOUT
            self._set(refill, State.COMMITTED, f"committed by {employee_id}")
            self.chat.send(office.channel,
                           f"{employee_id} is refilling the snack box. Nobody else needs to buy.")
            return refill

    def decline(self, refill_id: str, employee_id: str) -> Refill:
        """"Not me" from the person asked, or backing out after committing."""
        with self._lock:
            refill = self.refills[refill_id]
            holder = (refill.offered_to if refill.state is State.OFFERED else
                      refill.committed_by if refill.state is State.COMMITTED else None)
            if holder != employee_id:
                raise InvalidTransition(f"{employee_id} does not hold refill {refill.id}")
            self._hand_over(refill, f"{employee_id} declined")
            return refill

    def record_purchase(self, refill_id: str, employee_id: str, amount: Decimal,
                        receipt_image: bytes, items=()) -> Refill:
        """The committed volunteer posts amount + receipt photo. The claim is
        filed for them straight away, so nobody waits on their own paperwork."""
        with self._lock:
            refill = self.refills[refill_id]
            office = self.offices[refill.office]
            if refill.state is not State.COMMITTED or refill.committed_by != employee_id:
                raise InvalidTransition(f"{employee_id} is not the committed buyer of {refill.id}")
            amount = Decimal(amount)
            if amount <= 0 or not receipt_image:
                raise ValueError("a positive amount and a receipt image are required")
            now = self.clock()
            left = budget.remaining(office, *budget.local_month(office, now), self.refills.values())
            refill.buyer, refill.amount, refill.currency = employee_id, amount, office.currency
            refill.receipt_image, refill.items, refill.purchased_at = receipt_image, tuple(items), now
            if amount > left:
                # The money is already spent, so we neither refuse it nor wave it
                # through: a human decides, and the budget shows it meanwhile.
                self._set(refill, State.NEEDS_APPROVAL, f"{amount} exceeds remaining {left}")
                self.chat.send(office.admin_id,
                               f"{employee_id} spent {amount} {office.currency} on snacks but only "
                               f"{left} {office.currency} of this month's budget was left. Approve?")
            else:
                self._set(refill, State.PURCHASED, f"{amount} {office.currency}")
                self._file_claim(refill)
            return refill

    # ------------------------------------------------------------------ admin

    def approve_overage(self, refill_id: str, approver_id: str) -> Refill:
        with self._lock:
            refill = self._overage(refill_id, approver_id)
            self._set(refill, State.PURCHASED, f"overage approved by {approver_id}")
            self._file_claim(refill)
            return refill

    def reject_overage(self, refill_id: str, approver_id: str) -> Refill:
        with self._lock:
            refill = self._overage(refill_id, approver_id)
            self._set(refill, State.REJECTED, f"overage rejected by {approver_id}")
            self.chat.send(refill.buyer, "Your over-budget snack purchase was not approved.")
            return refill

    # ------------------------------------------------------------------ scheduler

    def tick(self) -> None:
        """Everything time-driven: expired offers, missed purchases, retries,
        unfiled claims and HR approvals. Safe to call as often as you like."""
        with self._lock:
            now = self.clock()
            for refill in list(self.refills.values()):
                if refill.state is State.OFFERED and now >= refill.offer_expires_at:
                    self._hand_over(refill, f"{refill.offered_to} did not answer")
                elif refill.state is State.COMMITTED and now >= refill.purchase_deadline:
                    self.chat.send(refill.committed_by,
                                   "You didn't get to the snack run, so I've passed it on.")
                    self._hand_over(refill, f"{refill.committed_by} did not buy in time")
                elif refill.state is State.OPEN and now >= refill.retry_at:
                    self._assign(refill)
                elif refill.state is State.BLOCKED_BUDGET:
                    self._assign(refill)          # unblocks itself when a new month starts
                elif refill.state is State.PURCHASED:
                    self._file_claim(refill)      # HR was down earlier: try again
                elif refill.state is State.CLAIMED:
                    self._sync_claim(refill)

    def monthly_report(self, year: int, month: int, reporting_currency: str, rates: dict) -> dict:
        with self._lock:
            return budget.monthly_report(self.offices, list(self.refills.values()),
                                         year, month, reporting_currency, rates)

    # ------------------------------------------------------------------ internals

    def _assign(self, refill: Refill) -> None:
        """Budget check first, then ask exactly one person."""
        office = self.offices[refill.office]
        now = self.clock()
        left = budget.remaining(office, *budget.local_month(office, now), self.refills.values())
        if left < office.min_purchase:
            if refill.state is not State.BLOCKED_BUDGET:
                self._set(refill, State.BLOCKED_BUDGET, f"only {left} left")
                text = (f"The snack box is empty but only {left} {office.currency} of this "
                        f"month's budget is left, so nobody is being asked to buy.")
                self.chat.send(office.channel, text)
                self.chat.send(office.admin_id, text)
            return
        refill.cap = min(office.max_purchase, left)
        ranked = rank_candidates(office, self._today(office), now, self.employees,
                                 self.presence, self.refills.values(), exclude=refill.passed)
        if not ranked:
            # Everyone eligible has passed or nobody is in. Tell the whole office,
            # start the rotation afresh and try again later.
            refill.offered_to = refill.offer_expires_at = None
            refill.passed.clear()
            refill.retry_at = now + RETRY_INTERVAL
            self._set(refill, State.OPEN, "no volunteer available")
            self.chat.send(office.channel,
                           f"The snack box is empty and no volunteer could take it. Any volunteer "
                           f"in the office can claim it (up to {refill.cap} {office.currency}).")
            return
        refill.offered_to = ranked[0]
        refill.offer_expires_at = now + OFFER_TIMEOUT
        refill.retry_at = None
        self._set(refill, State.OFFERED, f"offered to {ranked[0]}")
        self.chat.send(ranked[0],
                       f"The {office.code} snack box is empty and it's your turn. Can you refill it "
                       f"(up to {refill.cap} {office.currency})? Reply yes or no within 2 hours.")

    def _hand_over(self, refill: Refill, reason: str) -> None:
        refill.passed.add(refill.offered_to or refill.committed_by)
        refill.offered_to = refill.committed_by = None
        refill.offer_expires_at = refill.purchase_deadline = None
        refill.history.append((self.clock(), refill.state, reason))
        self._assign(refill)

    def _file_claim(self, refill: Refill) -> None:
        office = self.offices[refill.office]
        try:
            refill.claim_id = self.hr.create_claim(
                amount=refill.amount, currency=refill.currency,
                description=f"Snack refill {refill.id}, {office.code} office",
                receipt_image=refill.receipt_image, employee_id=refill.buyer)
        except Exception:
            return  # stays PURCHASED with the receipt safe; tick() retries
        refill.claimed_at = self.clock()
        self._set(refill, State.CLAIMED, refill.claim_id)
        self.chat.send(refill.buyer,
                       f"Thanks! Reimbursement claim {refill.claim_id} for {refill.amount} "
                       f"{refill.currency} is filed. HR usually approves within 10 days.")

    def _sync_claim(self, refill: Refill) -> None:
        office = self.offices[refill.office]
        try:
            status = self.hr.status(refill.claim_id)
        except Exception:
            return
        if status == "approved":
            refill.reimbursed_at = self.clock()
            self._set(refill, State.REIMBURSED, refill.claim_id)
            self.chat.send(refill.buyer, f"Claim {refill.claim_id} was approved.")
        elif status == "rejected":
            self._set(refill, State.REJECTED, f"HR rejected {refill.claim_id}")
            self.chat.send(refill.buyer, f"HR rejected claim {refill.claim_id}.")
            self.chat.send(office.admin_id, f"HR rejected snack claim {refill.claim_id}.")
        elif self.clock() - refill.claimed_at > CLAIM_OVERDUE and not refill.overdue_flagged:
            refill.overdue_flagged = True
            self.chat.send(office.admin_id,
                           f"Claim {refill.claim_id} ({refill.buyer}, {refill.amount} "
                           f"{refill.currency}) has waited more than 10 days in HR.")

    def _overage(self, refill_id: str, approver_id: str) -> Refill:
        refill = self.refills[refill_id]
        if refill.state is not State.NEEDS_APPROVAL:
            raise InvalidTransition(f"refill {refill.id} is {refill.state.value}")
        if approver_id != self.offices[refill.office].admin_id:
            raise NotEligible(f"{approver_id} cannot approve spend for {refill.office}")
        return refill

    def _set(self, refill: Refill, state: State, note: str = "") -> None:
        refill.state = state
        refill.history.append((self.clock(), state, note))

    def _today(self, office):
        return self.clock().astimezone(ZoneInfo(office.timezone)).date()

    def _who_has(self, refill: Refill) -> str:
        if refill.state is State.COMMITTED:
            return f"{refill.committed_by} is buying"
        if refill.state is State.OFFERED:
            return f"{refill.offered_to} has been asked"
        if refill.state is State.BLOCKED_BUDGET:
            return "waiting for budget"
        return "looking for a volunteer"
