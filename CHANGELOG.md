# Changelog — Cloud Pricing Table Converter

## v3.8 — 2026-08-03
**Frontend payload cut 95% (403KB → 20.5KB), cache-busting fixed, accessibility and polish pass**

### Performance
- **Logos were shipping at full source resolution.** `azure-logo.png` was 3840×2160 (287KB) and `aws-logo.png` 2400×2400 (41KB), both rendered at 20px tall. Resized to 2× display size for retina: 334KB → 4.8KB combined
- **CloudFront compression was off.** Set `Compress: true` — `app.js` 48KB → 9.5KB, `style.css` 12.5KB → 4KB, `index.html` 15.9KB → 2.8KB
- **`app.js` was uploaded as `application/octet-stream`**, which CloudFront refuses to compress. `deploy.sh` set an explicit Content-Type for `index.html` and `style.css` but not `app.js`. Now sets `application/javascript`
- Net first-load transfer: **403.2 KB → 20.5 KB (94.9% smaller)**

### Bugs fixed
- **Cache-busting never worked.** `index.html` requests `app.js?v={deploy_ts}` but CloudFront had `ForwardedValues.QueryString: false`, so the param was stripped and the stale cached copy served. This is why every deploy needed a manual invalidation and a hard refresh. Now forwards the query string, so a new deploy timestamp fetches fresh JS automatically
- Cache headers rationalised: logos `max-age=31536000` (immutable), CSS/JS `max-age=300`, `index.html` `no-cache` since it carries the version pointer

### Accessibility
- Added `:focus-visible` outline on all interactive elements — the app was previously unusable by keyboard, with no visible focus indicator anywhere
- Added `@media (prefers-reduced-motion: reduce)` — disables all transitions and the spinner animations for users who have motion sensitivity configured at OS level

### Visual
- `style.css` — added `--shadow-sm/md/lg` and `--t-fast/base` motion tokens so elevation and timing are consistent rather than ad-hoc per rule
- Buttons: subtle shadow, lift on hover, 1px press displacement
- Upload area: scales slightly and glows on `dragover`, icon lifts on hover — the drop target was previously hard to distinguish from hover state
- "Get Your Table" button pulses twice when it becomes ready, then settles
- Preview rows: full-row hover tint instead of text-colour-only, so the click target is obvious; costs use `tabular-nums` so digits align in a column
- Preview group cards: 8px radius and hover elevation
- Sign-in card: larger shadow, subtle entrance animation
- Scrollbars: 5px → 8px with inset padding and hover state (5px was hard to grab)
**Security hardening, CORS fixes, unified table colours, and 418 lines of dead code removed**

### Security
- `lambda_function.py` — **critical gap closed**: `/api/*` endpoints had no server-side auth. The frontend sent the Bearer token but the backend ignored it, leaving Bedrock and S3 callable by anyone with the API URL. Added `require_auth()` to the router; all public routes now verify the Google ID token and email domain before executing
- `lambda_function.py`, `auth_handler.py` — token verification result cached in Lambda memory keyed by `sha256(token)`, expiring with the token's own `exp` claim. Cuts ~250ms off every request after the first; only the hashed token and email are held, never the raw token
- Removed all company, customer, and personal identifiers from source: company domain and name, two customer project names used as code-comment examples, and hardcoded domain defaults (now empty — must be supplied via `ALLOWED_DOMAIN` at deploy time)
- Rewrote all 53 commits with `git filter-repo` to purge the same identifiers plus AWS account ID, CloudFront ID, API Gateway ID, and Google OAuth client ID from history, then force-pushed both branches
- `.gitignore` — added `*.pdf`, `*.csv`, `.env*`, `*.pem`, `*.key`, `uploads/`, `jobs/`; untracked `.kiro/settings/mcp.json`
- Deleted 134 stale `jobs/` folders from S3 (temp processing files containing full pricing JSON)

### Bugs fixed
- CORS preflight rejected `Authorization` — fixed in **two** places that both needed it: the API Gateway MOCK `OPTIONS` integrations (all six routes) and the Lambda's own `cors_response()` headers. Missing either one blocks the request
- `deploy.sh` — CloudFormation updated API Gateway method configs but never published them, so the stage kept serving a stale deployment. Added a forced `create-deployment` after every CF deploy
- `app.js` — `apiFetch` reported genuine network failures and expired tokens both as "Failed to fetch". Now distinguishes them and auto-signs-out on 401/403 with a clear message
- `deploy.sh` — template hash used `md5`/`md5sum`, neither reliably on PATH; switched to Python hashlib

### Changed
- GCP and Azure generated tables now use the same `#0000ff` scheme as AWS throughout — column header, group heading rows, divider, and footer links. Previously each cloud used its own brand blue, and group rows were indistinguishable from the column header
- GCP and Azure `generate` no longer dispatch Lambda workers (`total_chunks=0`), matching AWS. Assembly is synchronous; this also stops wasted Bedrock calls whose output was discarded
- First status poll reduced 3000ms → 500ms, so tables appear near-instantly
- Status text for GCP/Azure changed from "Claude is processing…" to "Building table…" (no longer accurate)

### Removed
Since v3.5/v3.6 moved all three clouds to direct itemised assembly, the Claude per-chunk worker pipeline became unreachable:

