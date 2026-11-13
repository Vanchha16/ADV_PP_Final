"""Optional relay for Bakong's Cambodia-only API.

Bakong's Open API only accepts requests from Cambodian IP addresses. If the shop
is hosted abroad (Render, PythonAnywhere, ...), run this tiny app on a VPS in
Cambodia and set on the shop:
    BAKONG_API_URL=https://<your-vps-host>/v1
    BAKONG_PROXY_KEY=<same value as PROXY_KEY below>

Run:  PROXY_KEY=... gunicorn -b 127.0.0.1:5001 proxy:app   (behind Nginx + TLS)
Calls go out via Python's http.client; Nginx proxy_pass straight to Bakong can
be blocked by TLS fingerprinting on Bakong's CDN.
"""
import http.client
import os

from flask import Flask, Response, request

app = Flask(__name__)
HOST = "api-bakong.nbc.gov.kh"
ALLOWED = {
    "check_transaction_by_md5", "check_transaction_by_hash",
    "check_transaction_by_short_hash", "check_transaction_by_md5_list",
    "check_transaction_by_hash_list", "check_bakong_account",
    "generate_deeplink_by_qr", "renew_token",
}
PROXY_KEY = os.environ["PROXY_KEY"]


@app.post("/v1/<endpoint>")
def proxy(endpoint):
    if endpoint not in ALLOWED:
        return {"error": "not allowed"}, 404
    if request.headers.get("X-Proxy-Key") != PROXY_KEY:
        return {"error": "forbidden"}, 403
    headers = {"Content-Type": "application/json"}
    if auth := request.headers.get("Authorization"):
        headers["Authorization"] = auth
    conn = http.client.HTTPSConnection(HOST, timeout=15)
    try:
        conn.request("POST", f"/v1/{endpoint}", body=request.get_data(), headers=headers)
        r = conn.getresponse()
        body = r.read()
    finally:
        conn.close()
    return Response(body, status=r.status, content_type="application/json")
