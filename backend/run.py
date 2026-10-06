"""One command to run everything:  python run.py
Serves the API and the web app together on one port (default 8811). No separate frontend server exists.

Environment (all optional for local use):
  PORT                 default 8811
  COPILOT_HOST         default 127.0.0.1 (this computer only). Use 0.0.0.0 so a phone on the same Wi-Fi can reach it.
  COPILOT_ALLOWED_HOSTS  host names/IPs the server will answer to besides localhost, e.g. 192.168.1.20
  COPILOT_PUBLIC_URL   the address a phone should post SMS to (shown on the Connect phone page)
  COPILOT_OTP_PROVIDER console (default, code appears in this window) | twilio | webhook   (see app/auth.py)
  COPILOT_DEV_OTP=1    also show the sign-in code on the login screen (local testing only)
  COPILOT_DATA_DIR     where the database and key live (default backend/data)
"""
import os
import sys

import uvicorn

from app.database import migrate

LOOPBACK = {"127.0.0.1", "localhost", "::1"}

if __name__ == "__main__":
    host = os.environ.get("COPILOT_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8811"))
    provider = os.environ.get("COPILOT_OTP_PROVIDER", "console").lower()
    if host not in LOOPBACK:
        if provider == "console" and os.environ.get("COPILOT_DEV_OTP") == "1":
            print("\nRefusing to listen on a network address with COPILOT_DEV_OTP=1: it would show sign-in codes to anyone.\n"
                  "  Unset it, or keep the server on 127.0.0.1.\n")
            sys.exit(2)
        print("WARNING: serving plain HTTP on a network address. Use HTTPS (reverse proxy) before exposing this beyond your own network.")
        if provider == "console":
            print("NOTE: sign-in codes are printed in this window (COPILOT_OTP_PROVIDER=console). Set twilio or webhook to text them.")
    info = migrate()
    if info["added_columns"]:
        print(f"Database upgraded (added {', '.join(info['added_columns'])}). Backup: {info['backup']}")
    shown = '127.0.0.1' if host in LOOPBACK else host
    print(f"\n  Open http://{shown}:{port}   (sign in with your phone number; the code appears {'in this window' if provider == 'console' else 'by SMS'})\n")
    uvicorn.run("app.main:app", host=host, port=port, log_level="warning",
                proxy_headers=os.environ.get("COPILOT_DEMO") == "1", forwarded_allow_ips="*")  # behind Render, see each visitor's own IP
