---
name: notion-upload
description: Bulk upload data (CSV, PDF, markdown) to a Notion database with batching and parallel agents. Use when the user wants to upload, import, push, or load data into Notion — especially large datasets (100+ rows).
user_invocable: true
---

# Notion Bulk Upload

Follow this process every time. Do not skip steps.

## Step 1: Confirm the target

Ask the user which Notion database to upload to. The two most common are:
- **Email Correspondence** — for email records, correspondence logs
- **Legal Matters** — for case data, legal matter records

Do NOT guess. If the user says "Notion" without specifying, ask:
> Which Notion database should I upload to — Email Correspondence, Legal Matters, or something else?

## Step 2: Identify source files

Find the source files the user wants to upload. Common formats:
- CSV / XLSX (structured data)
- PDF (extract text first)
- Markdown files

Read a sample of the data to understand the columns/fields.

## Step 3: Validate the schema

Use the Notion MCP `notion-fetch` tool to get the target database schema. Compare source columns against database properties. Map them and show the user:

> Here's how I'll map your data:
> - Column A → Property X
> - Column B → Property Y
>
> Does this look right?

## Step 4: Count and plan batches

Count total rows to upload. Plan batches:
- **Under 50 rows**: Upload directly, no batching needed
- **50-100 rows**: Single batch, one agent
- **100+ rows**: Split into batches of 50 rows each, dispatch parallel agents

Tell the user:
> I have [N] rows to upload. I'll split them into [X] batches of 50 and run them in parallel.

## Step 5: Execute the upload

For each batch, use a parallel Agent that:
1. Takes its assigned chunk of rows
2. Creates Notion pages using `notion-create-pages`
3. Reports success/failure count when done

Use TodoWrite to track each batch.

## Step 6: Report results

After all batches complete:
- Report total successful / failed / skipped
- List any specific errors
- Save a summary log to `./logs/upload-YYYY-MM-DD.md` on OneDrive

If any batch failed, offer to retry just the failed rows with a smaller batch size.
