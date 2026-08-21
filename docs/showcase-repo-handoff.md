# Stonewall Publication Runbook

This runbook describes how to keep the Stonewall showcase surfaces aligned across GitHub Pages, the official brief, and the portal demo.

## Principles

1. **Lead with innovation** — every published surface should foreground the platform thesis, not process commentary.
2. **Keep one narrative** — the showcase, official brief, and portal should feel like one product argument told in different formats.
3. **Preserve architectural clarity** — the audience should immediately understand the flat-file database, CLI layer, AI recall system, workflow sync, verification gates, and portal stack.
4. **Ship cleanly** — links, counts, and deployment surfaces should stay synchronized so the sendable URL always feels premium.

## Publication Workflow

### 1. Update the narrative surfaces

Refresh these files together whenever the product story evolves:

- `docs/index.html`
- `docs/official-brief.html`
- `docs/portal/index.html`
- `README.md`
- `docs/overview/official-brief.md`

### 2. Keep the messaging aligned

Check that each surface reinforces the same core claims:

- flat-file searchable database
- stdlib-only CLI intelligence layer
- AI recall architecture
- automated ingestion pipeline
- multi-platform sync with Notion as operator layer
- verification and QC automation
- phenomenology registry
- static portal deployment
- workflow leverage through DataGavel readiness and live deposition tailoring

### 3. Verify the deploy surfaces

Confirm these entrypoints all work after changes:

- `/`
- `/official-brief.html`
- `/portal/`

### 4. Trigger Pages deployment

Push to `main` and confirm the static Pages workflow completes successfully.

```bash
gh run list --workflow static.yml --limit 5
gh run view <run-id>
```

### 5. Do a language sweep

Before calling the site finished, grep the public copy for drift away from the product thesis.

```bash
python3 scripts/check_showcase_voice.py
```

The script scans publication surfaces and fails on any apologetic or hedging language. The result should be a clean exit on a publishable branch.

## Release Checklist

- [ ] Root showcase URL renders correctly
- [ ] Official brief renders correctly
- [ ] Portal renders correctly
- [ ] Metrics match `docs/site-data.json` (see [`public-content-policy.md`](public-content-policy.md) for field bindings)
- [ ] Product language is consistent across all surfaces
- [ ] No stray archive-language or process-language has crept back into the public story
