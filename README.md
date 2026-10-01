# Brightpath Crisis Relief Foundation

A fully functional, global **crisis-relief charity** web application. Brightpath is a
**grant-giving** platform — it does **not** collect donations. People register, submit a
grant application describing their crisis (with optional supporting documents), and the
foundation's administrators review, approve, or decline applications. When an application
is approved, the member is issued a **dedicated account number and routing number**, and
the foundation can **push grant funds** directly into that account as a **deposit**. Every
movement on an account generates an **in-app notification**, an **email notification**, and
a **printable receipt**. Members and administrators can also talk to each other through a
**two-way support chat** with **image attachments in both directions**.

> **Anti-fraud principle:** Brightpath never charges applicants a fee to apply for or to
> receive a grant. The site states this prominently. There is no "free money for signing
> up" mechanic — grants are awarded only after review, to a funded number of recipients.

---

## What's new in this enhanced version (Phase 1)

This build adds a complete **member account + payout + support** layer on top of the
original application flow:

1. **Member accounts & routing numbers** — On approval (or manual activation by an admin)
   every member is automatically assigned a unique **10-digit account number** and a
   **9-digit routing number**. The account carries a **balance**, **currency**, and
   **status** (`pending` → `active`).
2. **Admin "push money" payouts** — Admins can push funds to **any** member account (by
   user id or account number). This creates a **deposit** transaction, updates the balance,
   and notifies the member in-app **and** by email with a **full description and a
   clickable receipt**.
3. **Official designated sender** — Every payout records the **official foundation account
   details** (name, account number, routing number, bank, SWIFT, address) as the sender.
   These details are **configurable** from the admin settings page.
4. **Receipts** — Every transaction has a printable, clickable receipt at
   `/receipt/<tx_id>` with a stable receipt ID (`BP-RCPT-000001`).
5. **Notifications everywhere** — Members are notified of **every activity on their
   account** (signup, application status change, deposit received, admin support reply).
   Admins are notified of **every new signup, every new support message, and every contact
   message**. All notifications appear in the **notification center** with an **unread
   badge** in the navigation bar, and are also logged/emailed.
6. **Two-way support chat with images** — Members open support threads and chat with the
   foundation; admins see **every** thread in the admin inbox and can reply to anyone.
   **Images and files can be attached in both directions** (member → support and
   admin → member). Attachments are access-controlled (owner or admin only).
7. **Secure, persistent backend** — All member details, balances, transactions,
   notifications, support threads, and audit events are stored in a **persistent SQLite
   database** (`charity.db`). Passwords are hashed (PBKDF2 via Werkzeug), sessions are
   server-side, forms are **CSRF-protected**, public forms are **rate-limited**, and
   uploads are served only to the owner or an admin.

---

## What's new in Phase 2 (global currency, withdrawals & approvals)

Phase 2 makes Brightpath a genuinely **global** foundation with a complete, auditable
**money-in / money-out** workflow that an administrator fully controls:

1. **Country-based currency** — Every member picks their **country** at signup (and can
   change it in *My account*). The dashboard currency is derived automatically from that
   country using an ISO-4217 map covering **~180 countries** — `$` for the United States,
   `£` for the United Kingdom, `€` for the eurozone, `₦` for Nigeria, `₹` for India,
   `KSh` for Kenya, and so on. The currency code **and** its name are shown live on the
   register and account pages, and every amount across the dashboard, transactions,
   receipts and notifications is formatted with the member's own currency.
2. **Withdrawals through every method — especially cryptocurrency** — Members can request
   a withdrawal through **Bitcoin (BTC)**, **Ethereum (ETH)**, **USDT (TRC20)**,
   **USDT (ERC20)**, **bank transfer**, and **PayPal**. Each method shows the foundation's
   wallet/account details with a one-click **Copy** button on the member's dashboard and on
   the dedicated `/withdraw` page, plus the correct **network** (e.g. *Tron (TRC20)*) so
   funds are never sent on the wrong chain. Requested funds are **held** from the balance
   while pending and **returned automatically** if the request is declined.
3. **Admin-editable wallets** — Admins manage the visible withdrawal methods from
   **Admin → Settings**: add a new method, edit its name/type/network/address/instructions,
   toggle it **on/off**, or delete it. Whatever is enabled appears instantly on every
   member's dashboard and withdrawal page.
