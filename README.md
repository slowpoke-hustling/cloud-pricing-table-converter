# AWS Pricing Table Generator — Web App (aws-deployed branch)

Upload an AWS Pricing Calculator JSON export → get a copy-paste-ready HTML proposal table, powered by Claude Sonnet 4.6, deployed on AWS.

> **Branch guide:**
> - `main` — Kiro-based local tool (uses Kiro + AWS Pricing MCP, runs on your machine)
> - `aws-deployed` ← **you are here** — fully hosted web app (CloudFront + Lambda + Bedrock)

---

## Live URL

`https://d1k3i0xitygcxs.cloudfront.net`

Share this with your team — no install required, works in any browser.

---

## How it works

```
Browser → API Gateway → Lambda → Claude Sonnet 4.6 (Bedrock)
                              ↓
                        S3 (JSON archive)
                            ↑
                     CloudFront (frontend)
```

1. Upload AWS Pricing Calculator JSON export
2. Estimate preview appears instantly (groups, services, totals)
3. Click **Generate Table** → Claude processes each group in parallel
4. When done, **Open Table in New Tab** button lights up
5. Cmd+A → Cmd+C → paste into Google Doc

---

## Deploy your own

Requires AWS CLI with a named profile and Claude Sonnet 4.6 enabled in `us-east-1`.

```bash
./deploy.sh
```

The script creates all AWS resources and prints the CloudFront URL when done.

---

## Project structure

```
pricing-table-generator/
├── frontend/web/      HTML + CSS + JS (SA Agent style UI)
├── backend/           Lambda function (Python, Claude Sonnet 4.6)
├── template.yaml      CloudFormation (Lambda + API GW + S3 + CloudFront)
├── deploy.sh          One-command deploy
└── CHANGELOG.md
```

---

## Getting updates

```bash
git pull
./deploy.sh
```

Check `CHANGELOG.md` for what changed.
