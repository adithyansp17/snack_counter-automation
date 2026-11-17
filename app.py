"""Snack Counter: a local web app to drive the refill logic by hand.

    python app.py            then open http://localhost:8000

Standard library only. Chat, HR, presence and the clock are the simulated
stand-ins; the page lets you play every role (reporter, volunteers, admin, HR)
and move time forward to trigger timeouts. State lives in memory: restart or
press Reset to start again.
"""
import json
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from snack_counter import RefillService, SnackError, budget
from snack_counter.fakes import FakeClock, FakeHR
from snack_counter.sample import make_employees, make_offices

INDEX = Path(__file__).parent / "web" / "index.html"
REPORTING_CURRENCY = "NOK"
RATES = {"INR": Decimal("0.12")}        # 1 INR in NOK; a real system gets this from finance
TIME_FORMAT = "%a %d %b %H:%M"


class LiveChat:
    """Chat stand-in that also remembers when each message was sent."""

    def __init__(self, clock):
        self.clock = clock
        self.log = []

    def send(self, to, text):
        self.log.append({"time": self.clock(), "to": to, "text": text})


class LivePresence:
    """Presence stand-in: where each person is right now, set from the page."""

    def __init__(self, employees):
        self.where = {e.id: e.home_office for e in employees.values()}

    def office_on(self, employee_id, day):
        return self.where[employee_id]


class World:
    def __init__(self):
        self.reset()

    def reset(self):
        self.employees = make_employees()
        self.offices = make_offices()
        self.clock = FakeClock(datetime.now(timezone.utc).replace(second=0, microsecond=0))
        self.chat = LiveChat(self.clock)
        self.hr = FakeHR()
        self.presence = LivePresence(self.employees)
        self.svc = RefillService(self.offices, self.employees, self.presence,
                                 self.chat, self.hr, self.clock)

    # ---------------------------------------------------------------- actions

    def act(self, a):
        kind = a.get("type")
        svc = self.svc
        if kind == "reset":
            self.reset()
            return
        if kind == "report":
            svc.report_empty(a["office"], a["employee"])
        elif kind == "commit":
            svc.commit(a["refill"], a["employee"])
        elif kind == "decline":
            svc.decline(a["refill"], a["employee"])
        elif kind == "purchase":
            items = [s.strip() for s in str(a.get("items", "")).split(",") if s.strip()]
            try:
                amount = Decimal(str(a.get("amount", "")).strip())
            except ArithmeticError:
                raise ValueError("enter the receipt amount as a number, for example 850.50")
            svc.record_purchase(a["refill"], a["employee"], amount,
                                b"simulated-receipt.jpg", items=items)
        elif kind in ("approve_overage", "reject_overage"):
            admin = self.offices[svc.refills[a["refill"]].office].admin_id
            getattr(svc, kind)(a["refill"], admin)
        elif kind == "hr_approve":
            self.hr.approve(a["claim"])
        elif kind == "hr_reject":
            self.hr.reject(a["claim"])
        elif kind == "hr_down":
            self.hr.down = bool(a["down"])
        elif kind == "advance":
            self.clock.advance(hours=float(a["hours"]))
        elif kind == "presence":
            self.presence.where[a["employee"]] = a["location"] or None
        else:
            raise ValueError(f"unknown action {kind!r}")
        svc.tick()   # the scheduler: applies timeouts, retries and HR results

    # ---------------------------------------------------------------- view

    def state(self):
        now = self.clock()
        refills = list(self.svc.refills.values())
        offices = []
        for office in self.offices.values():
            year, month = budget.local_month(office, now)
            spent = budget.spent(office, year, month, refills)
            offices.append({
                "code": office.code, "currency": office.currency,
                "budget": office.monthly_budget, "spent": spent,
                "remaining": office.monthly_budget - spent,
                "min_purchase": office.min_purchase, "max_purchase": office.max_purchase,
                "month": f"{year}-{month:02d}", "channel": office.channel,
                "admin": office.admin_id,
                "local_time": now.astimezone(ZoneInfo(office.timezone)).strftime(TIME_FORMAT),
            })
        return {
            "now": now.strftime(TIME_FORMAT) + " UTC",
            "hr_down": self.hr.down,
            "offices": offices,
            "people": [{"id": e.id, "name": e.name, "home": e.home_office,
                        "volunteer": e.is_volunteer, "location": self.presence.where[e.id]}
                       for e in self.employees.values()],
            "refills": [{
                "id": r.id, "office": r.office, "state": r.state.value,
                "reported_by": r.reported_by, "offered_to": r.offered_to,
                "committed_by": r.committed_by, "offer_expires_at": r.offer_expires_at,
                "purchase_deadline": r.purchase_deadline, "retry_at": r.retry_at,
                "cap": r.cap, "buyer": r.buyer, "amount": r.amount, "currency": r.currency,
                "items": list(r.items), "claim_id": r.claim_id,
                "history": [{"time": t, "state": s.value, "note": note}
                            for t, s, note in r.history],
            } for r in refills],
            "chat": list(reversed(self.chat.log)),
            "claims": [{"id": claim_id, "amount": c["amount"], "currency": c["currency"],
                        "employee": c["employee_id"], "description": c["description"],
                        "status": c["status"]} for claim_id, c in self.hr.claims.items()],
            "report": self.svc.monthly_report(now.year, now.month, REPORTING_CURRENCY, RATES),
            "rates": RATES,
        }


def to_json(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.strftime(TIME_FORMAT) + " UTC"
    raise TypeError(f"cannot serialise {type(value).__name__}")


WORLD = World()
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX.read_text(encoding="utf-8"), "text/html")
        elif self.path == "/api/state":
            with LOCK:
                body = json.dumps(WORLD.state(), default=to_json)
            self._send(200, body, "application/json")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/action":
            self._send(404, "not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        error = None
        with LOCK:
            try:
                WORLD.act(json.loads(self.rfile.read(length) or b"{}"))
            except SnackError as exc:
                error = f"Refused: {exc}"
            except (ValueError, KeyError, ArithmeticError, TypeError) as exc:
                error = f"Invalid input: {exc}"
            body = json.dumps({"error": error, "state": WORLD.state()}, default=to_json)
        self._send(200, body, "application/json")

    def log_message(self, *args):   # keep the console quiet
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"Snack Counter is running at {url}  (Ctrl+C to stop)")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