4. **Admin approves every deposit and withdrawal** — A dedicated **Approvals queue**
   (`/admin/approvals`) lists every **pending** transaction with the member, method,
   destination and amount. Admins **Approve** to release it (deposits credit the balance;
   withdrawals were already held) or **Decline** with a reason. The navigation bar shows a
   live **pending-approvals badge**.
5. **Reversible transactions with reasons & next steps** — Any **completed** transaction
   can be **reversed** from the admin dashboard. The admin must supply a **reason** and
   **what the member should do next**; balances are corrected automatically (a reversed
   deposit is deducted, a reversed withdrawal is refunded) and the member is notified
   in-app and by email, with the reason and next steps shown on the transaction, the
   receipt, and in their notification centre.

The transaction lifecycle is now: **`pending` → `completed` / `rejected`**, and
**`completed` → `reversed`** — every state change is recorded with who reviewed it and when.

---

## Tech stack

- **Backend:** Python 3 + Flask (sessions, secure password hashing via Werkzeug)
- **Database:** SQLite (auto-created and seeded on first run) — persistent across restarts
- **Frontend:** Server-rendered Jinja2 templates + custom CSS design system + vanilla JS
- **File uploads:** stored on disk under `uploads/` (application evidence) and
  `uploads/support/` (chat attachments), served only to the owner or an admin
- **Email notifications:** SMTP-optional — sends via SMTP when configured, otherwise logs
- **No external services required** to run.

## Project structure

```
app.py                  # Flask app: routes, auth, DB, accounts, payouts, notifications, support, stats
charity.db              # SQLite database (created on first run) — persistent member data
seed_demo.py            # Optional: seed demo members, applications, deposits & support threads
e2e_test.py             # End-to-end test (register -> approve -> deposit -> receipt -> support)
uploads/                # Uploaded application evidence (created on first run)
uploads/support/        # Support-chat attachments (created on first run)
requirements.txt        # Python dependencies
templates/              # Jinja2 templates (all pages)
static/css/style.css    # Design system
static/js/main.js       # Nav, counters, copy-to-clipboard, chat scroll, reveals
```

## Running locally

```bash
pip install -r requirements.txt
PORT=8080 python3 app.py
# open http://127.0.0.1:8080
```

The database is created and seeded automatically on first run (admin account + default
settings). To load a richer demo dataset:

```bash
python3 seed_demo.py     # adds demo members, applications, deposits, withdrawals and support threads
```

## Live demo

- **Run it locally:** `PORT=8080 python3 app.py` → http://127.0.0.1:8080
  (or `gunicorn -b 0.0.0.0:8080 wsgi:app` for a production-style server).
  To share it publicly, see **Deployment & hosting** below.
- **Admin login:** `admin@brightfuturegrant.com` / `Admin@12345`
- **Demo member:** `amara@example.com` / `Password123` (and `luis@example.com`,
  `priya@example.com`, `daniel@example.com` — all `Password123`)
- **Applicant:** register at `/register`, then apply at `/apply`

## Accounts & demo credentials

- **Administrator (seeded):** `admin@brightfuturegrant.com` / `Admin@12345`
  → lands on the **admin review dashboard** (`/admin`)
- **Applicants / members:** register at `/register` (free), then apply at `/apply`.
- **Demo members (if you ran `seed_demo.py`):** `amara@example.com`, `luis@example.com`,
  `priya@example.com`, `daniel@example.com` — all with password `Password123`. Each member's
  country (Nigeria, Mexico, India, Kenya) drives their dashboard currency (NGN, MXN, INR,
  KES). The seed also creates sample **deposits** and **withdrawals** in every status
  (`pending`, `completed`, `rejected`) so the approvals queue and reversal flow have data.

## Pages / routes

### Public site

| Route | Description |
|---|---|
| `/` | Home — hero, live impact stats, mission, programs, how it works, CTA |
| `/about` | Mission, values, governance |
| `/programs` | The four grant programs + grant ranges |
| `/how-to-apply` | Step-by-step application guide |
| `/eligibility` | Who can / cannot apply, review process |
| `/faq` | Frequently asked questions |
| `/transparency` | Public grants feed (masked names) + impact totals |
| `/contact` | Contact form + anti-fraud reporting (sends an acknowledgement email) |
| `/register`, `/login`, `/logout` | Account management (welcome email on register) |

