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
from datetime import datetime

REGION = "us-east-1"
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
S3_BUCKET = os.environ.get("S3_BUCKET", "")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)

# ── Per-group system prompt ───────────────────────────────────────────────────

GROUP_PROMPT = """You are generating service description lines for an AWS pricing proposal table.

Output ONLY the service lines for the given batch — no <tr> wrapper, no group heading, no totals, no cost lines.

Format each service as:
ServiceName - Description<br>
- field: value<br>
- field: value<br>
<br>

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
- Service name is plain text, followed by " - Description" if a description exists
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
        import traceback; traceback.print_exc()
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

def split_group_into_chunks(group_name, group_data):
    """Split a group into chunks of MAX_SERVICES_PER_CHUNK services each."""
    chunks = []

    if "Services" in group_data:
        # Flat group — chunk the services list
        services = group_data["Services"]
        for i in range(0, len(services), MAX_SERVICES_PER_CHUNK):
            chunk_svcs = services[i:i + MAX_SERVICES_PER_CHUNK]
            chunks.append({
                "group_name": group_name,
                "chunk_data": {"Services": chunk_svcs},
                "is_nested": False,
                "sub_name": None,
            })
    elif isinstance(group_data, dict):
        # Nested group — chunk within each sub-group
        for sub_name, sub_data in group_data.items():
            if not isinstance(sub_data, dict):
                continue
            services = sub_data.get("Services", [])
            for i in range(0, len(services), MAX_SERVICES_PER_CHUNK):
                chunk_svcs = services[i:i + MAX_SERVICES_PER_CHUNK]
                chunks.append({
                    "group_name": group_name,
                    "chunk_data": {"Services": chunk_svcs},
                    "is_nested": True,
                    "sub_name": sub_name,
                })
    elif isinstance(group_data, list):
        # Some exports use a list of services directly
        services = group_data
        for i in range(0, len(services), MAX_SERVICES_PER_CHUNK):
            chunk_svcs = services[i:i + MAX_SERVICES_PER_CHUNK]
            chunks.append({
                "group_name": group_name,
                "chunk_data": {"Services": chunk_svcs},
                "is_nested": False,
                "sub_name": None,
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
  .divider td {{ background-color: #0000ff; border: none; height: 10px; padding: 0; }}
  .sum-label {{ text-align: right; }}
  .sum-value {{ text-align: right; white-space: nowrap; }}
  .sum-bold td {{ font-weight: bold; }}
  a {{ color: #0000ff; font-size: 9.5pt; }}
</style>
</head>
<body>
<div style="font-family:Arial; font-size:9.5pt; background:#fff8e1; border:1px solid #f0c040; padding:8px 12px; width:656px; margin-bottom:10px;">
  <b>After pasting into Google Docs:</b><br>
  1. Select the whole table → click the <b>line &amp; paragraph spacing</b> icon → <b>Remove space after paragraph</b><br>
  2. Select the whole table → click <b>Table options</b> in the toolbar (top right) → scroll to Colour → set table border to <b>1pt</b>
</div>
<table>
  <colgroup><col class="col-no"><col><col class="col-cost"></colgroup>
  <tr><th>No</th><th>Description</th><th>Monthly Cost</th></tr>
{rows}
  <tr class="divider"><td colspan="3"></td></tr>
  <tr><td colspan="2" class="sum-label">Total Monthly Cost</td><td class="sum-value">USD {total_monthly}</td></tr>
  <tr><td colspan="2" class="sum-label">Conversion to MYR ( USD 1 - RM {myr_rate} )</td><td class="sum-value">RM {total_myr}</td></tr>
  <tr><td colspan="2" class="sum-label">Tax (8%)</td><td class="sum-value">RM {tax}</td></tr>
  <tr class="sum-bold"><td colspan="2" class="sum-label">Total Monthly Payment</td><td class="sum-value">RM {total_with_tax}</td></tr>
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
    if path == "/api/generate":
        return handle_generate(event)
    if path == "/api/status":
        return handle_status(event)
    if path == "/__process":
        return handle_process(event)
    return cors_response(404, json.dumps({"error": f"Not found: {path}"}))


# ── /api/generate — save job, trigger all group workers async ─────────────────

def handle_generate(event):
    try:
        body = json.loads(event.get("body", "{}"))
        json_input = body.get("json", "")
        myr_rate = float(body.get("myr_rate", 4.4))

        data = json_input if isinstance(json_input, dict) else json.loads(json_input)
        if "Groups" not in data or "Total Cost" not in data:
            return cors_response(400, json.dumps({"error": "Not a valid AWS Pricing Calculator export"}))

        customer_name = data.get("Name", "Customer")
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
                key = f"uploads/{customer_name}/{timestamp}-{content_hash}.json"

                # Check if identical content already exists
                existing = s3.list_objects_v2(
                    Bucket=S3_BUCKET,
                    Prefix=f"uploads/{customer_name}/",
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

        # Save job metadata
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"jobs/{job_id}/meta.json",
            Body=json.dumps({
                "customer_name": customer_name,
                "groups": groups,
                "chunks": chunks,
                "total_chunks": len(chunks),
                "myr_rate": myr_rate,
                "total_monthly": f"{total_monthly:,.2f}",
                "total_myr": f"{total_myr:,.2f}",
                "tax": f"{tax:,.2f}",
                "total_with_tax": f"{total_myr + tax:,.2f}",
                "calc_url": calc_url,
            }).encode(),
            ContentType="application/json",
        )

        # Save full data for workers
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"jobs/{job_id}/input.json",
            Body=json.dumps({"data": data, "myr_rate": myr_rate}).encode(),
            ContentType="application/json",
        )

        # Trigger one worker per chunk (all async, run in parallel)
        fn_name = os.environ.get("WORKER_FUNCTION", "pricing-table-generator")
        for i, chunk in enumerate(chunks):
            lam.invoke(
                FunctionName=fn_name,
                InvocationType="Event",
                Payload=json.dumps({
                    "path": "/__process",
                    "httpMethod": "POST",
                    "body": json.dumps({
                        "job_id": job_id,
                        "chunk_index": i,
                    }),
                }).encode(),
            )

        return cors_response(200, json.dumps({
            "job_id": job_id,
            "customer_name": customer_name,
            "total_groups": len(groups),
            "total_chunks": len(chunks),
            "groups": groups,
            "status": "processing",
        }))

    except Exception as e:
        import traceback; traceback.print_exc()
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

        # All chunks done — reassemble into group rows
        # Group chunks by group_name, maintaining order
        group_html_parts = {}  # group_name -> {sub_name -> [html_parts]}
        for i in range(total_chunks):
            chunk = chunks[i]
            result = done_chunks[i]
            gname = chunk["group_name"]
            sub_name = chunk.get("sub_name")
            is_nested = chunk.get("is_nested", False)
            partial = result.get("partial_html", "")

            if gname not in group_html_parts:
                group_html_parts[gname] = {"is_nested": is_nested, "parts": {}}
            key = sub_name if sub_name else "__flat__"
            if key not in group_html_parts[gname]["parts"]:
                group_html_parts[gname]["parts"][key] = []
            group_html_parts[gname]["parts"][key].append(partial)

        # Build final rows in group order
        rows_html = []
        for row_num, gname in enumerate(groups, 1):
            if gname not in group_html_parts:
                continue
            ginfo = group_html_parts[gname]
            is_nested = ginfo["is_nested"]
            parts = ginfo["parts"]
            clean_name = re.sub(r"^Original Grouping\s*>\s*", "", gname).strip()

            # Calculate group total from input
            inp = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"jobs/{job_id}/input.json")["Body"].read())
            gdata = inp["data"]["Groups"].get(gname, {})
            if isinstance(gdata, list):
                gdata = {"Services": gdata}
            if "Services" in gdata:
                gtotal = sum(float(s["Service Cost"]["monthly"]) for s in gdata["Services"])
            else:
                gtotal = sum(float(s["Service Cost"]["monthly"]) for sd in gdata.values() if isinstance(sd, dict) for s in sd.get("Services", []))

            if not is_nested:
                # Flat group — join all partial htmls
                inner = "\n".join(parts.get("__flat__", []))
                rows_html.append(f'  <tr>\n    <td class="no-cell">{row_num}.</td>\n    <td class="desc-cell">\n<b>{clean_name}</b><br>\n<br>\n{inner}\n    </td>\n    <td class="cost-cell">USD {gtotal:,.2f}</td>\n  </tr>')
            else:
                # Nested group — wrap sub-groups with numbered headings
                inner_parts = []
                for sub_num, (sub_name, sub_parts) in enumerate(parts.items(), 1):
                    clean_sub = re.sub(r"^Original Grouping\s*>\s*", "", sub_name).strip()
                    inner_parts.append(f"<b>{sub_num}. {clean_sub}</b><br>\n<br>\n" + "\n".join(sub_parts))
                inner = "\n<br>\n".join(inner_parts)
                rows_html.append(f'  <tr>\n    <td class="no-cell">{row_num}.</td>\n    <td class="desc-cell">\n<b>{clean_name}</b><br>\n<br>\n{inner}\n    </td>\n    <td class="cost-cell">USD {gtotal:,.2f}</td>\n  </tr>')

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

        return cors_response(200, json.dumps({
            "status": "done",
            "html": html,
            "customer_name": meta["customer_name"],
            "total_monthly": meta["total_monthly"],
            "total_myr": meta["total_myr"],
        }))

    except Exception as e:
        import traceback; traceback.print_exc()
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
        import traceback; traceback.print_exc()
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


# ── CORS ──────────────────────────────────────────────────────────────────────

def cors_response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
        },
        "body": body if isinstance(body, str) else json.dumps(body),
    }
