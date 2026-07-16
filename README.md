# Cloud Pricing Table Converter — Web App

Convert AWS, GCP, and Azure pricing calculator exports into copy-paste-ready HTML proposal tables, powered by Claude Sonnet 4.6, deployed on AWS.

> **Branch guide:**
> - `main` — Kiro-based local tool (runs on your machine via Kiro)
> - `web-app` ← **you are here** — fully hosted web app (CloudFront + Lambda + Bedrock)

---

## Live URL

After running `./deploy.sh`, the CloudFront URL will be printed at the end.

Share this with your team — no install required, works in any browser.

---

## How it works

```
Browser → API Gateway → Lambda → Claude Sonnet 4.6 (Bedrock)
                              ↓
                        S3 (file archive + jobs)
                            ↑
                     CloudFront (frontend)
```

**AWS tab:**
1. Enter customer name + upload AWS Pricing Calculator JSON
2. Press Parse Estimate → preview appears
3. Click Generate Table → Claude processes each group in parallel
4. Open Table in New Tab → Cmd+A → Cmd+C → paste into Google Doc

**GCP tab:**
1. Enter customer name + paste GCP Calculator estimate text
2. Press Parse Estimate → Claude extracts all services
3. Click Generate Table → Claude formats descriptions
4. Open Table in New Tab → paste into Google Doc

**Azure tab:**
1. Enter customer name + upload Azure Calculator `.xlsx` export
2. Press Parse Estimate → Claude reads and formats the estimate
3. Click Generate Table → Claude formats descriptions as bullet points
4. Open Table in New Tab → paste into Google Doc

---

## Deploy your own

Requires AWS CLI with a named profile and Claude Sonnet 4.6 enabled in `us-east-1`.

```bash
cd infra
chmod +x deploy.sh
./deploy.sh
```

**First time setup — set git identity so your real name isn't exposed:**
```bash
git config user.name "YourGitHubUsername"
git config user.email "yourusername@users.noreply.github.com"
```

---

## Project structure

```
cloud-pricing-table-converter/
├── frontend/src/      HTML + CSS + JS (browser UI)
├── backend/           Lambda function (Python, Claude Sonnet 4.6)
├── infra/
│   ├── template.yaml  CloudFormation (Lambda + API GW + S3 + CloudFront)
│   └── deploy.sh      One-command deploy
└── CHANGELOG.md
```

---

## Getting updates

```bash
git pull
AWS_PROFILE=your-profile ./deploy.sh
```

Check `CHANGELOG.md` for what changed.