### Member area (login required)

| Route | Description |
|---|---|
| `/dashboard` | Member dashboard — account summary, applications, recent activity, notifications |
| `/account` | Account page — balance, account/routing numbers (copy buttons), profile & password |
| `/account/settings` | POST — update profile / change password |
| `/apply` | Submit a new grant application (multipart: text fields + evidence upload) |
| `/application/<id>` | Application detail + status + attached evidence |
| `/uploads/<stored_name>` | Secure evidence download — **owner or admin only** |
| `/transactions` | Full transaction history with receipt links |
| `/withdraw` | Withdrawal page — copy wallets/accounts, request a withdrawal, see history |
| `/receipt/<tx_id>` | Printable, clickable receipt for a deposit/transaction |
| `/notifications` | Notification center (all account activity) |
| `/notifications/read` | POST — mark all notifications as read |
| `/support` | Support hub — start a new chat, list existing threads |
| `/support/new` | POST — open a new support thread (with optional attachment) |
| `/support/<thread_id>` | Two-way chat thread (user or admin view) with attachments |
| `/support/attachment/<stored_name>` | Secure chat attachment — **owner or admin only** |

### Admin area (admin login required)

| Route | Description |
|---|---|
| `/admin` | Admin dashboard — stats, applications (approve/decline), contacts, evidence, email log, CSV exports |
| `/admin/application/<id>` | POST — set decision / award / notes (emails + notifies the applicant) |
| `/admin/users` | Members & accounts — account/routing/balance/status, manual activation |
| `/admin/users/<id>/activate` | POST — assign account numbers & activate a member |
| `/admin/push-money` | POST — push grant funds to any member account (creates a deposit) |
| `/admin/transactions` | All transactions + members list + push-money form + approve/decline/reverse actions |
| `/admin/approvals` | Approvals queue — every **pending** deposit & withdrawal, approve or decline with a reason |
| `/admin/transactions/<id>/approve` | POST — approve a pending deposit (credits balance) or withdrawal |
| `/admin/transactions/<id>/reject` | POST — decline a pending transaction with a **reason** + **next steps** (refunds held funds) |
| `/admin/transactions/<id>/reverse` | POST — reverse a completed transaction with a **reason** + **next steps** |
| `/admin/support` | Support inbox — every member thread |
| `/admin/support/<thread_id>` | Reply to a member thread (with attachments) |
| `/admin/settings` | Official foundation sender account **and** the editable withdrawal methods / wallets |
| `/admin/export/<kind>.csv` | CSV export — `applications`, `transactions`, or `users` |

## Data model

- **users** — id, full_name, email (unique), password_hash, phone, address, country, role,
  account_number (unique), routing_number, balance, currency, account_status, is_verified,
  created_at
- **applications** — user_id, full_name, country, crisis_type, amount_requested, currency,
  household_size, situation, status, awarded_amount, admin_notes, timestamps
- **application_files** — application_id, original_name, stored_name, size, uploaded_at
- **transactions** — user_id, reference, type (`deposit`/`withdrawal`), amount, currency,
  balance_after, description, **method, destination, network**, **reason, instructions**,
  **reviewed_by, reviewed_at**, sender_name, sender_account, sender_routing, sender_bank,
  sender_swift, sender_address, status, created_at
- **notifications** — user_id, category, title, body, link, is_read, created_at
- **support_threads** — user_id, subject, status, created_at, updated_at
- **support_messages** — thread_id, sender_id, sender_role, body, attachment fields, created_at
- **contacts** — name, email, subject, message, created_at
- **email_log** — to_email, subject, body, status, created_at
- **settings** — key/value store for the official sender details, foundation info, and the
  `withdrawal_methods` JSON list (the editable wallets)
- **audit_log** — actor_id, action, detail, created_at

Application statuses: `submitted → under_review → approved | declined`.
Account statuses: `pending → active`.
Transaction statuses: `pending → completed | rejected`, and `completed → reversed`.

## Accounts, deposits & receipts

- When an application is **approved**, `assign_account()` issues a unique **account number**
  (10 digits) and **routing number** (9 digits) and sets the account to **active**.
