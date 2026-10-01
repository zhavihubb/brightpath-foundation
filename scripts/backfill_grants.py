"""One-time backfill: credit grant awards approved before the grant-credit feature.

For every application with status='approved' and an awarded_amount that has no
matching completed 'grant' transaction, this creates the grant disbursement and
credits the member's available balance — exactly as the admin approval flow now
does going forward.

It is idempotent (safe to run repeatedly) and never charges the member a fee.

Usage:
    python scripts/backfill_grants.py --dry-run   # preview only
    python scripts/backfill_grants.py             # apply

Respects BRIGHTPATH_DB (falls back to <project>/charity.db).
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("BRIGHTPATH_DB") or os.path.join(BASE_DIR, "charity.db")
DRY = "--dry-run" in sys.argv


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def main():
    if not os.path.exists(DB):
        print(f"Database not found: {DB}")
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    foundation = "Bright Future Grant"
    try:
        row = con.execute("SELECT value FROM settings WHERE key = 'foundation_name'").fetchone()
        if row and row["value"]:
            foundation = row["value"]
    except sqlite3.Error:
        pass

    apps = con.execute(
        "SELECT a.id, a.user_id, a.awarded_amount, a.currency, u.full_name, u.balance "
        "FROM applications a JOIN users u ON u.id = a.user_id "
        "WHERE a.status = 'approved' AND a.awarded_amount IS NOT NULL AND a.awarded_amount > 0 "
        "ORDER BY a.id"
    ).fetchall()

    created = skipped = 0
    for a in apps:
        ref = f"GRANT-APP-{a['id']}"
        # Already credited by the new approval flow (deterministic grant reference)?
        credited_already = con.execute(
            "SELECT 1 FROM transactions WHERE reference = ? AND type = 'grant'", (ref,)
        ).fetchone()
        # Or already disbursed as a matching completed deposit/grant (legacy data)?
        disbursed_already = con.execute(
            "SELECT 1 FROM transactions WHERE user_id = ? AND status = 'completed' "
            "AND type IN ('deposit','grant') AND ABS(amount - ?) < 0.005",
            (a["user_id"], float(a["awarded_amount"])),
        ).fetchone()
        if credited_already or disbursed_already:
            skipped += 1
            continue
        print(
            f"app #{a['id']}  {a['full_name']:<20} credit {a['currency']} "
            f"{a['awarded_amount']:>12,.2f}  (balance {a['balance']:,.2f} -> "
            f"{a['balance'] + a['awarded_amount']:,.2f})"
        )
        if DRY:
            created += 1
            continue
        con.execute(
            "INSERT INTO transactions (user_id, type, amount, currency, description, reference, "
            "sender_name, status, created_by, created_at) "
            "VALUES (?, 'grant', ?, ?, ?, ?, ?, 'completed', 1, ?)",
            (a["user_id"], float(a["awarded_amount"]), a["currency"],
             f"Grant disbursement for approved application #{a['id']}", ref, foundation, now_iso()),
        )
        con.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (float(a["awarded_amount"]), a["user_id"]),
        )
        created += 1

    if not DRY:
        con.commit()
    con.close()
    verb = "Would credit" if DRY else "Credited"
    print(f"\n{verb} {created} grant(s); skipped {skipped} already-credited.")
    if DRY:
        print("Dry run — nothing written. Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
