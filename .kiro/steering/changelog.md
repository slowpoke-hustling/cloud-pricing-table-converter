---
inclusion: always
---

# Changelog Rules — Cloud Pricing Table Converter

## File
`CHANGELOG.md` at the repo root.

## When to add an entry
- Code changes to `backend/lambda_function.py` (model, prompt, logic)
- Frontend changes (`frontend/web/`)
- Infrastructure changes (`template.yaml`, `deploy.sh`)
- `.kiro/` config changes (hooks, steering, MCP)
- New feature deployed to AWS

## When NOT to add an entry
- ROADMAP.md edits
- README.md minor fixes
- Local-only changes not deployed

## Versioning
- `vMAJOR.MINOR — YYYY-MM-DD`
- MAJOR: New feature, new cloud provider support, significant restructure
- MINOR: Bug fix, model swap, UI tweak, prompt update

## Format
```markdown
## vX.X — YYYY-MM-DD
**Brief title**
- Bullet point of what changed
- Another bullet point
```

## Current version
Check the top entry in CHANGELOG.md for the current version, then increment appropriately.
