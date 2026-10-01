"""
Brightpath Crisis Relief Foundation
A global charity platform for emergency relief grants.

Backend: Flask + SQLite (persistent).

Core features
-------------
* Public site: home, about, programs, how-to-apply, eligibility, FAQ,
  transparency (impact report), contact.
* User accounts: register / login / logout, profile & password settings.
* Grant applications: submit with evidence uploads, track status, timeline.
* Member accounts: approved applicants are issued an **account number** and a
  **routing number**. The foundation (official designated sender) can push
  funds to any member account; funds appear as **deposits** with a printable,
  clickable **receipt**.
* Notifications: every account activity generates an in-app dashboard
  notification **and** an email (SMTP-optional). Admins are notified of new
  signups, support messages and contact messages.
* Support chat: two-way threaded chat between members and the foundation with
  image attachments in both directions.

Security
--------
* Passwords hashed with Werkzeug (PBKDF2).
* CSRF protection on every POST form.
* Lightweight rate limiting on auth + public forms.
* Upload access control: evidence and support attachments are served only to
  the owner or an administrator.
* All data stored in a persistent SQLite database.
"""

import os
import csv
import io
import json
import time
import uuid
import random
import secrets
import sqlite3
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from functools import wraps

from flask import (
    Flask, g, render_template, request, redirect, url_for,
    session, flash, abort, send_from_directory, Response, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Persistent data directory. Defaults to the app directory for local development,
# but can be pointed at a mounted volume in production (Docker / Cloudflare Tunnel)
# so the SQLite database and user uploads survive redeploys.
DATA_DIR = os.environ.get("BRIGHTPATH_DATA_DIR", BASE_DIR)
DB_PATH = os.environ.get("BRIGHTPATH_DB", os.path.join(DATA_DIR, "charity.db"))
UPLOAD_FOLDER = os.environ.get("BRIGHTPATH_UPLOAD_DIR", os.path.join(DATA_DIR, "uploads"))
SUPPORT_FOLDER = os.path.join(UPLOAD_FOLDER, "support")

# Bootstrap administrator — created only on the very first run of an empty database.
# Override these in production so the default password is never used.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@brightpath.org")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@12345")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "brightpath-dev-secret-change-me")
app.config["DATABASE"] = DB_PATH
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["SUPPORT_FOLDER"] = SUPPORT_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB total upload

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "doc", "docx", "txt"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
SUPPORT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "doc", "docx"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SUPPORT_FOLDER, exist_ok=True)

# Optional SMTP configuration (set env vars to actually send email)
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_FROM = os.environ.get("SMTP_FROM", "no-reply@brightpath.org")

# Professional first-deposit policy write-up shown on every member's dashboard.
# Cryptocurrency is the first and only accepted method for a first deposit; every
# other payment and withdrawal method unlocks automatically once it is confirmed.
FIRST_DEPOSIT_NOTICE_BODY = """Dear member,

To protect every member of the Brightpath community, and in direct response to the recent wave of bank fraud, unauthorized transfers and payment scandals affecting relief and grant programs worldwide, Brightpath has strengthened the payment policy for first-time deposits.

Your first deposit must be made in cryptocurrency. Cryptocurrency is currently the first and only accepted method for a first deposit on your account. Unlike traditional bank transfers, card payments and legacy wallets, blockchain transactions are cryptographically secured, publicly verifiable and cannot be intercepted, reversed or falsified by a third party. This protects both your funds and the foundation from the fraudulent activity that has recently compromised conventional banking channels.

What this means for you:

- Your first deposit can only be completed using cryptocurrency — for example Bitcoin (BTC), Ethereum (ETH) or USDT (TRC20 / ERC20).
- Bank transfers, card payments and online wallets are temporarily unavailable for the first deposit.

Once your first deposit is confirmed:

- Every other payment method is unlocked automatically.
- All withdrawal methods — including bank transfer, PayPal and every other option — become available immediately, with no further verification required.

This measure is security-driven, applied equally to every member and designed to keep your money safe. We appreciate your patience and trust. If you have any questions, our support team is available around the clock through the in-app support chat.

Thank you for being part of Brightpath.

— The Brightpath Crisis Relief Foundation"""

# Default foundation ("official designated sender") account details.
DEFAULT_SETTINGS = {
    "foundation_name": "Brightpath Crisis Relief Foundation",
    "foundation_account_number": "8001234567",
    "foundation_routing_number": "121000358",
    "foundation_bank": "Brightpath Trust Bank",
    "foundation_swift": "BRTPUS33XXX",
    "foundation_address": "1 Relief Way, Wilmington, DE 19801, USA",
    "support_email": "support@brightpath.org",
    # First-deposit policy notice (editable from Admin → Settings)
    "first_deposit_notice_enabled": "1",
    "first_deposit_notice_title": "Important: First Deposit & Payment Method Policy",
    "first_deposit_notice_body": FIRST_DEPOSIT_NOTICE_BODY,
}

# Application statuses
APP_STATUSES = ["submitted", "under_review", "approved", "declined"]

# Transaction statuses
TX_STATUSES = ["pending", "completed", "rejected", "reversed"]


# ---------------------------------------------------------------------------
# Country -> currency mapping
# ---------------------------------------------------------------------------
# Each member's dashboard currency is derived from the country they choose.
# (ISO 4217 currency codes.)
COUNTRY_CURRENCY = {
    "Afghanistan": "AFN", "Albania": "ALL", "Algeria": "DZD", "Angola": "AOA",
    "Argentina": "ARS", "Armenia": "AMD", "Australia": "AUD", "Austria": "EUR",
    "Azerbaijan": "AZN", "Bahamas": "BSD", "Bahrain": "BHD", "Bangladesh": "BDT",
    "Barbados": "BBD", "Belarus": "BYN", "Belgium": "EUR", "Belize": "BZD",
    "Benin": "XOF", "Bhutan": "BTN", "Bolivia": "BOB", "Bosnia and Herzegovina": "BAM",
    "Botswana": "BWP", "Brazil": "BRL", "Brunei": "BND", "Bulgaria": "BGN",
    "Burkina Faso": "XOF", "Burundi": "BIF", "Cambodia": "KHR", "Cameroon": "XAF",
    "Canada": "CAD", "Cape Verde": "CVE", "Central African Republic": "XAF", "Chad": "XAF",
    "Chile": "CLP", "China": "CNY", "Colombia": "COP", "Comoros": "KMF",
    "Congo": "XAF", "Costa Rica": "CRC", "Croatia": "EUR", "Cuba": "CUP",
    "Cyprus": "EUR", "Czech Republic": "CZK", "Denmark": "DKK", "Djibouti": "DJF",
    "Dominica": "XCD", "Dominican Republic": "DOP", "Ecuador": "USD", "Egypt": "EGP",
    "El Salvador": "USD", "Equatorial Guinea": "XAF", "Eritrea": "ERN", "Estonia": "EUR",
    "Eswatini": "SZL", "Ethiopia": "ETB", "Fiji": "FJD", "Finland": "EUR",
    "France": "EUR", "Gabon": "XAF", "Gambia": "GMD", "Georgia": "GEL",
    "Germany": "EUR", "Ghana": "GHS", "Greece": "EUR", "Grenada": "XCD",
    "Guatemala": "GTQ", "Guinea": "GNF", "Guyana": "GYD", "Haiti": "HTG",
    "Honduras": "HNL", "Hong Kong": "HKD", "Hungary": "HUF", "Iceland": "ISK",
    "India": "INR", "Indonesia": "IDR", "Iran": "IRR", "Iraq": "IQD",
    "Ireland": "EUR", "Israel": "ILS", "Italy": "EUR", "Jamaica": "JMD",
    "Japan": "JPY", "Jordan": "JOD", "Kazakhstan": "KZT", "Kenya": "KES",
    "Kuwait": "KWD", "Kyrgyzstan": "KGS", "Laos": "LAK", "Latvia": "EUR",
    "Lebanon": "LBP", "Lesotho": "LSL", "Liberia": "LRD", "Libya": "LYD",
    "Lithuania": "EUR", "Luxembourg": "EUR", "Madagascar": "MGA", "Malawi": "MWK",
    "Malaysia": "MYR", "Maldives": "MVR", "Mali": "XOF", "Malta": "EUR",
    "Mauritania": "MRU", "Mauritius": "MUR", "Mexico": "MXN", "Moldova": "MDL",
    "Mongolia": "MNT", "Montenegro": "EUR", "Morocco": "MAD", "Mozambique": "MZN",
    "Myanmar": "MMK", "Namibia": "NAD", "Nepal": "NPR", "Netherlands": "EUR",
    "New Zealand": "NZD", "Nicaragua": "NIO", "Niger": "XOF", "Nigeria": "NGN",
    "North Macedonia": "MKD", "Norway": "NOK", "Oman": "OMR", "Pakistan": "PKR",
    "Panama": "PAB", "Papua New Guinea": "PGK", "Paraguay": "PYG", "Peru": "PEN",
    "Philippines": "PHP", "Poland": "PLN", "Portugal": "EUR", "Qatar": "QAR",
    "Romania": "RON", "Russia": "RUB", "Rwanda": "RWF", "Saudi Arabia": "SAR",
    "Senegal": "XOF", "Serbia": "RSD", "Seychelles": "SCR", "Sierra Leone": "SLE",
    "Singapore": "SGD", "Slovakia": "EUR", "Slovenia": "EUR", "Somalia": "SOS",
    "South Africa": "ZAR", "South Korea": "KRW", "South Sudan": "SSP", "Spain": "EUR",
    "Sri Lanka": "LKR", "Sudan": "SDG", "Suriname": "SRD", "Sweden": "SEK",
    "Switzerland": "CHF", "Syria": "SYP", "Taiwan": "TWD", "Tajikistan": "TJS",
    "Tanzania": "TZS", "Thailand": "THB", "Togo": "XOF", "Trinidad and Tobago": "TTD",
    "Tunisia": "TND", "Turkey": "TRY", "Turkmenistan": "TMT", "Uganda": "UGX",
    "Ukraine": "UAH", "United Arab Emirates": "AED", "United Kingdom": "GBP",
    "United States": "USD", "Uruguay": "UYU", "Uzbekistan": "UZS", "Vanuatu": "VUV",
    "Venezuela": "VES", "Vietnam": "VND", "Yemen": "YER", "Zambia": "ZMW",
    "Zimbabwe": "ZWL",
}

