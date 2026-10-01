"""Verify grant transactions render as positive credits in member + admin views."""
import os
import re
import sqlite3
import sys
import requests

BASE = os.environ.get("BASE", "http://127.0.0.1:8093")
DB = os.environ.get("BRIGHTPATH_DB", "/tmp/testgrant/charity.db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "madkitbennny@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Satellite@2020")
CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')


def csrf(s, url):
    r = s.get(url)
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


row = db_row(
    "SELECT a.id AS app_id, a.user_id FROM applications a JOIN users u ON u.id = a.user_id "
    "WHERE u.email = 'daniel@example.com' ORDER BY a.id DESC LIMIT 1"
)
app_id, user_id = row["app_id"], row["user_id"]

# admin approves -> creates a completed grant
a = requests.Session()
tok, _ = csrf(a, f"{BASE}/login")
a.post(f"{BASE}/login", data={"_csrf_token": tok, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
tok, _ = csrf(a, f"{BASE}/admin")
a.post(f"{BASE}/admin/application/{app_id}", data={
    "_csrf_token": tok, "decision": "approved", "awarded_amount": "1500", "admin_notes": "ok"})

tx = db_row("SELECT id FROM transactions WHERE reference = ? AND type='grant'", (f"GRANT-APP-{app_id}",))
tx_id = tx["id"]

# member views
m = requests.Session()
tok, _ = csrf(m, f"{BASE}/login")
m.post(f"{BASE}/login", data={"_csrf_token": tok, "email": "daniel@example.com", "password": "Password123"})

dash = m.get(f"{BASE}/dashboard").text
txs = m.get(f"{BASE}/transactions").text
acct = m.get(f"{BASE}/account").text
rcpt = m.get(f"{BASE}/receipt/{tx_id}").text

check("dashboard shows Grant + positive amount", "Grant" in dash and "+ KES 1,500.00" in dash)
check("transactions shows Grant + positive amount", "Grant" in txs and "+ KES 1,500.00" in txs)
check("account shows Grant + positive amount", "Grant" in acct and "+ KES 1,500.00" in acct)
check("receipt titled 'Grant Disbursement'", "Grant Disbursement Receipt" in rcpt)
check("receipt type row = Grant", re.search(r"Type</span><strong>Grant</strong>", rcpt) is not None)
check("receipt says amount granted", "Amount granted" in rcpt)
check("receipt keeps no-fee promise", "never charges applicants a fee" in rcpt)

# admin view
admin_tx = a.get(f"{BASE}/admin/transactions").text
check("admin transactions shows Grant", "Grant" in admin_tx)

print()
if check.failed:
    print("RESULT: FAILURES PRESENT")
    sys.exit(1)
print("RESULT: ALL GRANT-RENDER CHECKS PASSED")
