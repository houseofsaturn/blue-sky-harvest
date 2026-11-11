#!/usr/bin/env python3
"""
Connect gleaner to Dropbox for MODE=api (fatline, or any machine without the
Dropbox desktop app). Writes ~/.gleaner/dropbox.env with APPKEY, APPSECRET and
REFRESH. Nothing you type is shown on screen, and nothing is printed back.

    python3 dropbox_login.py           log in (once)
    python3 dropbox_login.py --check   test the saved login: lists Apps/cyby

Use the SAME Dropbox app as cyby's KOReader (the one whose folder is Apps/cyby).
In the Dropbox App Console, its Permissions tab needs files.metadata.read,
files.content.read and files.content.write ticked (press Submit) BEFORE you log in.
Only the Python standard library is used, so plain python3 works.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONF = Path(os.environ.get("GLEANER_CONFIG_DIR", Path.home() / ".gleaner"))
ENV = CONF / "dropbox.env"


def load() -> dict:
    out = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    try:
        with urllib.request.urlopen(url, body, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        sys.exit(f"❌ Dropbox said no ({e.code}): {detail}")


def check() -> None:
    d = load()
    if not all(d.get(k) for k in ("APPKEY", "APPSECRET", "REFRESH")):
        sys.exit(f"❌ No complete login in {ENV}. Run:  python3 dropbox_login.py")
    tok = post_form("https://api.dropbox.com/oauth2/token", {
        "grant_type": "refresh_token", "refresh_token": d["REFRESH"],
        "client_id": d["APPKEY"], "client_secret": d["APPSECRET"],
    })["access_token"]
    req = urllib.request.Request(
        "https://api.dropboxapi.com/2/files/list_folder",
        data=json.dumps({"path": ""}).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            entries = json.load(r)["entries"]
    except urllib.error.HTTPError as e:
        sys.exit(f"❌ Logged in, but couldn't list the folder ({e.code}). "
                 "Check the app's Permissions tab, then log in again.")
    folders = sorted(e["name"] for e in entries if e[".tag"] == "folder")
    print("✅ Dropbox works. gleaner can see these folders in Apps/cyby:")
    for f in folders:
        print("   ", f)
    if not folders:
        print("   (none: is this the same app cyby uses? Its folder should hold gleanings, readings…)")


def login() -> None:
    print("🌾 Connect gleaner to Dropbox (the app cyby uses, folder Apps/cyby)")
    print("   Paste each value and press Enter. Nothing appears as you paste. That's deliberate.\n")
    key = getpass.getpass("   App key: ").strip()
    secret = getpass.getpass("   App secret: ").strip()
    if not key or not secret:
        sys.exit("❌ Need both the app key and the app secret.")
    url = ("https://www.dropbox.com/oauth2/authorize?" + urllib.parse.urlencode({
        "client_id": key, "response_type": "code", "token_access_type": "offline"}))
    print("\n   Open this address in a browser (on the Mac is fine), sign in, press Allow,")
    print("   then copy the code Dropbox shows you:\n")
    print("   " + url + "\n")
    code = getpass.getpass("   Code from Dropbox: ").strip()
    if not code:
        sys.exit("❌ No code entered.")
    got = post_form("https://api.dropboxapi.com/oauth2/token", {
        "code": code, "grant_type": "authorization_code",
        "client_id": key, "client_secret": secret,
    })
    refresh = got.get("refresh_token")
    if not refresh:
        sys.exit("❌ Dropbox didn't hand back a refresh token. Try again from the start.")
    CONF.mkdir(parents=True, exist_ok=True)
    os.chmod(CONF, 0o700)
    old = os.umask(0o077)
    try:
        ENV.write_text(f"# Dropbox login for gleaner (MODE=api). Private: never commit.\n"
                       f"APPKEY={key}\nAPPSECRET={secret}\nREFRESH={refresh}\n")
    finally:
        os.umask(old)
    os.chmod(ENV, 0o600)
    print(f"\n   ✅ saved to {ENV}\n")
    check()


if __name__ == "__main__":
    check() if "--check" in sys.argv[1:] else login()
