# Company Pricing Table Generator

Generate copy-paste-ready AWS proposal tables from AWS Pricing Calculator exports in seconds.

---

## Prerequisites

Before you start, make sure you have:
- **Git** installed — [download here](https://git-scm.com/downloads)
- **Kiro** installed and open
- **`uv` / `uvx`** installed — run this in your terminal:
  ```bash
  pip install uv
  ```
  Or follow the [uv install guide](https://docs.astral.sh/uv/getting-started/installation/)

---

## First-time setup

### 1. Clone the repo
```bash
git clone git@github.com:ky-gap/pricing-table-generator.git
```
> You need to be added as a collaborator first. Contact your SA team lead if you don't have access.

### 2. Open the folder in Kiro
In Kiro: **File → Open Folder** → select the `pricing-table-generator` folder.

### 3. Verify the AWS Pricing MCP is working
In Kiro chat, type:
```
run setup
```
Kiro will check that `uvx` and the AWS Pricing MCP server are reachable. You should see `AWS Pricing MCP ready`.

---

## How to generate a proposal table

### Step 1 — Export your estimate as JSON
1. Open your [AWS Pricing Calculator](https://calculator.aws) estimate
2. Click **Export** → **JSON**
3. Rename the file to your customer name, e.g. `Ayris Logic.json`

### Step 2 — Drop the JSON into the upload folder
Place the file inside the **`upload json file here`** folder in this project.

### Step 3 — Ask Kiro to generate the table
In Kiro chat, type:
```
Generate proposal table for Ayris Logic.json, MYR rate 4.4
```
Replace `Ayris Logic` with your customer name. Adjust the MYR rate to today's rate if needed — check [xe.com](https://www.xe.com/currencyconverter/convert/?Amount=1&From=USD&To=MYR) for the latest.

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
Generate proposal table for Ayris Logic.json, MYR rate 4.45
```

---

## Important notes

- **Customer JSON and HTML files are never committed to git** — they stay on your machine only. This is intentional to protect customer data.
- The `upload json file here` folder is just a working area. Clear it out after you're done if you like.
- If you get an MCP error, re-run `run setup` to check your `uvx` installation.

---

## Questions?
Contact your SA team lead.
