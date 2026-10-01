"""Focused test: approving a grant credits the member's balance (fee-free), idempotently.

Run against a throwaway instance:
    BRIGHTPATH_DB=/tmp/testgrant/charity.db BRIGHTPATH_DATA_DIR=/tmp/testgrant PORT=8093 python3 app.py
    BRIGHTPATH_DB=/tmp/testgrant/charity.db python3 seed_demo.py
    BASE=http://127.0.0.1:8093 BRIGHTPATH_DB=/tmp/testgrant/charity.db python3 test_grant_credit.py
"""
import os
import re
import sqlite3
import sys
import requests

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:  # noqa: BLE001
    pass

BASE = os.environ.get("BASE", "http://127.0.0.1:8093")
DB = os.environ.get("BRIGHTPATH_DB", "/tmp/testgrant/charity.db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "madkitbennny@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Satellite@2020")
CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')


def csrf(session, url):
    r = session.get(url)
    m = CSRF_RE.search(r.text)
    return (m.group(1) if m else ""), r


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        check.failed = True


check.failed = False


def db_row(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


# ---- find Daniel's under_review application + baseline balance ----
row = db_row(
    "SELECT a.id AS app_id, a.user_id, u.balance, u.currency FROM applications a "
    "JOIN users u ON u.id = a.user_id WHERE u.email = 'daniel@example.com' "
    "AND a.status = 'under_review' ORDER BY a.id DESC LIMIT 1"
)
if not row:
    print("FAIL could not find Daniel's under_review application (seed first)")
    sys.exit(1)
app_id = row["app_id"]
user_id = row["user_id"]
currency = row["currency"]
base_balance = float(row["balance"] or 0)
print(f"app #{app_id} user #{user_id} currency {currency} starting balance {base_balance}")

# ---- admin login ----
a = requests.Session()
tok, _ = csrf(a, f"{BASE}/login")
r = a.post(f"{BASE}/login", data={"_csrf_token": tok, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
           allow_redirects=True)
check("admin login", r.status_code == 200 and "Review dashboard" in r.text)


def approve(amount, decision="approved"):
    tok, _ = csrf(a, f"{BASE}/admin")
    return a.post(f"{BASE}/admin/application/{app_id}", data={
        "_csrf_token": tok, "decision": decision, "awarded_amount": str(amount),
        "admin_notes": "Test approval.",
    }, allow_redirects=True)


def balance():
    return float(db_row("SELECT balance FROM users WHERE id = ?", (user_id,))["balance"] or 0)


def grant_tx():
    return db_row(
        "SELECT * FROM transactions WHERE reference = ? AND type = 'grant'",
        (f"GRANT-APP-{app_id}",),
    )


# ---- 1. approve with 1500 -> balance increases by 1500 ----
r = approve(1500)
check("approve #1 -> 200", r.status_code == 200)
check(f"balance credited (+1500): {balance()}", abs(balance() - (base_balance + 1500)) < 0.005)
tx = grant_tx()
check("grant transaction recorded (completed)", bool(tx) and tx["status"] == "completed")
check("grant tx amount = 1500", bool(tx) and abs(float(tx["amount"]) - 1500) < 0.005)

# ---- 2. re-approve same amount -> no double credit ----
approve(1500)
check(f"re-approve same amount -> no double credit: {balance()}",
      abs(balance() - (base_balance + 1500)) < 0.005)

# ---- 3. re-approve with larger amount -> only delta applied ----
approve(2000)
check(f"re-approve 2000 -> delta only (+500): {balance()}",
      abs(balance() - (base_balance + 2000)) < 0.005)

# ---- 4. decline -> grant reversed ----
approve(2000, decision="declined")
check(f"decline -> grant reversed back to {base_balance}: {balance()}",
      abs(balance() - base_balance) < 0.005)
tx = grant_tx()
check("grant tx now reversed", bool(tx) and tx["status"] == "reversed")

# ---- 5. member never charged a fee (balance never went negative) ----
check("balance never negative", balance() >= 0)

print()
if check.failed:
    print("RESULT: FAILURES PRESENT")
    sys.exit(1)
print("RESULT: ALL GRANT-CREDIT CHECKS PASSED")
