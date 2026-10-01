"""End-to-end test for the enhanced Bright Future Grant app.

Flow: register -> apply -> admin approve (account issued) -> admin push money
      -> receipt -> notifications -> support chat (with image) -> admin reply.
"""
import os
import re
import sys
import time
import requests

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:  # noqa: BLE001
    pass

BASE = os.environ.get("BASE", "http://127.0.0.1:8092")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@brightfuturegrant.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')
EMAIL = f"applicant{int(time.time())}@example.com"


def csrf(session, url):
    r = session.get(url)
    m = CSRF_RE.search(r.text)
    return (m.group(1) if m else ""), r


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        check.failed = True


check.failed = False

# ---- 1. Register a new member ----
u = requests.Session()
tok, _ = csrf(u, f"{BASE}/register")
r = u.post(f"{BASE}/register", data={
    "_csrf_token": tok, "full_name": "Test Applicant", "email": EMAIL,
    "country": "Kenya", "phone": "+254700000000", "password": "Password123",
}, allow_redirects=True)
check("register -> dashboard 200", r.status_code == 200 and "Your applications" in r.text)

# ---- 2. Submit an application ----
tok, _ = csrf(u, f"{BASE}/apply")
r = u.post(f"{BASE}/apply", data={
    "_csrf_token": tok, "full_name": "Test Applicant", "country": "Kenya",
    "crisis_type": "Disaster Relief", "household_size": "4",
    "amount_requested": "2500", "currency": "USD",
    "situation": "Flood destroyed our home.",
}, allow_redirects=True)
check("apply -> dashboard 200", r.status_code == 200)
m = re.search(r'/application/(\d+)', r.text)
app_id = m.group(1) if m else "1"

