import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.tactical_brief import (
    build_case_matchers,
    build_upcoming_items,
    gather_uncataloged_by_case,
    parse_case_records,
    parse_case_sections,
    parse_manifest_rows,
    render_case,
    render_today,
    resolve_case_heading,
)


class TacticalBriefTests(unittest.TestCase):
    def test_parse_manifest_rows_handles_summary_with_pipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.md"
            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/transcripts/test.md | transcript | 2026-03-24 | Attorney | — | Smith | INSURER Policy# POLXXXXXXXX | Claim# CLMXXXXXXXXXX | no |",
                    ]
                ),
                encoding="utf-8",
            )

            rows = parse_manifest_rows(manifest_path)
            self.assertEqual(len(rows), 1)
            self.assertIn("Claim# CLMXXXXXXXXXX", rows[0].summary)

    def test_case_render_surfaces_priority_upcoming_and_intake(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest_path = root / "manifest.md"
            case_md_path = root / "index_by_case.md"
            case_dates_path = root / "case_dates.json"
            report_path = root / "report.json"

            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/transcripts/matter_alpha_call.md | transcript | 2026-03-24 | Attorney | — | Smith | Smith call with OC on corp rep date and mediation. | no |",
                        "| A002 | sources/transcripts/matter_beta.md | transcript | 2026-03-10 | Attorney | — | Jones | Jones scheduling update. | no |",
                    ]
                ),
                encoding="utf-8",
            )
            case_md_path.write_text(
                "\n".join(
                    [
                        "# Cases",
                        "",
                        "## SMITH",
                        "- **Case No.**: 2025-CA-012345 SC",
                        "- **OC**: Opposing Counsel LLC",
                        "- **Mediation**: Scheduled 4/7/26 with Mediator; start time TBD",
                        "- **Key Discovery**:",
                        "  - Corp rep depo: OC demanded name + dates by Monday 5 PM or Motion to Compel",
                        "  - SDTs are out",
                        "- **Artifacts**:",
                        "  - A001 — Smith call transcript",
                        "",
                        "## JONES",
                        "- **OC**: Defense Counsel PC",
                    ]
                ),
                encoding="utf-8",
            )
            case_dates_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Smith v. Acme Corp",
                            "claim": "CL12345AB",
                            "reserve": "$1,000,000",
                            "incurred": "$1,234,567",
                            "depo_date": "",
                            "disco_date": "",
                            "complaint_filed": "",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "uncataloged_canonical_sources": [
                            "sources/teams_screenshots/smith rog verification 3.20.26.md",
                            "sources/teams_screenshots/matter beta update.md",
                        ]
                    }
                ),
                encoding="utf-8",
            )

            artifacts = parse_manifest_rows(manifest_path)
            records = parse_case_records(case_dates_path)
            sections = parse_case_sections(case_md_path)
            matchers = build_case_matchers(sections, records)
            report = json.loads(report_path.read_text(encoding="utf-8"))

            output = render_case(
                query="smith",
                artifacts=artifacts,
                sections=sections,
                matchers=matchers,
                report=report,
                reference_date=date(2026, 3, 25),
                recent_limit=5,
            )

            self.assertIn("Case Brief — SMITH", output)
            self.assertIn("Claim: CL12345AB", output)
            self.assertIn("Corp rep depo: OC demanded name + dates by Monday 5 PM or Motion to Compel", output)
            self.assertIn("2026-04-07", output)
            self.assertIn("sources/teams_screenshots/smith rog verification 3.20.26.md", output)

    def test_today_render_groups_recent_heat_upcoming_and_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest_path = root / "manifest.md"
            case_md_path = root / "index_by_case.md"
            case_dates_path = root / "case_dates.json"

            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/transcripts/matter_alpha_call.md | transcript | 2026-03-24 | Attorney | — | Smith | Smith call with OC. | no |",
                        "| A002 | sources/transcripts/matter_alpha_email.md | email | 2026-03-23 | Attorney | — | Smith | Smith email chain. | no |",
                        "| A003 | sources/transcripts/matter_gamma.md | transcript | 2026-03-22 | Attorney | — | Brown | Brown mediation scheduling. | no |",
                    ]
                ),
                encoding="utf-8",
            )
            case_md_path.write_text(
                "\n".join(
                    [
                        "# Cases",
                        "",
                        "## SMITH",
                        "- **Mediation**: Scheduled 4/7/26 with Mediator",
                        "",
                        "## BROWN",
                        "- **Key Events**: mediation scheduled 6/11/26",
                        "",
                        "## FLEET (GENERAL / TEAM)",
                        "- **Key Events**: monthly review",
                    ]
                ),
                encoding="utf-8",
            )
            case_dates_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Smith v. Acme Corp",
                            "claim": "CL12345AB",
                            "reserve": "",
                            "incurred": "",
                            "depo_date": "",
                            "disco_date": "",
                            "complaint_filed": "",
                        },
                        {
                            "name": "Brown v. Acme Corp",
                            "claim": "CL67890CD",
                            "reserve": "",
                            "incurred": "",
                            "depo_date": "",
                            "disco_date": "",
                            "complaint_filed": "",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            artifacts = parse_manifest_rows(manifest_path)
            records = parse_case_records(case_dates_path)
            sections = parse_case_sections(case_md_path)
            matchers = build_case_matchers(sections, records)
            report = {
                "uncataloged_canonical_sources": [
                    "sources/teams_screenshots/smith rog verification 3.20.26.md",
                    "sources/teams_screenshots/matter status tight 3.23.26.md",
                ]
            }

            output = render_today(
                reference_date=date(2026, 3, 25),
                artifacts=artifacts,
                sections=sections,
                matchers=matchers,
                report=report,
                window_days=45,
                recent_days=7,
                limit=5,
            )

            self.assertIn("Upcoming (45d window)", output)
            self.assertIn("2026-04-07 | SMITH", output)
            self.assertIn("Recent Case Heat (7d lookback)", output)
            self.assertIn("SMITH | 2 artifacts", output)
            self.assertIn("Open Intake Backlog", output)

    def test_resolve_case_heading_and_backlog_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_md_path = root / "index_by_case.md"
            case_dates_path = root / "case_dates.json"

            case_md_path.write_text(
                "\n".join(
                    [
                        "# Cases",
                        "",
                        "## SMITH",
                        "- **Style**: Smith v. Acme Corp",
                        "",
                        "## WHITE",
                        "- **Style**: White v. Carrier Corp & Driver",
                    ]
                ),
                encoding="utf-8",
            )
            case_dates_path.write_text(
                json.dumps(
                    [
                        {"name": "Smith v. Acme Corp", "claim": "CL12345AB"},
                        {"name": "White v. Carrier Corp", "claim": "CL67890CD"},
                    ]
                ),
                encoding="utf-8",
            )

            sections = parse_case_sections(case_md_path)
            records = parse_case_records(case_dates_path)
            matchers = build_case_matchers(sections, records)

            self.assertEqual(resolve_case_heading("smith", matchers), "SMITH")
            backlog = gather_uncataloged_by_case(
                {
                    "uncataloged_canonical_sources": [
                        "sources/teams_archives/Driver_White_Case_Archive.md"
                    ]
                },
                matchers,
            )
            self.assertEqual(
                backlog["WHITE"][0],
                "sources/teams_archives/Driver_White_Case_Archive.md",
            )

    def test_build_upcoming_items_uses_case_dates_and_case_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_md_path = root / "index_by_case.md"
            case_dates_path = root / "case_dates.json"

            case_md_path.write_text(
                "\n".join(
                    [
                        "# Cases",
                        "",
                        "## SAMPLE",
                        "- **Key Discovery**:",
                        "  - NOD Corp Rep TB Spine & Sport depo 5/5/26 DT and Sub",
                    ]
                ),
                encoding="utf-8",
            )
            case_dates_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Sample v. Logistics Co",
                            "claim": "SAMPLE-001",
                            "reserve": "",
                            "incurred": "",
                            "depo_date": "5/5/2026",
                            "disco_date": "",
                            "complaint_filed": "",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            sections = parse_case_sections(case_md_path)
            records = parse_case_records(case_dates_path)
            matchers = build_case_matchers(sections, records)
            items = build_upcoming_items(
                reference_date=date(2026, 3, 25),
                window_days=60,
                sections=sections,
                matchers=matchers,
            )

            self.assertTrue(any(item.when == date(2026, 5, 5) for item in items))


if __name__ == "__main__":
    unittest.main()