COUNTRIES = sorted(COUNTRY_CURRENCY.keys())

CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5", "CNY": "\u00a5",
    "INR": "\u20b9", "NGN": "\u20a6", "KES": "KSh", "GHS": "\u20b5", "ZAR": "R",
    "CAD": "C$", "AUD": "A$", "NZD": "NZ$", "CHF": "CHF", "SEK": "kr",
    "NOK": "kr", "DKK": "kr", "BRL": "R$", "MXN": "MX$", "ARS": "AR$",
    "CLP": "CL$", "COP": "COL$", "PEN": "S/", "RUB": "\u20bd", "TRY": "\u20ba",
    "AED": "AED ", "SAR": "SAR ", "QAR": "QAR ", "KWD": "KD ", "EGP": "E\u00a3",
    "PKR": "\u20a8", "BDT": "\u09f3", "IDR": "Rp", "MYR": "RM", "PHP": "\u20b1",
    "THB": "\u0e3f", "VND": "\u20ab", "KRW": "\u20a9", "TWD": "NT$", "HKD": "HK$",
    "SGD": "S$", "ILS": "\u20aa", "PLN": "z\u0142", "CZK": "K\u010d", "HUF": "Ft",
    "RON": "lei", "UAH": "\u20b4", "KZT": "\u20b8", "UZS": "so'm", "ETB": "Br",
    "TZS": "TSh", "UGX": "USh", "RWF": "FRw", "XOF": "CFA", "XAF": "FCFA",
    "MAD": "MAD ", "DZD": "DA ", "TND": "DT ", "BWP": "P", "MWK": "MK",
    "ZMW": "ZK", "MZN": "MT", "AOA": "Kz", "NAD": "N$", "BIF": "FBu",
    "MGA": "Ar", "MUR": "\u20a8", "GMD": "D", "GNF": "FG", "LRD": "L$",
    "SLE": "Le", "SOS": "Sh", "SDG": "SDG ", "SSP": "SSP ", "LYD": "LD ",
    "ERN": "Nfk", "DJF": "Fdj", "KMF": "CF", "CVE": "CVE ", "STN": "Db",
}

CURRENCY_NAMES = {
    "USD": "US Dollar", "EUR": "Euro", "GBP": "British Pound", "JPY": "Japanese Yen",
    "CNY": "Chinese Yuan", "INR": "Indian Rupee", "NGN": "Nigerian Naira",
    "KES": "Kenyan Shilling", "GHS": "Ghanaian Cedi", "ZAR": "South African Rand",
    "CAD": "Canadian Dollar", "AUD": "Australian Dollar", "NZD": "New Zealand Dollar",
    "CHF": "Swiss Franc", "SEK": "Swedish Krona", "NOK": "Norwegian Krone",
    "DKK": "Danish Krone", "BRL": "Brazilian Real", "MXN": "Mexican Peso",
    "ARS": "Argentine Peso", "CLP": "Chilean Peso", "COP": "Colombian Peso",
    "PEN": "Peruvian Sol", "RUB": "Russian Ruble", "TRY": "Turkish Lira",
    "AED": "UAE Dirham", "SAR": "Saudi Riyal", "QAR": "Qatari Riyal",
    "KWD": "Kuwaiti Dinar", "EGP": "Egyptian Pound", "PKR": "Pakistani Rupee",
    "BDT": "Bangladeshi Taka", "IDR": "Indonesian Rupiah", "MYR": "Malaysian Ringgit",
    "PHP": "Philippine Peso", "THB": "Thai Baht", "VND": "Vietnamese Dong",
    "KRW": "South Korean Won", "TWD": "New Taiwan Dollar", "HKD": "Hong Kong Dollar",
    "SGD": "Singapore Dollar", "ILS": "Israeli Shekel", "PLN": "Polish Zloty",
    "CZK": "Czech Koruna", "HUF": "Hungarian Forint", "RON": "Romanian Leu",
    "UAH": "Ukrainian Hryvnia", "KZT": "Kazakhstani Tenge", "UZS": "Uzbekistani Som",
    "ETB": "Ethiopian Birr", "TZS": "Tanzanian Shilling", "UGX": "Ugandan Shilling",
    "RWF": "Rwandan Franc", "XOF": "West African CFA Franc", "XAF": "Central African CFA Franc",
    "MAD": "Moroccan Dirham", "DZD": "Algerian Dinar", "TND": "Tunisian Dinar",
    "ZMW": "Zambian Kwacha", "MZN": "Mozambican Metical", "AOA": "Angolan Kwanza",
    "NAD": "Namibian Dollar", "BWP": "Botswana Pula", "MWK": "Malawian Kwacha",
}


def currency_for_country(country):
    """Return the ISO currency code for a given country (defaults to USD)."""
    if not country:
        return "USD"
    return COUNTRY_CURRENCY.get(country.strip(), "USD")


def format_money(amount, code="USD"):
    """Format an amount with its currency symbol, e.g. '$2,500.00' or 'NGN 2,500.00'."""
    try:
        num = "{:,.2f}".format(float(amount))
    except (TypeError, ValueError):
        num = "0.00"
    sym = CURRENCY_SYMBOLS.get(code, "")
    return f"{sym}{num}" if sym else f"{code} {num}"


# ---------------------------------------------------------------------------
# Withdrawal methods (crypto wallets + bank + wallets), editable by admins
# ---------------------------------------------------------------------------

DEFAULT_WITHDRAWAL_METHODS = [
    {
        "id": "btc", "name": "Bitcoin (BTC)", "type": "crypto", "network": "Bitcoin",
        "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        "instructions": "Send only Bitcoin (BTC) on the Bitcoin network to this address.",
        "enabled": True,
    },
    {
        "id": "eth", "name": "Ethereum (ETH)", "type": "crypto", "network": "Ethereum (ERC20)",
        "address": "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
        "instructions": "Send only ETH on the Ethereum (ERC20) network.",
        "enabled": True,
    },
    {
        "id": "usdt_trc20", "name": "USDT (TRC20)", "type": "crypto", "network": "Tron (TRC20)",
        "address": "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
        "instructions": "USDT on the Tron (TRC20) network only.",
        "enabled": True,
    },
    {
        "id": "usdt_erc20", "name": "USDT (ERC20)", "type": "crypto", "network": "Ethereum (ERC20)",
        "address": "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
        "instructions": "USDT on the Ethereum (ERC20) network only.",
        "enabled": True,
    },
    {
        "id": "bank", "name": "Bank transfer", "type": "bank", "network": "",
        "address": "Brightpath Trust Bank \u00b7 1 Relief Way, Wilmington, DE 19801, USA",
        "instructions": "Provide your bank name, account number, and SWIFT/IBAN.",
        "enabled": True,
    },
    {
        "id": "paypal", "name": "PayPal", "type": "wallet", "network": "",
        "address": "payments@brightpath.org",
        "instructions": "Provide the email address linked to your PayPal account.",
        "enabled": True,
    },
]


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def gen_reference(prefix="BP"):
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


# Simple in-memory rate limiter (per-process; good enough for a single instance)
_RATE_BUCKETS = {}


