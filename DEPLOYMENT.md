# Deploying Bright Future Grant (GitHub + Cloudflare)

This guide takes you from this repository to a live, HTTPS-secured site on your
own domain using **Cloudflare**. It covers the domain you buy from **WhoGoHost**,
getting the code onto **GitHub**, and hosting the Flask app behind a
**Cloudflare Tunnel**.

---

> **Your setup at a glance**
> - **Domain:** `brightfuturegrant.com` (WhoGoHost, renews 30 Sep 2027)
> - **App:** `https://app.brightfuturegrant.com` → Flask app via Cloudflare Tunnel
> - **Landing page:** `https://brightfuturegrant.com` → static page on Cloudflare Pages
> - **Code:** <https://github.com/zhavihubb/brightpath-foundation>

---

## ⚡ Fast path (automated)

Two scripts do most of the work. You only supply a Cloudflare API token and a server.

**A. Create the Cloudflare zone, tunnel, DNS and Pages project (one command):**

```bash
CF_API_TOKEN=your-cloudflare-api-token python3 scripts/cloudflare_setup.py
```

It prints the **two nameservers** (set them at WhoGoHost), the **tunnel token**
(paste into `.env`), and the exact next commands. See the token's required
permissions at the top of the script.

**B. Bootstrap a fresh Ubuntu/Debian VPS (one command):**

```bash
CLOUDFLARE_TUNNEL_TOKEN=xxxx ADMIN_EMAIL=you@brightfuturegrant.com \
ADMIN_PASSWORD='S0me-Str0ng-Pass' bash scripts/deploy_server.sh
```

It installs Docker, clones the repo, writes a `.env` with a fresh `SECRET_KEY`,
and starts the app + tunnel. The manual steps below are the same thing, spelled
out — use them if you prefer to do it by hand.

---

## 0. How the pieces fit together

| Piece | What it does | Where it lives |
|-------|--------------|----------------|
| **Flask app** (`app.py`, `wsgi.py`) | The actual website + member area + admin dashboard | Runs in Docker on any always-on machine (VPS, home server, Cloud PC) |
| **SQLite database** (`charity.db`) + `uploads/` | All data and files | A persistent **volume** mounted at `/data` |
| **Cloudflare Tunnel** (`cloudflared`) | Securely publishes the app to your domain — outbound only, no open ports | Runs next to the app (docker-compose) |
| **Cloudflare DNS + proxy** | Domain, TLS certificates, DDoS protection, caching, WAF | Cloudflare's global network |
| **Cloudflare Pages** (optional) | Fast static landing page for the apex domain | `public/` folder in this repo |

> **Important:** Cloudflare *Pages* and *Workers* can only host **static** sites.
> Bright Future Grant is a dynamic Flask app with a database, so it must run on a server
> and be published through a **Cloudflare Tunnel**. That is exactly what this
> guide sets up. The optional Pages site (step 6) is only for a static landing
> page.

---

## 1. Push the code to GitHub

The code is already on GitHub:

> **Repository:** <https://github.com/zhavihubb/brightpath-foundation>

To push further changes:

```bash
git add .
git commit -m "your message"
git push            # origin/main is already configured
```

To clone it fresh onto your server (step 3):

```bash
git clone https://github.com/zhavihubb/brightpath-foundation.git
cd brightpath-foundation
```

> **Never commit secrets.** `.env`, `charity.db` and `uploads/` are already in
> `.gitignore`. Double-check with `git status` before pushing.

---

## 2. Point your WhoGoHost domain at Cloudflare

**Your domain:** `brightfuturegrant.com` (registered at WhoGoHost, renews 30 Sep 2027).

The plan for this domain:

| Hostname | Serves | Where |
|----------|--------|-------|
| `app.brightfuturegrant.com` | The full Flask application | Cloudflare **Tunnel** (step 4) |
| `brightfuturegrant.com` + `www` | Static marketing landing page | Cloudflare **Pages** (step 6) |

1. ~~Buy the domain~~ ✅ Already bought at WhoGoHost.
2. **Create a free Cloudflare account** at <https://dash.cloudflare.com>.
3. Click **Add a site**, enter `brightfuturegrant.com`, and choose the **Free** plan.
4. Cloudflare gives you **two nameservers**, e.g.:
   ```
   ada.ns.cloudflare.com
   rob.ns.cloudflare.com
   ```
5. In **WhoGoHost** → your domain → **Nameservers / DNS**, replace the existing
   nameservers with Cloudflare's two, then save.
6. Wait for propagation (usually 5–60 minutes; Cloudflare emails you when the
   site is **Active**).

After this, **all DNS for your domain is managed in Cloudflare**, not WhoGoHost.

---

## 3. Run the app on a server

