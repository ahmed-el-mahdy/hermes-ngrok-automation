#!/usr/bin/env python3
"""Build and query a private, local-only personal context index for Hermes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
from typing import Iterable


DEFAULT_ROOT = Path(os.getenv("HERMES_PERSONAL_MEMORY_ROOT", "/opt/data/personal_memory"))
DEFAULT_DB = DEFAULT_ROOT / "personal_context.sqlite3"
MEMORY_DIR = Path(os.getenv("HERMES_MEMORY_DIR", "/opt/data/memories"))

CHAT_CATEGORY = {
    "legal-consultant": "legal",
    "health-assistant": "health",
    "cv-update-request": "career",
    "ai-training-review": "training",
    "general-questions": "profile",
}

CATEGORY_TERMS = {
    "health": (
        "صحتي|صحيا|صحي|طبي|الدكتور|دواء|علاج|تحاليل|اشعة|اشعه|رنين|"
        "زوجتي|الحمل|جلطة|dvt|health|medical|medicine|wife|pregnan"
    ),
    "legal": (
        "قانون|قضية|القضيه|محكمة|خبير|ميراث|عقد|ملكية|حيازة|مدني|"
        "مرافعات|دستور|حقوق|شكوى|بلاغ|legal|case|court|law"
    ),
    "career": (
        "شغلي|عملي|وظيف|مقابلة|cv|career|work|job|interview|devops|"
        "azure|aws|kubernetes|terraform|خبرتي|مهاراتي"
    ),
    "finance": (
        "مرتب|راتب|ذهب|فضة|شقة|استثمار|فلوس|مالي|ميزاني|finance|"
        "salary|gold|silver|apartment|investment"
    ),
    "training": (
        "تدريب|كورس|محاضرات|منهج|ذكاء اصطناعي|ai training|course|"
        "curriculum|lecture"
    ),
    "profile": (
        "تعرف عني|تعرف ايه عني|معلوماتك عني|انا مين|ملفي|اسمي|"
        "عيلتي|أسرتي|اولادي|أولادي|profile|about me|who am i|family"
    ),
}

CATEGORY_EXPANSIONS = {
    "health": (
        "صحة",
        "الصحي",
        "الصحية",
        "طبي",
        "طبية",
        "دواء",
        "علاج",
        "أعراض",
        "تحاليل",
        "الكتف",
        "الظهر",
        "Vitamin",
        "MRI",
        "D11",
        "health",
    ),
    "legal": ("قانون", "القانوني", "قضية", "محكمة", "ملكية", "legal", "law"),
    "career": ("العمل", "مهني", "خبرة", "وظيفة", "devops", "career", "work"),
    "finance": ("مالي", "استثمار", "ذهب", "فضة", "شقة", "finance", "money"),
    "training": ("تدريب", "برنامج", "محاضرة", "منهج", "training", "course"),
    "profile": ("أحمد", "الملف", "الشخصي", "الأسرة", "تفضيلات", "profile"),
    "preferences": ("تفضيلات", "التعامل", "أسلوب", "preferences"),
}

PERSONAL_TRIGGER = re.compile(
    "|".join(f"(?:{terms})" for terms in CATEGORY_TERMS.values()),
    re.IGNORECASE,
)
DOCUMENT_INTENT = re.compile(
    r"\b(?:attachment|cv|document|file|memo|memorandum|report|curriculum)\b"
    r"|(?:الملف|ملف|المرفق|مرفق|المستند|مستند|التقرير|تقرير|"
    r"المذكرة|مذكرة|المنهج|منهج|السيرة|سيرة)",
    re.IGNORECASE,
)

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAQ\.[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(api[_ -]?key|password|passwd|token|secret)\b"
        r"\s*[:=]\s*\S+"
    ),
    re.compile(r"(?<!\d)(?:\d[ -]?){14}(?!\d)"),
    re.compile(r"(?<!\d)(?:\d[ -]?){16}(?!\d)"),
    re.compile(r"(?<!\d)(?:\+?20|0)?1[0125]\d{8}(?!\d)"),
)

ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
MOJIBAKE_RE = re.compile(r"[ØÙÃÂÐÑ]")
WORD_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)
STOP_WORDS = {
    "من",
    "في",
    "على",
    "عن",
    "الى",
    "إلى",
    "ايه",
    "إيه",
    "ما",
    "هو",
    "هي",
    "انا",
    "أنا",
    "the",
    "and",
    "for",
    "with",
    "what",
    "about",
}


def fix_mojibake(value: str) -> str:
    """Repair UTF-8 text that was decoded as Latin-1/Windows-1252."""
    current = value
    for _ in range(2):
        before_score = len(MOJIBAKE_RE.findall(current))
        if before_score == 0:
            break
        candidates = []
        for codec in ("latin-1", "cp1252"):
            try:
                candidates.append(current.encode(codec).decode("utf-8"))
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        if not candidates:
            break
        candidate = max(
            candidates,
            key=lambda item: (
                len(ARABIC_RE.findall(item)),
                -len(MOJIBAKE_RE.findall(item)),
            ),
        )
        if (
            len(MOJIBAKE_RE.findall(candidate)) >= before_score
            and len(ARABIC_RE.findall(candidate))
            <= len(ARABIC_RE.findall(current))
        ):
            break
        current = candidate
    return current


def redact_secrets(value: str) -> tuple[str, int]:
    text = value
    count = 0
    for pattern in SECRET_PATTERNS:
        text, replacements = pattern.subn("[REDACTED]", text)
        count += replacements
    return text, count


def normalize_value(value):
    if isinstance(value, str):
        normalized = fix_mojibake(value)
        return redact_secrets(normalized)[0]
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_value(item) for key, item in value.items()}
    return value


def atomic_text(path: Path, payload: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        path.write_text(payload, encoding="utf-8", newline="\n")
        return
    descriptor, raw_temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent.resolve(),
        text=True,
    )
    temp_path = Path(raw_temp_path)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    os.chmod(temp_path, mode)
    os.replace(temp_path, path.resolve())


def normalize_exports(root: Path) -> dict:
    source_dir = root / "source_chats"
    changed = 0
    redactions = 0
    for path in sorted(source_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        normalized = normalize_value(data)
        payload = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
        original = path.read_text(encoding="utf-8")
        if payload != original:
            atomic_text(path, payload)
            changed += 1
        redactions += payload.count("[REDACTED]")

    markdown_paths = [
        *sorted(source_dir.glob("*.md")),
        *sorted((root / "attachment_text").rglob("*.md")),
    ]
    for path in markdown_paths:
        original = path.read_text(encoding="utf-8")
        normalized, replacements = redact_secrets(fix_mojibake(original))
        if normalized != original:
            atomic_text(path, normalized.rstrip() + "\n")
            changed += 1
        redactions += replacements
    return {"changed_files": changed, "redaction_markers": redactions}


def split_markdown(
    path: Path,
    category: str,
    *,
    priority: int = 100,
    source: str | None = None,
) -> Iterable[dict]:
    text = fix_mojibake(path.read_text(encoding="utf-8"))
    title = path.stem
    section = title
    buffer: list[str] = []

    def emit() -> Iterable[dict]:
        content = "\n".join(buffer).strip()
        if content:
            for piece in split_text(content):
                yield {
                    "category": category,
                    "priority": priority,
                    "source": source or f"dossiers/{path.name}",
                    "title": title,
                    "section": section,
                    "content": piece,
                }

    for line in text.splitlines():
        if line.startswith("#"):
            yield from emit()
            buffer = []
            section = line.lstrip("#").strip() or title
        else:
            buffer.append(line)
    yield from emit()


def split_text(text: str, max_chars: int = 1800) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= max_chars:
        return [text] if text else []
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = ""
        if len(paragraph) > max_chars:
            sentences = re.split(r"(?<=[.!؟])\s+", paragraph)
            for sentence in sentences:
                if current and len(current) + len(sentence) + 1 > max_chars:
                    chunks.append(current)
                    current = ""
                if len(sentence) > max_chars:
                    if current:
                        chunks.append(current)
                        current = ""
                    chunks.extend(
                        sentence[index : index + max_chars]
                        for index in range(0, len(sentence), max_chars)
                    )
                else:
                    current = f"{current} {sentence}".strip()
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def iter_chat_chunks(root: Path) -> Iterable[dict]:
    for path in sorted((root / "source_chats").glob("*.json")):
        if path.name == "manifest.json":
            continue
        data = normalize_value(json.loads(path.read_text(encoding="utf-8")))
        slug = str(data.get("slug") or path.stem)
        category = CHAT_CATEGORY.get(slug, "profile")
        title = str(data.get("title") or slug)
        for index, turn in enumerate(data.get("turns") or [], start=1):
            if not isinstance(turn, dict):
                continue
            content = str(turn.get("content") or "").strip()
            if not content:
                continue
            role = str(turn.get("role") or "unknown")
            attachments = [
                str(item)
                for item in (turn.get("attachments") or [])
                if str(item).strip()
            ]
            images = [
                str(item)
                for item in (turn.get("images") or [])
                if str(item).strip()
            ]
            if attachments or images:
                content += "\n\nAttachment references: " + ", ".join(
                    dict.fromkeys([*attachments, *images])
                )
            for piece_index, piece in enumerate(split_text(content), start=1):
                yield {
                    "category": category,
                    "priority": 30 if role == "user" else 20,
                    "source": f"source_chats/{path.name}",
                    "title": title,
                    "section": f"{role} turn {index}.{piece_index}",
                    "content": piece,
                }


def dossier_category(path: Path) -> str:
    name = path.name.lower()
    if "health" in name:
        return "health"
    if "legal" in name:
        return "legal"
    if "career" in name or "technical" in name:
        return "career"
    if "family" in name or "finance" in name:
        return "finance"
    if "training" in name:
        return "training"
    if "interaction" in name:
        return "preferences"
    return "profile"


def iter_attachment_chunks(root: Path) -> Iterable[dict]:
    attachment_root = root / "attachment_text"
    if not attachment_root.exists():
        return
    for path in sorted(attachment_root.rglob("*.md")):
        relative = path.relative_to(attachment_root)
        slug = relative.parts[0] if len(relative.parts) > 1 else ""
        category = CHAT_CATEGORY.get(slug, dossier_category(path))
        yield from split_markdown(
            path,
            category,
            priority=80,
            source=f"attachment_text/{relative.as_posix()}",
        )


def build_index(root: Path, db_path: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = root / "source_chats" / "manifest.json"
    manifest = (
        normalize_value(json.loads(manifest_path.read_text(encoding="utf-8")))
        if manifest_path.exists()
        else {}
    )
    manifest_chats = [
        chat for chat in (manifest.get("chats") or []) if isinstance(chat, dict)
    ]
    source_chat_count = len(manifest_chats)
    source_turn_count = sum(
        int(chat.get("turn_count") or 0) for chat in manifest_chats
    )
    attachment_reference_count = sum(
        int(chat.get("attachment_count") or 0) for chat in manifest_chats
    )
    dossier_paths = sorted((root / "dossiers").glob("*.md"))
    attachment_text_paths = sorted((root / "attachment_text").rglob("*.md"))
    attachment_binary_paths = [
        path
        for path in sorted((root / "attachments").rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    ]
    chunks = []
    for path in dossier_paths:
        chunks.extend(split_markdown(path, dossier_category(path)))
    attachment_chunks = list(iter_attachment_chunks(root))
    chunks.extend(attachment_chunks)
    chunks.extend(iter_chat_chunks(root))
    if not chunks:
        raise RuntimeError(f"No personal context files found under {root}")

    temp_db = db_path.with_suffix(".tmp.sqlite3")
    if temp_db.exists():
        temp_db.unlink()
    connection = sqlite3.connect(temp_db)
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE chunks USING fts5(
                chunk_id UNINDEXED,
                category UNINDEXED,
                priority UNINDEXED,
                source UNINDEXED,
                title,
                section,
                content,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        for chunk in chunks:
            digest = hashlib.sha256(
                (
                    chunk["source"]
                    + "\0"
                    + chunk["section"]
                    + "\0"
                    + chunk["content"]
                ).encode("utf-8")
            ).hexdigest()[:20]
            connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    digest,
                    chunk["category"],
                    chunk["priority"],
                    chunk["source"],
                    chunk["title"],
                    chunk["section"],
                    chunk["content"],
                ),
            )
        connection.execute(
            "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            (
                (
                    "built_at",
                    datetime.now(timezone.utc).isoformat(),
                ),
                ("chunk_count", str(len(chunks))),
                ("source_chat_count", str(source_chat_count)),
                ("source_turn_count", str(source_turn_count)),
                (
                    "attachment_reference_count",
                    str(attachment_reference_count),
                ),
                ("dossier_count", str(len(dossier_paths))),
                (
                    "attachment_binary_file_count",
                    str(len(attachment_binary_paths)),
                ),
                (
                    "attachment_text_file_count",
                    str(len(attachment_text_paths)),
                ),
                (
                    "attachment_text_chunk_count",
                    str(len(attachment_chunks)),
                ),
                ("schema_version", "2"),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    os.chmod(temp_db, 0o600)
    os.replace(temp_db, db_path)
    categories: dict[str, int] = {}
    for chunk in chunks:
        category = chunk["category"]
        categories[category] = categories.get(category, 0) + 1
    return {
        "database": str(db_path),
        "chunk_count": len(chunks),
        "source_chat_count": source_chat_count,
        "source_turn_count": source_turn_count,
        "attachment_reference_count": attachment_reference_count,
        "dossier_count": len(dossier_paths),
        "attachment_binary_file_count": len(attachment_binary_paths),
        "attachment_text_file_count": len(attachment_text_paths),
        "attachment_text_chunk_count": len(attachment_chunks),
        "categories": categories,
    }


def detect_categories(query: str) -> list[str]:
    categories = [
        category
        for category, terms in CATEGORY_TERMS.items()
        if re.search(terms, query, re.IGNORECASE)
    ]
    specific = [
        category
        for category in categories
        if category not in {"profile", "preferences"}
    ]
    if specific:
        return specific
    return categories or ["profile"]


def detect_category(query: str) -> str:
    """Return the first category for backwards-compatible callers."""
    return detect_categories(query)[0]


def _search_category(
    query: str,
    *,
    category: str,
    db_path: Path,
    limit: int,
    max_chars: int,
) -> list[dict]:
    expression = fts_query(fix_mojibake(query), category)
    if not expression:
        return []
    prefer_attachments = bool(DOCUMENT_INTENT.search(fix_mojibake(query)))
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT chunk_id, category, source, title, section, content,
                   bm25(chunks) AS rank
            FROM chunks
            WHERE chunks MATCH ?
            ORDER BY
                CASE
                    WHEN ? = 1 AND source LIKE 'attachment_text/%' THEN 0
                    ELSE 1
                END,
                CASE WHEN category = ? THEN 0 ELSE 1 END,
                CAST(priority AS INTEGER) DESC,
                rank
            LIMIT ?
            """,
            (
                expression,
                int(prefer_attachments),
                category,
                max(limit * 4, limit),
            ),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        connection.close()

    category_rows = [row for row in rows if row["category"] == category]
    if category != "profile" and len(category_rows) >= 2:
        rows = category_rows

    results = []
    used = 0
    seen = set()
    for row in rows:
        content = row["content"].strip()
        fingerprint = content[:240]
        if fingerprint in seen:
            continue
        projected = used + len(content)
        if results and projected > max_chars:
            break
        results.append(
            {
                "category": row["category"],
                "source": row["source"],
                "title": row["title"],
                "section": row["section"],
                "content": content,
            }
        )
        seen.add(fingerprint)
        used = projected
        if len(results) >= limit:
            break
    return results


