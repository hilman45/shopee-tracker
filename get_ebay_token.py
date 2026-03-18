"""
One-time helper to get a valid eBay OAuth refresh token.

Uses a local HTTP server on port 8080 to automatically capture the
authorization code — no manual URL copying needed.

Before running:
  1. Go to https://developer.ebay.com/my/auth?env=production
  2. Click "Add eBay Redirect URL"
  3. Set the redirect URL to:  http://localhost:8080
  4. Note the new RuName that gets created and set RUNAME below.
  5. Run:  python get_ebay_token.py
"""

import base64
import os
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
RUNAME = os.getenv("EBAY_RUNAME", "Hilman_Rushdi-HilmanRu-Shopee-bvjuencpl")
SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory"
BASE_URL = "https://api.ebay.com"
REDIRECT_URI = "http://localhost:8080"

captured_code = {"value": None}
server_done = threading.Event()


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = params.get("code", [None])[0]
        if code:
            captured_code["value"] = code
            body = b"<h2>Authorization captured! You can close this tab.</h2>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code found.")
        server_done.set()

    def log_message(self, format, *args):
        pass  # suppress server log noise


def exchange_code(auth_code: str) -> dict:
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()
    resp = requests.post(
        f"{BASE_URL}/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    auth_url = (
        "https://auth.ebay.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={RUNAME}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(SCOPE)}"
    )

    print("\nStarting local callback server on http://localhost:8080 ...")
    server = HTTPServer(("localhost", 8080), CallbackHandler)
    t = threading.Thread(target=server.handle_request)
    t.start()

    print("Opening browser for eBay sign-in...")
    webbrowser.open(auth_url)
    print("(If the browser didn't open, visit this URL manually:)")
    print(auth_url)

    print("\nWaiting for eBay to redirect back...")
    server_done.wait(timeout=120)

    code = captured_code["value"]
    if not code:
        print("\nERROR: No authorization code received within 2 minutes.")
        raise SystemExit(1)

    print(f"\nCode captured. Exchanging for tokens...")
    try:
        data = exchange_code(code)
    except requests.HTTPError as e:
        print(f"\nERROR exchanging code: {e.response.status_code} {e.response.text}")
        raise SystemExit(1)

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print("\nERROR: No refresh_token in response:", data)
        raise SystemExit(1)

    print("\n" + "=" * 60)
    print("SUCCESS! Copy this into EBAY_REFRESH_TOKEN in your .env:")
    print("=" * 60)
    print(refresh_token)
    print("=" * 60)
