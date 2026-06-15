"""
Upstox OAuth2 token exchange helper.

Reads your app credentials + the one-time authorization `code` from
  data/upstox_secrets.json   (you create this — it is gitignored)
exchanges them for an access_token, and saves it to
  data/.upstox_token.json    (gitignored)

data/upstox_secrets.json format:
{
  "api_key":      "<API Key from Upstox developer app>",
  "api_secret":   "<API Secret>",
  "redirect_uri": "<exact redirect URL registered in the app>",
  "code":         "<the ?code=... value from the browser redirect>"
}

Run:  py upstox_auth.py
"""
import json, ssl, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / "data" / "upstox_secrets.json"
TOKEN_OUT = ROOT / "data" / ".upstox_token.json"

TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def main():
    if not SECRETS.exists():
        print(f"ERROR: {SECRETS} not found. Create it first (see header of this file).")
        return
    s = json.loads(SECRETS.read_text())
    for k in ("api_key", "api_secret", "redirect_uri", "code"):
        if not s.get(k):
            print(f"ERROR: '{k}' missing/empty in {SECRETS.name}")
            return

    form = urllib.parse.urlencode({
        "code": s["code"],
        "client_id": s["api_key"],
        "client_secret": s["api_secret"],
        "redirect_uri": s["redirect_uri"],
        "grant_type": "authorization_code",
    }).encode()

    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        TOKEN_URL, data=form, method="POST",
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        r = urllib.request.urlopen(req, timeout=40, context=ctx)
        resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print("TOKEN EXCHANGE FAILED:", e.code)
        print(e.read().decode()[:500])
        print("\nMost common cause: the `code` was already used or expired "
              "(codes are single-use). Re-open the authorization URL, get a "
              "fresh code, update data/upstox_secrets.json, and re-run.")
        return

    tok = resp.get("access_token")
    if not tok:
        print("No access_token in response:", resp)
        return

    TOKEN_OUT.write_text(json.dumps(resp, indent=2))
    print("SUCCESS. access_token saved to", TOKEN_OUT.name)
    print("  token (masked):", tok[:6] + "..." + tok[-4:])
    if "user_name" in resp:
        print("  account:", resp.get("user_name"), "| email:", resp.get("email"))
    print("\nNOTE: a standard Upstox access token expires daily (~03:30 IST).")
    print("Re-run this flow each day, or set up an extended token if your plan allows.")


if __name__ == "__main__":
    main()
