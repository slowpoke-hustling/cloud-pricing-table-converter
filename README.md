# AWS Sales Pricing Table Generator

Generate copy-paste-ready AWS proposal tables from AWS Pricing Calculator exports in seconds.

---

## First-time setup

You only need **Kiro** installed. Paste this prompt into a **new Kiro chat** and it will handle everything else:

```
Please set up the AWS Pricing Table Generator tool on my machine. Do the following steps in order:

1. Check if git is installed by running `git --version`. If it's not installed, install it using Homebrew (`brew install git`) on Mac or by running `winget install Git.Git` on Windows.
2. Check if uv/uvx is installed by running `uvx --version`. If it's not installed, install it by running `pip install uv`. If pip is also not available, install it via `curl -LsSf https://astral.sh/uv/install.sh | sh` on Mac or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` on Windows.
3. Clone the repo: `git clone git@github.com:ky-workinghard/pricing-table-generator.git`
4. Open the cloned folder in the current workspace.
5. Verify the AWS Pricing MCP server works by calling the get_pricing_service_codes tool. If it fails, tell me what went wrong.

Tell me when everything is ready or flag any step that failed.
```

> The repo is public — no invite needed. Anyone can clone and pull.

---

## How to generate a proposal table

### Step 1 — Export your estimate as JSON
1. Open your [AWS Pricing Calculator](https://calculator.aws) estimate
2. Click **Export** → **JSON**
3. Rename the file to your customer name, e.g. `Customer Name.json`

### Step 2 — Drop the JSON into the upload folder
Place the file inside the **`upload json file here`** folder in this project.

### Step 3 — Ask Kiro to generate the table
In Kiro chat, type:
```
Generate proposal table for Customer Name.json, MYR rate 4.4
```
Replace `Customer Name` with your customer name. Adjust the MYR rate to today's rate if needed — check [xe.com](https://www.xe.com/currencyconverter/convert/?Amount=1&From=USD&To=MYR) for the latest.

Kiro will:
- Read the JSON
- Look up all instance specs and pricing from AWS
- Generate a formatted HTML table
- Open it in your browser automatically

### Step 4 — Copy into your Google Doc
1. In the browser, select all (`Cmd+A`) → Copy (`Cmd+C`)
2. Paste into your Google Doc
3. Follow the two clean-up steps shown in the **yellow box** at the top of the page:
   - Remove space after paragraphs
   - Set table border to 1pt

---

## Other commands

**Check all past estimates in the upload folder:**
```
Show me all past estimates
```

**Regenerate with a different MYR rate:**
```
Generate proposal table for Customer Name.json, MYR rate 4.45
```

---

## Important notes

- **Customer JSON and HTML files are never committed to git** — they stay on your machine only. This is intentional to protect customer data.
- The `upload json file here` folder is just a working area. Clear it out after you're done if you like.
- If you get an MCP error, re-run `run setup` to check your `uvx` installation.

---

## Getting updates

When the tool is updated, pull the latest changes in Kiro chat:

```
Pull the latest updates from git
```

Check `CHANGELOG.md` to see what changed in each version.

---

## Questions?
Contact your SA team lead.
