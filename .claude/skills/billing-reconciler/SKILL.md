---
name: billing-reconciler
description: Reconcile timesheets, prebills, and billing imports for litigation billing workflows
disable-model-invocation: true
---

# Billing Reconciler

Process and reconcile billing files. This skill handles timesheet CSVs, prebill PDFs, and billing system imports.

## File Patterns

Look for these in the OneDrive root and billing folders:
- `Timesheet YYYY-MM-DD *.csv` — raw time entries exported from timekeeping
- `*Prebills*.pdf` — monthly prebill summaries from the firm
- `*_IMPORT_*.csv` — formatted imports for billing system
- `*_nonduplicate_elite_add_set_*.csv` — deduplicated entry sets
- `*net_new_billing_*.csv` — net new entries for a billing period

## Workflow

1. **Read the source files** — identify the timesheet CSVs and any prebill PDFs for the relevant period
2. **Parse and validate** — check for:
   - Duplicate entries (same date + client + description)
   - Missing matter numbers or client codes
   - Entries with 0.0 hours
   - Descriptions that are too short for billing (under 20 chars)
3. **Cross-reference** — if prebills are available, compare timesheet totals against prebill totals by matter
4. **Flag discrepancies** — report any mismatches, missing entries, or suspicious patterns
5. **Generate output** — produce a clean CSV or summary as requested

## Rules

- Always preserve the original files untouched
- Output reconciled files with a clear naming convention: `reconciled_YYYY-MM-DD.csv`
- Round hours to nearest 0.1 per standard billing practice
- Flag but do not auto-delete potential duplicates — let the user decide
