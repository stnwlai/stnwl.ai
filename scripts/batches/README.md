# scripts/batches/

This directory holds JSON batch payloads for the Anthropic Batch API processing pipeline.

## Purpose

Large document processing jobs are split into batch files of up to 50 records each,
processed asynchronously via the Anthropic Batch API.

## Workflow

1. **Generate batches** — Run `parse_emails.ps1` to produce `matched_emails.json`
2. **Split batches** — Run `split_batches.ps1`:
   ```powershell
   .\scripts\split_batches.ps1
   ```
3. **Launch batch job** — Run `run_nap_job.ps1`:
   ```powershell
   $env:NOTION_TOKEN = "ntn_xxx"; .\scripts\run_nap_job.ps1
   ```
4. **Check status** — Run `nap_job_status.ps1`
5. **Inspect output** — Run `check_output.ps1`

## Notes

- Batch files (`batch_NNN.json`) are generated at runtime and not committed to the repository
- Add `scripts/batches/*.json` to `.gitignore` to prevent accidental commits of production data