- `GROUP_PROMPT`, `GCP_GROUP_PROMPT`, `AZURE_GROUP_PROMPT` — Claude table-generation prompts
- `handle_process`, `handle_process_gcp`, `handle_process_azure` — async chunk workers, never invoked
- `get_ec2_specs`, `enrich_services_with_specs`, `_spec_cache` — EC2 vCPU/memory lookup, only used by the removed AWS worker
- `split_group_into_chunks`, `MAX_SERVICES_PER_CHUNK` — chunking logic whose output was discarded
- `OrderedDict` import — only used by removed chunking code
- `handle_status` chunk-polling loop and `done_chunks` bookkeeping — `total_chunks` is always 0 now
- `assemble_gcp_html` / `assemble_azure_html` — dropped unused `done_chunks` parameter
- Router simplified: only `/__parse-azure` remains internal (Azure xlsx still needs Claude to read the file)
- `style.css` — dead `.avatar` class and unused `@keyframes spin`

Lambda: 1523 → 1105 lines (27% smaller). No functional change — all six API endpoints plus `/auth/check` verified returning correct responses, no import errors in CloudWatch.

### Known / deferred
- Lambda still at 512MB. The Pricing API lookups are gone entirely, and Claude no longer generates tables — but Claude is **still used for parsing** (`handle_parse_gcp` on pasted text, `handle_do_parse_azure` on xlsx). Before dropping to 256MB, test `handle_do_parse_azure`: it loads the whole workbook via `openpyxl` before calling Claude, making it the most memory-hungry path in the app
- `openpyxl` reinstalled on every deploy (~15s, 286KB zip); a Lambda Layer would fix both
- No S3 lifecycle rule on `jobs/` — temp files will accumulate again

## v3.6 — 2026-08-03
**Google Sign-In auth + GCP/Azure itemised layout**

### Auth (Task 1)
- Added Google Sign-In (GSI) gate — only `@company-domain.com` accounts can access the tool
- New `auth_handler.py` Lambda: verifies Google ID token via tokeninfo endpoint, checks email domain
- New `/auth/check` API Gateway route backed by `pricing-table-generator-auth` Lambda
- `index.html`: sign-in screen with GSI button shown before app; `app` div hidden until authenticated
- `app.js`: `onGoogleSignIn` callback, `showApp`/`signOut`, session restored from `sessionStorage` on reload
- All API calls now include `Authorization: Bearer {id_token}` header via `apiFetch`/`apiPost`/`apiGet`
- `deploy.sh`: packages `auth_handler.py` as separate zip, injects `GOOGLE_CLIENT_ID` into frontend + Lambda env
- `template.yaml`: new `GoogleClientId` + `AllowedDomain` parameters, `AuthFunction`, `AuthPermission`, `/auth/check` API resources
- No DynamoDB allowlist needed — domain check is stateless

### GCP/Azure itemised layout (Task 2)
- GCP generated table: one row per group (blue `#1a73e8` header) + one row per service with individual cost and fields
- Azure generated table: one row per group (blue `#0078d4` header) + one row per service with `name (service_type)`, description bullets, individual cost
- Both skip Claude workers for assembly — reads directly from `chunks` data in meta
- Yellow "After pasting into Google Docs" advisory box removed from GCP and Azure HTML wrappers

## v3.5 — 2026-07-20
**Itemised table layout — one row per service with individual prices**

- Table output changed from "one row per group with services packed in a cell" to itemised layout:
  - Top-level group → shaded header row (`#0000ff`) with group total and row number
  - Sub-group headings → 5-stop blue gradient by nesting depth (`#2260ff` → `#598eff` → `#8fb6ff` → `#c6dbff`), all white text
  - Same depth = same colour (e.g. `ICT pricing` and `AWS pricing non-related` at depth 1 both get `#2260ff`)
  - Each service → individual white row with name, formatted properties, and individual monthly cost; no indent
- `collect_services_recursive` (backend) and `awsCollectServices` (frontend) fixed: was stopping when it hit a `Services` key, now collects flat services first then continues into sibling sub-groups — fixes year groups showing only top-level EC2s
- Property formatting done in Python directly — no Claude workers dispatched, table ready instantly on first poll
  - Skips: Tenancy, Region, zero/empty/not-selected fields, unit-only labels
  - Converts decimal percentages (0.03 → 3%)
  - Extracts `Number of instances` from Workload field
  - Shortens pricing strategy names (e.g. `Amazon EC2 Instance Savings Plans 3yr No Upfront` → `EC2 Savings Plans 3yr No Upfront`)
- `handle_generate` sets `total_chunks=0`, no Lambda workers invoked — assembly runs in `handle_status` synchronously
- "After pasting into Google Docs" yellow advisory box removed from table output
- Dead layout-toggle listener removed from `app.js` (toggle was reverted, listener remained)

## v3.4 — 2026-07-20
**Fix: sibling sub-groups silently dropped when top-level Services array present**

- Bug: `collect_services_recursive()` stopped recursing as soon as it found a `"Services"` key in a dict — any sibling sub-group keys at the same level (e.g. `"AWS pricing non-related to inventory list"`, `"ICT pricing"`) were never visited and their services were lost
- Fix: function now always collects the flat `"Services"` array first, then continues to recurse into every other sibling key — both are processed in a single pass
- Affected JSON shape: groups that mix a root-level `Services` array with named sibling sub-groups (e.g. Y1/Y2 year groups with direct EC2 entries alongside separate sub-group sections)

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
