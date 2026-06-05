---
inclusion: always
---

# AWS Pricing Table Generator — Kiro Instructions

You are assisting a sales team member.
Your job is to read AWS Pricing Calculator JSON exports and generate copy-paste-ready HTML proposal tables.

---

## CRITICAL: USE THE AWS PRICING MCP FOR EC2/RDS INSTANCE SPECS ONLY

The only reason to call the AWS Pricing MCP is to look up **vCPU and memory** for EC2 and RDS instance types, since those specs are not included in the JSON export.

- Need vCPU/memory for `t4g.2xlarge` → call `get_pricing` with `instanceType: t4g.2xlarge`
- Need vCPU/memory for an RDS instance → call `get_pricing` on `AmazonRDS`

Cache results within the same session — don't call the API twice for the same instance type.

**Do NOT use the MCP to look up rates, reverse-engineer costs, or calculate any values. All other data comes directly from the JSON.**

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

**For a flat group (single level)** — one row per group, services listed inside:
```html
<tr>
  <td class="no-cell">{n}.</td>
  <td class="desc-cell">
<b>{Group Name}</b><br>
<br>
{Service Name} - {Description if any}<br>
- {field}: {value}<br>
- {field}: {value}<br>
<br>
{Next Service Name}<br>
- {field}: {value}<br>
  </td>
  <td class="cost-cell">USD {group_total_cost}</td>
</tr>
```

**For a nested group (parent with sub-groups)** — one row for the whole parent, sub-groups numbered inside:
```html
<tr>
  <td class="no-cell">{n}.</td>
  <td class="desc-cell">
<b>{Parent Group Name}</b><br>
<br>
<b>1. {Sub-group Name}</b><br>
<br>
{Service Name}<br>
- {field}: {value}<br>
- {field}: {value}<br>
<br>
{Next Service Name}<br>
- {field}: {value}<br>
<br>
<b>2. {Sub-group Name}</b><br>
<br>
{Service Name}<br>
- {field}: {value}<br>
  </td>
  <td class="cost-cell">USD {group_total_cost}</td>
</tr>
```

**Rules:**
- Service name is plain text (not bold), followed by ` - Description` if the JSON has a Description field
- Each detail line starts with `- ` (dash space)
- A blank `<br>` line separates every service block
- A blank `<br>` line after every numbered sub-group heading
- No `&nbsp;` indentation anywhere
- Sub-group headings are bold: `<b>1. Sub-group Name</b>`

---

## WHAT TO INCLUDE PER SERVICE

**Copy ALL properties from the JSON exactly as they appear.** Skip a field only if its value is:
- Zero / empty / "Not selected" (e.g. `DT Inbound: Not selected: 0 TB per month`)
- Just a unit label with no actual number (e.g. `Management events units: millions`, `Data events units: millions`, `Network activity events units: millions`, `Insight events units: millions`)
- A blank or placeholder value (e.g. `Number of network activity events: per month` — no number present)
- A retention period label with no number (e.g. `Hourly backups warm retention period: Days`)
- `Tenancy: Shared Instances` — adds no value
- `Workload: Consistent` — skip this, BUT extract the `Number of instances` value from it and show it as a separate line: `- Number of instances: X`

**Formatting rules:**
- Decimal percentage fields (values like `0.1`, `0.03`, `0.5`) → multiply by 100 and display as `10%`, `3%`, `50%`
- This applies to: `Estimated annual increase in primary data (%)`, `Estimated daily change of primary data (%)`, `Mobile sampling rate`, and any other field whose name implies a percentage
- `Mobile sampling rate: 1` → `Mobile sampling rate: 100%`

For **EC2 and RDS/Aurora instances**, additionally look up vCPU and memory from the MCP (not in the JSON) and include them after the instance type line.

Pricing strategy: shorten to readable form — `Compute Savings Plans 3yr No Upfront`, `On Demand`, `Reserved 1yr No Upfront`.

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
