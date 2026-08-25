from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.errors import PublicationBoundaryError
from stonewall.publication import (
    BoundaryConfig,
    build_manifest,
    candidate_paths,
    check_boundary,
    load_config,
    scan_path,
    validate_reference_contract,
    write_manifest,
)


def config() -> BoundaryConfig:
    return BoundaryConfig(
        manifest_path=PurePosixPath("public-tree-manifest.json"),
        reference_root=PurePosixPath("examples/corpus"),
        allowed_email_domains=frozenset({"example.com"}),
        allowed_exact_paths=frozenset(),
        allowed_path_prefixes=("",),
        denied_exact_paths=frozenset({".env"}),
        denied_path_prefixes=("sources/", "tmp/"),
        denied_suffixes=frozenset({".key", ".pdf"}),
        reference_metadata_fields=frozenset({"date", "id", "type"}),
    )


class ScannerTests(unittest.TestCase):
    def scan(self, value: str, *, name: str = "record.txt"):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(value, encoding="utf-8")
            return scan_path(root, PurePosixPath(name), config())

    def test_allows_documentation_email_domains(self) -> None:
        self.assertEqual(self.scan("reviewer@example.com\n"), [])

    def test_blocks_unapproved_email_without_echoing_value(self) -> None:
        canary = "person" + "@mail.invalid"
        findings = self.scan(f"contact: {canary}\n")
        report = "\n".join(finding.render() for finding in findings)
        self.assertIn("email_address", report)
        self.assertNotIn(canary, report)

    def test_blocks_phone_without_echoing_value(self) -> None:
        canary = "212" + "-555-0199"
        report = "\n".join(f.render() for f in self.scan(f"call {canary}\n"))
        self.assertIn("phone_number", report)
        self.assertNotIn(canary, report)

    def test_blocks_ssn_shape_without_echoing_value(self) -> None:
        canary = "123" + "-45-6789"
        report = "\n".join(f.render() for f in self.scan(canary + "\n"))
        self.assertIn("ssn_shape", report)
        self.assertNotIn(canary, report)

    def test_blocks_absolute_user_path_without_echoing_value(self) -> None:
        canary = "/" + "Users/" + "named-user/Documents/evidence"
        report = "\n".join(f.render() for f in self.scan(canary + "\n"))
        self.assertIn("absolute_user_path", report)
        self.assertNotIn(canary, report)

    def test_blocks_home_user_path_without_echoing_value(self) -> None:
        canary = "/" + "home/" + "named-user/evidence"
        report = "\n".join(f.render() for f in self.scan(canary + "\n"))
        self.assertIn("absolute_user_path", report)
        self.assertNotIn(canary, report)

    def test_blocks_sensitive_filename_without_echoing_value(self) -> None:
        canary = "person" + "@mail.invalid.txt"
        report = "\n".join(f.render() for f in self.scan("record\n", name=canary))
        self.assertIn("email_address", report)
        self.assertNotIn(canary, report)

    def test_allows_explicit_username_placeholder(self) -> None:
        self.assertEqual(self.scan("C:\\Users\\<username>\\Documents\n"), [])

    def test_blocks_street_address_without_echoing_value(self) -> None:
        canary = "742" + " Evergreen Terrace"
        report = "\n".join(f.render() for f in self.scan(canary + "\n"))
        self.assertIn("street_address", report)
        self.assertNotIn(canary, report)

    def test_blocks_credential_shape_without_echoing_value(self) -> None:
        canary = "ghp_" + "A" * 32
        report = "\n".join(f.render() for f in self.scan(canary + "\n"))
        self.assertIn("credential_shape", report)
        self.assertNotIn(canary, report)

    def test_blocks_assigned_secret_without_echoing_value(self) -> None:
        canary = "unpublished" + "value123456"
        report = "\n".join(f.render() for f in self.scan(f'token="{canary}"\n'))
        self.assertIn("assigned_secret", report)
        self.assertNotIn(canary, report)

    def test_blocks_unquoted_assigned_secret_without_echoing_value(self) -> None:
        canary = "unquoted" + "value123456"
        report = "\n".join(f.render() for f in self.scan(f"API_KEY={canary}\n"))
        self.assertIn("assigned_secret", report)
        self.assertNotIn(canary, report)

    def test_blocks_json_assigned_secret_without_echoing_value(self) -> None:
        canary = "serialized" + "value123456"
        report = "\n".join(
            f.render() for f in self.scan(f'{{"api_key":"{canary}"}}\n')
        )
        self.assertIn("assigned_secret", report)
        self.assertNotIn(canary, report)

    def test_allows_environment_secret_expression(self) -> None:
        self.assertEqual(self.scan("SERVICE_TOKEN=process.env.SERVICE_TOKEN\n"), [])

    def test_allows_placeholder_secret(self) -> None:
        self.assertEqual(self.scan("SERVICE_TOKEN=YOUR_TOKEN_HERE\n"), [])

    def test_blocks_denied_prefix_and_file_type(self) -> None:
        findings = self.scan("bytes\n", name="sources/exhibit.pdf")
        self.assertEqual(
            {finding.rule for finding in findings},
            {"denied_path_prefix", "denied_file_type"},
        )

    def test_blocks_path_outside_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "record.txt").write_text("record\n", encoding="utf-8")
            strict = replace(
                config(), allowed_exact_paths=frozenset(), allowed_path_prefixes=()
            )
            findings = scan_path(root, PurePosixPath("record.txt"), strict)
        self.assertIn("unapproved_path", {finding.rule for finding in findings})

    def test_blocks_binary_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "asset.bin").write_bytes(b"ok\0not-text")
            findings = scan_path(root, PurePosixPath("asset.bin"), config())
        self.assertEqual([finding.rule for finding in findings], ["binary_content"])


