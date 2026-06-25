"""Strava OAuth token management for the owner (Phase-0 spike — your own data only).

Credentials come from env vars (STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET) — same pattern as
ANTHROPIC_API_KEY; this code never sees them in source. The one-time `activity:read_all` consent
is done in the browser; after that we persist the refresh token and silently refresh the 6-hour
access token as needed. stdlib only (urllib) — no new dependencies.

NOTE: the multi-user OAuth flow (per-user tokens, hosted callback, webhooks) comes later. This is
the owner-token shortcut to get real streams flowing for the validation spike.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

TOKEN_PATH = os.path.join(os.path.dirname(__file__), ".strava_tokens.json")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "strava_config.txt")
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
REDIRECT_URI = "http://localhost/exchange_token"      # any localhost URI; we just read the code back
SCOPE = "activity:read_all,profile:read_all"   # profile:read_all → read the athlete's current FTP


def _read_config() -> dict:
    """Parse strava_config.txt (KEY=VALUE per line). The user pastes their Client ID + Secret
    here in a text editor — no terminal needed. This file is a credential: don't commit it."""
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def _creds():
    cfg = _read_config()                                  # config file first, env var fallback
    cid = cfg.get("STRAVA_CLIENT_ID") or os.environ.get("STRAVA_CLIENT_ID")
    secret = cfg.get("STRAVA_CLIENT_SECRET") or os.environ.get("STRAVA_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError(f"Paste your Client ID and Secret into {CONFIG_PATH} "
                           "(open it in Notepad, fill the two lines, save).")
    return cid, secret


def authorize_url() -> str:
    """The one-time consent link. Click it, approve, then copy the `code=...` value out of the
    (failed-to-load) localhost redirect URL and pass it to exchange_code()."""
    cid, _ = _creds()
    q = urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "approval_prompt": "force", "scope": SCOPE,
    })
    return f"{AUTH_URL}?{q}"


def _post_token(payload: dict) -> dict:
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _save(tok: dict):
    with open(TOKEN_PATH, "w") as f:
        json.dump(tok, f)


def _load() -> dict | None:
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH) as f:
        return json.load(f)


def exchange_code(code: str) -> dict:
    """One-time: trade the browser authorization code for access + refresh tokens, and persist."""
    cid, secret = _creds()
    tok = _post_token({"client_id": cid, "client_secret": secret, "code": code,
                       "grant_type": "authorization_code"})
    if "access_token" not in tok:
        raise RuntimeError(f"Strava token exchange failed: {tok}")
    _save(tok)
    return tok


def get_access_token() -> str:
    """A valid access token, refreshing automatically when the 6-hour one has expired."""
    tok = _load()
    if not tok:
        raise RuntimeError("No Strava tokens yet. Run this module to authorize:\n"
                           "  python -m sources.strava_auth")
    if tok.get("expires_at", 0) - 60 > time.time():
        return tok["access_token"]
    cid, secret = _creds()                                # expired → refresh
    new = _post_token({"client_id": cid, "client_secret": secret,
                       "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    if "access_token" not in new:
        raise RuntimeError(f"Strava token refresh failed: {new}")
    _save(new)
    return new["access_token"]


if __name__ == "__main__":                                # interactive one-time authorize
    import sys
    if len(sys.argv) > 1:                                 # `python -m sources.strava_auth <code>`
        t = exchange_code(sys.argv[1])
        print("Authorized. Tokens saved. Scope:", t.get("scope", "?"))
    else:
        print("1) Open this URL, approve, then copy the `code=` value from the redirected URL:\n")
        print("   " + authorize_url())
        print("\n2) Run:  python -m sources.strava_auth <code>")
