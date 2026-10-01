"""Populate Bright Future Grant with a small, realistic demo dataset.

Run:  python seed_demo.py
This is optional. To start completely fresh instead, delete charity.db and
restart the app (it will recreate the schema and seed only the admin account).

Demo administrator login:
    admin@brightfuturegrant.com / Admin@12345
Demo member login: any listed email / Password123
"""
import os
import random
import sqlite3
import uuid
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

DB = os.path.join(os.path.dirname(__file__), "charity.db")

# Currency is derived from each member's country (single source of truth in app.py).
try:
    from app import currency_for_country
except Exception:  # pragma: no cover - fallback if app import is unavailable
    _FALLBACK = {"Nigeria": "NGN", "Mexico": "MXN", "India": "INR", "Kenya": "KES",
                 "United States": "USD", "United Kingdom": "GBP", "Germany": "EUR"}

    def currency_for_country(country):
        return _FALLBACK.get((country or "").strip(), "USD")


def now(days_ago=0, hours=0):
    return (datetime.utcnow() - timedelta(days=days_ago, hours=hours)).isoformat(timespec="seconds")


def gen_account():
    return str(random.randint(1, 9)) + "".join(str(random.randint(0, 9)) for _ in range(9))


def gen_routing():
    return "".join(str(random.randint(0, 9)) for _ in range(9))


def gen_ref(prefix="BP"):
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


# name, email, country, phone, balance, account_status, days_ago
# NOTE: balance already reflects the seeded deposits/withdrawals below.
MEMBERS = [
    ("Amara Okonkwo", "amara@example.com", "Nigeria", "+2348012345678", 1700.0, "active", 3),
    ("Luis Fernandez", "luis@example.com", "Mexico", "+525512345678", 1200.0, "active", 6),
    ("Priya Sharma", "priya@example.com", "India", "+919812345678", 650.0, "active", 9),
    ("Daniel Mwangi", "daniel@example.com", "Kenya", "+254712345678", 0.0, "pending", 1),
]

APPS = [
    (0, "Disaster Relief", 2500, 5, "approved", 2500, "Flood destroyed our home and belongings."),
    (1, "Medical Support", 1200, 4, "approved", 1200, "Urgent surgery for my daughter."),
    (2, "Education Continuity", 800, 6, "approved", 800, "School fees after losing my job."),
    (3, "Livelihood Recovery", 1500, 3, "under_review", None, "Small shop burned down; need to restock."),
]

# member_index, amount, method, network, destination, status, reason, instructions, days_ago
WITHDRAWALS = [
    (0, 500.0, "USDT (TRC20)", "Tron (TRC20)", "TQ5x8k2n9vR4s7w1p3mL6z8yB2cD4eF5gH",
     "completed", None, None, 2),
    (0, 300.0, "Bitcoin (BTC)", "Bitcoin", "bc1q9x8k2n9vR4s7w1p3mL6z8yB2cD4eF5gH",
     "pending", None, None, 0),
    (1, 200.0, "Bank transfer", "", "Banco Nacional · 0123456789 · SWIFT BNACMXXX",
     "rejected", "The bank account name did not match the account holder.",
     "Update your bank details under My Account, then submit a new withdrawal request.", 3),
    (2, 150.0, "PayPal", "", "priya.paypal@example.com",
     "pending", None, None, 0),
]

SUPPORT = [
    ("How do I receive my grant?", "I was approved — where will the money go?", "It will be deposited into your Bright Future Grant account. You'll get an email and a receipt here.", 0),
    ("Update my phone number", "I changed my number, can you update it?", "Of course — you can update it yourself under My Account → Profile.", 1),
]


