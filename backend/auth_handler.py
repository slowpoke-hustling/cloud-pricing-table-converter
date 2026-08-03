import json, os, urllib.request, urllib.parse
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "company-domain.com")
def handler(event, context):
    try:
        path = event.get("path", "")
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
        print(str(e))
        return api_response(500, {"error": "Internal server error"})
def verify_request(event):
    headers = event.get("headers") or {}
    auth_header = headers.get("Authorization") or headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"email": None, "error": "Missing Authorization header"}
    id_token = auth_header[7:]
    token_info = verify_google_id_token(id_token)
    if not token_info:
        return {"email": None, "error": "Invalid or expired ID token"}
    email = token_info.get("email", "").lower()
    if not email:
        return {"email": None, "error": "No email in token"}
    if not email.endswith("@" + ALLOWED_DOMAIN):
        return {"email": None, "error": "Access restricted to @" + ALLOWED_DOMAIN}
    return {"email": email, "error": None}
def verify_google_id_token(id_token):
    url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(id_token)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            info = json.loads(resp.read())
            if info.get("aud") != GOOGLE_CLIENT_ID:
                return None
            return info
    except Exception as e:
        print(str(e))
        return None
def api_response(status_code, body):
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type,Authorization", "Access-Control-Allow-Methods": "GET,POST,OPTIONS"}, "body": json.dumps(body)}
