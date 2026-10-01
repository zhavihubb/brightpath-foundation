#!/usr/bin/env python3
"""One-shot Cloudflare setup for Bright Future Grant (brightfuturegrant.com).

What this script does, entirely through the Cloudflare API:

  1. Verifies your API token and resolves the account ID.
  2. Adds the domain as a zone (or reuses it if it already exists) and prints
     the two nameservers you must set at WhoGoHost.
  3. Creates a Cloudflare Tunnel for the Flask app.
  4. Configures the tunnel's public hostname (app.<domain> -> http://brightpath:8080).
  5. Creates the DNS CNAME that points app.<domain> at the tunnel.
  6. Creates the Cloudflare Pages project for the static landing page.
  7. Prints the tunnel token (to paste into .env) and the exact next steps.

Required environment variables:
  CF_API_TOKEN     A Cloudflare API token with permissions:
                     - Account  -> Cloudflare Tunnel  -> Edit
                     - Account  -> Cloudflare Pages   -> Edit
                     - Account  -> Account Settings   -> Read
                     - Zone     -> Zone               -> Edit
                     - Zone     -> DNS                -> Edit
  CF_ACCOUNT_ID    (optional) your Cloudflare account ID; auto-detected if omitted.
  DOMAIN           (optional) defaults to brightfuturegrant.com
  APP_HOST         (optional) defaults to app.brightfuturegrant.com
  TUNNEL_NAME      (optional) defaults to brightpath

Usage:
  CF_API_TOKEN=xxxx python3 scripts/cloudflare_setup.py
"""
from __future__ import annotations

import os
import sys
import json
import requests

API = "https://api.cloudflare.com/client/v4"

DOMAIN = os.environ.get("DOMAIN", "brightfuturegrant.com")
APP_HOST = os.environ.get("APP_HOST", f"app.{DOMAIN}")
TUNNEL_NAME = os.environ.get("TUNNEL_NAME", "brightpath")
ORIGIN_SERVICE = os.environ.get("ORIGIN_SERVICE", "http://brightpath:8080")
PAGES_PROJECT = os.environ.get("PAGES_PROJECT", "brightpath")

TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()


def die(msg: str, code: int = 1):
    print(f"\n\u274c {msg}\n", file=sys.stderr)
    sys.exit(code)


def api(method: str, path: str, **kw):
    """Call the Cloudflare API and return the parsed JSON body."""
    url = f"{API}{path}"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    r = requests.request(method, url, headers=headers, timeout=30, **kw)
    try:
        data = r.json()
    except Exception:
        die(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
    if not data.get("success", False):
        errs = data.get("errors") or []
        # Surface the first error clearly.
        detail = "; ".join(e.get("message", str(e)) for e in errs) or r.text[:300]
        raise CloudflareError(method, path, r.status_code, detail, errs)
    return data.get("result")


class CloudflareError(Exception):
    def __init__(self, method, path, status, detail, errors):
        super().__init__(detail)
        self.method, self.path, self.status = method, path, status
        self.detail, self.errors = detail, errors


def step(n, text):
    print(f"\n\033[1m[{n}]\033[0m {text}")


def main():
    if not TOKEN:
        die("CF_API_TOKEN is not set. Create a token at "
            "https://dash.cloudflare.com/profile/api-tokens and re-run.")

    print("\033[1mBright Future Grant \u2014 Cloudflare setup\033[0m")
    print(f"  Domain      : {DOMAIN}")
    print(f"  App host    : {APP_HOST}")
    print(f"  Tunnel      : {TUNNEL_NAME}")
    print(f"  Origin      : {ORIGIN_SERVICE}")

    # -- 1. Verify token & resolve account ---------------------------------
    step(1, "Verifying API token\u2026")
    try:
        verify = api("GET", "/user/tokens/verify")
    except CloudflareError as e:
        die(f"Token verification failed: {e.detail}")
    print(f"    Token status: {verify.get('status')}")

    global ACCOUNT_ID
    if not ACCOUNT_ID:
        accounts = api("GET", "/accounts")
        if not accounts:
            die("No Cloudflare accounts found for this token.")
        ACCOUNT_ID = accounts[0]["id"]
        if len(accounts) > 1:
            print("    Multiple accounts found; using the first:")
            for a in accounts:
                print(f"      - {a['name']} ({a['id']})")
    print(f"    Account ID : {ACCOUNT_ID}")

    # -- 2. Add / reuse the zone -------------------------------------------
    step(2, f"Adding zone {DOMAIN}\u2026")
    zones = api("GET", f"/zones?name={DOMAIN}")
    if zones:
        zone = zones[0]
        print(f"    Zone already exists (status: {zone['status']})")
    else:
        zone = api("POST", "/zones", json={
            "name": DOMAIN,
            "account": {"id": ACCOUNT_ID},
            "jump_start": False,
        })
        print("    Zone created.")
    zone_id = zone["id"]
    nameservers = zone.get("name_servers", [])
    print(f"    Zone ID    : {zone_id}")
    print(f"    Status     : {zone['status']}")

    # -- 3. Create / reuse the tunnel --------------------------------------
    step(3, f"Creating tunnel '{TUNNEL_NAME}'\u2026")
    tunnels = api("GET", f"/accounts/{ACCOUNT_ID}/cfd_tunnel?name={TUNNEL_NAME}&is_deleted=false")
    if tunnels:
        tunnel = tunnels[0]
        print(f"    Tunnel already exists: {tunnel['id']}")
    else:
        tunnel = api("POST", f"/accounts/{ACCOUNT_ID}/cfd_tunnel", json={
            "name": TUNNEL_NAME,
            "config_src": "cloudflare",  # remotely-managed (config lives in Cloudflare)
        })
        print(f"    Tunnel created: {tunnel['id']}")
    tunnel_id = tunnel["id"]

    # -- 4. Configure tunnel ingress (remote config) -----------------------
    step(4, "Configuring tunnel ingress\u2026")
    api("PUT", f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{tunnel_id}/configurations", json={
        "config": {
            "ingress": [
                {"hostname": APP_HOST, "service": ORIGIN_SERVICE},
                {"service": "http_status:404"},
            ]
        }
    })
    print(f"    {APP_HOST} -> {ORIGIN_SERVICE}")

    # -- 5. DNS CNAME for the app subdomain --------------------------------
    step(5, f"Pointing DNS {APP_HOST} at the tunnel\u2026")
    target = f"{tunnel_id}.cfargotunnel.com"
    existing = api("GET", f"/zones/{zone_id}/dns_records?name={APP_HOST}")
    if existing:
        rec = existing[0]
        api("PUT", f"/zones/{zone_id}/dns_records/{rec['id']}", json={
            "type": "CNAME", "name": APP_HOST, "content": target, "proxied": True,
        })
        print("    DNS record updated.")
    else:
        api("POST", f"/zones/{zone_id}/dns_records", json={
            "type": "CNAME", "name": APP_HOST, "content": target, "proxied": True,
        })
        print("    DNS record created.")
    print(f"    {APP_HOST}  CNAME  {target}  (proxied)")

    # -- 6. Pages project for the landing page -----------------------------
    step(6, f"Creating Pages project '{PAGES_PROJECT}'\u2026")
    try:
        api("POST", f"/accounts/{ACCOUNT_ID}/pages/projects", json={
            "name": PAGES_PROJECT,
            "production_branch": "main",
        })
        print("    Pages project created.")
    except CloudflareError as e:
        if "already exists" in e.detail.lower():
            print("    Pages project already exists.")
        else:
            print(f"    \u26a0\ufe0f  Could not create Pages project: {e.detail}")

    # -- 7. Tunnel token ---------------------------------------------------
    step(7, "Fetching tunnel token\u2026")
    token = api("GET", f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{tunnel_id}/token")
    print("    Tunnel token retrieved.")

    # -- Summary -----------------------------------------------------------
    print("\n" + "=" * 68)
    print("\033[1mDONE \u2014 here is everything you need\033[0m")
    print("=" * 68)
    print("\n1) SET THESE NAMESERVERS AT WHOGOHOST (for " + DOMAIN + "):")
    for ns in nameservers:
        print(f"      {ns}")
    if not nameservers:
        print("      (open the Cloudflare dashboard to read them)")

    print("\n2) PUT THIS IN YOUR .env FILE ON THE SERVER:")
    print(f"      CLOUDFLARE_TUNNEL_TOKEN={token}")

    print("\n3) START THE STACK ON YOUR SERVER:")
    print("      git clone https://github.com/zhavihubb/brightpath-foundation.git")
    print("      cd brightpath-foundation")
    print("      cp .env.example .env      # paste the tunnel token above")
    print("      docker compose up -d --build")

    print("\n4) DEPLOY THE LANDING PAGE (optional):")
    print(f"      npx wrangler pages deploy public --project-name {PAGES_PROJECT}")

    print(f"\n5) Once DNS is active, open:  https://{APP_HOST}\n")

    # Save a machine-readable summary next to the script.
    out = os.path.join(os.path.dirname(__file__), "cloudflare_setup.out.json")
    with open(out, "w") as fh:
        json.dump({
            "account_id": ACCOUNT_ID,
            "zone_id": zone_id,
            "domain": DOMAIN,
            "nameservers": nameservers,
            "tunnel_id": tunnel_id,
            "app_host": APP_HOST,
            "origin_service": ORIGIN_SERVICE,
            "pages_project": PAGES_PROJECT,
        }, fh, indent=2)
    print(f"Summary written to {out}\n")


if __name__ == "__main__":
    main()