- An admin can also **manually activate** any member from `/admin/users`.
- The admin **push-money** form (`/admin/transactions` or `/admin/push-money`) accepts a
  member (by id or account number), an amount, and a description. It:
  1. creates a **deposit** transaction with `sender_*` fields filled from the **official
     foundation settings**,
  2. updates the member's **balance**,
  3. sends the member an **in-app notification** and an **email** with a full description
     and a **clickable receipt link**.
- Every transaction is viewable at `/transactions` and printable at `/receipt/<tx_id>`.

## Withdrawals, approvals & reversals

**Member side — `/withdraw`**

- The member sees every **enabled** withdrawal method as a card with the foundation's
  wallet/account details, the **network** (e.g. *Tron (TRC20)*), a short instruction, and a
  **Copy** button. The same cards also appear on the member dashboard.
- The member submits a request (method, amount ≤ balance, their own destination, optional
  note). This creates a **`withdrawal`** transaction with status **`pending`** and
  **holds** the amount from the balance (so it can't be double-spent).
- The member is notified immediately and every admin is alerted.

**Admin side — `/admin/approvals` and `/admin/transactions`**

- **Approve** a pending deposit → balance is credited and the member is notified.
- **Approve** a pending withdrawal → status becomes `completed` (funds were already held).
- **Decline** any pending transaction → status becomes `rejected`, held withdrawal funds are
  **refunded**, and the admin's **reason** + **what to do next** are stored and sent to the
  member.
- **Reverse** any completed transaction → status becomes `reversed`; a reversed deposit is
  **deducted** from the balance and a reversed withdrawal is **refunded**. A **reason** and
  **next steps** are required and shown to the member.

Every review records **who** did it and **when** (`reviewed_by`, `reviewed_at`) and writes an
audit-log entry. Members see the reason and next steps on the transaction, on the receipt,
and in their notification centre.

## Currency

`currency_for_country(country)` maps a member's country to an ISO-4217 code using the
`COUNTRY_CURRENCY` table (~180 entries). `format_money(amount, code)` (exposed to templates as
`fmt_money`) renders amounts with the right symbol/code and thousands separators. The member's
currency is stored on their account and used everywhere they see money.

## Notifications (in-app + email)

`notify()` writes an in-app notification; `notify_and_email()` also logs/emails a message.
`notify_admins()` fans a notification out to every administrator.

- **Members are notified on:** registration (welcome), application submitted, application
  decision (approve/decline), **deposit received**, and **admin support reply**.
- **Admins are notified on:** every **new signup**, every **new support message**, and every
  **contact message**.
- The navigation bar shows an **unread badge**; `/notifications` lists everything and
  `/notifications/read` marks all as read.

## Support chat (two-way, with images)

- Members start a thread at `/support` (subject + message + optional attachment) and chat at
  `/support/<thread_id>`.
- Admins see every thread at `/admin/support` and reply at `/admin/support/<thread_id>`.
- **Images and files are supported in both directions.** Accepted types:
  `pdf, png, jpg, jpeg, gif, webp, doc, docx, txt`. Attachments are stored with random UUID
  names and streamed through an access-controlled route (owner or admin only).

## Security

- **Password hashing:** Werkzeug PBKDF2.
- **CSRF protection:** a per-session token is embedded in every form and validated globally
  in a `before_request` hook.
- **Rate limiting:** in-memory limiter on public/abuse-prone endpoints.
- **Upload access control:** evidence and chat attachments are only downloadable by the
  owner or an administrator.
- **Size limits:** total request size capped at **25 MB** (`MAX_CONTENT_LENGTH`); oversized
  requests get a friendly error page.
- **Audit log:** key administrative and account actions are recorded in `audit_log`.

## Email notifications

`send_notification()` records every message in the `email_log` table. If SMTP environment
variables are set, it also delivers the message; otherwise it is logged (status
`logged (no SMTP configured)`), so the whole notification flow is testable without a mail
server.

Configure SMTP with:

```bash
export SMTP_HOST=smtp.example.com
export SMTP_PORT=587
export SMTP_USER=you@example.com
export SMTP_PASS=your-app-password
export SMTP_FROM="Brightpath <no-reply@brightfuturegrant.com>"
```

## Testing

An end-to-end test exercises the full lifecycle (**50 checks**):

```bash
python3 e2e_test.py
```

It registers a fresh member → submits an application → admin approves it → verifies the
account/routing numbers were issued → pushes a deposit → checks the balance, receipt,
transactions and notifications → opens a support thread with an image → admin replies →
verifies admin pages, CSV exports, access control, CSRF and the public pages. **Phase 2
adds:** currency derived from country, the register/account country dropdown, the dashboard
wallets + copy buttons, the withdraw page, submitting a withdrawal (balance held), the admin
approvals queue, approving a withdrawal, reversing it with a reason + next steps, the member
seeing the reason and refunded funds, and an admin editing the wallets so members see the
updated address.

## Notes for production

- Set a strong `SECRET_KEY` environment variable.
- Replace the Flask dev server with a production WSGI server (e.g. gunicorn + nginx).
- Configure SMTP (above) for real email delivery.
- Store uploads on durable object storage (S3) rather than local disk for multi-instance
  deployments, and add antivirus scanning of uploaded files.
- Use a production database (PostgreSQL) for higher traffic; the SQLite layer in `app.py`
  is the only thing to swap.
- Register the organization as a charity in your jurisdiction and comply with local
  data-protection law.

## Deployment & hosting (Cloudflare)

This app is a **dynamic Flask application**, so it runs on a server (a VPS, or any host
that can run Docker) and is published to the internet through a **Cloudflare Tunnel**.
Cloudflare Pages/Workers can only serve *static* files, so they host the optional
marketing landing page in `public/`, not the app itself.

The full, step-by-step guide lives in **[`DEPLOYMENT.md`](DEPLOYMENT.md)**. The short
version:

### 1. Point the domain (WhoGoHost) at Cloudflare
Domain: **`brightfuturegrant.com`** (already registered at WhoGoHost).
1. Create a free [Cloudflare](https://dash.cloudflare.com) account → **Add a site** →
   enter `brightfuturegrant.com` → choose the **Free** plan.
2. Cloudflare shows **two nameservers** (e.g. `ada.ns.cloudflare.com`). In the WhoGoHost
   dashboard, set the domain's **nameservers** to those two values and save.
3. Wait for Cloudflare to report the zone as **Active** (usually minutes to a few hours).

Planned hostnames: `app.brightfuturegrant.com` → the Flask app (Tunnel);
`brightfuturegrant.com` + `www` → the static landing page (Pages).

### 2. Run the app with Docker (on any VPS)
```bash
cp .env.example .env         # then edit: SECRET_KEY, ADMIN_EMAIL/PASSWORD, tunnel token
docker compose up -d --build # starts the app + the cloudflared tunnel
```
Data (SQLite DB + uploads) is stored in the `brightpath-data` volume, so it survives
redeploys. Without Docker, run it directly:
```bash
pip install -r requirements.txt
export SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
gunicorn --workers 3 --threads 4 --timeout 120 --bind 0.0.0.0:8080 wsgi:app
```

### 3. Publish it through a Cloudflare Tunnel
In the Cloudflare dashboard → **Zero Trust → Networks → Tunnels → Create a tunnel**
(choose **Cloudflared**), copy the **tunnel token** into `CLOUDFLARE_TUNNEL_TOKEN` in
`.env`, and add a **Public Hostname** such as `app.brightfuturegrant.com` → service
`http://brightpath:8080`. Cloudflare then serves the app over HTTPS with no open
inbound ports.

### 4. Optional: static landing page on Cloudflare Pages
```bash
npx wrangler pages deploy public --project-name brightpath
```
`wrangler.toml` points at the `public/` folder. Use this for the marketing page and
point the app subdomain at the Tunnel.

### Configuration reference
All secrets and paths are environment-driven (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Signs session cookies — set a long random value in production. |
| `PORT` | Port the server binds to (default `8080`). |
| `BRIGHTPATH_DATA_DIR` | Directory holding `charity.db` + `uploads/` (mount a volume). |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Bootstrap admin, seeded only when the DB is first created. |
| `SMTP_*` | Optional email delivery; if blank, emails are logged to the DB. |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token used by the bundled `cloudflared` service. |

> **Security:** never commit `.env` (it is git-ignored). Rotate the admin password and
> `SECRET_KEY` before going live, and keep the SQLite DB and `uploads/` on a persistent
> volume.