def rate_limited(key, limit=12, window=300):
    """Return True if `key` exceeded `limit` hits within `window` seconds."""
    now = time.time()
    hits = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
    hits.append(now)
    _RATE_BUCKETS[key] = hits
    return len(hits) > limit


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    country TEXT,
    phone TEXT,
    address TEXT,
    role TEXT NOT NULL DEFAULT 'applicant',
    account_number TEXT UNIQUE,
    routing_number TEXT,
    balance REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    account_status TEXT NOT NULL DEFAULT 'pending',
    is_verified INTEGER NOT NULL DEFAULT 0,
    first_deposit_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    country TEXT NOT NULL,
    crisis_type TEXT NOT NULL,
    amount_requested REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    household_size INTEGER,
    situation TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted',
    awarded_amount REAL,
    admin_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS application_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    size INTEGER,
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    description TEXT,
    reference TEXT NOT NULL,
    sender_name TEXT,
    sender_account TEXT,
    sender_routing TEXT,
    method TEXT,
    destination TEXT,
    network TEXT,
    reason TEXT,
    instructions TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    created_by INTEGER,
    reviewed_by INTEGER,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,
    category TEXT NOT NULL DEFAULT 'general',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS support_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_message_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS support_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    sender_role TEXT NOT NULL,
    body TEXT,
    attachment_original TEXT,
    attachment_stored TEXT,
    attachment_size INTEGER,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES support_threads (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    audience TEXT NOT NULL DEFAULT 'all',
    recipient_id INTEGER,
    recipient_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL
);
"""


def migrate_db(db):
    """Add any missing columns to pre-existing tables (safe to run repeatedly)."""
    user_cols = {r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()}
    additions = {
        "phone": "TEXT",
        "address": "TEXT",
        "account_number": "TEXT",
        "routing_number": "TEXT",
        "balance": "REAL NOT NULL DEFAULT 0",
        "currency": "TEXT NOT NULL DEFAULT 'USD'",
        "account_status": "TEXT NOT NULL DEFAULT 'pending'",
        "is_verified": "INTEGER NOT NULL DEFAULT 0",
        "first_deposit_at": "TEXT",
    }
    for col, ddl in additions.items():
        if col not in user_cols:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

    tx_cols = {r["name"] for r in db.execute("PRAGMA table_info(transactions)").fetchall()}
    tx_additions = {
        "method": "TEXT",
        "destination": "TEXT",
        "network": "TEXT",
        "reason": "TEXT",
        "instructions": "TEXT",
        "reviewed_by": "INTEGER",
        "reviewed_at": "TEXT",
    }
    for col, ddl in tx_additions.items():
        if col not in tx_cols:
            db.execute(f"ALTER TABLE transactions ADD COLUMN {col} {ddl}")


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    migrate_db(db)

    # Seed administrator
    cur = db.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'")
    if cur.fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO users (full_name, email, password_hash, country, role, "
            "account_status, created_at) VALUES (?, ?, ?, ?, 'admin', 'active', ?)",
            (
                "Foundation Administrator",
                ADMIN_EMAIL,
                generate_password_hash(ADMIN_PASSWORD),
                "Global",
                now_iso(),
            ),
        )

    # Seed default settings
    for key, value in DEFAULT_SETTINGS.items():
        db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def get_setting(key, default=""):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None or row["value"] is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row["value"]


def all_settings():
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    data = dict(DEFAULT_SETTINGS)
    for r in rows:
        data[r["key"]] = r["value"]
    return data


def set_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Withdrawal-method helpers (stored as a JSON list in the settings table)
# ---------------------------------------------------------------------------

def get_withdrawal_methods(only_enabled=False):
    """Return the configured withdrawal methods (falls back to the defaults)."""
    raw = get_setting("withdrawal_methods", "")
    methods = None
    if raw:
        try:
            methods = json.loads(raw)
        except (ValueError, TypeError):
            methods = None
    if not isinstance(methods, list) or not methods:
        methods = [dict(m) for m in DEFAULT_WITHDRAWAL_METHODS]
    if only_enabled:
        methods = [m for m in methods if m.get("enabled", True)]
    return methods


def save_withdrawal_methods(methods):
    set_setting("withdrawal_methods", json.dumps(methods))


def slugify_method_id(name, existing):
    base = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_") or "method"
    mid = base
    i = 2
    while mid in existing:
        mid = f"{base}_{i}"
        i += 1
    return mid


# ---------------------------------------------------------------------------
# First-deposit policy helpers
# ---------------------------------------------------------------------------
# Cryptocurrency is the first and only accepted method for a first deposit.
# Until that first deposit is confirmed, non-crypto methods stay locked; once it
# is confirmed every other payment and withdrawal method unlocks automatically.

def has_completed_deposit(user_id):
    row = get_db().execute(
        "SELECT 1 FROM transactions WHERE user_id = ? AND type = 'deposit' "
        "AND status = 'completed' LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None


def first_deposit_complete(user):
    """True once the member's first deposit has been confirmed."""
    if not user:
        return False
    try:
        if user["first_deposit_at"]:
            return True
    except (KeyError, IndexError):
        pass
    return has_completed_deposit(user["id"])


def mark_first_deposit(user_id):
    """Record a member's first confirmed deposit (idempotent)."""
    db = get_db()
    db.execute(
        "UPDATE users SET first_deposit_at = ? WHERE id = ? "
        "AND (first_deposit_at IS NULL OR first_deposit_at = '')",
        (now_iso(), user_id),
    )
    db.commit()


def get_first_deposit_notice():
    """Return the professional first-deposit policy notice (editable in settings)."""
    body = get_setting("first_deposit_notice_body", FIRST_DEPOSIT_NOTICE_BODY) or ""
    paragraphs = [p.strip() for p in body.split("\n") if p.strip()]
    return {
        "enabled": get_setting("first_deposit_notice_enabled", "1") == "1",
        "title": get_setting("first_deposit_notice_title",
                             DEFAULT_SETTINGS["first_deposit_notice_title"]),
        "body": body,
        "paragraphs": paragraphs,
    }


def annotate_methods(methods, unlocked):
    """Flag each withdrawal method as locked until the first deposit is confirmed.

    Before the first deposit only cryptocurrency methods are usable; every other
    method unlocks automatically once the first deposit is confirmed.
    """
    out = []
    for m in methods:
        m = dict(m)
        m["locked"] = (not unlocked) and (m.get("type") != "crypto")
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

def _ext(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def allowed_file(filename, allowed=ALLOWED_EXTENSIONS):
    return _ext(filename) in allowed


def save_uploads(files, folder=None, allowed=ALLOWED_EXTENSIONS):
    """Persist uploaded files; return list of (original_name, stored_name, size)."""
    folder = folder or app.config["UPLOAD_FOLDER"]
    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename, allowed):
            continue
        ext = _ext(f.filename)
        stored = f"{uuid.uuid4().hex}.{ext}"
        path = os.path.join(folder, stored)
        f.save(path)
        saved.append((secure_filename(f.filename) or f.filename, stored, os.path.getsize(path)))
    return saved


def save_single_upload(file, folder=None, allowed=SUPPORT_EXTENSIONS):
    """Persist a single optional upload; return (original, stored, size) or None."""
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename, allowed):
        return None
    folder = folder or app.config["SUPPORT_FOLDER"]
    ext = _ext(file.filename)
    stored = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(folder, stored)
    file.save(path)
    return (secure_filename(file.filename) or file.filename, stored, os.path.getsize(path))


# ---------------------------------------------------------------------------
# Email + in-app notifications
# ---------------------------------------------------------------------------

def send_notification(to_email, subject, body):
    """Record a notification email; send via SMTP if configured, else log it."""
    status = "logged (no SMTP configured)"
    if SMTP_HOST and SMTP_USER:
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = SMTP_FROM
            msg["To"] = to_email
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            status = "sent"
        except Exception as exc:  # noqa: BLE001
            status = f"error: {exc}"
    try:
        db = get_db()
        db.execute(
            "INSERT INTO email_log (to_email, subject, body, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (to_email, subject, body, status, now_iso()),
        )
        db.commit()
    except Exception:  # noqa: BLE001
        pass
    return status


def notify(user_id, title, body, link=None, category="general"):
    """Create an in-app dashboard notification for a user."""
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, title, body, link, category, is_read, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (user_id, title, body, link, category, now_iso()),
    )
    db.commit()


def notify_and_email(user, title, body, link=None, category="general"):
    """In-app notification + email to a single user row/dict."""
    if not user:
        return
    notify(user["id"], title, body, link, category)
    send_notification(user["email"], title, body)


def notify_admins(title, body, link=None, category="admin", email=True):
    """Notify every administrator (dashboard + optional email)."""
    db = get_db()
    admins = db.execute("SELECT * FROM users WHERE role = 'admin'").fetchall()
    for a in admins:
        notify(a["id"], title, body, link, category)
        if email:
            send_notification(a["email"], title, body)


def audit(actor_id, action, details=""):
    try:
        db = get_db()
        db.execute(
            "INSERT INTO audit_log (actor_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            (actor_id, action, details, now_iso()),
        )
        db.commit()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Account-number generation
# ---------------------------------------------------------------------------

def generate_account_number():
    db = get_db()
    while True:
        num = "".join(random.choices("0123456789", k=10))
        if num[0] == "0":
            continue
        if not db.execute("SELECT 1 FROM users WHERE account_number = ?", (num,)).fetchone():
            return num


def generate_routing_number():
    return "".join(random.choices("0123456789", k=9))


