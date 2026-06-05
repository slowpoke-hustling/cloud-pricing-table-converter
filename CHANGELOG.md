# Changelog — Pricing Table Generator

## v1.4 — 2026-06-05
**Skip empty/meaningless fields + percentage formatting**
- Skip `Workload: Consistent` — extract `Number of instances` as a separate line instead
- Skip fields with no actual value (unit labels, blank retention periods, empty data transfer)
- Decimal percentage fields now display as human-readable % (e.g. `0.1` → `10%`, `0.03` → `3%`, `1` → `100%`)
- Applies to: backup increase/change rates, mobile sampling rate, and any decimal % field

## v1.3 — 2026-06-05
**Full copy-paste approach — no reverse engineering**
- Removed all reverse-engineering logic (NAT Gateway, Transit Gateway, ALB, WAF rate calculations)
- MCP usage now scoped strictly to EC2/RDS vCPU + memory lookups only
- All other fields copy directly from JSON with no filtering or calculation
- Removed 20+ per-service field lists that were overriding the copy-paste rule

## v1.2 — 2026-06-05
**README update — manual-first workflow**
- Setup section replaced with single copy-paste Kiro prompt (handles git, uvx, clone automatically)
- Removed misleading "auto-detect" language
- Added xe.com link for MYR rate reference
- Added note that customer files are never committed to git

## v1.1 — 2026-06-05
**Table colour + gitignore hardening**
- Table header colour updated to `#0000ff`
- Gitignore updated to block all customer JSON and HTML from `upload json file here/` folder

## v1.0 — 2026-05-21
**Initial release**
- AWS Pricing Calculator JSON → HTML proposal table
- Supports EC2, RDS, Aurora, ALB, NLB, NAT Gateway, Transit Gateway, VPN, WAF, Fargate, ElastiCache, Backup, S3, CloudWatch, GuardDuty, KMS, CloudTrail, Security Hub, Config, Inspector, Secrets Manager, Lambda, Route 53, and more
- MYR conversion with 8% tax footer
- AWS Pricing MCP integration for EC2/RDS instance specs
- Auto-approve configured for MCP tools
