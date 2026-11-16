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
