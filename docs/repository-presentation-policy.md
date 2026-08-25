# Repository Presentation Policy

This document keeps the Stonewall showcase repository presentable to visitors, reviewers, and investors. A clean remote branch list and disciplined publication surfaces signal that the team ships with intent.

Public content binding rules live in [`public-content-policy.md`](public-content-policy.md). This document covers repository hygiene.

## Goals

1. **Professional first impression** — anyone opening the GitHub repo sees `main`, active PR branches, and nothing else.
2. **No abandoned agent scratch work** — Copilot, Cursor, and Claude branches merge through PRs or get deleted.
3. **Predictable naming** — branch names describe the change, not inside jokes or session artifacts.

## Branch inventory

At steady state, `origin` should contain:

| Branch | When it exists |
| --- | --- |
| `main` | Always |
| Feature/fix branches | Only while an open PR is in review |

Everything else gets deleted after merge or when the PR closes without merging.

## Branch naming

Use descriptive, lowercase, hyphenated names:

| Prefix | Use for |
| --- | --- |
| `cursor/<topic>-<suffix>` | Cursor Cloud agent work |
| `copilot/<topic>` | GitHub Copilot agent work |
| `claude/<topic>` | Claude agent work |
| `docs-drift/<topic>` | Automated docs-drift PRs |

**Required:** the name must state what changed (`fix-ci-pipeline-errors`, `public-content-policy`).

**Forbidden:** joke names, meme references, session nicknames, or opaque placeholders (`session-0000`, `misc-changes`, `implement-new-feature` with no context).

## Lifecycle

### When opening a PR

1. Branch from current `main`.
2. Use a professional branch name before pushing.
3. Open the PR promptly — do not leave long-lived unpushed or PR-less branches on `origin`.

### When merging a PR

Delete the head branch immediately after merge. GitHub offers this checkbox on merge; use it.

### When closing a PR without merge

Delete the head branch unless you plan to reopen within 48 hours.

### Periodic prune

Run monthly, or whenever the remote branch list looks cluttered:

```bash
git fetch --prune origin

# List branches whose PRs have merged
gh pr list --state merged --limit 100 --json headRefName,mergedAt

# Delete a merged branch manually
git push origin --delete <branch-name>
```

To audit what remains:

```bash
git branch -r
gh pr list --state open
```

Only `main` and branches tied to open PRs should appear in both lists.

## Agent-specific rules

Automated agents (Copilot, Cursor, Claude) must:

- Push only to branches named after the task outcome.
- Open or update a PR in the same session when the work is review-ready.
- Never leave orphan branches on `origin` without an associated open PR.
- Delete their branch after the PR merges.

If an agent session aborts, the operator or the next agent run should delete the orphan branch before starting unrelated work.

## Publication surfaces

Visitor-facing copy, metrics binding, and showcase voice rules are governed separately:

| Document | Covers |
| --- | --- |
| [`public-content-policy.md`](public-content-policy.md) | JSON-backed metrics, no hand-entered counts |
| [`AGENTS.md`](../AGENTS.md) | Showcase voice, banned phrasing, CI procedure |
| [`showcase-repo-handoff.md`](showcase-repo-handoff.md) | Publication workflow and release checklist |

Repository presentation and publication content work together: the repo should look as disciplined as the product story it tells.

## Verification

Before calling a cleanup complete:

- [ ] `git branch -r` shows only `origin/main` plus open-PR branches
- [ ] Every remote branch has a matching open PR (or is `main`)
- [ ] No joke, meme, or opaque branch names remain on `origin`
- [ ] Merged PR branches are deleted on GitHub
