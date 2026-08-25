# Stonewall Publication Runbook

This runbook describes how to keep the Stonewall showcase surfaces aligned across GitHub Pages, the official brief, the portal demo, and GitBook.

## Principles

1. **Lead with innovation** — every published surface should foreground the platform thesis, not process commentary.
2. **Keep one narrative** — the showcase, official brief, portal, and GitBook should feel like one product argument told in different formats.
3. **Preserve architectural clarity** — the audience should immediately understand content-addressed evidence, citations, retrieval explanations, and the publication gate.
4. **Ship cleanly** — links, counts, and deployment surfaces should stay synchronized so the sendable URL always feels premium.

## Publication Workflow

### 1. Update the narrative surfaces

Refresh these files together whenever the product story evolves:

- `docs/index.html`
- `docs/official-brief.html`
- `docs/portal/index.html`
- `README.md`
- `OFFICIAL_BRIEF.md`

### 2. Keep the messaging aligned

Check that each surface reinforces the same core claims:

- content-addressed evidence bundles
- line-verifiable citations
- explainable retrieval
- exact-tree publication checks

### 3. Verify the deploy surfaces

Confirm these entrypoints all work after changes:

- `/`
- `/official-brief.html`
- `/portal/`
- GitBook landing page

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