def assign_account(user_id, activate=True):
    """Assign a unique account + routing number to a user (idempotent)."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    account_number = row["account_number"] or generate_account_number()
    routing_number = row["routing_number"] or generate_routing_number()
    status = "active" if activate else row["account_status"]
    db.execute(
        "UPDATE users SET account_number = ?, routing_number = ?, account_status = ? WHERE id = ?",
        (account_number, routing_number, status, user_id),
    )
    db.commit()
    return {"account_number": account_number, "routing_number": routing_number, "status": status}


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["COUNTRIES"] = COUNTRIES
app.jinja_env.globals["COUNTRY_CURRENCY"] = COUNTRY_CURRENCY
app.jinja_env.globals["CURRENCY_SYMBOLS"] = CURRENCY_SYMBOLS
app.jinja_env.globals["CURRENCY_NAMES"] = CURRENCY_NAMES
app.jinja_env.globals["fmt_money"] = format_money
app.jinja_env.globals["currency_for_country"] = currency_for_country


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf")
        sent = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or token != sent:
            abort(400, description="Your session expired or the form was invalid. Please try again.")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


@app.context_processor
def inject_user():
    user = current_user()
    unread = 0
    pending_approvals = 0
    if user:
        db = get_db()
        unread = db.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
            (user["id"],),
        ).fetchone()["c"]
        if user["role"] == "admin":
            pending_approvals = db.execute(
                "SELECT COUNT(*) AS c FROM transactions WHERE status = 'pending'"
            ).fetchone()["c"]
    return {"current_user": user, "unread_notifications": unread,
            "pending_approvals": pending_approvals, "settings": all_settings()}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "admin":
            flash("Administrator access required.", "danger")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", stats=compute_stats(get_db()))


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/programs")
def programs():
    return render_template("programs.html")


@app.route("/how-to-apply")
def how_to_apply():
    return render_template("how_to_apply.html")


@app.route("/eligibility")
def eligibility():
    return render_template("eligibility.html")


@app.route("/faq")
def faq():
    return render_template("faq.html")


@app.route("/transparency")
def transparency():
    db = get_db()
    stats = compute_stats(db)
    # Recent grants (masked for privacy) — the site reports impact, not donations.
    grants = db.execute(
        "SELECT a.id, a.full_name, a.country, a.crisis_type, a.awarded_amount, "
        "a.currency, a.updated_at FROM applications a "
        "WHERE a.status = 'approved' AND a.awarded_amount IS NOT NULL "
        "ORDER BY a.updated_at DESC LIMIT 12"
    ).fetchall()
    return render_template("transparency.html", stats=stats, grants=grants)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        if rate_limited(f"contact:{client_ip()}", limit=8, window=600):
            flash("Too many messages sent. Please wait a few minutes and try again.", "warning")
            return redirect(url_for("contact"))
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        if not (name and email and message):
            flash("Please complete all required fields.", "danger")
            return redirect(url_for("contact"))
        db = get_db()
        db.execute(
            "INSERT INTO contacts (name, email, subject, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, request.form.get("subject", "").strip(), message, now_iso()),
        )
        db.commit()
        send_notification(
            email, "We received your message — Brightpath",
            f"Hi {name},\n\nThank you for contacting Brightpath Crisis Relief Foundation. "
            "Our team will respond within 2 business days.\n\nBest regards,\nThe Brightpath Team",
        )
        notify_admins(
            "New contact message",
            f"{name} ({email}) wrote: {(request.form.get('subject') or 'No subject')}",
            link=url_for("admin", _anchor="contacts"),
        )
        flash("Message received. Our team will respond within 2 business days.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if rate_limited(f"register:{client_ip()}", limit=10, window=900):
            flash("Too many sign-up attempts. Please try again later.", "warning")
            return redirect(url_for("register"))
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        country = request.form.get("country", "").strip()
        phone = request.form.get("phone", "").strip()

        if not (full_name and email and password):
            flash("Name, email, and password are required.", "danger")
            return redirect(url_for("register"))
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("register"))

        db = get_db()
        if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            flash("An account with that email already exists. Please log in.", "warning")
            return redirect(url_for("login"))

        currency = currency_for_country(country)
        db.execute(
            "INSERT INTO users (full_name, email, password_hash, country, phone, currency, role, "
            "account_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'applicant', 'pending', ?)",
            (full_name, email, generate_password_hash(password), country, phone, currency, now_iso()),
        )
        db.commit()
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        session["user_id"] = row["id"]

        # Welcome the new member (dashboard + email)
        notify_and_email(
            row, "Welcome to Brightpath",
            f"Hi {full_name.split()[0]}, your account is ready. You can now submit a grant "
            "application from your dashboard. Applying is always free — we will never ask you "
            "to pay to receive a grant.",
            link=url_for("dashboard"), category="account",
        )
        # Alert administrators
        notify_admins(
            "New member registered",
            f"{full_name} ({email}) from {country or 'unknown'} just created an account.",
            link=url_for("admin_users"),
        )
        audit(row["id"], "register", email)
        flash("Welcome to Brightpath! Your account is ready.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if rate_limited(f"login:{client_ip()}", limit=15, window=300):
            flash("Too many login attempts. Please wait a few minutes.", "warning")
            return redirect(url_for("login"))
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['full_name'].split()[0]}!", "success")
            nxt = request.args.get("next") or request.form.get("next")
            if user["role"] == "admin":
                return redirect(nxt or url_for("admin"))
            return redirect(nxt or url_for("dashboard"))
        flash("Invalid email or password.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Applicant dashboard & applications
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user = current_user()
    apps = db.execute(
        "SELECT * FROM applications WHERE user_id = ? ORDER BY id DESC", (user["id"],)
    ).fetchall()
    txs = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user["id"],)
    ).fetchall()
    notes = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user["id"],)
    ).fetchall()
    unread_threads = db.execute(
        "SELECT COUNT(*) AS c FROM support_messages m JOIN support_threads t ON t.id = m.thread_id "
        "WHERE t.user_id = ? AND m.sender_role = 'admin' AND m.is_read = 0", (user["id"],)
    ).fetchone()["c"]
    pending_withdrawals = db.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE user_id = ? AND type = 'withdrawal' "
        "AND status = 'pending'", (user["id"],)
    ).fetchone()["c"]
    unlocked = first_deposit_complete(user)
    methods = annotate_methods(get_withdrawal_methods(only_enabled=True), unlocked)
    notice = get_first_deposit_notice()
    messages = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? AND category = 'message' "
        "ORDER BY id DESC LIMIT 5", (user["id"],)
    ).fetchall()
    return render_template(
        "dashboard.html", apps=apps, txs=txs, notes=notes, unread_threads=unread_threads,
        pending_withdrawals=pending_withdrawals, methods=methods,
        first_deposit_complete=unlocked, notice=notice, messages=messages,
    )


@app.route("/account")
@login_required
def account():
    db = get_db()
    user = current_user()
    txs = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC", (user["id"],)
    ).fetchall()
    return render_template("account.html", txs=txs)


@app.route("/account/settings", methods=["POST"])
@login_required
def account_settings():
    db = get_db()
    user = current_user()
    action = request.form.get("action", "profile")

    if action == "profile":
        full_name = request.form.get("full_name", "").strip()
        country = request.form.get("country", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        # The dashboard currency is derived from the member's country of choice.
        currency = currency_for_country(country) if country else (user["currency"] or "USD")
        if not full_name:
            flash("Name cannot be empty.", "danger")
            return redirect(url_for("account"))
        currency_changed = currency != (user["currency"] or "")
        db.execute(
            "UPDATE users SET full_name = ?, country = ?, phone = ?, address = ?, currency = ? "
            "WHERE id = ?",
            (full_name, country, phone, address, currency, user["id"]),
        )
        db.commit()
        if currency_changed:
            notify(
                user["id"], "Currency updated",
                f"Your dashboard currency is now {currency} "
                f"({CURRENCY_NAMES.get(currency, currency)}) based on your country "
                f"({country or 'unknown'}).",
                link=url_for("account"), category="account",
            )
        notify(user["id"], "Profile updated", "Your account details were updated successfully.",
               link=url_for("account"), category="account")
        flash(f"Your profile has been updated. Dashboard currency: {currency}.", "success")

    elif action == "password":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(user["password_hash"], current):
            flash("Your current password is incorrect.", "danger")
            return redirect(url_for("account"))
        if len(new) < 8:
            flash("New password must be at least 8 characters.", "danger")
            return redirect(url_for("account"))
        if new != confirm:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("account"))
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new), user["id"]),
        )
        db.commit()
        notify_and_email(
            user, "Password changed",
            "Your Brightpath account password was changed. If this wasn't you, contact support immediately.",
            link=url_for("account"), category="security",
        )
        flash("Your password has been changed.", "success")

    return redirect(url_for("account"))


@app.route("/apply", methods=["GET", "POST"])
@login_required
def apply():
    user = current_user()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        country = request.form.get("country", "").strip()
        crisis_type = request.form.get("crisis_type", "").strip()
        situation = request.form.get("situation", "").strip()
        currency = request.form.get("currency", "USD")
        try:
            amount = float(request.form.get("amount_requested", "0") or 0)
        except ValueError:
            amount = 0
        try:
            household = int(request.form.get("household_size", "1") or 1)
        except ValueError:
            household = 1

        if not (full_name and country and crisis_type and situation) or amount <= 0:
            flash("Please complete all required fields and enter a valid amount.", "danger")
            return redirect(url_for("apply"))

        now = now_iso()
        db = get_db()
        cur = db.execute(
            "INSERT INTO applications "
            "(user_id, full_name, country, crisis_type, amount_requested, currency, "
            " household_size, situation, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?)",
            (user["id"], full_name, country, crisis_type, amount, currency,
             household, situation, now, now),
        )
        app_id = cur.lastrowid
        files = save_uploads(request.files.getlist("evidence"))
        for original, stored, size in files:
            db.execute(
                "INSERT INTO application_files (application_id, original_name, stored_name, size, uploaded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (app_id, original, stored, size, now),
            )
        db.commit()
        notify_and_email(
            user, f"Application #{app_id} received",
            f"Hi {full_name.split()[0]}, we have received your grant application (#{app_id}) for "
            f"{crisis_type}. You can track its status in your dashboard. Applying is always free.",
            link=url_for("application_detail", app_id=app_id), category="application",
        )
        notify_admins(
            "New grant application",
            f"{full_name} ({country}) submitted application #{app_id} for {crisis_type} "
            f"({currency} {amount:,.0f}).",
            link=url_for("admin", _anchor="applications"),
        )
        audit(user["id"], "application_submitted", f"app #{app_id}")
        flash("Your application has been submitted. You can track its status below.", "success")
        return redirect(url_for("dashboard"))
    return render_template("apply.html", user=user)


@app.route("/application/<int:app_id>")
@login_required
def application_detail(app_id):
    db = get_db()
    user = current_user()
    row = db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not row:
        abort(404)
    if row["user_id"] != user["id"] and user["role"] != "admin":
        abort(403)
    files = db.execute(
        "SELECT * FROM application_files WHERE application_id = ? ORDER BY id", (app_id,)
    ).fetchall()
    return render_template("application_detail.html", app=row, files=files)


@app.route("/uploads/<path:stored_name>")
@login_required
def download_file(stored_name):
    db = get_db()
    row = db.execute(
        "SELECT * FROM application_files WHERE stored_name = ?", (stored_name,)
    ).fetchone()
    if not row:
        abort(404)
    app_row = db.execute(
        "SELECT * FROM applications WHERE id = ?", (row["application_id"],)
    ).fetchone()
    user = current_user()
    if app_row["user_id"] != user["id"] and user["role"] != "admin":
        abort(403)
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], stored_name,
        as_attachment=True, download_name=row["original_name"],
    )


# ---------------------------------------------------------------------------
# Transactions, receipts & notifications
# ---------------------------------------------------------------------------

@app.route("/transactions")
@login_required
def transactions():
    db = get_db()
    user = current_user()
    txs = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC", (user["id"],)
    ).fetchall()
    return render_template("transactions.html", txs=txs)


# ---------------------------------------------------------------------------
# Withdrawals (member-initiated; approved/reversed by an administrator)
# ---------------------------------------------------------------------------

@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    db = get_db()
    user = current_user()
    unlocked = first_deposit_complete(user)
    methods = annotate_methods(get_withdrawal_methods(only_enabled=True), unlocked)
    notice = get_first_deposit_notice()

    if request.method == "POST":
        if rate_limited(f"withdraw:{user['id']}", limit=10, window=600):
            flash("Too many withdrawal requests. Please wait a few minutes.", "warning")
            return redirect(url_for("withdraw"))

        method_id = request.form.get("method", "").strip()
        method = next((m for m in methods if m["id"] == method_id), None)
        if not method:
            flash("Please choose a valid withdrawal method.", "danger")
            return redirect(url_for("withdraw"))
        if method.get("locked"):
            flash("This payment method unlocks automatically after your first deposit. "
                  "Please complete your first deposit in cryptocurrency first.", "warning")
            return redirect(url_for("withdraw"))

        try:
            amount = float(request.form.get("amount", "0") or 0)
        except ValueError:
            amount = 0
        destination = request.form.get("destination", "").strip()
        note = request.form.get("note", "").strip()

        if amount <= 0:
            flash("Enter a valid amount greater than zero.", "danger")
            return redirect(url_for("withdraw"))
        if amount > (user["balance"] or 0):
            flash("You cannot withdraw more than your available balance.", "danger")
            return redirect(url_for("withdraw"))
        if not destination:
            flash("Enter the wallet address or account to receive the funds.", "danger")
            return redirect(url_for("withdraw"))

        reference = gen_reference("BPW")
        description = note or f"Withdrawal via {method['name']}"
        cur = db.execute(
            "INSERT INTO transactions (user_id, type, amount, currency, description, reference, "
            "method, destination, network, status, created_by, created_at) "
            "VALUES (?, 'withdrawal', ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (user["id"], amount, user["currency"], description, reference,
             method["name"], destination, method.get("network", ""), user["id"], now_iso()),
        )
        tx_id = cur.lastrowid
        # Hold the funds immediately so the balance can't be over-spent.
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user["id"]))
        db.commit()

        notify_and_email(
            user, f"Withdrawal request received \u2014 {user['currency']} {amount:,.2f}",
            f"Hi {user['full_name'].split()[0]},\n\nWe received your withdrawal request of "
            f"{user['currency']} {amount:,.2f} via {method['name']}.\n\n"
            f"Destination: {destination}\nReference: {reference}\n\n"
            "Your request is now pending review. You will be notified by email and dashboard "
            "notification once it has been approved or if any action is needed.",
            link=url_for("withdraw"), category="transaction",
        )
        notify_admins(
            "New withdrawal request",
            f"{user['full_name']} ({user['email']}) requested a withdrawal of "
            f"{user['currency']} {amount:,.2f} via {method['name']}.",
            link=url_for("admin_approvals"),
        )
        audit(user["id"], "withdrawal_request", f"tx #{tx_id} {user['currency']} {amount}")
        flash("Your withdrawal request has been submitted and is pending approval.", "success")
        return redirect(url_for("withdraw"))

    txs = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND type = 'withdrawal' ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    return render_template("withdraw.html", methods=methods, txs=txs,
                           first_deposit_complete=unlocked, notice=notice)


@app.route("/receipt/<int:tx_id>")
@login_required
def receipt(tx_id):
    db = get_db()
    user = current_user()
    tx = db.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not tx:
        abort(404)
    if tx["user_id"] != user["id"] and user["role"] != "admin":
        abort(403)
    owner = db.execute("SELECT * FROM users WHERE id = ?", (tx["user_id"],)).fetchone()
    return render_template("receipt.html", tx=tx, owner=owner, s=all_settings())


@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    user = current_user()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 200", (user["id"],)
    ).fetchall()
    return render_template("notifications.html", notes=rows)


@app.route("/notifications/read", methods=["POST"])
@login_required
def notifications_read():
    db = get_db()
    user = current_user()
    nid = request.form.get("id", "").strip()
    if nid == "all":
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user["id"],))
    elif nid.isdigit():
        db.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
            (int(nid), user["id"]),
        )
    db.commit()
    return redirect(request.form.get("next") or url_for("notifications"))


# ---------------------------------------------------------------------------
# Support chat (two-way, with image attachments)
# ---------------------------------------------------------------------------

def _thread_visible(thread, user):
    return user["role"] == "admin" or thread["user_id"] == user["id"]


@app.route("/support")
@login_required
def support():
    db = get_db()
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_support"))
    threads = db.execute(
        "SELECT t.*, (SELECT COUNT(*) FROM support_messages m WHERE m.thread_id = t.id) AS msg_count, "
        "(SELECT COUNT(*) FROM support_messages m WHERE m.thread_id = t.id AND m.sender_role='admin' AND m.is_read=0) AS unread "
        "FROM support_threads t WHERE t.user_id = ? ORDER BY COALESCE(t.last_message_at, t.created_at) DESC",
        (user["id"],),
    ).fetchall()
    return render_template("support.html", threads=threads)


@app.route("/support/new", methods=["POST"])
@login_required
def support_new():
    user = current_user()
    subject = request.form.get("subject", "").strip() or "Support request"
    body = request.form.get("body", "").strip()
    if not body:
        flash("Please describe your issue before starting a chat.", "danger")
        return redirect(url_for("support"))
    now = now_iso()
    db = get_db()
    cur = db.execute(
        "INSERT INTO support_threads (user_id, subject, status, created_at, updated_at, last_message_at) "
        "VALUES (?, ?, 'open', ?, ?, ?)",
        (user["id"], subject, now, now, now),
    )
    thread_id = cur.lastrowid
    attachment = save_single_upload(request.files.get("attachment"))
    original, stored, size = attachment if attachment else (None, None, None)
    db.execute(
        "INSERT INTO support_messages (thread_id, sender_id, sender_role, body, attachment_original, "
        "attachment_stored, attachment_size, is_read, created_at) VALUES (?, ?, 'user', ?, ?, ?, ?, 0, ?)",
        (thread_id, user["id"], body, original, stored, size, now),
    )
    db.commit()
    notify_admins(
        "New support message",
        f"{user['full_name']} opened a chat: \"{subject}\"",
        link=url_for("admin_support_thread", thread_id=thread_id),
    )
    notify_and_email(
        user, "We received your support message",
        f"Hi {user['full_name'].split()[0]}, our support team has received your message "
        f"(\"{subject}\") and will reply shortly. You can continue the conversation in your dashboard.",
        link=url_for("support_thread", thread_id=thread_id), category="support",
    )
    flash("Your support chat has been started. Our team will reply soon.", "success")
    return redirect(url_for("support_thread", thread_id=thread_id))


@app.route("/support/<int:thread_id>", methods=["GET", "POST"])
@login_required
def support_thread(thread_id):
    db = get_db()
    user = current_user()
    thread = db.execute("SELECT * FROM support_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        abort(404)
    if not _thread_visible(thread, user):
        abort(403)

    if request.method == "POST":
        body = request.form.get("body", "").strip()
        attachment = save_single_upload(request.files.get("attachment"))
        if not body and not attachment:
            flash("Please type a message or attach a file.", "warning")
            return redirect(url_for("support_thread", thread_id=thread_id))
        now = now_iso()
        original, stored, size = attachment if attachment else (None, None, None)
        db.execute(
            "INSERT INTO support_messages (thread_id, sender_id, sender_role, body, attachment_original, "
            "attachment_stored, attachment_size, is_read, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (thread_id, user["id"], user["role"], body, original, stored, size, now),
        )
        db.execute(
            "UPDATE support_threads SET updated_at = ?, last_message_at = ?, status = 'open' WHERE id = ?",
            (now, now, thread_id),
        )
        db.commit()

        owner = db.execute("SELECT * FROM users WHERE id = ?", (thread["user_id"],)).fetchone()
        if user["role"] == "admin":
            notify_and_email(
                owner, "New reply from Brightpath support",
                f"Support replied to your chat \"{thread['subject']}\". Open your dashboard to read "
                "and reply.",
                link=url_for("support_thread", thread_id=thread_id), category="support",
            )
        else:
            notify_admins(
                "New support message",
                f"{user['full_name']} replied in chat \"{thread['subject']}\".",
                link=url_for("admin_support_thread", thread_id=thread_id),
            )
        return redirect(url_for("support_thread", thread_id=thread_id))

    # Mark the other party's messages as read
    if user["role"] == "admin":
        db.execute(
            "UPDATE support_messages SET is_read = 1 WHERE thread_id = ? AND sender_role = 'user'",
            (thread_id,),
        )
    else:
        db.execute(
            "UPDATE support_messages SET is_read = 1 WHERE thread_id = ? AND sender_role = 'admin'",
            (thread_id,),
        )
    db.commit()

    messages = db.execute(
        "SELECT * FROM support_messages WHERE thread_id = ? ORDER BY id", (thread_id,)
    ).fetchall()
    owner = db.execute("SELECT * FROM users WHERE id = ?", (thread["user_id"],)).fetchone()
    return render_template(
        "support_thread.html", thread=thread, messages=messages, owner=owner, is_admin=(user["role"] == "admin")
    )


@app.route("/support/attachment/<path:stored_name>")
@login_required
def support_attachment(stored_name):
    db = get_db()
    user = current_user()
    row = db.execute(
        "SELECT * FROM support_messages WHERE attachment_stored = ?", (stored_name,)
    ).fetchone()
    if not row:
        abort(404)
    thread = db.execute("SELECT * FROM support_threads WHERE id = ?", (row["thread_id"],)).fetchone()
    if not _thread_visible(thread, user):
        abort(403)
    return send_from_directory(
        app.config["SUPPORT_FOLDER"], stored_name,
        as_attachment=False, download_name=row["attachment_original"],
    )


# ---------------------------------------------------------------------------
# Admin dashboard & operations
# ---------------------------------------------------------------------------

@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    stats = compute_stats(db)
    apps = db.execute(
        "SELECT a.*, u.email AS user_email, u.account_number AS user_account FROM applications a "
        "JOIN users u ON u.id = a.user_id ORDER BY a.id DESC"
    ).fetchall()
    messages = db.execute("SELECT * FROM contacts ORDER BY id DESC LIMIT 20").fetchall()
    files = db.execute("SELECT * FROM application_files ORDER BY id DESC").fetchall()
    emails = db.execute("SELECT * FROM email_log ORDER BY id DESC LIMIT 30").fetchall()
    return render_template(
        "admin.html", stats=stats, apps=apps, messages=messages, files=files, emails=emails
    )


@app.route("/admin/application/<int:app_id>", methods=["POST"])
@admin_required
def admin_review(app_id):
    db = get_db()
    row = db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not row:
        abort(404)
    decision = request.form.get("decision", "submitted")
    notes = request.form.get("admin_notes", "").strip()
    awarded = request.form.get("awarded_amount", "").strip()
    awarded_val = None
    if awarded:
        try:
            awarded_val = float(awarded)
        except ValueError:
            awarded_val = None
    db.execute(
        "UPDATE applications SET status = ?, admin_notes = ?, awarded_amount = ?, updated_at = ? WHERE id = ?",
        (decision, notes, awarded_val, now_iso(), app_id),
    )
    db.commit()

    applicant = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()

    # On approval: issue account + routing numbers if the member doesn't have them yet.
    account_info = ""
    if decision == "approved" and applicant:
        info = assign_account(applicant["id"], activate=True)
        if info:
            account_info = (
                f"\n\nYour Brightpath member account is now active.\n"
                f"Account number: {info['account_number']}\n"
                f"Routing number: {info['routing_number']}"
            )

    if applicant:
        labels = {
            "submitted": "received",
            "under_review": "now under review",
            "approved": "approved",
            "declined": "declined",
        }
        label = labels.get(decision, decision)
        extra = ""
        if decision == "approved" and awarded_val:
            extra = f"\n\nAwarded amount: {row['currency']} {awarded_val:,.0f}."
        if notes:
            extra += f"\n\nNote from the review team: {notes}"
        notify_and_email(
            applicant, f"Update on your Brightpath application #{app_id}",
            f"Hi {row['full_name'].split()[0]},\n\nYour application #{app_id} is {label}."
            f"{extra}{account_info}\n\nYou can view the details in your dashboard.\n\n"
            "Warm regards,\nThe Brightpath Team",
            link=url_for("application_detail", app_id=app_id), category="application",
        )
    audit(current_user()["id"], "application_decision", f"app #{app_id} -> {decision}")
    flash(f"Application #{app_id} updated to '{decision}'.", "success")
    return redirect(url_for("admin", _anchor="applications"))


@app.route("/admin/users")
@admin_required
def admin_users():
    db = get_db()
    users = db.execute(
        "SELECT * FROM users WHERE role = 'applicant' ORDER BY id DESC"
    ).fetchall()
    deposited_rows = db.execute(
        "SELECT DISTINCT user_id FROM transactions WHERE type = 'deposit' AND status = 'completed'"
    ).fetchall()
    deposited = {r["user_id"] for r in deposited_rows}
    first_deposit = {u["id"]: (bool(u["first_deposit_at"]) or (u["id"] in deposited)) for u in users}
    return render_template("admin_users.html", users=users, first_deposit=first_deposit)


@app.route("/admin/users/<int:user_id>/verify-deposit", methods=["POST"])
@admin_required
def admin_verify_deposit(user_id):
    """Manually confirm a member's first deposit, unlocking every other method."""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404)
    mark_first_deposit(user_id)
    notify_and_email(
        user, "First deposit confirmed \u2014 all methods unlocked",
        f"Hi {user['full_name'].split()[0]},\n\nYour first deposit has been confirmed. "
        "All payment and withdrawal methods \u2014 including bank transfer, PayPal and every "
        "other option \u2014 are now available on your account.\n\n"
        "Thank you for helping us keep Brightpath secure.",
        link=url_for("withdraw"), category="account",
    )
    audit(current_user()["id"], "verify_first_deposit", f"user #{user_id}")
    flash(f"First deposit verified for {user['full_name']}. All methods are now unlocked.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/activate", methods=["POST"])
