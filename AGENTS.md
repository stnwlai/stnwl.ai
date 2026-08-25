# Repository Guide

## Scope

This repository contains one executable engineering reference. Keep it limited
to four contracts: content-addressed evidence, line-verifiable citations,
explainable BM25 retrieval, and a fail-closed publication boundary.

`README.md` is the only narrative surface. Do not add a Pages site, portal,
archive mirror, product brief, operational runbook, integration sample, agent
configuration, or production architecture.

## Commands

Run the full gate before opening or updating a pull request:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py"
PYTHONPATH=src python3 -m stonewall build --output build/reference
PYTHONPATH=src python3 -m stonewall verify --output build/reference
PYTHONPATH=src python3 scripts/check_public_boundary.py
```

Refresh `public-tree-manifest.json` only after every other edit:

```bash
PYTHONPATH=src python3 scripts/check_public_boundary.py --write-manifest
PYTHONPATH=src python3 scripts/check_public_boundary.py
```

## Change rules

- Keep source and tests dependency-free unless a dependency is essential to one
  of the four contracts.
- Use 4-space indentation, type annotations, and deterministic ordering.
- Preserve coded IDs and the `id`, `type`, `date` corpus metadata contract.
- Never commit credentials, personal information, environment-specific paths,
  generated bundles, caches, or local reports.
- Add or change a corpus record only when a focused test needs the case.
- Treat manifest drift as a review requirement, not as a formatting chore.
- Keep the remote to `main` plus branches with open pull requests; delete merged
  branches.