class ManifestAndContractTests(unittest.TestCase):
    def test_loads_repository_config(self) -> None:
        loaded = load_config(REPO_ROOT / "public-boundary.toml")
        self.assertEqual(loaded.manifest_path.as_posix(), "public-tree-manifest.json")
        self.assertIn("README.md", loaded.allowed_exact_paths)
        self.assertIn("src/stonewall/", loaded.allowed_path_prefixes)
        self.assertIn("sources/", loaded.denied_path_prefixes)

    def test_rejects_unknown_config_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "boundary.toml"
            path.write_text("version = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(PublicationBoundaryError, "version"):
                load_config(path)

    def test_rejects_non_relative_config_paths(self) -> None:
        for manifest_path in ("../outside.json", "/tmp/outside.json", "./manifest.json"):
            with self.subTest(manifest_path=manifest_path):
                with tempfile.TemporaryDirectory() as raw:
                    path = Path(raw) / "boundary.toml"
                    path.write_text(
                        "\n".join(
                            [
                                "version = 1",
                                f'manifest_path = "{manifest_path}"',
                                'reference_root = "reference"',
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(PublicationBoundaryError, "canonical relative"):
                        load_config(path)

    def test_rejects_escaping_reference_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "boundary.toml"
            path.write_text(
                "version = 1\n"
                'manifest_path = "manifest.json"\n'
                'reference_root = "../reference"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PublicationBoundaryError, "canonical relative"):
                load_config(path)

    def test_manifest_is_order_independent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("a\n", encoding="utf-8")
            (root / "b.txt").write_text("b\n", encoding="utf-8")
            left = build_manifest(
                root, [PurePosixPath("a.txt"), PurePosixPath("b.txt")], config()
            )
            right = build_manifest(
                root, [PurePosixPath("b.txt"), PurePosixPath("a.txt")], config()
            )
        self.assertEqual(left, right)

    def test_manifest_records_digest_size_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "record.txt").write_text("record\n", encoding="utf-8")
            payload = build_manifest(root, [PurePosixPath("record.txt")], config())
        entry = payload["entries"][0]
        self.assertEqual(
            set(entry),
            {
                "path",
                "sha256",
                "size",
                "executable",
            },
        )

    def test_candidate_enumeration_includes_untracked_nonignored_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            (root / "candidate.txt").write_text("candidate\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            paths = candidate_paths(root)
        self.assertEqual(
            {path.as_posix() for path in paths}, {"candidate.txt", "tracked.txt"}
        )

    def test_reference_contract_is_clean(self) -> None:
        loaded = load_config(REPO_ROOT / "public-boundary.toml")
        self.assertEqual(validate_reference_contract(REPO_ROOT, loaded), [])

    def test_invalid_reference_contract_does_not_echo_source_value(self) -> None:
        canary = "identity" + "_bearing_value"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            reference = root / "examples" / "corpus"
            reference.mkdir(parents=True)
            (reference / "record.md").write_text(
                f"---\nid: {canary}\ntype: case\ndate: 2025-01-01\n---\n\n# Record\n",
                encoding="utf-8",
            )
            findings = validate_reference_contract(root, config())
        report = "\n".join(finding.render() for finding in findings)
        self.assertIn("reference_contract_invalid", report)
        self.assertNotIn(canary, report)

    def test_check_requires_public_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            reference = root / "examples" / "corpus"
            reference.mkdir(parents=True)
            (reference / "case.md").write_text(
                "---\nid: M0001\ntype: case\ndate: 2025-01-01\n---\n\n# Matter M0001\n\nRecord.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            findings = check_boundary(root, config())
        self.assertIn("manifest_missing", {finding.rule for finding in findings})

    def test_write_manifest_rejects_escape_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            outside = root.parent / "outside-public-tree.json"
            escaped = replace(
                config(), manifest_path=PurePosixPath("../outside-public-tree.json")
            )
            with self.assertRaisesRegex(PublicationBoundaryError, "escapes"):
                write_manifest(root, escaped)
            self.assertFalse(outside.exists())

    def test_manifest_detects_byte_drift_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            reference = root / "examples" / "corpus"
            reference.mkdir(parents=True)
            artifact_path = reference / "case.md"
            artifact_path.write_text(
                "---\nid: M0001\ntype: case\ndate: 2025-01-01\n---\n\n# Matter M0001\n\nRecord.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            write_manifest(root, config())
            self.assertEqual(check_boundary(root, config()), [])
            artifact_path.write_text(
                artifact_path.read_text(encoding="utf-8").replace("Record.", "Changed."),
                encoding="utf-8",
            )
            findings = check_boundary(root, config())
        self.assertIn("manifest_drift", {finding.rule for finding in findings})

    def test_manifest_detects_executable_mode_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            reference = root / "examples" / "corpus"
            reference.mkdir(parents=True)
            artifact_path = reference / "case.md"
            artifact_path.write_text(
                "---\nid: M0001\ntype: case\ndate: 2025-01-01\n---\n\n# Matter M0001\n\nRecord.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            write_manifest(root, config())
            artifact_path.chmod(artifact_path.stat().st_mode ^ 0o100)
            findings = check_boundary(root, config())
        self.assertIn("manifest_drift", {finding.rule for finding in findings})


if __name__ == "__main__":
    unittest.main()