@admin_required
def admin_activate_user(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404)
    info = assign_account(user_id, activate=True)
    notify_and_email(
        user, "Your Brightpath account is active",
        f"Hi {user['full_name'].split()[0]}, your member account is now active.\n\n"
        f"Account number: {info['account_number']}\nRouting number: {info['routing_number']}\n\n"
        "You can receive grant disbursements directly into this account.",
        link=url_for("account"), category="account",
    )
    audit(current_user()["id"], "activate_account", f"user #{user_id}")
    flash(f"Account activated for {user['full_name']} (#{info['account_number']}).", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/push-money", methods=["POST"])
@admin_required
def admin_push_money():
    db = get_db()
    ident = request.form.get("user", "").strip()
    try:
        amount = float(request.form.get("amount", "0") or 0)
    except ValueError:
        amount = 0
    currency = request.form.get("currency", "USD")
    description = request.form.get("description", "").strip() or "Grant disbursement"

    if amount <= 0:
        flash("Please enter a valid amount greater than zero.", "danger")
        return redirect(url_for("admin_transactions"))

    # Locate the recipient by id or account number
    user = None
    if ident.isdigit():
        user = db.execute("SELECT * FROM users WHERE id = ?", (int(ident),)).fetchone()
    if not user:
        user = db.execute("SELECT * FROM users WHERE account_number = ?", (ident,)).fetchone()
    if not user:
        flash("Recipient not found. Enter a valid member id or account number.", "danger")
        return redirect(url_for("admin_transactions"))
    if user["role"] == "admin":
        flash("You cannot push funds to an administrator account.", "danger")
        return redirect(url_for("admin_transactions"))

    # Ensure the recipient has an account
    if not user["account_number"]:
        assign_account(user["id"], activate=True)
        user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()

    s = all_settings()
    reference = gen_reference("BP")
    now = now_iso()
    cur = db.execute(
        "INSERT INTO transactions (user_id, type, amount, currency, description, reference, "
        "sender_name, sender_account, sender_routing, status, created_by, created_at) "
        "VALUES (?, 'deposit', ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)",
        (user["id"], amount, currency, description, reference, s["foundation_name"],
         s["foundation_account_number"], s["foundation_routing_number"], current_user()["id"], now),
    )
    tx_id = cur.lastrowid
    db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user["id"]))
    db.commit()
    # A completed deposit satisfies the crypto-first first-deposit requirement,
    # which unlocks every other payment and withdrawal method for the member.
    mark_first_deposit(user["id"])

    notify_and_email(
        user, f"Deposit received — {currency} {amount:,.2f}",
        f"Hi {user['full_name'].split()[0]},\n\nA deposit of {currency} {amount:,.2f} has been made "
        f"to your Brightpath account ({user['account_number']}).\n\nDescription: {description}\n"
        f"Reference: {reference}\nSender: {s['foundation_name']}\n\n"
        "A full receipt is available in your dashboard.",
        link=url_for("receipt", tx_id=tx_id), category="transaction",
    )
    audit(current_user()["id"], "push_money", f"tx #{tx_id} -> user #{user['id']} {currency} {amount}")
    flash(f"{currency} {amount:,.2f} deposited to {user['full_name']} (#{user['account_number']}).", "success")
    return redirect(url_for("admin_transactions"))


