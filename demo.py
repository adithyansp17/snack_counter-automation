"""Run one Oslo refill end to end and print the chat transcript: python demo.py"""
from datetime import datetime
from decimal import Decimal

from snack_counter import RefillService, SnackError
from snack_counter.fakes import UTC, FakeChat, FakeClock, FakeHR, FakePresence
from snack_counter.sample import make_employees, make_offices

employees = make_employees()
clock = FakeClock(datetime(2026, 11, 10, 9, 0, tzinfo=UTC))
chat, hr = FakeChat(), FakeHR()
svc = RefillService(make_offices(), employees, FakePresence(employees), chat, hr, clock)


def show(step):
    print(f"\n== {step}")
    for to, text in chat.messages:
        print(f"   -> {to}: {text}")
    chat.messages.clear()


refill = svc.report_empty("OSL", "guest")
show(f"guest reports the Oslo box empty; {refill.offered_to} is asked")

clock.advance(hours=2)
svc.tick()
show(f"no answer for 2 hours; handed to {refill.offered_to}")

buyer = refill.offered_to
svc.commit(refill.id, buyer)
show(f"{buyer} commits")

try:
    svc.commit(refill.id, "ola" if buyer != "ola" else "kari")
except SnackError as error:
    print(f"\n== a second volunteer tries to commit\n   refused: {error}")

svc.record_purchase(refill.id, buyer, Decimal("850.50"), b"receipt.jpg", items=["fruit", "nuts"])
show(f"{buyer} posts the receipt")

clock.advance(days=3)
hr.approve(refill.claim_id)
svc.tick()
show("HR approves three days later")

second = svc.report_empty("BLR", "ravi")
svc.commit(second.id, second.offered_to)
svc.record_purchase(second.id, second.committed_by, Decimal("2500"), b"receipt.jpg")
chat.messages.clear()

print("\n== November report for management (NOK, 1 INR = 0.12 NOK)")
report = svc.monthly_report(2026, 11, "NOK", {"INR": Decimal("0.12")})
for code, line in report["offices"].items():
    print(f"   {code}: spent {line['spent']} of {line['budget']} {line['currency']}"
          f" = {line['spent_in_reporting_currency']} NOK, {line['refills']} refill(s),"
          f" {line['awaiting_reimbursement']} {line['currency']} awaiting reimbursement")
print(f"   TOTAL: {report['total']} NOK")