def fts_query(query: str, category: str = "") -> str:
    words = list(CATEGORY_EXPANSIONS.get(category, ()))
    for word in WORD_RE.findall(query):
        if len(word) < 2 or word in STOP_WORDS:
            continue
        cleaned = word.replace('"', "")
        if cleaned and cleaned not in words:
            words.append(cleaned)
    return " OR ".join(f'"{word}"' for word in words[:32])


def search(
    query: str,
    *,
    db_path: Path = DEFAULT_DB,
    limit: int = 6,
    max_chars: int = 7000,
) -> list[dict]:
    if not db_path.exists():
        return []
    categories = detect_categories(fix_mojibake(query))
    if len(categories) == 1:
        return _search_category(
            query,
            category=categories[0],
            db_path=db_path,
            limit=limit,
            max_chars=max_chars,
        )

    per_category_limit = max(2, limit // len(categories))
    per_category_chars = max(1200, max_chars // len(categories))
    results = []
    for category, terms in CATEGORY_TERMS.items():
        if category not in categories:
            continue
        results.extend(
            _search_category(
                query,
                category=category,
                db_path=db_path,
                limit=per_category_limit,
                max_chars=per_category_chars,
            )
        )
    return results[:limit]


def should_retrieve_personal_context(query: str) -> bool:
    return bool(PERSONAL_TRIGGER.search(fix_mojibake(query)))


def retrieve_personal_context(
    query: str,
    *,
    db_path: Path = DEFAULT_DB,
    limit: int = 6,
    max_chars: int = 7000,
) -> str:
    if not should_retrieve_personal_context(query):
        return ""
    matches = search(query, db_path=db_path, limit=limit, max_chars=max_chars)
    if not matches:
        return ""
    blocks = []
    for match in matches:
        blocks.append(
            f"SOURCE: {match['source']} | {match['section']}\n"
            f"{match['content']}"
        )
    return "\n\n---\n\n".join(blocks)


def sync_core(root: Path, memory_dir: Path) -> dict:
    source_dir = root / "core"
    required = ("USER.md", "MEMORY.md")
    missing = [name for name in required if not (source_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing core files: {', '.join(missing)}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = root / "backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    memory_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    synced = []
    for name in required:
        destination = memory_dir / name
        if destination.exists():
            shutil.copy2(destination, backup_dir / name)
            os.chmod(backup_dir / name, 0o600)
        payload = (source_dir / name).read_text(encoding="utf-8").strip() + "\n"
        atomic_text(destination, payload)
        synced.append(str(destination))
    return {"synced": synced, "backup_dir": str(backup_dir)}


def stats(db_path: Path) -> dict:
    if not db_path.exists():
        return {"database": str(db_path), "exists": False}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        category_rows = connection.execute(
            "SELECT category, count(*) FROM chunks GROUP BY category ORDER BY category"
        ).fetchall()
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    finally:
        connection.close()
    return {
        "database": str(db_path),
        "exists": True,
        "mode": oct(db_path.stat().st_mode & 0o777),
        "metadata": metadata,
        "categories": dict(category_rows),
    }


def validate(root: Path, db_path: Path) -> dict:
    errors = []
    source_files = sorted((root / "source_chats").glob("*.json"))
    chat_files = [path for path in source_files if path.name != "manifest.json"]
    if len(chat_files) != 5:
        errors.append(f"expected 5 source chats, found {len(chat_files)}")
    dossier_files = sorted((root / "dossiers").glob("*.md"))
    attachment_text_files = sorted((root / "attachment_text").rglob("*.md"))
    attachment_binary_files = [
        path
        for path in sorted((root / "attachments").rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    ]
    if len(dossier_files) < 7:
        errors.append(f"expected at least 7 dossiers, found {len(dossier_files)}")
    for path in [
        *source_files,
        *dossier_files,
        *attachment_text_files,
        *(root / "core").glob("*.md"),
    ]:
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"secret-like value remains in {path.name}")
                break
        if MOJIBAKE_RE.search(text):
            errors.append(f"mojibake marker remains in {path.name}")
    database_stats = stats(db_path)
    if not database_stats.get("exists"):
        errors.append("personal context database is missing")
    elif int(database_stats.get("metadata", {}).get("chunk_count", "0")) < 50:
        errors.append("personal context database contains too few chunks")
    metadata = database_stats.get("metadata", {})
    if metadata.get("source_chat_count") not in {None, "5"}:
        errors.append("personal context database does not contain all 5 chats")
    if metadata.get("source_turn_count") not in {None, "99"}:
        errors.append("personal context database does not contain all 99 turns")
    if metadata.get("attachment_text_file_count") not in {
        None,
        str(len(attachment_text_files)),
    }:
        errors.append("attachment text file count does not match the index")
    if metadata.get("attachment_binary_file_count") not in {
        None,
        str(len(attachment_binary_files)),
    }:
        errors.append("attachment binary file count does not match the index")
    for name, maximum in (("USER.md", 8000), ("MEMORY.md", 5000)):
        path = root / "core" / name
        if not path.exists():
            errors.append(f"{name} is missing")
        elif len(path.read_text(encoding="utf-8")) > maximum:
            errors.append(f"{name} exceeds configured memory limit")
    result = {
        "passed": not errors,
        "errors": errors,
        "source_chat_count": len(chat_files),
        "dossier_count": len(dossier_files),
        "attachment_binary_file_count": len(attachment_binary_files),
        "attachment_text_file_count": len(attachment_text_files),
        "database": database_stats,
    }
    return result


def print_result(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--db", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("normalize")
    subparsers.add_parser("build")
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=6)
    subparsers.add_parser("stats")
    subparsers.add_parser("validate")
    subparsers.add_parser("sync-core")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root
    db_path = args.db or (root / DEFAULT_DB.name)
    if args.command == "normalize":
        print_result(normalize_exports(root))
    elif args.command == "build":
        print_result(build_index(root, db_path))
    elif args.command == "search":
        print_result(
            search(
                args.query,
                db_path=db_path,
                limit=max(1, min(args.limit, 20)),
            )
        )
    elif args.command == "stats":
        print_result(stats(db_path))
    elif args.command == "validate":
        result = validate(root, db_path)
        print_result(result)
        return 0 if result["passed"] else 1
    elif args.command == "sync-core":
        print_result(sync_core(root, MEMORY_DIR))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"passed": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