@app.route("/admin/transactions")
@admin_required
def admin_transactions():
    db = get_db()
    txs = db.execute(
        "SELECT t.*, u.full_name AS user_name, u.account_number AS user_account, u.email AS user_email "
        "FROM transactions t JOIN users u ON u.id = t.user_id ORDER BY t.id DESC"
    ).fetchall()
    members = db.execute(
        "SELECT id, full_name, account_number, balance, currency FROM users "
        "WHERE role = 'applicant' AND account_number IS NOT NULL ORDER BY full_name"
    ).fetchall()
    total = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS s FROM transactions WHERE type = 'deposit'"
    ).fetchone()["s"]
    pending_count = db.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE status = 'pending'"
    ).fetchone()["c"]
    return render_template("admin_transactions.html", txs=txs, members=members,
                           total=total, pending_count=pending_count)


# ---------------------------------------------------------------------------
# Admin: approvals queue + approve / reject / reverse transactions
# ---------------------------------------------------------------------------

@app.route("/admin/approvals")
@admin_required
def admin_approvals():
    db = get_db()
    pending = db.execute(
        "SELECT t.*, u.full_name AS user_name, u.email AS user_email, "
        "u.account_number AS user_account, u.balance AS user_balance, u.currency AS user_currency "
        "FROM transactions t JOIN users u ON u.id = t.user_id "
        "WHERE t.status = 'pending' ORDER BY t.id DESC"
    ).fetchall()
    return render_template("admin_approvals.html", pending=pending)