You need one always-on machine with Docker installed. Any small VPS works
(e.g. a $5–6/month instance), as does a home server or mini-PC.

```bash
# On the server:
git clone https://github.com/<your-username>/brightpath.git
cd brightpath

# Create your environment file from the template
cp .env.example .env
nano .env          # fill in SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, etc.
```

Generate a strong `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 4. Create the Cloudflare Tunnel

A tunnel gives the app a secure public address **without opening any inbound
ports**.

1. In Cloudflare → **Zero Trust** → **Networks** → **Tunnels** →
   **Create a tunnel** → **Cloudflared**.
2. Name it `brightpath` and **copy the tunnel token** (a long string starting
   with `eyJ...`).
3. Paste it into `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
   ```
4. Still in the tunnel setup, add a **Public Hostname**:
   - **Subdomain:** `app`  (or `www`)
   - **Domain:** your domain
   - **Service Type:** `HTTP`
   - **URL:** `brightpath:8080`   ← the Docker service name + internal port
5. Save. Cloudflare automatically creates the DNS record.

### Start everything

```bash
docker compose up -d --build
docker compose logs -f brightpath    # watch it boot
```

Visit **https://app.brightfuturegrant.com** — you should see Bright Future Grant with a valid
Cloudflare TLS certificate.

### First login

The administrator is created on first run from your `.env`:

```
Email:    ADMIN_EMAIL
Password: ADMIN_PASSWORD
```

Log in, open **Admin → Settings**, and confirm your wallet addresses, the
first-deposit notice, and the sender details.

---

## 5. Environment variables

All configuration is via environment variables (see `.env.example`):

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Signs session cookies. **Must** be a long random string. |
| `PORT` | Internal port (default `8080`). |
| `BRIGHTPATH_DATA_DIR` | Where the DB + uploads live (default `/data` in Docker). |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Bootstrap admin, created only on first run. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | Optional email delivery. If unset, emails are logged to the database. |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token for the `cloudflared` container. |

### Persisting data

`docker-compose.yml` mounts a named volume `brightpath-data` at `/data`. The
SQLite database and uploads live there, so they survive `docker compose down`
and rebuilds. **Back this volume up regularly:**

```bash
docker run --rm -v brightpath-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/brightpath-backup-$(date +%F).tar.gz -C /data .
```

---

## 6. Optional: static landing page on Cloudflare Pages

This repo includes a ready-to-deploy static landing page in `public/`.

**Option A — Wrangler CLI:**

```bash
npx wrangler pages deploy public --project-name brightpath
```

**Option B — Cloudflare dashboard:**

1. **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Pick this repository.
3. **Build output directory:** `public`  (no build command needed).
4. Deploy, then add your **apex/www** domain under the project's **Custom
   domains**.

Now `https://brightfuturegrant.com` shows the landing page while
`https://app.brightfuturegrant.com` runs the full application.

---

## 7. Production checklist

- [ ] `SECRET_KEY` set to a long random value (not the default).
- [ ] `ADMIN_PASSWORD` changed from the default and stored safely.
- [ ] Domain nameservers point to Cloudflare and the site shows **Active**.
- [ ] Tunnel is **Healthy** in the Cloudflare dashboard.
- [ ] SSL/TLS mode set to **Full (strict)** in Cloudflare → SSL/TLS.
- [ ] **Always Use HTTPS** enabled (SSL/TLS → Edge Certificates).
- [ ] A backup routine for the `brightpath-data` volume.
- [ ] SMTP configured if you want real emails (otherwise they log to the DB).
- [ ] Rotate any credentials that were ever shared in plain text.

---

## 8. Alternative hosting options

- **Cloudflare Containers (beta):** deploy the same `Dockerfile` to Cloudflare's
  edge. Requires a Workers paid plan; SQLite persistence is limited, so a
  managed database is recommended for scale.
- **Any Docker host + Cloudflare proxy:** run the container on a VPS, put
  Cloudflare in front (orange-cloud the DNS record), and open ports 80/443.
  The Tunnel method above is simpler and more secure.
- **PaaS (Render, Railway, Fly.io):** the included `Procfile` and `Dockerfile`
  work out of the box. Mount a persistent disk at `/data`.

---

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `502` from Cloudflare | The app isn't running or the tunnel URL is wrong. Check `docker compose logs`. |
| Tunnel shows **Down** | Token is wrong/expired, or the container can't reach the internet. Re-copy the token. |
| Login redirects loop | `SECRET_KEY` changed between restarts. Set a fixed value in `.env`. |
| Data disappears after redeploy | The `/data` volume isn't mounted. Check `docker-compose.yml`. |
| Emails not arriving | SMTP env vars unset — check the in-app email log or configure SMTP. |
