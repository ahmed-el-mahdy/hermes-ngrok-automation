#!/usr/bin/env python3
"""Extract private Personal-project attachments using local tools only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile


DEFAULT_ROOT = Path(
    os.getenv("HERMES_PERSONAL_MEMORY_ROOT", "/opt/data/personal_memory")
)
IMAGE_SUFFIXES = {
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
TEXT_SUFFIXES = {".md", ".txt"}
DOCUMENT_SUFFIXES = {".docx", ".pdf"}
IGNORED_NAMES = {"manifest.json"}
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def run(*command: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def atomic_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(payload)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def extract_docx(path: Path) -> tuple[str, float, str]:
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml")
    root = ET.fromstring(document)
    lines = []
    for paragraph in root.iter(f"{{{WORD_NS}}}p"):
        text = "".join(
            node.text or ""
            for node in paragraph.iter(f"{{{WORD_NS}}}t")
        ).strip()
        if text:
            lines.append(text)
    return "\n".join(lines), 99.0, "DOCX XML text extraction"


def extract_text_file(path: Path) -> tuple[str, float, str]:
    return (
        path.read_text(encoding="utf-8", errors="replace"),
        99.0,
        "direct UTF-8 text extraction",
    )


def preprocess_image(path: Path, destination: Path) -> None:
    if not shutil.which("ffmpeg"):
        if path.suffix.lower() in {".heic", ".heif"}:
            raise RuntimeError("ffmpeg is required for HEIC images")
        shutil.copy2(path, destination)
        return
    run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-vf",
        (
            "scale=1800:1800:force_original_aspect_ratio=decrease:"
            "flags=lanczos,format=gray,eq=contrast=1.20:brightness=0.02,"
            "unsharp=5:5:0.7"
        ),
        str(destination),
    )


def parse_tsv(payload: str) -> tuple[str, float, int]:
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    confidences = []
    for raw_line in payload.splitlines()[1:]:
        columns = raw_line.split("\t", 11)
        if len(columns) != 12:
            continue
        text = columns[11].strip()
        try:
            confidence = float(columns[10])
        except ValueError:
            confidence = -1
        if not text or confidence < 0:
            continue
        key = tuple(columns[index] for index in (1, 2, 3, 4))
        lines.setdefault(key, []).append(text)
        confidences.append(confidence)
    rendered = "\n".join(" ".join(words) for words in lines.values()).strip()
    average = (
        sum(confidences) / len(confidences)
        if confidences
        else 0.0
    )
    return rendered, average, len(confidences)


def ocr_image(path: Path) -> tuple[str, float, str]:
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract is required for image OCR")
    with tempfile.TemporaryDirectory(prefix="hermes-personal-ocr-") as raw:
        processed = Path(raw) / "processed.png"
        preprocess_image(path, processed)
        candidates = []
        page_modes = ["6"]
        for page_mode in page_modes:
            try:
                result = run(
                    "tesseract",
                    str(processed),
                    "stdout",
                    "-l",
                    "ara+eng",
                    "--oem",
                    "1",
                    "--psm",
                    page_mode,
                    "--dpi",
                    "150",
                    "tsv",
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                continue
            text, confidence, words = parse_tsv(result.stdout)
            score = confidence + min(15.0, words / 8.0)
            candidates.append((score, text, confidence, page_mode, words))
            if page_mode == "6" and (confidence < 60 or words < 15):
                page_modes.append("11")
        if not candidates:
            return "", 0.0, "Tesseract ara+eng OCR timed out"
        _, text, confidence, page_mode, words = max(
            candidates,
            key=lambda item: item[0],
        )
        return (
            text,
            confidence,
            f"Tesseract ara+eng OCR, PSM {page_mode}, {words} words",
        )


def extract_pdf(
    path: Path,
    *,
    max_pages: int,
) -> tuple[str, float, str]:
    if shutil.which("pdftotext"):
        direct = run("pdftotext", "-layout", str(path), "-")
        text = direct.stdout.strip()
        if len(text) >= 200:
            return text, 98.0, "PDF embedded-text extraction"
    if not shutil.which("pdftoppm"):
        raise RuntimeError("pdftoppm is required for scanned PDF OCR")
    with tempfile.TemporaryDirectory(prefix="hermes-personal-pdf-") as raw:
        prefix = Path(raw) / "page"
        run(
            "pdftoppm",
            "-f",
            "1",
            "-l",
            str(max_pages),
            "-png",
            "-r",
            "220",
            str(path),
            str(prefix),
            timeout=max(180, max_pages * 20),
        )
        pages = sorted(Path(raw).glob("page-*.png"))
        page_texts = []
        confidences = []
        for index, page in enumerate(pages, start=1):
            text, confidence, _ = ocr_image(page)
            if text.strip():
                page_texts.append(f"## Page {index}\n\n{text.strip()}")
            confidences.append(confidence)
        confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else 0.0
        )
        return (
            "\n\n".join(page_texts),
            confidence,
            f"scanned PDF OCR, {len(pages)} pages",
        )


def extract(
    path: Path,
    *,
    max_pdf_pages: int,
) -> tuple[str, float, str]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ocr_image(path)
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".pdf":
        return extract_pdf(path, max_pages=max_pdf_pages)
    if suffix in TEXT_SUFFIXES:
        return extract_text_file(path)
    raise RuntimeError(f"unsupported attachment type: {suffix}")


def output_path(root: Path, source: Path) -> Path:
    relative = source.relative_to(root / "attachments")
    prefix = "ocr-" if source.suffix.lower() in IMAGE_SUFFIXES else "extract-"
    return (
        root
        / "attachment_text"
        / relative.parent
        / f"{prefix}{source.stem}.md"
    )


def render_markdown(
    source: Path,
    *,
    method: str,
    confidence: float,
    text: str,
) -> str:
    confidence_label = (
        "high"
        if confidence >= 80
        else "medium"
        if confidence >= 55
        else "low"
    )
    warning = (
        "OCR text can contain mistakes. Verify names, dates, dosages, case "
        "numbers, and legal wording against the original attachment."
        if source.suffix.lower() in IMAGE_SUFFIXES or "OCR" in method
        else "Extracted text should still be checked against the signed or "
        "official original before consequential use."
    )
    return (
        f"# Attachment extraction: {source.name}\n\n"
        f"- Source attachment: {source.name}\n"
        f"- Extraction method: {method}\n"
        f"- OCR confidence: {confidence:.1f}% ({confidence_label})\n"
        "- Privacy: processed locally inside the Hermes VM\n"
        f"- Verification warning: {warning}\n\n"
        "---\n\n"
        f"{text.strip()}\n"
    )


def process(args: argparse.Namespace) -> dict:
    root = args.root
    attachment_root = root / "attachments"
    if not attachment_root.exists():
        return {
            "passed": True,
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "files": [],
        }
    sources = [
        path
        for path in sorted(attachment_root.rglob("*"))
        if path.is_file()
        and path.name not in IGNORED_NAMES
        and path.suffix.lower()
        in IMAGE_SUFFIXES | DOCUMENT_SUFFIXES | TEXT_SUFFIXES
    ]
    if args.documents_only:
        sources = [
            path for path in sources if path.suffix.lower() not in IMAGE_SUFFIXES
        ]
    if args.source:
        requested = set()
        attachment_root_resolved = attachment_root.resolve()
        for raw_source in args.source:
            candidate = (attachment_root / raw_source).resolve()
            if not candidate.is_relative_to(attachment_root_resolved):
                raise ValueError(
                    f"source must stay under the attachments directory: {raw_source}"
                )
            requested.add(candidate)
        sources = [path for path in sources if path.resolve() in requested]
        missing = sorted(
            str(path.relative_to(attachment_root_resolved))
            for path in requested
            if not path.is_file()
        )
        if missing:
            raise ValueError(
                "attachment source not found: " + ", ".join(missing)
            )
    rows = []
    processed = skipped = failed = 0
    for source in sources:
        destination = output_path(root, source)
        if (
            not args.force
            and destination.exists()
            and destination.stat().st_mtime >= source.stat().st_mtime
        ):
            skipped += 1
            rows.append(
                {
                    "source": str(source.relative_to(root)),
                    "output": str(destination.relative_to(root)),
                    "status": "skipped",
                }
            )
            continue
        try:
            text, confidence, method = extract(
                source,
                max_pdf_pages=args.max_pdf_pages,
            )
            status = "processed"
            if not text.strip():
                status = "no_text"
                text = (
                    "[No reliable text was extracted from this attachment. "
                    "The original file remains archived for visual review.]"
                )
            atomic_text(
                destination,
                render_markdown(
                    source,
                    method=method,
                    confidence=confidence,
                    text=text,
                ),
            )
            processed += 1
            rows.append(
                {
                    "source": str(source.relative_to(root)),
                    "output": str(destination.relative_to(root)),
                    "status": status,
                    "confidence": round(confidence, 1),
                    "method": method,
                    "characters": len(text),
                }
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            failed += 1
            rows.append(
                {
                    "source": str(source.relative_to(root)),
                    "status": "failed",
                    "error": str(exc),
                }
            )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": (
            "selected"
            if args.source
            else "documents-only"
            if args.documents_only
            else "all"
        ),
        "requested_sources": list(args.source),
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "files": rows,
    }
    atomic_text(
        root / "attachment_text" / "extraction-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    manifest["passed"] = failed == 0
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract attachment text locally. Use --documents-only for routine "
            "imports and --source for selective image OCR."
        )
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--documents-only",
        action="store_true",
        help="extract text/PDF/DOCX files without scanning images",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="RELATIVE_PATH",
        help=(
            "process only this path relative to attachments/; repeat for "
            "multiple files"
        ),
    )
    parser.add_argument("--max-pdf-pages", type=int, default=80)
    args = parser.parse_args()
    result = process(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