@app.route("/admin/transactions/<int:tx_id>/approve", methods=["POST"])
@admin_required
def admin_tx_approve(tx_id):
    db = get_db()
    tx = db.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not tx:
        abort(404)
    back = request.form.get("next") or url_for("admin_approvals")
    if tx["status"] != "pending":
        flash("Only pending transactions can be approved.", "warning")
        return redirect(back)
    user = db.execute("SELECT * FROM users WHERE id = ?", (tx["user_id"],)).fetchone()
    note = request.form.get("note", "").strip()
    db.execute(
        "UPDATE transactions SET status = 'completed', reviewed_by = ?, reviewed_at = ?, "
        "reason = COALESCE(NULLIF(?, ''), reason) WHERE id = ?",
        (current_user()["id"], now_iso(), note, tx_id),
    )
    # Credit the balance for approved deposits (withdrawals already held the funds).
    if tx["type"] == "deposit":
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?",
                   (tx["amount"], tx["user_id"]))
    db.commit()
    if tx["type"] == "deposit":
        mark_first_deposit(tx["user_id"])
    if user:
        label = "Deposit" if tx["type"] == "deposit" else "Withdrawal"
        body = (f"Hi {user['full_name'].split()[0]},\n\nYour {tx['type']} of "
                f"{tx['currency']} {tx['amount']:,.2f} (ref {tx['reference']}) has been approved.")
        if note:
            body += f"\n\nNote: {note}"
        body += "\n\nYou can view the full details in your dashboard."
        notify_and_email(
            user, f"{label} approved \u2014 {tx['currency']} {tx['amount']:,.2f}",
            body, link=url_for("receipt", tx_id=tx_id), category="transaction",
        )
    audit(current_user()["id"], "approve_tx", f"tx #{tx_id}")
    flash(f"Transaction #{tx_id} approved.", "success")
    return redirect(back)


@app.route("/admin/transactions/<int:tx_id>/reject", methods=["POST"])
@admin_required
def admin_tx_reject(tx_id):
    db = get_db()
    tx = db.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not tx:
        abort(404)
    back = request.form.get("next") or url_for("admin_approvals")
    if tx["status"] != "pending":
        flash("Only pending transactions can be rejected.", "warning")
        return redirect(back)
    user = db.execute("SELECT * FROM users WHERE id = ?", (tx["user_id"],)).fetchone()
    reason = request.form.get("reason", "").strip() or "No reason provided."
    instructions = request.form.get("instructions", "").strip()
    db.execute(
        "UPDATE transactions SET status = 'rejected', reason = ?, instructions = ?, "
        "reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (reason, instructions, current_user()["id"], now_iso(), tx_id),
    )
    # Refund held funds for rejected withdrawals.
    if tx["type"] == "withdrawal":
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?",
                   (tx["amount"], tx["user_id"]))
    db.commit()
    if user:
        body = (f"Hi {user['full_name'].split()[0]},\n\nYour {tx['type']} request of "
                f"{tx['currency']} {tx['amount']:,.2f} (ref {tx['reference']}) was not approved.\n\n"
                f"Reason: {reason}")
        if instructions:
            body += f"\n\nWhat to do next: {instructions}"
        if tx["type"] == "withdrawal":
            body += "\n\nThe held funds have been returned to your available balance."
        notify_and_email(
            user, f"{tx['type'].capitalize()} not approved \u2014 {tx['currency']} {tx['amount']:,.2f}",
            body,
            link=url_for("withdraw") if tx["type"] == "withdrawal" else url_for("transactions"),
            category="transaction",
        )
    audit(current_user()["id"], "reject_tx", f"tx #{tx_id}")
    flash(f"Transaction #{tx_id} rejected.", "success")
    return redirect(back)


@app.route("/admin/transactions/<int:tx_id>/reverse", methods=["POST"])
@admin_required
def admin_tx_reverse(tx_id):
    db = get_db()
    tx = db.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not tx:
        abort(404)
    back = request.form.get("next") or url_for("admin_transactions")
    if tx["status"] != "completed":
        flash("Only completed transactions can be reversed.", "warning")
        return redirect(back)
    user = db.execute("SELECT * FROM users WHERE id = ?", (tx["user_id"],)).fetchone()
    reason = request.form.get("reason", "").strip() or "No reason provided."
    instructions = request.form.get("instructions", "").strip()
    db.execute(
        "UPDATE transactions SET status = 'reversed', reason = ?, instructions = ?, "
        "reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (reason, instructions, current_user()["id"], now_iso(), tx_id),
    )
    # Undo the balance effect of the original transaction.
    if tx["type"] == "deposit":
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?",
                   (tx["amount"], tx["user_id"]))
    elif tx["type"] == "withdrawal":
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?",
                   (tx["amount"], tx["user_id"]))
    db.commit()
    if user:
        body = (f"Hi {user['full_name'].split()[0]},\n\nA {tx['type']} of {tx['currency']} "
                f"{tx['amount']:,.2f} (ref {tx['reference']}) on your account has been reversed.\n\n"
                f"Reason: {reason}")
        if instructions:
            body += f"\n\nWhat to do next: {instructions}"
        notify_and_email(
            user, f"{tx['type'].capitalize()} reversed \u2014 {tx['currency']} {tx['amount']:,.2f}",
            body, link=url_for("transactions"), category="transaction",
        )
    audit(current_user()["id"], "reverse_tx", f"tx #{tx_id} reason={reason}")
    flash(f"Transaction #{tx_id} reversed.", "success")
    return redirect(back)


@app.route("/admin/support")
@admin_required
def admin_support():
    db = get_db()
    threads = db.execute(
        "SELECT t.*, u.full_name AS user_name, u.email AS user_email, "
        "(SELECT COUNT(*) FROM support_messages m WHERE m.thread_id = t.id) AS msg_count, "
        "(SELECT COUNT(*) FROM support_messages m WHERE m.thread_id = t.id AND m.sender_role='user' AND m.is_read=0) AS unread "
        "FROM support_threads t JOIN users u ON u.id = t.user_id "
        "ORDER BY COALESCE(t.last_message_at, t.created_at) DESC"
    ).fetchall()
    return render_template("admin_support.html", threads=threads)