# ---- 3. Admin login & approve ----
a = requests.Session()
tok, _ = csrf(a, f"{BASE}/login")
r = a.post(f"{BASE}/login", data={"_csrf_token": tok, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, allow_redirects=True)
check("admin login -> admin 200", r.status_code == 200 and "Review dashboard" in r.text)

tok, _ = csrf(a, f"{BASE}/admin")
r = a.post(f"{BASE}/admin/application/{app_id}", data={
    "_csrf_token": tok, "decision": "approved", "awarded_amount": "2500",
    "admin_notes": "Approved. Stay strong.",
}, allow_redirects=True)
check(f"admin approve app #{app_id}", r.status_code == 200)

# ---- 4. Member account now has account number ----
r = u.get(f"{BASE}/account")
check("member /account 200", r.status_code == 200)
acct = re.search(r'data-copy="(\d{10})"', r.text)
check("account number issued (10 digits)", bool(acct))
acct_no = acct.group(1) if acct else ""

# ---- 5. Admin pushes money ----
tok, _ = csrf(a, f"{BASE}/admin/transactions")
r = a.post(f"{BASE}/admin/push-money", data={
    "_csrf_token": tok, "user": acct_no, "amount": "1500.00", "currency": "USD",
    "description": "Disaster Relief grant disbursement",
}, allow_redirects=True)
check("admin push-money", r.status_code == 200 and "deposited" in r.text)

# ---- 6. Member sees balance + receipt ----
# Approving the grant (step 3) credits the awarded amount, so the balance is
# 2,500 (grant) + 1,500 (admin deposit) = 4,000.
r = u.get(f"{BASE}/account")
check("grant disbursement credited (2,500.00)", "2,500.00" in r.text)
check("member balance updated (4,000.00)", "4,000.00" in r.text)
m = re.search(r'/receipt/(\d+)', r.text)
tx_id = m.group(1) if m else "1"
r = u.get(f"{BASE}/receipt/{tx_id}")
check("receipt page 200", r.status_code == 200 and "Deposit Receipt" in r.text)
check("receipt shows sender foundation account", "8001234567" in r.text)

# ---- 7. Member transactions & notifications ----
r = u.get(f"{BASE}/transactions")
check("transactions page 200", r.status_code == 200 and "1500" in r.text.replace(",", ""))
r = u.get(f"{BASE}/notifications")
check("notifications page 200", r.status_code == 200 and "Deposit received" in r.text)

# ---- 8. Support chat with image attachment ----
tok, _ = csrf(u, f"{BASE}/support")
png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
r = u.post(f"{BASE}/support/new", data={
    "_csrf_token": tok, "subject": "Question about my grant", "body": "When will funds arrive?",
}, files={"attachment": ("proof.png", png, "image/png")}, allow_redirects=True)
check("support new thread 200", r.status_code == 200 and "Question about my grant" in r.text)
thread = re.search(r'/support/(\d+)', r.text)
thread_id = thread.group(1) if thread else "1"

# ---- 9. Admin sees thread & replies with image ----
r = a.get(f"{BASE}/admin/support")
check("admin support inbox 200", r.status_code == 200 and "Question about my grant" in r.text)
tok, _ = csrf(a, f"{BASE}/support/{thread_id}")
r = a.post(f"{BASE}/support/{thread_id}", data={
    "_csrf_token": tok, "body": "Funds are already in your account. See receipt.",
}, files={"attachment": ("reply.png", png, "image/png")}, allow_redirects=True)
check("admin reply 200", r.status_code == 200 and "already in your account" in r.text)

# ---- 10. Admin settings & users pages ----
r = a.get(f"{BASE}/admin/users")
check("admin users page 200", r.status_code == 200 and "Test Applicant" in r.text)
r = a.get(f"{BASE}/admin/settings")
check("admin settings page 200", r.status_code == 200 and "8001234567" in r.text)
r = a.get(f"{BASE}/admin/export/users.csv")
check("admin CSV export 200", r.status_code == 200 and "account_number" in r.text)

# ---- 11. Access control ----
r = u.get(f"{BASE}/admin", allow_redirects=False)
check("member blocked from /admin (302)", r.status_code == 302)
r = requests.get(f"{BASE}/account", allow_redirects=False)
check("anon blocked from /account (302)", r.status_code == 302)

# ---- 12. CSRF enforced ----
r = u.post(f"{BASE}/account/settings", data={"action": "profile", "full_name": "Hacker"}, allow_redirects=False)
check("POST without CSRF rejected (400)", r.status_code == 400)

# ---- 13. Public pages ----
for path in ["/", "/about", "/programs", "/how-to-apply", "/eligibility", "/faq", "/transparency", "/contact", "/login", "/register"]:
    r = requests.get(BASE + path)
    check(f"public {path} 200", r.status_code == 200)

# ---- 14. Country-based currency (member registered with Kenya -> KES) ----
r = u.get(f"{BASE}/account")
check("account currency derived from country (KES)", "KES" in r.text)
r = requests.get(f"{BASE}/register")
check("register has country dropdown", "Select your country" in r.text and "Nigeria" in r.text)

# ---- 15. Wallets visible & copyable on the dashboard ----
r = u.get(f"{BASE}/dashboard")
check("dashboard shows withdrawal wallets", "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh" in r.text)
check("dashboard wallet has copy button", "data-copy-target=" in r.text and "Withdrawal methods" in r.text)
r = u.get(f"{BASE}/withdraw")
check("withdraw page 200 & lists methods", r.status_code == 200 and "Bitcoin (BTC)" in r.text and "USDT (TRC20)" in r.text)

# ---- 16. Member requests a withdrawal (funds held) ----
DEST = "bc1qtestdestination0000000000000000000000"
tok, _ = csrf(u, f"{BASE}/withdraw")
r = u.post(f"{BASE}/withdraw", data={
    "_csrf_token": tok, "method": "btc", "amount": "100.00",
    "destination": DEST, "note": "Test withdrawal",
}, allow_redirects=True)
check("withdrawal request submitted (pending)", r.status_code == 200 and "pending approval" in r.text)
check("withdrawal appears in history", DEST in r.text)
r = u.get(f"{BASE}/account")
# 4,000 (grant + deposit) - 100 held for the pending withdrawal = 3,900.
check("balance held after request (3,900.00)", "3,900.00" in r.text)

# ---- 17. Admin approves the withdrawal from the approvals queue ----
r = a.get(f"{BASE}/admin/approvals")
check("admin approvals page 200", r.status_code == 200 and "Approvals queue" in r.text)
wtx = None
for chunk in r.text.split("approval-card")[1:]:
    if DEST in chunk:
        m = re.search(r"/admin/transactions/(\d+)/approve", chunk)
        if m:
            wtx = m.group(1)
            break
check("pending withdrawal found in approvals", bool(wtx))
tok, _ = csrf(a, f"{BASE}/admin/approvals")
r = a.post(f"{BASE}/admin/transactions/{wtx}/approve", data={
    "_csrf_token": tok, "next": "/admin/approvals", "note": "Approved by test",
}, allow_redirects=True)
check("admin approved withdrawal", r.status_code == 200)
r = u.get(f"{BASE}/withdraw")
check("withdrawal now completed", "Completed" in r.text)

# ---- 18. Admin reverses the withdrawal with a reason + next steps ----
tok, _ = csrf(a, f"{BASE}/admin/transactions")
r = a.post(f"{BASE}/admin/transactions/{wtx}/reverse", data={
    "_csrf_token": tok, "next": "/admin/transactions",
    "reason": "Sent to an unverified wallet address.",
    "instructions": "Contact support to verify your wallet and resubmit.",
}, allow_redirects=True)
check("admin reversed withdrawal", r.status_code == 200)
r = u.get(f"{BASE}/withdraw")
check("member sees reversal reason", "unverified wallet address" in r.text)
check("member sees next steps", "verify your wallet" in r.text)
r = u.get(f"{BASE}/account")
check("funds returned after reversal (1,500.00)", "1,500.00" in r.text)

# ---- 19. Admin can edit withdrawal wallets ----
tok, _ = csrf(a, f"{BASE}/admin/settings")
r = a.post(f"{BASE}/admin/settings", data=[
    ("_csrf_token", tok), ("form_action", "methods"),
    ("m_id", "btc"), ("m_name", "Bitcoin (BTC)"), ("m_type", "crypto"),
    ("m_network", "Bitcoin"), ("m_address", "bc1qeditedwallet000000000000000000000000"),
    ("m_instructions", "Send BTC only."), ("m_enabled", "1"),
    ("m_id", "paypal"), ("m_name", "PayPal"), ("m_type", "wallet"),
    ("m_network", ""), ("m_address", "payouts@brightfuturegrant.com"),
    ("m_instructions", "PayPal email only."), ("m_enabled", "1"),
], allow_redirects=True)
check("admin saved edited wallets", r.status_code == 200 and "bc1qeditedwallet000000000000000000000000" in r.text)
r = u.get(f"{BASE}/withdraw")
check("member sees updated wallet address", "bc1qeditedwallet000000000000000000000000" in r.text)

# ---- 20. First-deposit notice & crypto-first gating (fresh member, no deposit) ----
l = requests.Session()
LOCKED_EMAIL = f"locked{int(time.time())}@example.com"
LOCKED_NAME = f"Locked Member {int(time.time())}"
tok, _ = csrf(l, f"{BASE}/register")
r = l.post(f"{BASE}/register", data={
    "_csrf_token": tok, "full_name": LOCKED_NAME, "email": LOCKED_EMAIL,
    "country": "Nigeria", "phone": "+234700000000", "password": "Password123",
}, allow_redirects=True)
check("locked member register -> dashboard 200", r.status_code == 200)

r = l.get(f"{BASE}/dashboard")
check("dashboard shows first-deposit notice", "First Deposit" in r.text and "Payment Method Policy" in r.text)
check("locked notice shows crypto-required status", "cryptocurrency required" in r.text)
check("dashboard marks non-crypto methods locked", "Locked" in r.text and "wallet-locked" in r.text)

r = l.get(f"{BASE}/withdraw")
check("withdraw shows crypto-only hint", "Only cryptocurrency methods are available" in r.text)
check("withdraw shows locked badge", "Locked" in r.text)

# server-side guard: a locked (non-crypto) method must be rejected even if forged
tok, _ = csrf(l, f"{BASE}/withdraw")
r = l.post(f"{BASE}/withdraw", data={
    "_csrf_token": tok, "method": "paypal", "amount": "10.00",
    "destination": "locked.paypal@example.com", "note": "should be blocked",
}, allow_redirects=True)
check("locked method rejected server-side", "unlocks automatically after your first deposit" in r.text)

# a crypto method is not blocked by the first-deposit lock (fails later only on balance)
tok, _ = csrf(l, f"{BASE}/withdraw")
r = l.post(f"{BASE}/withdraw", data={
    "_csrf_token": tok, "method": "btc", "amount": "10.00",
    "destination": "bc1qlockedmember0000000000000000000000", "note": "crypto allowed",
}, allow_redirects=True)
check("crypto method not blocked by lock", "unlocks automatically after your first deposit" not in r.text)

# ---- 21. A completed first deposit unlocks every method ----
r = u.get(f"{BASE}/dashboard")
check("funded member dashboard shows unlocked status", "all methods unlocked" in r.text)
check("funded member has no locked wallets", "wallet-locked" not in r.text)
r = u.get(f"{BASE}/withdraw")
check("funded member withdraw has no crypto-only hint", "Only cryptocurrency methods are available" not in r.text)

# ---- 22. Admin messaging (broadcast to all + individual message) ----
r = a.get(f"{BASE}/admin/messages")
check("admin messages page 200", r.status_code == 200 and "Compose a message" in r.text)

tok, _ = csrf(a, f"{BASE}/admin/messages")
r = a.post(f"{BASE}/admin/messages/send", data={
    "_csrf_token": tok, "audience": "all", "title": "You are not alone",
    "body": "A shout-out from the Bright Future Grant team: keep going, we believe in you.",
}, allow_redirects=True)
check("admin broadcast to all sent", r.status_code == 200 and "delivered to all" in r.text)

r = u.get(f"{BASE}/dashboard")
check("member dashboard shows messages section", "Messages from the foundation" in r.text and "You are not alone" in r.text)
r = u.get(f"{BASE}/notifications")
check("member notifications include the message", "You are not alone" in r.text)

r = a.get(f"{BASE}/admin/messages")
m = re.search(r'<option value="(\d+)">' + re.escape(LOCKED_NAME), r.text)
locked_id = m.group(1) if m else None
check("locked member listed in recipient select", bool(locked_id))
tok, _ = csrf(a, f"{BASE}/admin/messages")
r = a.post(f"{BASE}/admin/messages/send", data={
    "_csrf_token": tok, "audience": "user", "recipient_id": locked_id or "",
    "title": "A personal note for you", "body": "Hi, this is a private motivational note just for you.",
}, allow_redirects=True)
check("admin individual message sent", r.status_code == 200 and "delivered to" in r.text)
r = l.get(f"{BASE}/dashboard")
check("individual message reaches member", "A personal note for you" in r.text)

# ---- 23. Admin can manually verify a first deposit (unlocks methods) ----
r = a.get(f"{BASE}/admin/users")
check("admin users shows first-deposit column", "First deposit" in r.text and "Verify first deposit" in r.text)
tok, _ = csrf(a, f"{BASE}/admin/users")
r = a.post(f"{BASE}/admin/users/{locked_id}/verify-deposit", data={"_csrf_token": tok}, allow_redirects=True)
check("admin verify first deposit", r.status_code == 200 and "first deposit verified" in r.text.lower())
r = l.get(f"{BASE}/withdraw")
check("member unlocked after manual verify", "Only cryptocurrency methods are available" not in r.text)

print("\nRESULT:", "ALL PASSED" if not check.failed else "SOME FAILED")
sys.exit(1 if check.failed else 0)
