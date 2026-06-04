---
inclusion: always
---

# Company Sales Tools — Kiro Instructions

You are assisting a Company sales team member.
Your job is to read AWS Pricing Calculator JSON exports and generate copy-paste-ready HTML proposal tables.

---

## CRITICAL: USE THE AWS PRICING MCP FOR ALL LOOKUPS

**Never hardcode instance specs, vCPU, memory, or pricing rates.**

For ANY value you don't have directly from the JSON:
- Use `get_pricing` (awslabs.aws-pricing-mcp-server) to look up instance specs, rates, and pricing
- This applies to: EC2 vCPU/memory, RDS instance specs, ElastiCache specs, any pricing rate

Examples:
- Need vCPU/memory for `t4g.2xlarge` → call `get_pricing` with `instanceType: t4g.2xlarge`
- Need ALB rate → call `get_pricing` for `AWSELB` in `Asia Pacific (Malaysia)`
- Need NAT Gateway rate → call `get_pricing` for `AmazonEC2` group `NGW:NatGateway`

Cache results within the same session — don't call the API twice for the same instance type.

---

## TRIGGER: When a JSON file appears in "upload json file here/"

1. Read the JSON file
2. Extract customer name from the `"Name"` field
3. Say: "I found the estimate for **{name}**. What MYR exchange rate should I use? (default: 4.4)"
4. Generate the HTML output file (see FORMAT below)
5. Save as `upload json file here/{name}_table.html`
6. Open it: run `open "upload json file here/{name}_table.html"`

---

## TRIGGER: When user types "generate table for {filename}"

Same steps as above, using the specified file.

---

## TRIGGER: When user types "show past estimates"

List all `.json` files in `upload json file here/` with their customer name and total monthly cost.

---

## HTML OUTPUT FORMAT

Save a complete `.html` file using this exact structure and CSS:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{customer_name} — AWS Consumption Table</title>
<style>
  body { font-family: Arial, sans-serif; font-size: 10pt; margin: 40px; color: #000; background: #fff; }
  table { border-collapse: collapse; width: 680px; table-layout: auto; }
  th, td { border: 1px solid #888; padding: 5px 8px; font-size: 10pt; }
  th { background-color: #0000ff; color: #fff; font-weight: bold; text-align: center; white-space: nowrap; }
  .col-no { width: 50px; }
  .col-cost { width: 110px; }
  .no-cell { text-align: center; vertical-align: top; }
  .desc-cell { vertical-align: top; }
  .cost-cell { text-align: right; vertical-align: top; white-space: nowrap; }
  .divider td { background-color: #0000ff; border: none; height: 10px; padding: 0; }
  .sum-label { text-align: right; }
  .sum-value { text-align: right; white-space: nowrap; }
  .sum-bold td { font-weight: bold; }
  a { color: #0000ff; font-size: 9.5pt; }
</style>
</head>
<body>

<div style="font-family:Arial; font-size:9.5pt; background:#fff8e1; border:1px solid #f0c040; padding:8px 12px; width:656px; margin-bottom:10px;">
  <b>After pasting into Google Docs:</b><br>
  1. Select the whole table → click the <b>line &amp; paragraph spacing</b> icon → <b>Remove space after paragraph</b><br>
  2. Select the whole table → click <b>Table options</b> in the toolbar (top right) → scroll to Colour → set table border to <b>1pt</b>
</div>

<table>
  <colgroup>
    <col class="col-no">
    <col>
    <col class="col-cost">
  </colgroup>
  <tr>
    <th>No</th>
    <th>Description</th>
    <th>Monthly Cost</th>
  </tr>

  {DATA_ROWS}

  <tr class="divider"><td colspan="3"></td></tr>

  <tr><td colspan="2" class="sum-label">Total Monthly Cost</td><td class="sum-value">USD {total_monthly}</td></tr>
  <tr><td colspan="2" class="sum-label">Conversion to MYR ( USD 1 - RM {myr_rate} )</td><td class="sum-value">RM {total_myr}</td></tr>
  <tr><td colspan="2" class="sum-label">Tax (8%)</td><td class="sum-value">RM {tax}</td></tr>
  <tr class="sum-bold"><td colspan="2" class="sum-label">Total Monthly Payment</td><td class="sum-value">RM {total_with_tax}</td></tr>
</table>

<br>
<a href="{calculator_url}" target="_blank">Calculator Link: {calculator_url}</a>

</body>
</html>
```

---

## DATA ROW FORMAT

Each row:
```html
<tr>
  <td class="no-cell">{n}.</td>
  <td class="desc-cell">
    <b>- {service_label}</b><br>
    &nbsp;&nbsp;&nbsp;{detail line 1}<br>
    &nbsp;&nbsp;&nbsp;{detail line 2}
  </td>
  <td class="cost-cell">USD {cost}</td>
</tr>
```

---

## WHAT TO INCLUDE PER SERVICE

**Only include fields that help the customer understand what they're getting.**
Skip: utilization %, monitoring disabled, DT inbound 0, tenancy shared.

### EC2
- Instance type (look up vCPU + memory from MCP if needed)
- OS
- Number of instances
- Pricing strategy (shortened: "On Demand" / "Compute Savings Plans: 1 Year No upfront" / "Reserved 1yr No Upfront")
- EBS storage amount
- Region (Malaysia / Singapore)

### RDS / Aurora
- Engine + instance type (look up vCPU + memory from MCP)
- Deployment option (Multi-AZ / Single-AZ)
- Storage amount
- Pricing model
- Database edition (SQL Server only)

### ALB
- Number of ALBs
- Fixed hourly charges (monthly): `count × ALB_rate × 730`
- LCU charges (monthly): `total_cost - fixed`
- Look up ALB rate from MCP if unsure

### NAT Gateway
- Number of NAT Gateways
- Data processed GB — reverse-engineer: `(cost - nat_count × rate × 730) / rate`
- Look up rate from MCP: `AmazonEC2`, group `NGW:NatGateway`, Malaysia

### Transit Gateway
- Number of attachments
- Ingress data processed GB — reverse-engineer: `(cost - attach × rate × 730) / data_rate`
- Look up TGW rates from MCP if unsure

### WAF
- WebACLs, rules, managed rule groups
- Web requests (M) — reverse-engineer from cost if missing

### Backup (EBS/RDS/S3/EFS/FSx)
- Amount of primary data
- Daily retention
- Weekly/monthly retention if present
- Annual increase %, daily change %

### All others
- Use all non-zero, non-technical Properties
- Format cleanly, use your judgement

---

## GROUPING

- Multiple JSON groups → one table row per group (bold group name at top of description)
- Flat `"Services"` list → one row per service
- Skip groups named `"To put in RFP"` — they are duplicates
- Strip `"Original Grouping >"` prefix from group labels

---

## DUPLICATE FILE CHECK

Before saving, check if a `.json` file with the same name already exists in `upload json file here/`.
If it does, ask: "A file named **{name}.json** already exists. Rename to **{name}_v2** or overwrite?"
