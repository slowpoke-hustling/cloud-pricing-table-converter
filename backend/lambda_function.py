"""
Pricing Table Generator — Lambda Backend
Processes one group at a time via Claude Sonnet 4.6.
/api/generate  → saves JSON, returns job_id + group list immediately
/api/process   → called per-group, runs Claude for that group, saves partial result
/api/status    → returns all completed group rows + assembles final HTML when done
"""
import json
import boto3
import os
import re
import uuid
import hashlib
import traceback
import base64
import io
import time
import urllib.request
import urllib.parse
import openpyxl
from collections import OrderedDict
from datetime import datetime

REGION = "us-east-1"
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
S3_BUCKET = os.environ.get("S3_BUCKET", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ALLOWED_DOMAIN   = os.environ.get("ALLOWED_DOMAIN", "company-domain.com")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)


# ── Auth helpers ──────────────────────────────────────────────────────────────

# In-memory token cache: token_hash → (email, expires_at_unix)
# Avoids calling Google's tokeninfo on every request for the same token.
# Lambda instance lifetime is typically minutes to hours, so tokens expire
# naturally (Google ID tokens are valid for 1 hour).
_token_cache: dict = {}

def verify_id_token(id_token):
    """Verify Google ID token via tokeninfo. Returns email or None.
    Result is cached in Lambda memory by token hash for the token's lifetime."""
    token_hash = hashlib.sha256(id_token.encode()).hexdigest()

    # Check cache first
    cached = _token_cache.get(token_hash)
    if cached:
        email, expires_at = cached
        if time.time() < expires_at:
            return email
        else:
            del _token_cache[token_hash]

    # Verify with Google
    try:
        url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(id_token)
        with urllib.request.urlopen(url, timeout=5) as resp:
            info = json.loads(resp.read())
            if info.get("aud") != GOOGLE_CLIENT_ID:
                return None
            email = info.get("email", "").lower()
            if not email.endswith("@" + ALLOWED_DOMAIN):
                return None
            # Cache until token expiry (exp claim) minus 30s safety margin
            exp = int(info.get("exp", 0))
            if exp:
                _token_cache[token_hash] = (email, exp - 30)
            return email
    except Exception:
        return None


def require_auth(event):
    """
    Extract and verify the Bearer token from the request.
    Returns (email, None) on success or (None, error_response) on failure.
    Skips auth when GOOGLE_CLIENT_ID is not configured (dev/test mode).
    """
    if not GOOGLE_CLIENT_ID:
        return "dev", None   # auth not configured — allow through (deploy.sh warns)
    headers = event.get("headers") or {}
    auth = headers.get("Authorization") or headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None, cors_response(401, json.dumps({"error": "Missing Authorization header"}))
    email = verify_id_token(auth[7:])
    if not email:
        return None, cors_response(403, json.dumps({"error": "Invalid token or unauthorised domain"}))
    return email, None

# ── Per-group system prompt ───────────────────────────────────────────────────

GROUP_PROMPT = """You are generating service description lines for an AWS pricing proposal table.

Output ONLY the service lines for the given batch — no <tr> wrapper, no group heading, no totals, no cost lines.

Format each service as:
ServiceName<br>
- field: value<br>
- field: value<br>
<br>

If the service has a Description, append it to the name with a dash: ServiceName - Description<br>
If there is NO Description, just use the ServiceName alone with NO dash or trailing punctuation.

(blank <br> line between each service)

## RULES
- Copy ALL properties from the JSON exactly — do not skip any field unless it matches the exclusions below
- NEVER add cost/price lines (e.g. "Monthly: $X" or "12 months: $Y") — these are not in the Properties
- Skip: "Tenancy: Shared Instances", "Region" field, zero/empty/"Not selected" fields (e.g. "DT Inbound: Not selected: 0 TB per month")
- Skip unit-label-only fields with no number: "Management events units: millions", "Data events units: millions", "Network activity events units: millions", "Insight events units: millions"
- Skip blank placeholder values: "Number of network activity events: per month" (no number)
- Skip retention period labels with no value: "Hourly backups warm retention period: Days"
- "Workload: Consistent, Number of instances: X" → skip the Workload line, show "- Number of instances: X" as a separate line
- Decimal percentages (0.1, 0.03, 1) → 10%, 3%, 100% for fields like "Estimated annual increase", "Estimated daily change", "Mobile sampling rate"
- EC2/RDS instance types: the vCPU and Memory values are already provided in the Properties as "vCPU" and "Memory" — include them after the instance type line
- Pricing strategy: shorten → "Compute Savings Plans 3yr No Upfront", "On Demand", "Reserved 1yr No Upfront"
- Each field line starts with "- "
- No &nbsp; indentation

Output ONLY the service lines, nothing else."""


MAX_SERVICES_PER_CHUNK = 10  # Max services per Claude call

# ── EC2 spec cache + lookup ───────────────────────────────────────────────────
_spec_cache = {}

