---
name: case-file-finder
description: Locate case files, depositions, and documents across the OneDrive workspace by client name, matter, date, or document type
---

# Case File Finder

Quickly locate documents across the OneDrive workspace.

## Search Strategy

When asked to find a file or case materials:

1. **Parse the request** — extract client name, matter keywords, date range, and document type
2. **Search folders first** — case folders are usually named by client or matter:
   ```
   glob pattern: {ONEDRIVE_ROOT}/*{keyword}*/
   ```
3. **Search files by name** — use multiple patterns:
   ```
   glob: {ONEDRIVE_ROOT}/**/*{keyword}*
   ```
4. **Search file contents** if name search fails — grep for client names, case numbers, or matter descriptions inside .txt and .md files

The OneDrive root is configured via the `ONEDRIVE_PERSONAL_ROOT` and `ONEDRIVE_FIRM_ROOT` environment variables.

## Known Folder Patterns

| Pattern | Contains |
|---------|----------|
| `*depo*`, `*DEPO*` | Deposition transcripts and outlines |
| `*disco*` | Discovery responses |
| `*billing*`, `*Prebills*` | Billing and financial records |
| `*otter_ai*` | Call transcripts from Otter.ai |

## File Naming Conventions

- Depo transcripts: `[Matter] DEPO of [Witness].ext`
- Legal filings: `[Docket#] [Motion Type].pdf/docx`
- Subpoenas: `SDT - [Entity].docx`

## Output

Return a concise list of matching files with full paths, grouped by type (transcripts, filings, billing, etc.). If multiple matches exist, rank by recency (modification date).
