# Company Sales Tools

Generate copy-paste-ready AWS pricing tables for proposals in seconds.

---

## Setup (one time only)

Paste this prompt into Kiro:

```
Clone the repo at https://github.com/g-asiapacific/pricing-table-generator.git, open the folder in the current workspace, then run the setup hook to install the AWS Pricing MCP server.
```

Kiro will clone the repo, open it, and install everything automatically.

---

## How to generate a proposal table

### Step 1 — Export your estimate as JSON
1. Open your [AWS Pricing Calculator](https://calculator.aws) estimate
2. Click **Export** → **JSON**
3. Rename the file to your customer name (e.g. `Ayris Logic.json`)

### Step 2 — Drop the file into Kiro
Drag the JSON file into the **`upload json file here`** folder in Kiro's file explorer.

Kiro will automatically detect it and start generating the table.

### Step 3 — Copy into Google Doc
1. Kiro opens the table in your browser
2. Select all → Copy → Paste into your Google Doc
3. Follow the two clean-up steps shown in the yellow box on the page

---

## Generate a table manually

Type this in Kiro chat:

```
Generate proposal table for [filename].json, MYR rate 4.4
```

Replace `[filename]` with your customer name and adjust the MYR rate if needed.

---

## View past estimates

```
Show me all past estimates
```

---

## Questions?
Contact your SA team lead.
