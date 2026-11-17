# Snack Counter Automation: design

## What "automate" means here

The snacks are not the problem; **ownership** is. Nobody owns an empty box, nobody knows whether someone else is already buying, and the buyer owns the paperwork. So I automate the coordination and the paperwork, and leave the shopping and HR's approval to people. A chat bot is the whole user interface, because every employee already uses the chat tool: no new app, no new login.

## How a refill moves from "empty" to "reimbursed"

```
report_empty ─► OFFERED ─► COMMITTED ─► PURCHASED ─► CLAIMED ─► REIMBURSED
                 │  ▲          │            ▲            └─► REJECTED (by HR)
        no answer 2h / "no"    │ no receipt in 24h
                 ▼  │          ▼            │
              next volunteer ◄─┘     NEEDS_APPROVAL ─► REJECTED (by admin)
                 │
   nobody left ─► OPEN (office channel told, retried every 4h)
   budget gone ─► BLOCKED_BUDGET (channel + admin told, resumes next month)
```

1. **Report.** Anyone in the office tells the bot the box is empty. If a refill is already in progress for that office, the report joins it; there is never more than one active refill per office.
2. **Budget check.** If the month's remaining budget is below a typical minimum purchase, nobody is asked; the office and its admin are told why.
3. **Offer.** The bot asks exactly **one** volunteer by direct message, with a spending cap (the smaller of the typical maximum and what is left this month) and a 2-hour deadline.
4. **Commit.** A "yes" is an atomic first-wins transition and is announced in the office channel. Any other present volunteer may step in before the asked person answers.
5. **Purchase.** The buyer posts the amount and a receipt photo. The bot files the HR claim immediately under the buyer's employee ID. If the amount exceeds the remaining budget, the office admin approves or rejects it first.
6. **Reimbursed.** The bot polls HR, tells the buyer when the claim is approved, and alerts the admin if it has waited more than 10 days.

## Main parts and the data each keeps

| Part | Responsibility | Data it keeps |
|---|---|---|
| **Refill service** (`service.py`) | The state machine; the only code that changes a refill | Refill records: office, state, who was asked / committed / passed, deadlines, amount, currency, receipt, items, HR claim ID, timestamps, audit history |
| **Buyer selection** (`selection.py`) | Ranks eligible volunteers | Nothing; derived from refill records and presence |
| **Budget and report** (`budget.py`) | Remaining budget per office and month; management report | Nothing; derived from refill records. Office config holds currency, budget, typical purchase range, time zone, admin |
| **Chat adapter** (simulated) | Sends direct and channel messages, receives commands | Nothing |
| **HR adapter** (simulated) | Creates claims with the five fields HR accepts, reads status | Nothing; HR stays the source of truth for approval and payment |
| **Presence** (simulated) | "Which office is this person in today?" | Nothing; would read desk booking, calendar or chat status |
| **Scheduler** | Calls `tick()` every few minutes | Nothing |

Spend, fairness and the report are all computed from the one refill table, so they cannot drift apart.

## How each problem is prevented

| Problem | Rule | Proved by |
|---|---|---|
| Box sits empty for days | One named person is asked, with a deadline. Silence, "no", or a missed purchase hands it on automatically. If everyone passes or nobody is in, the office channel is told and the bot keeps retrying. | `test_reassignment.py` |
| Two people buy the same day | One active refill per office; first commit wins, the rest are refused; the commit is announced. | `test_commit.py` |
| A few people do most refills | Ranking: fewest purchases still awaiting money, then fewest refills in 30 days, then longest since last refill. Only volunteers present at that office today are asked, visitors included. | `test_selection.py` |
| Weeks to get money back | The claim is filed the moment the receipt arrives; HR outages are retried without losing the receipt; overdue claims are escalated. People with money outstanding are asked last. | `test_lifecycle.py` |
| Nobody knows the spend | Every purchase is recorded against its office and month. One report gives each office in its own currency plus a single converted total. | `test_budget.py` |

## Money rules

Each office's budget is checked in its own currency; currencies are converted only in the report, using a rate passed in for that month. Amounts are decimals, never floats. Each office line is rounded and then summed, so the total equals what a reader adds up. A purchase belongs to the month of the **office's local clock**. A visitor's purchase is charged to the counter they filled, in that counter's currency; HR converts to their payroll currency.

## Trade-offs

- **Ask one person at a time, not the whole group.** Slower in the worst case, but a broadcast is exactly the "someone else will do it" failure we have today. Open step-in keeps goodwill possible.
- **Budget is checked twice, and the second check does not refuse.** Before asking, so nobody shops with no budget; at receipt, where an overspend goes to a human, because the volunteer has already paid.
- **Presence is a hint.** If it is wrong, the 2-hour timeout corrects it. I did not build a precise attendance source.
- **No reservation of budget at commit.** One active refill per office makes it unnecessary.
- **In-memory store and one lock.** Enough to prove the rules. In production the same rule is a conditional database update plus a unique index on active refills per office.
- **HR claims are not idempotent.** HR accepts only five fields, so a timeout after HR has accepted a claim could produce a duplicate on retry. I would ask HR for a lookup or idempotency key.

## Deliberately not built

- **Inventory or consumption tracking** (sensors, scanning, counting). Items are stored with each purchase, and the time between refills is a free signal of what gets eaten. Anything more costs more than the snacks.
- **Ordering, supplier integration, company cards.** A card would remove reimbursement entirely and is probably the better long-term answer, but it is a policy decision, not software.
- **Receipt OCR and fraud checks.** HR already approves every claim.
- **A production UI or dashboard.** Chat plus one monthly report covers every user. The included web page is only a test harness for the simulated systems.
- **Live exchange rates.** One agreed rate per month is reproducible and auditable.
- **Quiet hours, public holidays, manual cancel of a false report.** Needed before real use; small, and they do not change the design.

## Assumptions (questions sent to the team)

Reporting currency is NOK with one finance-supplied rate per month; HR accepts a claim in the purchase currency and converts to payroll currency; any employee may report an empty box; visiting volunteers may buy; an office admin exists who can approve overspend; budgets do not roll over.