def get_ec2_specs(instance_type):
    """Look up vCPU and memory for an EC2 instance type via AWS Pricing API."""
    if not instance_type:
        return "?", "?"
    if instance_type in _spec_cache:
        return _spec_cache[instance_type]
    try:
        pricing_client = boto3.client("pricing", region_name="us-east-1")
        for location in ["Asia Pacific (Singapore)", "Asia Pacific (Malaysia)", "US East (N. Virginia)"]:
            resp = pricing_client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                    {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                    {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                    {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                ],
                MaxResults=1,
            )
            items = resp.get("PriceList", [])
            if items:
                attrs = json.loads(items[0]).get("product", {}).get("attributes", {})
                result = (attrs.get("vcpu", "?"), attrs.get("memory", "?"))
                _spec_cache[instance_type] = result
                return result
    except Exception as e:
        print(f"Spec lookup failed for {instance_type}: {e}")
        traceback.print_exc()
    _spec_cache[instance_type] = ("?", "?")
    return "?", "?"

def enrich_services_with_specs(services):
    """Add vCPU/Memory to EC2/RDS service Properties before sending to Claude."""
    for svc in services:
        name = svc.get("Service Name", "")
        props = svc.get("Properties", {})
        if "EC2" in name:
            instance_type = props.get("Advance EC2 instance", "")
            if instance_type and "vCPU" not in props:
                vcpu, memory = get_ec2_specs(instance_type)
                props["vCPU"] = vcpu
                props["Memory"] = memory
    return services

def collect_services_recursive(node, path=()):
    """
    Recursively walk a group node at any nesting depth and return a flat list of
    (path_tuple, service_dict) pairs.  path_tuple contains all sub-key names
    from the group root down to (but not including) the Services array.

    A node may have BOTH a top-level "Services" list AND sibling sub-group keys
    (e.g. "AWS pricing non-related to inventory list", "ICT pricing").
    We collect the flat Services first, then recurse into every non-Services sibling.
    """
    if isinstance(node, list):
        return [(path, s) for s in node]
    if isinstance(node, dict):
        results = []
        # Collect any flat Services at this level first
        if "Services" in node and isinstance(node["Services"], list):
            results.extend((path, s) for s in node["Services"])
        # Always recurse into non-Services sibling keys (sub-groups)
        for key, val in node.items():
            if key == "Services":
                continue
            results.extend(collect_services_recursive(val, path + (key,)))
        return results
    return []


# ── Property formatting helpers for itemised layout ───────────────────────────

# Fields to skip unconditionally
_SKIP_FIELDS = {
    "Tenancy", "Region",
    "Management events units", "Data events units", "Network activity events units",
    "Insight events units",
}
_SKIP_VALUE_PATTERNS = [
    r"^0\s+",           # zero-quantity fields e.g. "0 TB per month"
    r"Not selected",    # "DT Inbound: Not selected"
    r"^\s*$",           # blank
    r"^per\s+\w",       # unit-only placeholders e.g. "per month", "per hour"
    r"^Days\s*$",       # empty retention period
    r"^Weeks\s*$",
]
_DECIMAL_PCT_FIELDS = [
    "Estimated annual increase", "Estimated daily change", "Mobile sampling rate",
]
_PRICING_STRATEGY_MAP = {
    "Amazon EC2 Instance Savings Plans 3yr No Upfront": "EC2 Savings Plans 3yr No Upfront",
    "Compute Savings Plans 3yr No Upfront": "Compute Savings Plans 3yr No Upfront",
    "Compute Savings Plans 1yr No Upfront": "Compute Savings Plans 1yr No Upfront",
    "Reserved 1yr No Upfront": "Reserved 1yr No Upfront",
    "Reserved 3yr No Upfront": "Reserved 3yr No Upfront",
    "OnDemand": "On Demand",
}


def _should_skip_field(key, value):
    """Return True if this property field should be omitted from the output."""
    if key in _SKIP_FIELDS:
        return True
    val_str = str(value).strip()
    for pat in _SKIP_VALUE_PATTERNS:
        if re.search(pat, val_str, re.IGNORECASE):
            return True
    return False


def _format_value(key, value):
    """Apply value transformations: percentage, pricing strategy shortening."""
    val_str = str(value).strip()
    # Decimal percentage fields
    for pct_field in _DECIMAL_PCT_FIELDS:
        if pct_field.lower() in key.lower():
            try:
                f = float(val_str)
                return f"{f * 100:.0f}%"
            except ValueError:
                pass
    # Pricing strategy
    for long, short in _PRICING_STRATEGY_MAP.items():
        if long.lower() in val_str.lower():
            return short
    return val_str


# AWS Calculator max nesting is 5 levels — use 5 fixed blue stops, all white text
_GRP_COLOURS = ["#0000ff", "#2260ff", "#598eff", "#8fb6ff", "#c6dbff"]

def grp_heading_style(depth, max_depth=None):
    """Return inline CSS for a group heading row at the given nesting depth (0-based)."""
    bg = _GRP_COLOURS[min(depth, len(_GRP_COLOURS) - 1)]
    return f"background-color:{bg};color:#fff;font-weight:bold;"


def format_service_props_html(svc):
    """
    Format a single service's properties as HTML lines for the itemised table cell.
    Returns an HTML string like:
      - field: value<br>
      - field: value<br>
    Handles Workload → Number of instances extraction.
    """
    lines = []
    props = svc.get("Properties", {})
    for key, value in props.items():
        val_str = str(value).strip()
        # Workload: Consistent, Number of instances: X  →  extract instances only
        if key == "Workload":
            m = re.search(r"Number of instances[:\s]+(\d+)", val_str, re.IGNORECASE)
            if m:
                lines.append(f"- Number of instances: {m.group(1)}")
            continue
        if _should_skip_field(key, value):
            continue
        formatted_val = _format_value(key, value)
        lines.append(f"- {key}: {formatted_val}")
    return "<br>\n".join(lines) + ("<br>" if lines else "")


def split_group_into_chunks(group_name, group_data):
    """
    Split a group into chunks of MAX_SERVICES_PER_CHUNK services each.
    Handles any nesting depth — sub_name is now a tuple representing the
    full path from group root to the Services node (e.g. ('GroupA', 'SubGroup')).
    """
    if isinstance(group_data, list):
        flat = [((), s) for s in group_data]
    else:
        flat = collect_services_recursive(group_data)

    is_nested = any(len(path) > 0 for path, _ in flat)

    # Bucket services by their full path tuple
    sub_buckets = OrderedDict()
    for path, svc in flat:
        if path not in sub_buckets:
            sub_buckets[path] = []
        sub_buckets[path].append(svc)

    chunks = []
    for path_key, services in sub_buckets.items():
        # sub_name: JSON-encode the path tuple so it survives S3 round-trip
        sub_name = json.dumps(list(path_key)) if path_key else None
        for i in range(0, len(services), MAX_SERVICES_PER_CHUNK):
            chunks.append({
                "group_name": group_name,
                "chunk_data": {"Services": services[i:i + MAX_SERVICES_PER_CHUNK]},
                "is_nested": is_nested,
                "sub_name": sub_name,
            })

    return chunks if chunks else [{"group_name": group_name, "chunk_data": group_data, "is_nested": False, "sub_name": None}]


HTML_WRAPPER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{customer_name} — AWS Consumption Table</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 10pt; margin: 40px; color: #000; background: #fff; }}
  table {{ border-collapse: collapse; width: 680px; table-layout: auto; }}
  th, td {{ border: 1px solid #888; padding: 5px 8px; font-size: 10pt; }}
  th {{ background-color: #0000ff; color: #fff; font-weight: bold; text-align: center; white-space: nowrap; }}
  .col-no {{ width: 50px; }}
  .col-cost {{ width: 110px; }}
  .no-cell {{ text-align: center; vertical-align: top; }}
  .desc-cell {{ vertical-align: top; }}
  .cost-cell {{ text-align: right; vertical-align: top; white-space: nowrap; }}
  /* Itemised layout — group/sub-group heading rows (colours generated inline per row) */
  .divider td {{ background-color: #0000ff; border: none; height: 10px; padding: 0; }}
  .sum-label {{ text-align: right; }}
  .sum-value {{ text-align: right; white-space: nowrap; }}
  .sum-bold td {{ font-weight: bold; }}
  a {{ color: #0000ff; font-size: 9.5pt; }}
</style>
</head>
<body>
<table>
  <colgroup><col class="col-no"><col><col class="col-cost"></colgroup>
  <tr><th>No</th><th>Description</th><th>Monthly Cost</th></tr>
{rows}
  <tr class="divider"><td colspan="3"></td></tr>
  <tr><td colspan="2" class="sum-label">Total Monthly Cost</td><td class="sum-value">USD {total_monthly}</td></tr>
  <tr><td colspan="2" class="sum-label">Conversion to __CURRENCY__ ( USD 1 - __CURRENCY__ __RATE__ )</td><td class="sum-value">__CURRENCY__ __LOCAL__</td></tr>
  <tr><td colspan="2" class="sum-label">Tax (__TAX_PCT__)</td><td class="sum-value">__CURRENCY__ __TAX__</td></tr>
  <tr class="sum-bold"><td colspan="2" class="sum-label">Total Monthly Payment</td><td class="sum-value">__CURRENCY__ __TOTAL__</td></tr>
</table>
<br>
<a href="{calc_url}" target="_blank">Calculator Link: {calc_url}</a>
</body>
</html>"""


# ── Router ────────────────────────────────────────────────────────────────────

def handler(event, context):
    path = event.get("path", "") or event.get("rawPath", "")
    method = (event.get("httpMethod", "") or
              event.get("requestContext", {}).get("http", {}).get("method", "POST"))

    if method == "OPTIONS":
        return cors_response(200, "")

    # Internal async worker paths invoked by Lambda directly — skip auth
    if path in ("/__process", "/__process-gcp", "/__process-azure", "/__parse-azure"):
        if path == "/__process":
            return handle_process(event)
        if path == "/__process-gcp":
            return handle_process_gcp(event)
        if path == "/__parse-azure":
            return handle_do_parse_azure(event)
        if path == "/__process-azure":
            return handle_process_azure(event)

    # All public API routes require a valid token
    _, auth_err = require_auth(event)
    if auth_err:
        return auth_err

    if path == "/api/generate":
        return handle_generate(event)
    if path == "/api/generate-gcp":
        return handle_generate_gcp(event)
    if path == "/api/status":
        return handle_status(event)
    if path == "/api/parse-gcp":
        return handle_parse_gcp(event)
    if path == "/api/parse-azure":
        return handle_parse_azure(event)
    if path == "/api/generate-azure":
        return handle_generate_azure(event)
    return cors_response(404, json.dumps({"error": f"Not found: {path}"}))


GCP_PARSE_PROMPT = """You are parsing a GCP Calculator estimate that was copy-pasted as raw text.

Extract ALL services and return ONLY a JSON object in this exact structure:
{
  "total_estimated_cost": 2646.53,
  "groups": [
    {
      "name": "Compute",
      "services": [
        {
          "name": "Core Server (Compute Engine)",
          "cost": 113.82,
          "fields": [
            { "key": "Machine type", "value": "e2-standard-4, vCPUs: 4, RAM: 16 GB" },
            { "key": "Boot disk size (GiB)", "value": "150 GiB" }
          ]
        }
      ]
    }
  ]
}

RULES:
- total_estimated_cost = the value from "Total estimated cost$X,XXX.XX" at the end of the paste — this is the authoritative total, extract it exactly
- Extract every group (Compute, Networking, Storage, Security, Databases, etc.)
- Extract every service under each group with its exact dollar cost
- Extract every field/value pair for each service
- SKIP fields where value is "false"
- SKIP "Service type" fields
- Keep ALL "Region", "Source Location", and "Destination Location" fields with their exact values as shown
- If there are multiple Region fields for the same service, label the second one "Region (Internal ALB)"
- Use the exact service name as shown (e.g. "S2S VPN (Cloud VPN)")
- Service cost = dollar amount IMMEDIATELY AFTER the service name — never use a dollar amount that appears BEFORE the service name
- A dollar amount before a service name is the GROUP subtotal, not the service cost — ignore it
- Example: "$6.36Cloud DNS (Cloud DNS)$4.40..." → Cloud DNS cost = 4.40 (not 6.36)
- Example: "Secret Manager$1.96..." → Secret Manager cost = 1.96
- Group name should be Title Case (e.g. "Compute" not "compute")
- Services that appear BEFORE any group header go into a group called "Other"
- Return ONLY the JSON object, no explanation, no markdown code blocks"""


# ── /api/parse-gcp — use Claude to parse raw GCP paste text into structured JSON ──

def handle_parse_gcp(event):
    try:
        body = json.loads(event.get("body", "{}"))
        text = body.get("text", "").strip()
        if not text:
            return cors_response(400, json.dumps({"error": "No text provided"}))

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 8000,
                "system": GCP_PARSE_PROMPT,
                "messages": [{"role": "user", "content": text}],
            }),
            contentType="application/json",
            accept="application/json",
        )

        raw = json.loads(response["body"].read())["content"][0]["text"].strip()
        # Strip markdown code blocks if Claude wrapped the response
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)
        groups = parsed.get("groups", [])

        # Use the authoritative total extracted from "Total estimated cost" line
        # Fall back to summing service costs if not present
        authoritative_total = parsed.get("total_estimated_cost")

        # Calculate group totals from service costs
        for g in groups:
            g["total"] = sum(s.get("cost", 0) for s in g.get("services", []))

        calculated_total = sum(g["total"] for g in groups)
        total = authoritative_total if authoritative_total else calculated_total

        return cors_response(200, json.dumps({
            "groups": groups,
            "total": total,
        }))

    except json.JSONDecodeError as e:
        return cors_response(500, json.dumps({"error": f"Claude returned invalid JSON: {e}"}))
    except Exception as e:
        traceback.print_exc()
        return cors_response(500, json.dumps({"error": str(e)}))


# ── /api/generate — save job, trigger all group workers async ─────────────────

def handle_generate(event):
    try:
        body = json.loads(event.get("body", "{}"))
        json_input = body.get("json", "")
        myr_rate = float(body.get("myr_rate", 4.4))
        currency = body.get("currency", "MYR")

        data = json_input if isinstance(json_input, dict) else json.loads(json_input)
        if "Groups" not in data or "Total Cost" not in data:
            return cors_response(400, json.dumps({"error": "Not a valid AWS Pricing Calculator export"}))

        # Use user-provided customer name if given, else fall back to JSON name
        customer_name = body.get("customer_name", "").strip() or data.get("Name", "Customer")
        job_id = uuid.uuid4().hex

        # Build chunk list — split large groups into batches of MAX_SERVICES_PER_CHUNK
        chunks = []
        groups = []
        for gname, gdata in data.get("Groups", {}).items():
            if "To put in RFP" in gname:
                continue
            # Normalize gdata to dict if it's a list
            if isinstance(gdata, list):
                gdata = {"Services": gdata}
            group_chunks = split_group_into_chunks(gname, gdata)
            for c in group_chunks:
                chunks.append(c)
            groups.append(gname)

        total_monthly = float(data["Total Cost"]["monthly"])
        total_myr = total_monthly * myr_rate
        tax = total_myr * 0.08
        calc_url = data.get("Metadata", {}).get("Share Url", "")

        # Save to S3 — deduplicate by content hash
        if S3_BUCKET:
            try:
                json_bytes = json.dumps(data).encode("utf-8")
                content_hash = hashlib.md5(json_bytes).hexdigest()[:12]
                timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                key = f"uploads/aws/{customer_name}/{timestamp}-{content_hash}.json"

                # Check if identical content already exists
                existing = s3.list_objects_v2(
                    Bucket=S3_BUCKET,
                    Prefix=f"uploads/aws/{customer_name}/",
                )
                already_stored = any(
                    obj["Key"].endswith(f"-{content_hash}.json")
                    for obj in existing.get("Contents", [])
                )

                if not already_stored:
                    s3.put_object(
                        Bucket=S3_BUCKET,
                        Key=key,
                        Body=json_bytes,
                        ContentType="application/json",
                        Metadata={"customer": customer_name, "myr_rate": str(myr_rate)},
                    )
                    print(f"Saved new upload: {key}")
                else:
                    print(f"Duplicate content skipped for {customer_name} (hash: {content_hash})")
            except Exception as e:
                print(f"S3 upload failed (non-fatal): {e}")

        # Save job metadata — itemised layout skips Claude workers, total_chunks=0
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"jobs/{job_id}/meta.json",
            Body=json.dumps({
                "customer_name": customer_name,
                "groups": groups,
                "chunks": [],       # itemised assembly reads input.json directly — no workers
                "total_chunks": 0,
                "myr_rate": myr_rate,
                "currency": currency,
                "total_monthly": f"{total_monthly:,.2f}",
                "total_myr": f"{total_myr:,.2f}",
                "tax": f"{tax:,.2f}",
                "total_with_tax": f"{total_myr + tax:,.2f}",
                "calc_url": calc_url,
            }).encode(),
            ContentType="application/json",
        )

        # Save full input data for assembly
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"jobs/{job_id}/input.json",
            Body=json.dumps({"data": data, "myr_rate": myr_rate, "currency": currency}).encode(),
            ContentType="application/json",
        )

        # No Lambda workers dispatched — frontend polls /api/status once and gets done immediately
        return cors_response(200, json.dumps({
            "job_id": job_id,
            "customer_name": customer_name,
            "total_groups": len(groups),
            "total_chunks": 0,
            "groups": groups,
            "status": "processing",
        }))

    except Exception as e:
        traceback.print_exc()
        return cors_response(500, json.dumps({"error": str(e)}))


# ── /api/status — check how many groups done, return HTML when all done ───────

def handle_status(event):
    try:
        params = event.get("queryStringParameters") or {}
        job_id = params.get("job_id", "")
        if not job_id:
            return cors_response(400, json.dumps({"error": "Missing job_id"}))

        meta_obj = s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json")
        meta = json.loads(meta_obj["Body"].read())
        chunks = meta.get("chunks", [])
        groups = meta.get("groups", [])
        total_chunks = meta.get("total_chunks", len(chunks))
        currency = meta.get("currency", "MYR")
        tax_pct = "9% GST" if currency == "SGD" else "8% SST"

        # Check which chunks are done
        done_chunks = {}  # chunk_index -> partial_html
        errors = []
        for i in range(total_chunks):
            key = f"jobs/{job_id}/chunk_{i}.json"
            try:
                obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
                result = json.loads(obj["Body"].read())
                if result.get("error"):
                    errors.append(f"Chunk {i}: {result['error']}")
                else:
                    done_chunks[i] = result
            except Exception:
                pass

        if errors:
            return cors_response(200, json.dumps({"status": "error", "error": "; ".join(errors)}))

        completed = len(done_chunks)
        # Which groups have all their chunks done
        groups_done = set()
        group_chunk_counts = {}
        for i, c in enumerate(chunks):
            gname = c["group_name"]
            group_chunk_counts[gname] = group_chunk_counts.get(gname, [])
            group_chunk_counts[gname].append(i)
        for gname, chunk_indices in group_chunk_counts.items():
            if all(idx in done_chunks for idx in chunk_indices):
                groups_done.add(gname)

        if completed < total_chunks:
            return cors_response(200, json.dumps({
                "status": "processing",
                "completed": completed,
                "total": total_chunks,
                "groups_done": list(groups_done),
                "groups": groups,
            }))

        # Azure parse job — check if result is ready
        if meta.get("cloud") == "azure_parse":
            if meta.get("status") == "error":
                return cors_response(200, json.dumps({"status": "error", "error": meta.get("error", "Parse failed")}))
            if meta.get("status") == "done":
                result = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/result.json")["Body"].read())
                return cors_response(200, json.dumps({"status": "done", **result}))
            return cors_response(200, json.dumps({"status": "processing"}))

        # GCP job — different assembly path
        if meta.get("cloud") == "gcp":
            return assemble_gcp_html(meta, groups, chunks, done_chunks)

        # Azure job — different assembly path
        if meta.get("cloud") == "azure":
            return assemble_azure_html(meta, groups, chunks, done_chunks)

        # All chunks done — build itemised table: one row per group/sub-group heading + one row per service
        inp = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/input.json")["Body"].read())
        rows_html = []

        for row_num, gname in enumerate(groups, 1):
            clean_name = re.sub(r"^Original Grouping\s*>\s*", "", gname).strip()

            # Get flat list of (path, service) for this group
            gdata = inp["data"]["Groups"].get(gname, {})
            if isinstance(gdata, list):
                gdata = {"Services": gdata}
            all_services = collect_services_recursive(gdata)

            # Calculate total for this top-level group
            gtotal = sum(float(s["Service Cost"]["monthly"]) for _, s in all_services)

            # Compute max sub-group depth for this group (for gradient scaling)
            max_depth = max((len(path) for path, _ in all_services), default=0)

            # Emit top-level group heading row (depth 0)
            style0 = grp_heading_style(0, max_depth)
            rows_html.append(
                f'  <tr>'
                f'<td class="no-cell" style="{style0}">{row_num}.</td>'
                f'<td class="desc-cell" style="{style0}"><b>{clean_name}</b></td>'
                f'<td class="cost-cell" style="{style0}">USD {gtotal:,.2f}</td>'
                f'</tr>'
            )

            # Bucket services by path, preserving insertion order
            path_buckets = {}   # path_tuple -> [service, ...]
            for path, svc in all_services:
                if path not in path_buckets:
                    path_buckets[path] = []
                path_buckets[path].append(svc)

            # Assign dot-numbers to every unique sub-path prefix
            prefix_counters = {}
            path_numbers = {}

            def get_sub_path_number(path):
                if path in path_numbers:
                    return path_numbers[path]
                parent = path[:-1]
                if parent not in prefix_counters:
                    prefix_counters[parent] = 0
                prefix_counters[parent] += 1
                n = prefix_counters[parent]
                parent_num = path_numbers.get(parent, str(row_num))
                path_numbers[path] = f"{parent_num}.{n}"
                return path_numbers[path]

            for path in path_buckets:
                for depth in range(1, len(path) + 1):
                    get_sub_path_number(path[:depth])

            emitted_paths = set()

            for path, services in path_buckets.items():
                # Emit any new sub-group heading rows for this path
                for depth in range(1, len(path) + 1):
                    prefix = path[:depth]
                    if prefix not in emitted_paths:
                        emitted_paths.add(prefix)
                        label = prefix[-1]
                        sub_num = path_numbers.get(prefix, "")
                        style = grp_heading_style(depth, max_depth)
                        rows_html.append(
                            f'  <tr>'
                            f'<td class="no-cell" style="{style}">{sub_num}.</td>'
                            f'<td class="desc-cell" style="{style}"><b>{label}</b></td>'
                            f'<td class="cost-cell" style="{style}"></td>'
                            f'</tr>'
                        )

                # Emit one row per service
                for svc in services:
                    svc_name = (svc.get("Service Name") or "").strip()
                    svc_desc = (svc.get("Description") or "").strip()
                    display_name = f"{svc_name} - {svc_desc}" if svc_desc else svc_name
                    props_html = format_service_props_html(svc)
                    svc_cost = float(svc.get("Service Cost", {}).get("monthly", 0))
                    rows_html.append(
                        f'  <tr>'
                        f'<td class="no-cell"></td>'
                        f'<td class="desc-cell">'
                        f'<b>{display_name}</b><br>\n{props_html}'
                        f'</td>'
                        f'<td class="cost-cell">USD {svc_cost:,.2f}</td>'
                        f'</tr>'
                    )

        html = HTML_WRAPPER.format(
            customer_name=meta["customer_name"],
            rows="\n".join(rows_html),
            total_monthly=meta["total_monthly"],
            myr_rate=meta["myr_rate"],
            total_myr=meta["total_myr"],
            tax=meta["tax"],
            total_with_tax=meta["total_with_tax"],
            calc_url=meta["calc_url"],
        )
        # Replace currency placeholders
        html = html.replace("__CURRENCY__", currency)
        html = html.replace("__RATE__", str(meta["myr_rate"]))
        html = html.replace("__LOCAL__", meta["total_myr"])
        html = html.replace("__TAX_PCT__", tax_pct)
        html = html.replace("__TAX__", meta["tax"])
        html = html.replace("__TOTAL__", meta["total_with_tax"])

        return cors_response(200, json.dumps({
            "status": "done",
            "html": html,
            "customer_name": meta["customer_name"],
            "total_monthly": meta["total_monthly"],
            "total_myr": meta["total_myr"],
        }))

    except Exception as e:
        traceback.print_exc()
        return cors_response(500, json.dumps({"error": str(e)}))


# ── /__process — runs Claude for ONE group ────────────────────────────────────

def handle_process(event):
    job_id = None
    chunk_index = 0
    try:
        body = json.loads(event.get("body", "{}"))
        job_id = body["job_id"]
        chunk_index = body["chunk_index"]

        # Load metadata and input
        meta = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json")["Body"].read())
        inp = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/input.json")["Body"].read())
        data = inp["data"]

        chunk = meta["chunks"][chunk_index]
        group_name = chunk["group_name"]
        sub_name = chunk.get("sub_name")
        chunk_data = chunk["chunk_data"]
        clean_name = re.sub(r"^Original Grouping\s*>\s*", "", group_name).strip()
        context_label = f"{clean_name}" + (f" / {sub_name}" if sub_name else "")

        services = chunk_data.get("Services", [])
        # Enrich EC2 services with vCPU/Memory from AWS Pricing API
        services = enrich_services_with_specs(services)
        # Log first EC2 to verify enrichment
        for s in services:
            if "EC2" in s.get("Service Name",""):
                print(f"EC2 props after enrichment: vCPU={s['Properties'].get('vCPU','MISSING')} Memory={s['Properties'].get('Memory','MISSING')}")
                break
        svc_total = sum(float(s["Service Cost"]["monthly"]) for s in services)

        user_msg = f"""Group context: {context_label}
Services total: USD {svc_total:,.2f}
Number of services in this batch: {len(services)}

Services JSON:
{json.dumps({"Services": services}, indent=2)}"""

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 8000,
                "system": GROUP_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            }),
            contentType="application/json",
            accept="application/json",
        )

        partial_html = json.loads(response["body"].read())["content"][0]["text"].strip()
        partial_html = re.sub(r"^```html?\s*", "", partial_html)
        partial_html = re.sub(r"\s*```$", "", partial_html)

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"jobs/{job_id}/chunk_{chunk_index}.json",
            Body=json.dumps({
                "partial_html": partial_html,
                "group_name": group_name,
                "sub_name": sub_name,
            }).encode(),
            ContentType="application/json",
        )

    except Exception as e:
        traceback.print_exc()
        if job_id is not None:
            try:
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=f"jobs/{job_id}/chunk_{chunk_index}.json",
                    Body=json.dumps({"error": str(e)}).encode(),
                    ContentType="application/json",
                )
            except Exception:
                pass

    return cors_response(200, "")


GCP_GROUP_PROMPT = """You are generating service description lines for a GCP pricing proposal table.

The input is structured data parsed from a GCP Calculator estimate page. Each service has a name, total cost, and a list of fields (key/value pairs).

Output ONLY the service lines for the given group — no <tr> wrapper, no group heading, no totals row.

Format each service as:
ServiceName<br>
- field: value<br>
- field: value<br>
<br>

(blank <br> line between each service)

## RULES
- Use the service name exactly as given
- Output EVERY field in the fields list — do not skip, filter, or judge any field
- Every field line MUST start with "- "
- No trailing dash or punctuation after service name
- If a service has zero fields, just output the service name line followed by a blank <br>
- The cost column is handled separately — do NOT add any cost or price values

Output ONLY the service lines, nothing else."""


GCP_HTML_WRAPPER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{customer_name} — GCP Consumption Table</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 10pt; margin: 40px; color: #000; background: #fff; }}
  table {{ border-collapse: collapse; width: 680px; table-layout: auto; }}
  th, td {{ border: 1px solid #888; padding: 5px 8px; font-size: 10pt; }}
  th {{ background-color: #1a73e8; color: #fff; font-weight: bold; text-align: center; white-space: nowrap; }}
  .col-no {{ width: 50px; }}
  .col-cost {{ width: 110px; }}
  .no-cell {{ text-align: center; vertical-align: top; }}
  .desc-cell {{ vertical-align: top; }}
  .cost-cell {{ text-align: right; vertical-align: top; white-space: nowrap; }}
  .divider td {{ background-color: #1a73e8; border: none; height: 10px; padding: 0; }}
  .sum-label {{ text-align: right; }}
  .sum-value {{ text-align: right; white-space: nowrap; }}
  .sum-bold td {{ font-weight: bold; }}
  a {{ color: #1a73e8; font-size: 9.5pt; }}
</style>
</head>
<body>
<table>
  <colgroup><col class="col-no"><col><col class="col-cost"></colgroup>
  <tr><th>No</th><th>Description</th><th>Monthly Cost</th></tr>
{rows}
  <tr class="divider"><td colspan="3"></td></tr>
  <tr><td colspan="2" class="sum-label">Total Monthly Cost</td><td class="sum-value">USD {total_monthly}</td></tr>
  <tr><td colspan="2" class="sum-label">Conversion to __CURRENCY__ ( USD 1 - __CURRENCY__ __RATE__ )</td><td class="sum-value">__CURRENCY__ __LOCAL__</td></tr>
  <tr><td colspan="2" class="sum-label">Tax (__TAX_PCT__)</td><td class="sum-value">__CURRENCY__ __TAX__</td></tr>
  <tr class="sum-bold"><td colspan="2" class="sum-label">Total Monthly Payment</td><td class="sum-value">__CURRENCY__ __TOTAL__</td></tr>
</table>
{calc_link}
</body>
</html>"""


# ── GCP HTML assembly ─────────────────────────────────────────────────────────

def assemble_gcp_html(meta, groups, chunks, done_chunks):
    currency = meta.get("currency", "MYR")
    tax_pct = "9% GST" if currency == "SGD" else "8% SST"
    calc_url = meta.get("calc_url", "")
    calc_link = f'<br><a href="{calc_url}" target="_blank">Calculator Link: {calc_url}</a>' if calc_url else ""

    # Build group lookup from chunks (chunk_data is the full group object)
    gcp_groups = {c["group_name"]: c["chunk_data"] for c in chunks}

    GRP_STYLE = "background-color:#4a90e8;color:#fff;font-weight:bold;"
    rows_html = []
    for row_num, gname in enumerate(groups, 1):
        g = gcp_groups.get(gname, {})
        gtotal = float(g.get("total", 0))
        services = g.get("services", [])

        # Group heading row
        rows_html.append(
            f'  <tr>'
            f'<td class="no-cell" style="{GRP_STYLE}">{row_num}.</td>'
            f'<td class="desc-cell" style="{GRP_STYLE}"><b>{gname}</b></td>'
            f'<td class="cost-cell" style="{GRP_STYLE}">USD {gtotal:,.2f}</td>'
            f'</tr>'
        )
        # One row per service
        for svc in services:
            svc_name = svc.get("name", "").strip()
            svc_cost = float(svc.get("cost") or 0)
            fields = svc.get("fields") or []
            field_lines = "<br>\n".join(
                f"- {f['key']}: {f['value']}"
                for f in fields
                if str(f.get("value", "")).strip().lower() not in ("", "false", "0")
            )
            props_html = (field_lines + "<br>") if field_lines else ""
            rows_html.append(
                f'  <tr>'
                f'<td class="no-cell"></td>'
                f'<td class="desc-cell"><b>{svc_name}</b><br>\n{props_html}</td>'
                f'<td class="cost-cell">USD {svc_cost:,.2f}</td>'
                f'</tr>'
            )

    html = GCP_HTML_WRAPPER.format(
        customer_name=meta["customer_name"],
        rows="\n".join(rows_html),
        total_monthly=meta["total_monthly"],
        calc_link=calc_link,
    )
    html = html.replace("__CURRENCY__", currency)
    html = html.replace("__RATE__", str(meta["usd_rate"]))
    html = html.replace("__LOCAL__", meta["total_local"])
    html = html.replace("__TAX_PCT__", tax_pct)
    html = html.replace("__TAX__", meta["tax"])
    html = html.replace("__TOTAL__", meta["total_with_tax"])
    return cors_response(200, json.dumps({
        "status": "done", "html": html,
        "customer_name": meta["customer_name"],
        "total_monthly": meta["total_monthly"],
    }))


# ── /api/generate-gcp ─────────────────────────────────────────────────────────

def handle_generate_gcp(event):
    try:
        body = json.loads(event.get("body", "{}"))
        groups = body.get("groups", [])           # [{name, total, services:[{name,quantity,region,cost}]}]
        customer_name = body.get("customer_name", "Customer")
        usd_rate = float(body.get("usd_rate", 4.4))
        currency = body.get("currency", "MYR")
        calc_url = body.get("calc_url", "")

        if not groups:
            return cors_response(400, json.dumps({"error": "No groups provided"}))

        job_id = uuid.uuid4().hex
        total_monthly = sum(g["total"] for g in groups)
        total_local = total_monthly * usd_rate
        tax = total_local * 0.08

        # Save raw groups to S3 under uploads/gcp/
        if S3_BUCKET:
            try:
                raw_bytes = json.dumps({"customer": customer_name, "groups": groups}).encode()
                content_hash = hashlib.md5(raw_bytes).hexdigest()[:12]
                timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                key = f"uploads/gcp/{customer_name}/{timestamp}-{content_hash}.json"
                existing = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"uploads/gcp/{customer_name}/")
                already_stored = any(obj["Key"].endswith(f"-{content_hash}.json") for obj in existing.get("Contents", []))
                if not already_stored:
                    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=raw_bytes, ContentType="application/json",
                                  Metadata={"customer": customer_name})
                    print(f"Saved GCP upload: {key}")
            except Exception as e:
                print(f"S3 GCP upload failed (non-fatal): {e}")

        # Build chunks — one per group, stored in meta for assemble_gcp_html
        chunks = [{"group_name": g["name"], "chunk_data": g, "is_nested": False, "sub_name": None} for g in groups]
        group_names = [g["name"] for g in groups]

        s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json",
            Body=json.dumps({
                "cloud": "gcp",
                "customer_name": customer_name,
                "groups": group_names,
                "chunks": chunks,
                "total_chunks": 0,          # itemised assembly reads chunks directly — no workers needed
                "usd_rate": usd_rate,
                "currency": currency,
                "total_monthly": f"{total_monthly:,.2f}",
                "total_local": f"{total_local:,.2f}",
                "tax": f"{tax:,.2f}",
                "total_with_tax": f"{total_local + tax:,.2f}",
                "calc_url": calc_url,
            }).encode(), ContentType="application/json")

        # No Lambda workers — assembly happens synchronously in handle_status
        return cors_response(200, json.dumps({
            "job_id": job_id, "customer_name": customer_name,
            "total_groups": len(groups), "total_chunks": 0,
            "groups": group_names, "status": "processing",
        }))
    except Exception as e:
        traceback.print_exc()
        return cors_response(500, json.dumps({"error": str(e)}))


# ── /__process-gcp ────────────────────────────────────────────────────────────

def handle_process_gcp(event):
    job_id = None
    chunk_index = 0
    try:
        body = json.loads(event.get("body", "{}"))
        job_id = body["job_id"]
        chunk_index = body["chunk_index"]

        meta = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json")["Body"].read())
        chunk = meta["chunks"][chunk_index]
        group = chunk["chunk_data"]
        group_name = chunk["group_name"]

        services = group.get("services", [])
        svc_total = group.get("total", 0)
        user_msg = f"""Group: {group_name}
Total: USD {svc_total:,.2f}
Services:
{json.dumps(services, indent=2)}"""

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "system": GCP_GROUP_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            }),
            contentType="application/json", accept="application/json",
        )
        partial_html = json.loads(response["body"].read())["content"][0]["text"].strip()
        partial_html = re.sub(r"^```html?\s*", "", partial_html)
        partial_html = re.sub(r"\s*```$", "", partial_html)

        s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/chunk_{chunk_index}.json",
            Body=json.dumps({"partial_html": partial_html, "group_name": group_name, "sub_name": None}).encode(),
            ContentType="application/json")

    except Exception as e:
        traceback.print_exc()
        if job_id is not None:
            try:
                s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/chunk_{chunk_index}.json",
                    Body=json.dumps({"error": str(e)}).encode(), ContentType="application/json")
            except Exception:
                pass
    return cors_response(200, "")


AZURE_PARSE_PROMPT = """You are parsing an Azure pricing estimate exported as Excel (CSV rows).

Each row has these columns: Service category, Service type, Custom name, Region, Description, Estimated monthly cost, Estimated upfront cost.

For each service row, convert the Description into clean bullet points. The Description is a dense comma/semicolon-separated string — break it into meaningful, readable lines.

Return ONLY a JSON object:
{
  "customer_name": "Lorem Ipsum",
  "total": 1197.13,
  "groups": [
    {
      "name": "Compute",
      "total": 472.0,
      "services": [
        {
          "name": "On Demand Linux t3.medium",
          "service_type": "Virtual Machines",
          "region": "Southeast Asia",
          "cost": 78.69,
          "description": "- 2 x B2als v2 (2 vCPUs, 4 GB RAM)\n- 730 Hours/month (Pay as you go)\n- OS: Linux\n- Disk: 1 managed disk E6, LRS 13 GB\n- Outbound: 5 GB to East Asia"
        }
      ]
    }
  ]
}

RULES:
- Group services by Service category (Compute, Networking, Databases, Storage, DevOps, etc.)
- Service name = Custom name if provided, otherwise Service type
- Description bullet points: extract key specs only — instance size, vCPUs, RAM, hours, storage size, redundancy, tier, key quantities. Skip verbose marketing text.
- Skip any spec where the quantity is 0 (e.g. "0 managed disks", "0 GB outbound", "0 static IPs") — zero values add no information
- Each bullet starts with "- " and MUST be separated by actual newline characters \\n in the JSON string
- Keep descriptions concise — 3-6 bullets per service max
- customer_name = the estimate name from the header row (row 2)
- total = the Total value from the summary rows at the bottom
- Skip rows where Service category is "Support", or where the row contains "Licensing Program", "Billing Account", "Billing Profile", "Disclaimer", or "All prices shown"
- Return ONLY the JSON, no explanation, no markdown"""


AZURE_GROUP_PROMPT = """You are generating service description lines for an Azure pricing proposal table.

Each service has a name, cost, region, and description (already formatted as bullet points).

Output ONLY the service lines for the given group — no <tr> wrapper, no group heading, no totals row.

Format each service as:
ServiceName (ServiceType)<br>
- bullet point<br>
- bullet point<br>
<br>

(blank <br> line between each service)

RULES:
- Use the service name and service type as given
- Output the description bullet points exactly as provided — one per line starting with "- "
- Do NOT add any cost or price values
- No trailing punctuation after service name

Output ONLY the service lines, nothing else."""


AZURE_HTML_WRAPPER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{customer_name} — Azure Consumption Table</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 10pt; margin: 40px; color: #000; background: #fff; }}
  table {{ border-collapse: collapse; width: 680px; table-layout: auto; }}
  th, td {{ border: 1px solid #888; padding: 5px 8px; font-size: 10pt; }}
  th {{ background-color: #0078d4; color: #fff; font-weight: bold; text-align: center; white-space: nowrap; }}
  .col-no {{ width: 50px; }}
  .col-cost {{ width: 110px; }}
  .no-cell {{ text-align: center; vertical-align: top; }}
  .desc-cell {{ vertical-align: top; }}
  .cost-cell {{ text-align: right; vertical-align: top; white-space: nowrap; }}
  .divider td {{ background-color: #0078d4; border: none; height: 10px; padding: 0; }}
  .sum-label {{ text-align: right; }}
  .sum-value {{ text-align: right; white-space: nowrap; }}
  .sum-bold td {{ font-weight: bold; }}
  a {{ color: #0078d4; font-size: 9.5pt; }}
</style>
</head>
<body>
<table>
  <colgroup><col class="col-no"><col><col class="col-cost"></colgroup>
  <tr><th>No</th><th>Description</th><th>Monthly Cost</th></tr>
{rows}
  <tr class="divider"><td colspan="3"></td></tr>
  <tr><td colspan="2" class="sum-label">Total Monthly Cost</td><td class="sum-value">USD {total_monthly}</td></tr>
  <tr><td colspan="2" class="sum-label">Conversion to __CURRENCY__ ( USD 1 - __CURRENCY__ __RATE__ )</td><td class="sum-value">__CURRENCY__ __LOCAL__</td></tr>
  <tr><td colspan="2" class="sum-label">Tax (__TAX_PCT__)</td><td class="sum-value">__CURRENCY__ __TAX__</td></tr>
  <tr class="sum-bold"><td colspan="2" class="sum-label">Total Monthly Payment</td><td class="sum-value">__CURRENCY__ __TOTAL__</td></tr>
</table>
</body>
</html>"""


# ── /api/parse-azure — read xlsx, send to Claude, return structured JSON ──────

def handle_parse_azure(event):
    """Save xlsx to S3, trigger async parse worker, return job_id immediately."""
    try:
        body = json.loads(event.get("body", "{}"))
        xlsx_b64 = body.get("xlsx_b64", "")
        filename = body.get("filename", "estimate.xlsx")
        customer_name_override = body.get("customer_name", "").strip()
        if not xlsx_b64:
            return cors_response(400, json.dumps({"error": "No xlsx data provided"}))

        xlsx_bytes = base64.b64decode(xlsx_b64)
        job_id = uuid.uuid4().hex

        # Save xlsx to S3
        s3_customer = customer_name_override or filename.replace(".xlsx", "")
        content_hash = hashlib.md5(xlsx_bytes).hexdigest()[:12]
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        xlsx_key = f"uploads/azure/{s3_customer}/{timestamp}-{content_hash}.xlsx"
        s3.put_object(Bucket=S3_BUCKET, Key=xlsx_key, Body=xlsx_bytes,
                      ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # Save job meta
        s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json",
            Body=json.dumps({
                "cloud": "azure_parse",
                "xlsx_key": xlsx_key,
                "filename": filename,
                "customer_name": customer_name_override,
                "status": "processing",
            }).encode(), ContentType="application/json")

        # Trigger async worker
        fn_name = os.environ.get("WORKER_FUNCTION", "pricing-table-generator")
        lam.invoke(FunctionName=fn_name, InvocationType="Event",
            Payload=json.dumps({"path": "/__parse-azure", "httpMethod": "POST",
                "body": json.dumps({"job_id": job_id})}).encode())

        return cors_response(200, json.dumps({"job_id": job_id, "status": "processing"}))

    except Exception as e:
        traceback.print_exc()
        return cors_response(500, json.dumps({"error": str(e)}))


def handle_do_parse_azure(event):
    """Async worker: read xlsx from S3, send to Claude, save result."""
    try:
        body = json.loads(event.get("body", "{}"))
        job_id = body["job_id"]

        meta = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json")["Body"].read())
        xlsx_key = meta["xlsx_key"]
        customer_name_override = meta.get("customer_name", "")

        xlsx_bytes = s3.get_object(Bucket=S3_BUCKET, Key=xlsx_key)["Body"].read()
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
        ws = wb.active

        rows_text = []
        for row in ws.iter_rows(values_only=True):
            if any(v is not None for v in row):
                rows_text.append("\t".join(str(v) if v is not None else "" for v in row[:7]))
        text = "\n".join(rows_text)

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 8000,
                "system": AZURE_PARSE_PROMPT,
                "messages": [{"role": "user", "content": text}],
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(response["body"].read())["content"][0]["text"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)

        for g in parsed.get("groups", []):
            g["total"] = sum(s.get("cost", 0) for s in g.get("services", []))
        if customer_name_override:
            parsed["customer_name"] = customer_name_override

        # Save result and mark done
        s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/result.json",
            Body=json.dumps(parsed).encode(), ContentType="application/json")
        s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json",
            Body=json.dumps({**meta, "status": "done"}).encode(), ContentType="application/json")

    except Exception as e:
        traceback.print_exc()
        try:
            meta = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json")["Body"].read())
            s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json",
                Body=json.dumps({**meta, "status": "error", "error": str(e)}).encode(),
                ContentType="application/json")
        except Exception:
            pass
    return cors_response(200, "")


# ── /api/generate-azure ───────────────────────────────────────────────────────
def handle_generate_azure(event):
    try:
        body = json.loads(event.get("body", "{}"))
        groups = body.get("groups", [])
        customer_name = body.get("customer_name", "Customer")
        usd_rate = float(body.get("usd_rate", 4.4))
        currency = body.get("currency", "MYR")

        if not groups:
            return cors_response(400, json.dumps({"error": "No groups provided"}))

        job_id = uuid.uuid4().hex
        total_monthly = sum(g["total"] for g in groups)
        total_local = total_monthly * usd_rate
        tax = total_local * 0.08

        chunks = [{"group_name": g["name"], "chunk_data": g, "is_nested": False, "sub_name": None} for g in groups]
        group_names = [g["name"] for g in groups]

        s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json",
            Body=json.dumps({
                "cloud": "azure",
                "customer_name": customer_name,
                "groups": group_names,
                "chunks": chunks,
                "total_chunks": 0,          # itemised assembly reads chunks directly — no workers needed
                "usd_rate": usd_rate,
                "currency": currency,
                "total_monthly": f"{total_monthly:,.2f}",
                "total_local": f"{total_local:,.2f}",
                "tax": f"{tax:,.2f}",
                "total_with_tax": f"{total_local + tax:,.2f}",
            }).encode(), ContentType="application/json")

        # No Lambda workers — assembly happens synchronously in handle_status
        return cors_response(200, json.dumps({
            "job_id": job_id, "customer_name": customer_name,
            "total_groups": len(groups), "total_chunks": 0,
            "groups": group_names, "status": "processing",
        }))
    except Exception as e:
        traceback.print_exc()
        return cors_response(500, json.dumps({"error": str(e)}))


# ── /__process-azure ──────────────────────────────────────────────────────────

def handle_process_azure(event):
    job_id = None
    chunk_index = 0
    try:
        body = json.loads(event.get("body", "{}"))
        job_id = body["job_id"]
        chunk_index = body["chunk_index"]

        meta = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/meta.json")["Body"].read())
        chunk = meta["chunks"][chunk_index]
        group = chunk["chunk_data"]
        group_name = chunk["group_name"]

        services = group.get("services", [])
        svc_total = group.get("total", 0)
        user_msg = f"""Group: {group_name}
Total: USD {svc_total:,.2f}
Services:
{json.dumps(services, indent=2)}"""

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "system": AZURE_GROUP_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            }),
            contentType="application/json", accept="application/json",
        )
        partial_html = json.loads(response["body"].read())["content"][0]["text"].strip()
        partial_html = re.sub(r"^```html?\s*", "", partial_html)
        partial_html = re.sub(r"\s*```$", "", partial_html)

        s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/chunk_{chunk_index}.json",
            Body=json.dumps({"partial_html": partial_html, "group_name": group_name, "sub_name": None}).encode(),
            ContentType="application/json")

    except Exception as e:
        traceback.print_exc()
        if job_id is not None:
            try:
                s3.put_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/chunk_{chunk_index}.json",
                    Body=json.dumps({"error": str(e)}).encode(), ContentType="application/json")
            except Exception:
                pass
    return cors_response(200, "")


# ── Azure HTML assembly ───────────────────────────────────────────────────────

def assemble_azure_html(meta, groups, chunks, done_chunks):
    currency = meta.get("currency", "MYR")
    tax_pct = "9% GST" if currency == "SGD" else "8% SST"

    # Build group lookup from chunks
    azure_groups = {c["group_name"]: c["chunk_data"] for c in chunks}

    GRP_STYLE = "background-color:#2e96e8;color:#fff;font-weight:bold;"
    rows_html = []
    for row_num, gname in enumerate(groups, 1):
        g = azure_groups.get(gname, {})
        gtotal = float(g.get("total", 0))
        services = g.get("services", [])

        # Group heading row
        rows_html.append(
            f'  <tr>'
            f'<td class="no-cell" style="{GRP_STYLE}">{row_num}.</td>'
            f'<td class="desc-cell" style="{GRP_STYLE}"><b>{gname}</b></td>'
            f'<td class="cost-cell" style="{GRP_STYLE}">USD {gtotal:,.2f}</td>'
            f'</tr>'
        )
        # One row per service
        for svc in services:
            svc_name = svc.get("name", "").strip()
            svc_type = svc.get("service_type", "").strip()
            svc_cost = float(svc.get("cost") or 0)
            display_name = f"{svc_name} ({svc_type})" if svc_type else svc_name
            description = svc.get("description", "")
            props_html = ""
            if description:
                lines = [l.strip() for l in description.split("\n") if l.strip()]
                props_html = "<br>\n".join(lines) + "<br>"
            rows_html.append(
                f'  <tr>'
                f'<td class="no-cell"></td>'
                f'<td class="desc-cell"><b>{display_name}</b><br>\n{props_html}</td>'
                f'<td class="cost-cell">USD {svc_cost:,.2f}</td>'
                f'</tr>'
            )

    html = AZURE_HTML_WRAPPER.format(
        customer_name=meta["customer_name"],
        rows="\n".join(rows_html),
        total_monthly=meta["total_monthly"],
    )
    html = html.replace("__CURRENCY__", currency)
    html = html.replace("__RATE__", str(meta["usd_rate"]))
    html = html.replace("__LOCAL__", meta["total_local"])
    html = html.replace("__TAX_PCT__", tax_pct)
    html = html.replace("__TAX__", meta["tax"])
    html = html.replace("__TOTAL__", meta["total_with_tax"])
    return cors_response(200, json.dumps({
        "status": "done", "html": html,
        "customer_name": meta["customer_name"],
        "total_monthly": meta["total_monthly"],
    }))


# ── CORS ──────────────────────────────────────────────────────────────────────


def cors_response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
        },
        "body": body if isinstance(body, str) else json.dumps(body),
    }
