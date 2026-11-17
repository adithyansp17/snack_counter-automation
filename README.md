# Snack Counter Automation

Take-home exercise: automate keeping two office snack counters (Oslo, Bengaluru) stocked and reimbursed.

- **[DESIGN.md](DESIGN.md)**: the design document.
- **`snack_counter/`**: core logic. Python standard library only (plus `tzdata` for time zones on Windows).
- **`tests/`**: automated tests for the rules.
- **`app.py`**: a small local web app to drive the logic by hand.

## Run

Requires Python 3.9+.

```
python -m pip install -r requirements.txt
python -m pytest          # the rules
python app.py             # web app at http://localhost:8000
python demo.py            # one refill end to end, printed as a chat transcript
```

On Windows you can double-click `run_app.bat` or `run_tests.bat` instead.

## The web app

The chat tool, HR system, presence and clock are simulated, so the page lets you play every role:

1. In an office card, pick a person and click **reports the box empty**. One volunteer is asked; the message appears in the chat panel.
2. Click **says yes**, **says no**, or let another volunteer step in. Or use **+2 hours** in the header to let the offer time out and pass to the next person.
3. Enter an amount and click **submits receipt**. A claim appears in the HR panel straight away.
4. Click **Approve** in the HR panel to finish the refill. The monthly report updates as you go.

Things worth trying: change who is in the office under People, take HR offline before submitting a receipt, submit an amount above the remaining budget, or use up the budget and report the box empty again.

State is kept in memory; **Reset** or a restart starts again.

## Layout

| File | What it holds |
|---|---|
| `snack_counter/models.py` | Refill, Office, Employee, the states |
| `snack_counter/service.py` | The refill lifecycle (the only code that changes state) |
| `snack_counter/selection.py` | Choosing who buys |
| `snack_counter/budget.py` | Budget check and the monthly report |
| `snack_counter/fakes.py` | Simulated chat tool, HR system, presence and clock |
| `snack_counter/sample.py` | Sample offices and employees used by tests, demo and app |
| `app.py`, `web/index.html` | The local web app |

## Tests, by rule

| Rule | File |
|---|---|
| Two people cannot both commit to the same refill | `tests/test_commit.py` |
| A refill nobody completes is handed to someone else | `tests/test_reassignment.py` |
| Budgets and totals are correct across both currencies | `tests/test_budget.py` |
| Only present volunteers are asked; work is spread fairly | `tests/test_selection.py` |
| Empty to reimbursed; HR outage, rejection, overdue claims | `tests/test_lifecycle.py` |
