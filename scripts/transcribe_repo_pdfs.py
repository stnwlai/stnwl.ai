#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = REPO_ROOT / "sources"
DEFAULT_REPORT = REPO_ROOT / "catalog" / "intake" / "repo_pdf_transcription_report.json"
IGNORE_PARTS = {"onedrive_ingest"}
TEXT_COMPANION_SUFFIXES = {".docx", ".html", ".md", ".rtf", ".txt"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.replace("\u00ad", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def sidecar_path(pdf_path: Path) -> Path:
    return pdf_path.with_name(f"{pdf_path.name}.md")


def read_sidecar_metadata(md_path: Path) -> dict[str, str]:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---\n"):
        return {}
    _, _, remainder = text.partition("---\n")
    front_matter, _, _ = remainder.partition("\n---")
    data: dict[str, str] = {}
    for line in front_matter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def has_text_companion(pdf_path: Path) -> bool:
    for suffix in TEXT_COMPANION_SUFFIXES:
        companion = pdf_path.with_suffix(suffix)
        if companion.exists():
            return True
    return False


def extract_pdf_text(pdf_path: Path, dpi: int) -> tuple[str, list[str], int]:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path), strict=False)
    page_texts: list[str] = []
    embedded_chars = 0
    for page in reader.pages:
        text = normalize_text(page.extract_text() or "")
        page_texts.append(text)
        embedded_chars += len(text)
    if embedded_chars:
        return "pypdf", page_texts, len(reader.pages)

    import fitz  # type: ignore
    from rapidocr_onnxruntime import RapidOCR  # type: ignore

    engine = RapidOCR()
    doc = fitz.open(str(pdf_path))
    ocr_page_texts: list[str] = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        result, _ = engine(pix.tobytes("png"))
        lines = [item[1].strip() for item in (result or []) if len(item) > 1 and item[1].strip()]
        ocr_page_texts.append(normalize_text("\n".join(lines)))
    return "ocr-rapidocr", ocr_page_texts, len(doc)


def render_markdown(pdf_path: Path, method: str, page_texts: list[str], page_count: int) -> str:
    rel_path = pdf_path.relative_to(REPO_ROOT).as_posix()
    sha = sha256_file(pdf_path)
    combined_text = "\n\n".join(
        f"## Page {index}\n\n{page_text or '_No text extracted from this page._'}"
        for index, page_text in enumerate(page_texts, start=1)
    ).strip()
    extracted_chars = sum(len(page) for page in page_texts)
    lines = [
        "---",
        f'title: "{yaml_escape(pdf_path.name)}"',
        f'source_pdf: "{yaml_escape(str(pdf_path))}"',
        f'relative_source_path: "{yaml_escape(rel_path)}"',
        f'sha256: "{sha}"',
        f'page_count: "{page_count}"',
        f'extraction_method: "{method}"',
        f'extracted_chars: "{extracted_chars}"',
        f'generated_at: "{datetime.now().isoformat(timespec="seconds")}"',
        "---",
        "",
        f"# {pdf_path.name}",
        "",
        "## Source Metadata",
        f"- Source PDF: `{rel_path}`",
        f"- SHA256: `{sha}`",
        f"- Pages: `{page_count}`",
        f"- Extraction method: `{method}`",
        f"- Extracted characters: `{extracted_chars}`",
        "",
        "## Extracted Text",
        "",
        combined_text or "_No text extracted in this run._",
        "",
    ]
    return "\n".join(lines)


def collect_pdfs(source_root: Path) -> list[Path]:
    pdfs = []
    for path in sorted(source_root.rglob("*.pdf")):
        if any(part in IGNORE_PARTS for part in path.parts):
            continue
        pdfs.append(path)
    return pdfs


def main() -> int:
    parser = argparse.ArgumentParser(description="Create adjacent markdown derivatives for repo PDFs.")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--include-text-companions", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source_root = Path(args.source_root)
    report_rows = []
    for pdf_path in collect_pdfs(source_root):
        md_path = sidecar_path(pdf_path)
        if has_text_companion(pdf_path) and not args.include_text_companions:
            report_rows.append(
                {
                    "pdf_path": pdf_path.relative_to(REPO_ROOT).as_posix(),
                    "status": "skipped-text-companion",
                }
            )
            continue
        if md_path.exists() and not args.overwrite:
            metadata = read_sidecar_metadata(md_path)
            report_rows.append(
                {
                    "pdf_path": pdf_path.relative_to(REPO_ROOT).as_posix(),
                    "markdown_path": md_path.relative_to(REPO_ROOT).as_posix(),
                    "status": "existing",
                    "extraction_method": metadata.get("extraction_method", ""),
                    "page_count": metadata.get("page_count", ""),
                    "extracted_chars": metadata.get("extracted_chars", ""),
                }
            )
            continue

        method, page_texts, page_count = extract_pdf_text(pdf_path, args.dpi)
        markdown = render_markdown(pdf_path, method, page_texts, page_count)
        md_path.write_text(markdown, encoding="utf-8")
        report_rows.append(
            {
                "pdf_path": pdf_path.relative_to(REPO_ROOT).as_posix(),
                "markdown_path": md_path.relative_to(REPO_ROOT).as_posix(),
                "status": "written",
                "extraction_method": method,
                "page_count": page_count,
                "extracted_chars": sum(len(page) for page in page_texts),
            }
        )
        print(f"{method}\t{pdf_path.relative_to(REPO_ROOT).as_posix()} -> {md_path.relative_to(REPO_ROOT).as_posix()}")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_rows, indent=2), encoding="utf-8")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
