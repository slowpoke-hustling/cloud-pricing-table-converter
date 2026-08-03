import json
import os
import time
import hashlib
import urllib.request
import urllib.parse

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ALLOWED_DOMAIN   = os.environ.get("ALLOWED_DOMAIN", "")

# In-memory token cache: token_hash -> (email, expires_at_unix)
# Avoids calling Google tokeninfo on every request for the same token.
_token_cache = {}


def handler(event, context):
    try:
        path   = event.get("path", "")
        method = event.get("httpMethod", "GET")
        if method == "OPTIONS":
            return api_response(200, {})
        auth_result = verify_request(event)
        if auth_result["error"]:
            return api_response(403, {"error": auth_result["error"]})
        email = auth_result["email"]
        if path == "/auth/check" and method == "GET":
            return api_response(200, {"email": email, "allowed": True})
        return api_response(404, {"error": "Not found"})
    except Exception as e:
        print("Auth handler error: " + str(e))
        return api_response(500, {"error": "Internal server error"})


def verify_request(event):
    headers     = event.get("headers") or {}
    auth_header = headers.get("Authorization") or headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"email": None, "error": "Missing Authorization header"}
    id_token = auth_header[7:]
    email = verify_google_id_token(id_token)
    if not email:
        return {"email": None, "error": "Invalid or expired ID token"}
    return {"email": email, "error": None}


def verify_google_id_token(id_token):
    """Verify Google ID token via tokeninfo, with in-memory cache."""
    token_hash = hashlib.sha256(id_token.encode()).hexdigest()

    # Cache hit
    cached = _token_cache.get(token_hash)
    if cached:
        email, expires_at = cached
        if time.time() < expires_at:
            return email
        del _token_cache[token_hash]

    # Verify with Google
    url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(id_token)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            info = json.loads(resp.read())
            if info.get("aud") != GOOGLE_CLIENT_ID:
                print("Token audience mismatch: " + str(info.get("aud")))
                return None
            email = info.get("email", "").lower()
            if not email.endswith("@" + ALLOWED_DOMAIN):
                return None
            # Cache until token expiry minus 30s safety margin
            exp = int(info.get("exp", 0))
            if exp:
                _token_cache[token_hash] = (email, exp - 30)
            return email
    except Exception as e:
        print("Token verification error: " + str(e))
        return None


def api_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }
