# Stonewall

**Legal document intelligence for litigation teams that move fast.**

Stonewall turns scattered emails, pleadings, medical records, deposition material,
spreadsheets, and notes into a searchable, validated, AI-ready litigation corpus.

[![Stonewall Home](https://img.shields.io/badge/Home-stnwl.ai-c96b3c?style=for-the-badge)](https://www.stnwl.ai/)
[![Organization](https://img.shields.io/badge/GitHub-stnwlai-111827?style=for-the-badge&logo=github)](https://github.com/stnwlai)
[![Verify](https://img.shields.io/badge/CI-verify.yml-2088ff?style=for-the-badge&logo=githubactions&logoColor=white)](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square)](#stack)
[![Node](https://img.shields.io/badge/Node.js-22-5fa04e?style=flat-square)](#stack)
[![Notion API](https://img.shields.io/badge/Notion-API-000000?style=flat-square)](#stack)

---

## The pitch

Law firms do not need another document dump.

They need a command surface that answers:

- What changed?
- What matters now?
- What deadlines are moving?
- Which documents support the next filing, deposition, demand, or client update?
- Which facts are verified, and which still need QC?

Stonewall is that layer.

---

## What it does

| Surface | Outcome |
| --- | ---: |
| **Ingestion** | Pulls OneDrive, Outlook, PDF, DOCX, XLSX, CSV, EML, MSG, TXT, HTML, XML, and ZIP material into a normalized corpus. |
| **Classification** | Extracts dates, parties, claim numbers, document types, matter links, and workflow signals. |
| **Notion Sync** | Turns case data into an operator-facing matter board with dates, status, links, and review queues. |
| **AI Review** | Uses Claude and OpenAI workflows for summarization, classification, recall, and tactical drafting support. |
| **QC Automation** | Runs validation sweeps so bad metadata, missing links, and drift are visible before they become liability. |
| **Publication** | Ships polished static surfaces for demos, briefs, portal views, and stakeholder review. |

---

## Why it wins

- **Built for litigation reality.** Messy exports, late records, fragmented folders, and deadline pressure are first-class design constraints.
- **Operator-first.** The platform is not just storage. It stages the next move.
- **AI with guardrails.** Structured sidecars, source links, validation, and review queues keep outputs traceable.
- **Static where possible. Automated where useful.** Fast to deploy, easy to inspect, hard to break.
- **Commercially legible.** Home, showcase, portal, and official brief all tell one clean product story.

---

## Proof points

Headline metrics bind to [`docs/site-data.json`](docs/site-data.json) — see the
[public content policy](docs/public-content-policy.md).

| Metric | Scale |
| --- | ---: |
| Artifacts cataloged | 1,887 |
| Active matters represented | 64 |
| Behavioral patterns indexed | 197 |
| Emails processed | 6,000+ |
| Artifact classes | 23 |
| Verification suite | 800 tests |

---

## Product surfaces

- **[Stonewall home](https://www.stnwl.ai/)** — the canonical public product narrative, live.
- **[Official brief](docs/overview/official-brief.md)** — the product thesis in long form.
- **[Operator portal demo](docs/portal/)** — the static command-cockpit exhibit with JSON data snapshots.
- **[Architecture](docs/ARCHITECTURE.md)** — the engineering-grade walkthrough of every layer.
- **[Reference corpus](hoss-stonewall/sample_corpus/)** — a deterministic, generator-built corpus that exercises ingest, classification, and verification end to end.

---

## Architecture

```text
OneDrive / Outlook / Case Files
            |
            v
      Ingestion Pipeline
            |
            v
  Parsing + Markdown Sidecars
            |
            v
 Classification + AI Review
            |
            v
      Notion Operator Layer
            |
            v
 QC Reports + Static Showcase
```

The system favors inspectable files, repeatable scripts, environment-based configuration,
and CI-visible checks over opaque one-off automation.

---

## Quickstart

The exact sequence CI runs on every push (`.github/workflows/verify.yml`):

```bash
node --test tests/tracker_helpers.test.mjs tests/email_consolidator.test.mjs
python3 -m unittest discover -s tests -p "test_*.py"
python3 scripts/check_showcase_voice.py
python3 scripts/verify_repo_consistency.py
python3 scripts/repo_sweep.py
```

There is no `package.json` or `requirements.txt` — the Node scripts are
zero-dependency ESM, and Python scripts that need extraction libraries take them
at runtime via `uv run --with <pkg>`. Copy `.env.example` to `.env` before
running anything that talks to Notion or OneDrive.

---

## Stack

| Layer | Tools |
| --- | --- |
| Runtime | Python 3.12, Node.js 22, PowerShell 7+ |
| Package management | `uv` (runtime dependency injection) |
| AI | Anthropic Claude API, OpenAI API |
| Case management | Notion API |
| Storage | Microsoft OneDrive |
| Automation | GitHub Actions |
| Delivery | Static HTML on Pages |

---

## Repository map

```text
.
├── docs/                     # showcase site, product docs, and operator portal
│   ├── overview/             # official brief, product architecture, workflow surfaces
│   ├── showcase/             # engineering-exhibit narratives
│   └── portal/               # portal demo app and JSON data snapshots
├── hoss-stonewall/
│   └── sample_corpus/        # deterministic reference corpus, verified in CI
├── scripts/                  # ingestion, sync, QC, and reporting automation
├── agents/                   # AI agent configuration
├── tests/                    # Node + Python verification suites
├── archive/                  # durable narrative edition of the showcase
├── .github/workflows/        # CI/CD pipelines
└── .env.example              # every required environment variable, documented
```

---

## Security posture

- Credentials are never committed. API tokens, database IDs, and file paths load
  from environment variables; `.env.example` documents every knob.
- The verification workflow runs the full test suite, voice guard, consistency
  check, and hygiene sweep on every push.
- Sync operations are idempotent and rate-limit aware by design.

---

## Bottom line

**Stonewall converts litigation chaos into operational leverage.**

It is the control plane between the document mess and the legal move that wins the day.
