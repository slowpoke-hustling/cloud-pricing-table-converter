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

**Include all non-zero, non-technical fields.** Skip: utilization %, monitoring disabled, DT inbound 0, tenancy shared, enable monitoring.

### EC2
- Region (Malaysia / Singapore)
- Operating system
- Number of instances
- Advance EC2 instance (type)
- vCPU + Memory (look up from MCP)
- Pricing strategy (short form: "On Demand" / "Compute Savings Plans 1yr No Upfront" / "Compute Savings Plans 3yr No Upfront" / "Reserved 1yr No Upfront")
- EBS Storage amount

### RDS (MySQL / PostgreSQL / MariaDB / SQL Server)
- Instance type (look up vCPU + memory from MCP)
- Deployment option (Multi-AZ / Single-AZ)
- Storage amount
- Pricing strategy
- Database edition (SQL Server only)
- License (SQL Server only)

### Aurora
- Instance type (look up vCPU + memory from MCP)
- Quantity (nodes)
- Storage amount
- Pricing strategy

### ALB
- Number of Application Load Balancers
- Application Load Balancer fixed hourly charges (Monthly): use value from JSON if present
- Application Load Balancer LCU usage charges (Monthly): use value from JSON if present

### NLB
- Number of Network Load Balancers
- Processed bytes per NLB for TCP (if present in JSON)
- Average number of new TCP connections (if present)
- Average TCP connection duration (if present)

### NAT Gateway
- Number of NAT Gateways
- Data Processed per NAT Gateway: use value from JSON if present, otherwise omit

### Transit Gateway
- Number of Transit Gateway attachments
- Ingress data processed per TGW attachment: use value from JSON if present, otherwise omit

### VPN
- Number of Site-to-Site VPN Connections

### WAF
- Number of Web Access Control Lists (Web ACLs) utilized
- Number of Rules added per Web ACL (if present)
- Number of Rule Groups per Web ACL (if present)
- Number of Managed Rule Groups per Web ACL (if present)
- Number of web requests received across all web ACLs (if present in JSON)

### Fargate
- Operating system
- CPU Architecture
- Average duration
- Number of tasks or pods
- Amount of memory allocated
- Amount of ephemeral storage allocated for Amazon ECS

### ElastiCache
- Cache Engine (Redis / Valkey)
- Instance type
- Nodes
- Pricing strategy

### Backup (EBS / RDS / EFS / S3 / FSx)
- Amount of primary data to be backed up
- Estimated annual increase in primary data (as %)
- Estimated daily change of primary data (as %)
- Daily backups warm retention period
- Weekly backups warm retention period (if present)
- Monthly backups warm retention period (if present)

### S3 Standard / Glacier
- S3 Standard storage (or Glacier storage)
- Description/label if present

### EFS
- Desired Storage Capacity

### ECR
- Amount of data stored

### CloudWatch
- Number of Metrics (includes detailed and custom metrics)
- Standard Logs: Data Ingested
- Standard Logs Delivered to CloudWatch Logs (if present)

### GuardDuty
- i) GuardDuty Foundational Threat Detection
  - AWS CloudTrail Management Event Analysis
  - EC2 VPC Flow Log Analysis (if present)
- ii) GuardDuty Malware Protection for EC2 (if EBS scan present)
  - EBS Volume Data Scan Analysis
- iii) Malware Protection for S3 (if present)
  - Total Size of S3 Objects scanned
- iv) RDS Protection (if present)
  - RDS provisioned instance vCPU

### KMS
- Number of customer managed Customer Master Keys (CMK)
- Number of symmetric requests
- Number of RSA GenerateDataKeyPair requests (if present)

### CloudTrail
- Write management trails
- Read management trails (if present)
- S3 trails (if present)
- Lambda trails (if present)

### Security Hub
- Number of Accounts
- Number of Security Checks per Account

### Config
- Number of Continuous Configuration items recorded
- Number of Config rule evaluations

### Inspector
- Average No. of EC2 instances scanned per month
- Average number of Lambda functions scanned in a month (if present)
- Total number of newly pushed container images per month (if present)

### Secrets Manager
- Number of secrets
- Average duration of each secret
- Number of API calls

### Lambda
- Architecture
- Number of requests
- Amount of ephemeral storage allocated

### Step Functions
- Workflow requests
- State transitions per workflow

### Route 53
- Hosted Zones
- Additional Records in Hosted Zones (if present)
- Standard queries (if present)

### ACM
- Number of API calls

### PrivateLink
- Number of VPC Interface endpoints per AWS region

### SNS
- Requests

### SES
- Email messages sent from EC2

### FSx for Windows File Server
- Deployment type
- Desired storage capacity
- Desired aggregate throughput

### Directory Service
- Total number of directories
- Edition

### CloudHSM
- Number of HSMs (hsm1.medium)

### DRS (Elastic Disaster Recovery)
- Number of source servers replicated per month
- Number of disks
- Average change rate on disks per day
- Storage on all disks and all servers

### EKS
- Number of EKS Clusters

### Systems Manager - Parameter Store
- Standard parameters
- Advanced parameters
- Frequency of API interactions per parameter

### Data Transfer
- Outbound Data Transfer to Internet (skip if 0)

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