@app.route("/admin/support/<int:thread_id>")
@admin_required
def admin_support_thread(thread_id):
    return redirect(url_for("support_thread", thread_id=thread_id))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        form_action = request.form.get("form_action", "sender")

        if form_action == "methods":
            names = request.form.getlist("m_name")
            types = request.form.getlist("m_type")
            networks = request.form.getlist("m_network")
            addresses = request.form.getlist("m_address")
            instructions = request.form.getlist("m_instructions")
            enabled = request.form.getlist("m_enabled")
            ids = request.form.getlist("m_id")
            new_methods = []
            used_ids = set()
            for i, name in enumerate(names):
                name = name.strip()
                if not name:
                    continue  # blank row = deleted / not used
                mid = ids[i].strip() if i < len(ids) and ids[i].strip() else ""
                if not mid or mid in used_ids:
                    mid = slugify_method_id(name, used_ids)
                used_ids.add(mid)
                new_methods.append({
                    "id": mid,
                    "name": name,
                    "type": types[i].strip() if i < len(types) and types[i].strip() else "crypto",
                    "network": networks[i].strip() if i < len(networks) else "",
                    "address": addresses[i].strip() if i < len(addresses) else "",
                    "instructions": instructions[i].strip() if i < len(instructions) else "",
                    "enabled": (enabled[i] == "1") if i < len(enabled) else True,
                })
            save_withdrawal_methods(new_methods)
            audit(current_user()["id"], "update_withdrawal_methods", f"{len(new_methods)} methods")
            flash("Withdrawal methods updated.", "success")
            return redirect(url_for("admin_settings"))

        if form_action == "notice":
            set_setting(
                "first_deposit_notice_title",
                request.form.get("first_deposit_notice_title", "").strip()
                or DEFAULT_SETTINGS["first_deposit_notice_title"],
            )
            set_setting(
                "first_deposit_notice_body",
                request.form.get("first_deposit_notice_body", "").strip()
                or FIRST_DEPOSIT_NOTICE_BODY,
            )
            set_setting(
                "first_deposit_notice_enabled",
                "1" if request.form.get("first_deposit_notice_enabled") else "0",
            )
            audit(current_user()["id"], "update_first_deposit_notice", "")
            flash("First-deposit notice updated.", "success")
            return redirect(url_for("admin_settings"))

        for key in DEFAULT_SETTINGS:
            if key in request.form:
                set_setting(key, request.form.get(key, "").strip())
        flash("Foundation settings updated.", "success")
        return redirect(url_for("admin_settings"))

    return render_template("admin_settings.html", methods=get_withdrawal_methods(),
                           notice=get_first_deposit_notice())


# ---------------------------------------------------------------------------
# Admin: messages / broadcasts to members (shout-outs & motivational notes)
# ---------------------------------------------------------------------------

@app.route("/admin/messages")
@admin_required
def admin_messages():
    db = get_db()
    members = db.execute(
        "SELECT id, full_name, email, account_number FROM users "
        "WHERE role = 'applicant' ORDER BY full_name"
    ).fetchall()
    history = db.execute(
        "SELECT b.*, u.full_name AS sender_name, r.full_name AS recipient_name "
        "FROM broadcasts b "
        "LEFT JOIN users u ON u.id = b.created_by "
        "LEFT JOIN users r ON r.id = b.recipient_id "
        "ORDER BY b.id DESC LIMIT 100"
    ).fetchall()
    sent_count = db.execute("SELECT COUNT(*) AS c FROM broadcasts").fetchone()["c"]
    return render_template("admin_messages.html", members=members, history=history,
                           sent_count=sent_count)


@app.route("/admin/messages/send", methods=["POST"])
@admin_required
def admin_messages_send():
    db = get_db()
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    audience = request.form.get("audience", "all")
    recipient_raw = request.form.get("recipient_id", "").strip()

    if not body:
        flash("Please write a message before sending.", "danger")
        return redirect(url_for("admin_messages"))
    if not title:
        title = "Message from the Brightpath team"

    if audience == "user":
        if not recipient_raw.isdigit():
            flash("Please choose a member to message.", "danger")
            return redirect(url_for("admin_messages"))
        recipients = db.execute(
            "SELECT * FROM users WHERE id = ? AND role = 'applicant'", (int(recipient_raw),)
        ).fetchall()
        if not recipients:
            flash("That member could not be found.", "danger")
            return redirect(url_for("admin_messages"))
        recipient_id_val = int(recipient_raw)
    else:
        recipients = db.execute(
            "SELECT * FROM users WHERE role = 'applicant' ORDER BY id"
        ).fetchall()
        recipient_id_val = None

    if not recipients:
        flash("There are no members to message yet.", "warning")
        return redirect(url_for("admin_messages"))

    # Deliver the message as an in-app notification and an email to every recipient.
    for u in recipients:
        notify(u["id"], title, body, link=url_for("notifications"), category="message")
        send_notification(u["email"], title, body)

    db.execute(
        "INSERT INTO broadcasts (title, body, audience, recipient_id, recipient_count, "
        "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, body, "user" if recipient_id_val else "all", recipient_id_val,
         len(recipients), current_user()["id"], now_iso()),
    )
    db.commit()
    audit(current_user()["id"], "broadcast_message",
          f"{'all' if not recipient_id_val else 'user #' + str(recipient_id_val)} -> "
          f"{len(recipients)} recipients")
    if recipient_id_val:
        flash(f"Your message was delivered to {recipients[0]['full_name']}.", "success")
    else:
        flash(f"Your message was delivered to all {len(recipients)} members.", "success")
    return redirect(url_for("admin_messages"))


@app.route("/admin/export/<kind>.csv")
@admin_required
def admin_export(kind):
    db = get_db()
    if kind == "applications":
        rows = db.execute(
            "SELECT a.id, a.full_name, u.email, a.country, a.crisis_type, a.amount_requested, "
            "a.currency, a.status, a.awarded_amount, a.created_at FROM applications a "
            "JOIN users u ON u.id = a.user_id ORDER BY a.id DESC"
        ).fetchall()
        header = ["id", "full_name", "email", "country", "crisis_type", "amount_requested",
                  "currency", "status", "awarded_amount", "created_at"]
    elif kind == "transactions":
        rows = db.execute(
            "SELECT t.id, t.reference, u.full_name, u.account_number, t.type, t.amount, t.currency, "
            "t.description, t.sender_name, t.status, t.created_at FROM transactions t "
            "JOIN users u ON u.id = t.user_id ORDER BY t.id DESC"
        ).fetchall()
        header = ["id", "reference", "full_name", "account_number", "type", "amount", "currency",
                  "description", "sender_name", "status", "created_at"]
    elif kind == "users":
        rows = db.execute(
            "SELECT id, full_name, email, country, phone, account_number, routing_number, balance, "
            "currency, account_status, created_at FROM users WHERE role = 'applicant' ORDER BY id DESC"
        ).fetchall()
        header = ["id", "full_name", "email", "country", "phone", "account_number", "routing_number",
                  "balance", "currency", "account_status", "created_at"]
    else:
        abort(404)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for r in rows:
        writer.writerow([r[h] for h in header])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=brightpath_{kind}.csv"},
    )


@app.errorhandler(413)
def too_large(error):
    flash("Your upload was too large. Please keep total attachments under 25 MB.", "danger")
    return redirect(url_for("apply"))


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=getattr(error, "description", "Bad request.")), 400


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message="You don't have access to this page."), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


@app.errorhandler(500)
def server_error(error):
    return render_template("error.html", code=500, message="Something went wrong on our side."), 500


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def compute_stats(db):
    total_apps = db.execute("SELECT COUNT(*) AS c FROM applications").fetchone()["c"]
    approved = db.execute(
        "SELECT COUNT(*) AS c FROM applications WHERE status = 'approved'"
    ).fetchone()["c"]
    pending = db.execute(
        "SELECT COUNT(*) AS c FROM applications WHERE status IN ('submitted','under_review')"
    ).fetchone()["c"]
    declined = db.execute(
        "SELECT COUNT(*) AS c FROM applications WHERE status = 'declined'"
    ).fetchone()["c"]
    disbursed = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS s FROM transactions WHERE type = 'deposit'"
    ).fetchone()["s"]
    users = db.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'applicant'").fetchone()["c"]
    active_accounts = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'applicant' AND account_status = 'active'"
    ).fetchone()["c"]
    countries = db.execute(
        "SELECT COUNT(DISTINCT country) AS c FROM applications WHERE country IS NOT NULL AND country != ''"
    ).fetchone()["c"]
    open_threads = db.execute(
        "SELECT COUNT(*) AS c FROM support_threads WHERE status = 'open'"
    ).fetchone()["c"]
    pending_tx = db.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE status = 'pending'"
    ).fetchone()["c"]
    withdrawn = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS s FROM transactions "
        "WHERE type = 'withdrawal' AND status = 'completed'"
    ).fetchone()["s"]
    return {
        "total_apps": total_apps,
        "approved": approved,
        "pending": pending,
        "declined": declined,
        "disbursed_sum": disbursed,
        "users": users,
        "active_accounts": active_accounts,
        "countries": countries,
        "open_threads": open_threads,
        "pending_tx": pending_tx,
        "withdrawn_sum": withdrawn,
    }


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

@app.template_filter("money")
def money_filter(value):
    try:
        return "{:,.2f}".format(float(value))
    except (TypeError, ValueError):
        return "0.00"


@app.template_filter("money0")
def money0_filter(value):
    try:
        return "{:,.0f}".format(float(value))
    except (TypeError, ValueError):
        return "0"


@app.template_filter("datefmt")
def datefmt_filter(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y")
    except ValueError:
        return value


@app.template_filter("datetimefmt")
def datetimefmt_filter(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y · %H:%M")
    except ValueError:
        return value


@app.template_filter("filesize")
def filesize_filter(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.0f} TB"


@app.template_filter("statuslabel")
def statuslabel_filter(value):
    return {
        "submitted": "Submitted",
        "under_review": "Under Review",
        "approved": "Approved",
        "declined": "Declined",
    }.get(value, (value or "").title())


@app.template_filter("maskname")
def maskname_filter(value):
    """Mask a full name for public display, e.g. 'John Doe' -> 'J. D.'."""
    if not value:
        return "Anonymous"
    parts = [p for p in str(value).split() if p]
    return " ".join(f"{p[0].upper()}." for p in parts) or "Anonymous"


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