def main():
    if not os.path.exists(DB):
        print("charity.db not found. Start the app once first so the schema is created.")
        return
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    if db.execute("SELECT COUNT(*) c FROM users WHERE role='applicant'").fetchone()["c"] > 0:
        print("Demo members already exist — skipping seed to avoid duplicates.")
        return

    member_ids = []
    for (name, email, country, phone, balance, status, days) in MEMBERS:
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            continue
        currency = currency_for_country(country)
        cur = db.execute(
            "INSERT INTO users (full_name, email, password_hash, country, phone, role, "
            "account_number, routing_number, balance, currency, account_status, is_verified, created_at) "
            "VALUES (?,?,?,?,?,'applicant',?,?,?,?,?,1,?)",
            (name, email, generate_password_hash("Password123"), country, phone,
             gen_account(), gen_routing(), balance, currency, status, now(days)),
        )
        member_ids.append(cur.lastrowid)
        db.execute(
            "INSERT INTO notifications (user_id, title, body, link, category, is_read, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (cur.lastrowid, "Welcome to Bright Future Grant",
             f"Hi {name.split()[0]}, your account is ready. You can now submit a grant application.",
             "/dashboard", "account", 1, now(days)),
        )

    for (mi, crisis, amount, hh, status, awarded, situation) in APPS:
        if mi >= len(member_ids):
            continue
        uid = member_ids[mi]
        name = MEMBERS[mi][0]
        country = MEMBERS[mi][2]
        currency = currency_for_country(country)
        db.execute(
            "INSERT INTO applications (user_id, full_name, country, crisis_type, amount_requested, "
            "currency, household_size, situation, status, awarded_amount, admin_notes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, name, country, crisis, amount, currency, hh, situation, status, awarded,
             "Approved after review." if status == "approved" else None, now(7), now(2)),
        )
        if status == "approved" and awarded:
            ref = gen_ref()
            db.execute(
                "INSERT INTO transactions (user_id, type, amount, currency, description, reference, "
                "sender_name, sender_account, sender_routing, status, created_by, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,'completed',1,?)",
                (uid, "deposit", awarded, currency, f"{crisis} grant disbursement", ref,
                 "Bright Future Grant", "8001234567", "121000358", now(2)),
            )
            db.execute(
                "INSERT INTO notifications (user_id, title, body, link, category, is_read, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (uid, f"Deposit received — {currency} {awarded:,.2f}",
                 f"A deposit of {currency} {awarded:,.2f} has been made to your Bright Future Grant account. "
                 "A full receipt is available in your dashboard.", "/transactions", "transaction", 0, now(2)),
            )

    # Confirm the first deposit for members whose grant was disbursed (0, 1, 2).
    # Member 3 (Daniel) has no deposit yet, so his account stays crypto-only.
    for mi in (0, 1, 2):
        if mi < len(member_ids):
            db.execute(
                "UPDATE users SET first_deposit_at=? "
                "WHERE id=? AND (first_deposit_at IS NULL OR first_deposit_at='')",
                (now(2), member_ids[mi]),
            )

    for (mi, amount, method, network, destination, status, reason, instructions, days) in WITHDRAWALS:
        if mi >= len(member_ids):
            continue
        uid = member_ids[mi]
        currency = currency_for_country(MEMBERS[mi][2])
        ref = gen_ref("BPW")
        reviewed_by = 1 if status in ("completed", "rejected") else None
        reviewed_at = now(days) if status in ("completed", "rejected") else None
        db.execute(
            "INSERT INTO transactions (user_id, type, amount, currency, description, reference, "
            "method, destination, network, status, reason, instructions, reviewed_by, reviewed_at, "
            "created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, "withdrawal", amount, currency, f"Withdrawal via {method}", ref,
             method, destination, network, status, reason, instructions,
             reviewed_by, reviewed_at, uid, now(days)),
        )
        if status == "completed":
            db.execute(
                "INSERT INTO notifications (user_id, title, body, link, category, is_read, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (uid, f"Withdrawal approved — {currency} {amount:,.2f}",
                 f"Your withdrawal of {currency} {amount:,.2f} via {method} was approved and sent.",
                 "/withdraw", "transaction", 0, now(days)),
            )
        elif status == "pending":
            db.execute(
                "INSERT INTO notifications (user_id, title, body, link, category, is_read, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (uid, f"Withdrawal request received — {currency} {amount:,.2f}",
                 f"Your withdrawal request of {currency} {amount:,.2f} via {method} is pending review.",
                 "/withdraw", "transaction", 0, now(days)),
            )
        elif status == "rejected":
            db.execute(
                "INSERT INTO notifications (user_id, title, body, link, category, is_read, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (uid, f"Withdrawal not approved — {currency} {amount:,.2f}",
                 f"Your withdrawal request was not approved. Reason: {reason} "
                 f"What to do next: {instructions}", "/withdraw", "transaction", 0, now(days)),
            )

    for (subject, first, reply, mi) in SUPPORT:
        if mi >= len(member_ids):
            continue
        uid = member_ids[mi]
        cur = db.execute(
            "INSERT INTO support_threads (user_id, subject, status, created_at, updated_at, last_message_at) "
            "VALUES (?,?, 'open', ?,?,?)",
            (uid, subject, now(3), now(2), now(2)),
        )
        tid = cur.lastrowid
        db.execute(
            "INSERT INTO support_messages (thread_id, sender_id, sender_role, body, is_read, created_at) "
            "VALUES (?,?,'user',?,1,?)", (tid, uid, first, now(3)),
        )
        db.execute(
            "INSERT INTO support_messages (thread_id, sender_id, sender_role, body, is_read, created_at) "
            "VALUES (?,1,'admin',?,0,?)", (tid, reply, now(2)),
        )

    # A demo shout-out / motivational broadcast to every member.
    if member_ids:
        b_title = "You've got this \u2014 a note from the Bright Future Grant team"
        b_body = ("Hello from the Bright Future Grant team. We know times can be tough, but your strength "
                  "and resilience inspire us every day. Keep going \u2014 we are standing with you. "
                  "Warm regards, The Bright Future Grant Team")
        db.execute(
            "INSERT INTO broadcasts (title, body, audience, recipient_id, recipient_count, "
            "created_by, created_at) VALUES (?,?,?,?,?,?,?)",
            (b_title, b_body, "all", None, len(member_ids), 1, now(1)),
        )
        for uid in member_ids:
            db.execute(
                "INSERT INTO notifications (user_id, title, body, link, category, is_read, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (uid, b_title, b_body, "/dashboard", "message", 0, now(1)),
            )

    db.commit()
    db.close()
    print(f"Seeded {len(member_ids)} demo members, applications, deposits, withdrawals and support threads.")
    print("Seeded a demo broadcast message to all members and confirmed first deposits for funded members.")
    print("Demo member login: any listed email / Password123")


if __name__ == "__main__":
    main()
