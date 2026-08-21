---
name: legal-chapter
description: Generate long-form legal narratives, case analyses, and book-length chapters — saved incrementally to files to avoid truncation. Use when the user asks for a chapter, narrative, analysis, chronicle, or any writing that will exceed ~2000 words.
user_invocable: true
---

# Legal Chapter Writer

Long-form legal narratives get truncated in chat. This skill ensures every word gets saved to disk.

## Rules

1. **NEVER stream long content in chat.** Always write to files.
2. **Max 1500 words per section** before saving to disk and continuing.
3. **Always confirm when saved** — give a 2-3 sentence summary of what was written, not the content itself.

## Process

### Step 1: Gather sources

Ask the user:
> What source files or case materials should I draw from? And what should I title this?

Read all source documents. If there are many, use parallel agents to read them concurrently.

### Step 2: Create an outline

Write an outline with section headers to `./writing/{title}/outline.md`. Show the outline to the user and confirm before proceeding.

### Step 3: Write each section

For each section in the outline:
1. Write the section (max 1500 words)
2. Save immediately to `./writing/{title}/chapter-{NN}.md`
3. Confirm in chat: "Saved section N: [title] — [2-sentence summary]"
4. Continue to the next section

Use TodoWrite to track progress through the outline.

### Step 4: Assemble the final document

After all sections are written:
1. Read each chapter file sequentially
2. Merge them into `./writing/{title}/final-narrative.md` with:
   - A table of contents at the top
   - Consistent formatting throughout
   - A citation index at the end listing all source files referenced
3. Report the final word count and file location

### Output location

All files go to: `./writing/{title}/`

Create the directory if it doesn't exist.

### Style notes

- Use clear, professional legal prose
- For case analyses, include specific citations to source documents (file names, page numbers, timestamps)
- Never use placeholder text — every claim must reference actual source material
