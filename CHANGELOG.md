# Changelog — Cloud Pricing Table Converter

## v3.3 — 2026-07-16
**Refactor: standardize folder structure**
- `frontend/web/` renamed to `frontend/src/` — consistent with sa-tools convention
- `template.yaml` and `deploy.sh` moved into `infra/` subfolder
- `deploy.sh` path references updated to use `$SCRIPT_DIR/..` for sibling folders
- README updated to reflect new structure
- No functional changes — AWS deployment unaffected

## v3.2 — 2026-07-10
**Fix: recursive group parsing + hierarchical sub-group numbering**

- Bug fix: groups with 3+ levels of nesting (e.g. `Groups → Workloads → GroupA → SubGroup → Services`) were silently dropped — only 2 levels were traversed
- `collect_services_recursive()` (backend) and `awsCollectServices()` (frontend) now carry the **full path tuple** at any nesting depth, stopping only when they reach a `Services` array
- `split_group_into_chunks()` encodes path tuples as JSON so they survive the S3 round-trip
- Assembly in `handle_status` renders hierarchical headings from path tuples: `1.`, `1.1`, `1.1.1` etc. — services remain unnumbered
- Preview in `awsRenderPreview` mirrors the same structure with indented sub-group headers and service rows
- `OrderedDict` import moved from inline-in-function to top-level imports

## v3.1 — 2026-07-01
**Post-release cleanup, repo rename, Azure polish**
- Azure: zero-value specs skipped in descriptions (e.g. "0 managed disks" no longer shown)
- Azure: async parse uses polling pattern — no more API Gateway timeout on large xlsx files
- Lambda memory increased to 1024MB for faster processing
- Code cleanup: removed dead `awsGroupList`, orphaned CSS block, duplicate GCP listeners
- All inline `import` statements moved to top of `lambda_function.py`
- `*.xlsx` added to `.gitignore` on web-app branch
- Pre-push checklist hook added to workspace
- Repo renamed: `pricing-table-generator` → `cloud-pricing-table-converter`
- Branch renamed: `aws-deployed` → `web-app`
- README updated on both branches — all three providers documented

## v3.0 — 2026-07-01
**GCP + Azure tab support, major parser overhaul, UI polish**

### GCP Tab
- Replaced regex/tokenizer parser with Claude Sonnet 4.6 — no more `FIELD_LABELS` hardcoding
- Async parse flow: `/api/parse-gcp` returns structured JSON in ~5s
- Total cross-checked against `Total estimated cost` line from raw paste
- Customer name field (step 1) shared across all tabs with localStorage history (up to 20 names)
- Parse button disabled until both customer name and paste area are filled
- Invalidates on paste/name change to prevent stale generate

### Azure Tab (new)
- Upload `.xlsx` export from Azure Calculator — Claude extracts and formats descriptions as bullet points
- Async parse: file saved to S3, background Lambda calls Claude, frontend polls `/api/status`
- Service type shown in brackets `(Virtual Machines)` in preview and generated table
- S3 path: `uploads/azure/{customer}/{timestamp}.xlsx`
- `openpyxl` bundled in Lambda zip for xlsx reading

### AWS Tab
- Customer name field added (step 1) — used for S3 path and table header
- Parse button flow: upload file + enter name → press Parse → preview renders
- Customer name passed to backend for S3 path `uploads/aws/{customer}/`

### UI/UX
- Spinning circle replaced with pulsing dots animation (compositor-friendly, doesn't freeze)
- Group processing dots in preview panel
- Customer name datalist — all three tabs share localStorage history
- Tab bottom borders: AWS orange, GCP black, Azure blue — all consistent
- GCP group header border, parse button, generate button all match black theme
- Prompt boxes: AWS orange, GCP black, Azure blue; "Click Here" button stays purple
- Deploy script: auto cache-bust `app.js` and `style.css` per deploy; `style.css` uploaded with `no-cache`

## v2.1 — 2026-06-22
**Repo cleanup + Kiro automation**
- Removed local workflow files: `upload json file here/`, hooks (`json-uploaded.json`, `setup.json`), steering (`sales-tools.md`)
- Cleaned up `.gitignore` — removed stale upload folder patterns
- Added `.kiro/hooks/changelog-reminder.json` — auto-reminds to update CHANGELOG after each session
- Added `.kiro/steering/changelog.md` — documents versioning rules and format
- Updated `README.md` — added git identity setup instructions and AWS_PROFILE usage note

## v2.0 — 2026-06-08
**AWS-deployed web app (web-app branch)**
- New branch `web-app` — fully hosted on AWS (CloudFront + Lambda + API Gateway + S3)
- Single S3 bucket per deployment with prefixes: `frontend/`, `lambda/`, `uploads/`, `jobs/`
- Frontend: SA Agent–style UI with estimate preview (collapsible groups + services), SA Agent–style pricing tab
- Claude Sonnet 4.6 via Bedrock generates the proposal table
- Per-group chunking (max 10 services/call) to avoid API Gateway 29s timeout
- Async job processing: `/api/generate` returns `job_id`, `/api/status` polls for result
- EC2/RDS vCPU + Memory looked up via AWS Pricing API (`pricing:GetProducts`) inside Lambda
- MYR/SGD currency selector with live rate link; SGD uses 9% GST, MYR uses 8% SST
- Upload JSON → instant estimate preview (groups, services, totals) before generating
- "Open Table in New Tab" button activates after generation; visible prompt guides user
- Collapsible group/service chevrons in preview for discoverability
- S3 upload deduplication by MD5 content hash — same content never stored twice
- JSON history stored at `uploads/{customer}/{timestamp}-{hash}.json`
- `deploy.sh` one-command deploy; CloudFormation manages all AWS resources

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
