---
name: case-lookup
description: Answer case-specific questions (vehicle holds, last OC contact, trial dates, offer history) by searching Notion and OneDrive in parallel. Use when the user asks about a specific client or case needing a factual answer.
---

# Case Lookup

Answer case questions fast. Search Notion databases and OneDrive case folders in parallel, return the answer, and draft a client email.

## When This Fires

Any question that names a client/case and asks for a fact:
- "when can [client] release the vehicle"
- "last contact with OC on [case]"
- "trial date for [matter]"
- "what was the last offer on [case]"
- "legal hold status on [case]"

## Step 1: Parse the Query

Extract:
- **Client name** (last name or case shorthand)
- **Question type** — classify as one of:
  - `hold_status` — vehicle hold, legal hold, release date
  - `oc_contact` — last contact with opposing counsel
  - `deadline` — trial date, mediation date, discovery cutoff, next deadline
  - `offer` — last demand, last offer, settlement status
  - `general` — anything else about the case

## Step 2: Search in Parallel

Launch parallel searches based on question type. ALWAYS search Legal Matters. Add email/OneDrive searches based on type.

### Always: Legal Matters DB

Database ID: use `NOTION_LEGAL_MATTERS_DB` environment variable

Search by client name in the Case Name or Plaintiff fields. Use `mcp__plugin_notion_notion__notion-search` with the client name, or `mcp__plugin_notion_notion__notion-query-database-view` on the "All Cases" view.

Key fields by question type:
- `hold_status` → **Legal Hold Status**, **Notes**, **Status**, **Phase**
- `oc_contact` → **Opposing Counsel**, **OC Firm**, then go to email search
- `deadline` → **Trial Date**, **Mediation Date**, **Discovery Date**, **CME Deadline**, **Depo Date**, **Next Deadline**
- `offer` → **Specials**, **Reserve**, **Incurred**, **Notes**, **DataGavel Status**
- `general` → Pull all populated fields

### For `oc_contact` and `offer`: All Email DB

Database ID: use `NOTION_ALL_EMAIL_DB` environment variable

Search for emails related to the case. Use `mcp__plugin_notion_notion__notion-search` with the client name to find email pages linked to the case.

For `oc_contact`:
- Look for the OC name (from Legal Matters) in From/To/CC fields
- Sort by Date descending
- Return the most recent 2-3 emails with: Subject, Date, Direction, From

For `offer`:
- Search email subjects containing: offer, demand, settlement, reserve, authority, evaluation
- Sort by Date descending
- Return the most recent matches

### For `offer` and `hold_status`: OneDrive Case Folders

Search OneDrive using case-file-finder patterns with the `ONEDRIVE_FIRM_ROOT` path.

Look for:
- `offer` → demand letters, settlement correspondence, authority requests
- `hold_status` → hold letters, release authorizations, property damage correspondence

File patterns to match:
- `*demand*`, `*offer*`, `*settlement*`, `*authority*`
- `*hold*`, `*release*`, `*property*`, `*vehicle*`

## Step 3: Synthesize the Answer

Present the answer in this format:

```
## [Client Name] — [Question Type]

**Answer:** [The direct factual answer — date, status, amount, or "not found"]

**Sources:**
- Legal Matters: [what was found]
- Email: [most recent relevant email if searched]
- OneDrive: [relevant docs if searched]

---

**Draft client email:**

[Short, professional email the user can paste into Outlook. Address the client by first name.
State the fact. Keep it to 2-3 sentences.]
```

## Step 4: When Info Is Missing

If the answer isn't in Notion or OneDrive, say so clearly:

> "I checked Legal Matters, All Email, and OneDrive for [client]. [Field] is empty / no matching emails found / no matching docs. This might be in the case management system."

Don't guess. Don't fabricate dates or amounts.

## Email Draft Guidelines

- Address client by first name
- Be direct: "The vehicle is still on legal hold" not "I wanted to reach out regarding..."
- Include the specific date/fact they asked about
- If action is needed from the client, state it clearly
- Keep it under 4 sentences
