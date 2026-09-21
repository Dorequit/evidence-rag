"""SQLite-backed ingestion and extractive retrieval. No model or network required."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path


STOP_WORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "can", "do", "for", "from",
    "how", "i", "in", "is", "it", "of", "on", "or", "our", "the", "to", "was", "what",
    "when", "where", "which", "who", "why", "with", "you", "your", "we", "should",
    "often", "does", "have", "de", "del", "el",
    "en", "es", "la", "las", "los", "para", "por", "que", "se", "un", "una", "y",
}


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            heading TEXT NOT NULL,
            page INTEGER NOT NULL,
            body TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            body, heading, content='chunks', content_rowid='id',
            tokenize='porter unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, body, heading)
            VALUES (new.id, new.body, new.heading);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, body, heading)
            VALUES ('delete', old.id, old.body, old.heading);
        END;
        """
    )
    # Upgrade indexes created by an earlier local version without losing documents.
    fts_schema = db.execute("SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'").fetchone()["sql"]
    if "porter unicode61" not in fts_schema:
        db.executescript(
            """
            DROP TRIGGER chunks_insert;
            DROP TRIGGER chunks_delete;
            DROP TABLE chunks_fts;
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                body, heading, content='chunks', content_rowid='id',
                tokenize='porter unicode61 remove_diacritics 2'
            );
            INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild');
            CREATE TRIGGER chunks_insert AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, body, heading)
                VALUES (new.id, new.body, new.heading);
            END;
            CREATE TRIGGER chunks_delete AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, body, heading)
                VALUES ('delete', old.id, old.body, old.heading);
            END;
            """
        )
    return db


def _split_long(text: str, limit: int = 780) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ0-9])", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        # Very long log lines still need to fit a single search result.
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if len(current) + len(sentence) + 1 > limit and current:
            parts.append(current)
            current = ""
        current = (current + " " + sentence).strip()
    if current:
        parts.append(current)
    return parts


def split_chunks(content: str) -> list[tuple[str, int, str]]:
    """Keep headings and PDF page numbers beside the extracted passages."""
    chunks: list[tuple[str, int, str]] = []
    heading = "Overview"
    for page, page_text in enumerate(content.split("\f"), start=1):
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                paragraph = " ".join(buffer).strip()
                for part in _split_long(paragraph):
                    if part:
                        chunks.append((heading, page, part))
                buffer.clear()

        for line in page_text.splitlines():
            line = line.strip()
            if not line:
                flush()
            elif line.startswith("#") and re.match(r"^#{1,6}\s+", line):
                flush()
                heading = re.sub(r"^#{1,6}\s+", "", line).strip()
            else:
                buffer.append(line)
        flush()
    return chunks


def add_document(db: sqlite3.Connection, name: str, content: str, kind: str = "text") -> tuple[int, bool]:
    name = Path(name).name.strip()[:150]
    content = content.strip()
    if not name or not content:
        raise ValueError("A document needs a name and non-empty text.")
    if len(content) > 5_000_000:
        raise ValueError("Extracted text exceeds the 5 MB limit.")
    chunks = split_chunks(content)
    if not chunks:
        raise ValueError("No searchable text was found in this document.")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    prior = db.execute("SELECT id FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    if prior:
        return prior["id"], False
    with db:
        cursor = db.execute(
            "INSERT INTO documents(name, kind, sha256, content) VALUES (?, ?, ?, ?)",
            (name, kind, digest, content),
        )
        document_id = cursor.lastrowid
        db.executemany(
            "INSERT INTO chunks(document_id, heading, page, body) VALUES (?, ?, ?, ?)",
            [(document_id, heading, page, body) for heading, page, body in chunks],
        )
    return document_id, True


def list_documents(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute(
        """SELECT d.id, d.name, d.kind, d.created_at, COUNT(c.id) AS chunks
           FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
           GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC"""
    ).fetchall()
    return [dict(row) for row in rows]


def get_document(db: sqlite3.Connection, document_id: int) -> dict | None:
    row = db.execute(
        "SELECT id, name, kind, content, created_at FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    return dict(row) if row else None


def delete_document(db: sqlite3.Connection, document_id: int) -> bool:
    with db:
        cursor = db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return cursor.rowcount > 0


def _terms(query: str) -> list[str]:
    words = re.findall(r"[^\W_]+", query.lower(), re.UNICODE)
    terms = [word for word in words if len(word) > 1 and word not in STOP_WORDS]
    return list(dict.fromkeys(terms))[:12]


def _match_count(text: str, terms: list[str]) -> int:
    text = text.lower()
    def variants(term: str) -> tuple[str, ...]:
        if term.endswith("ed") and len(term) > 5:
            return term, term[:-2]
        if term.endswith("s") and len(term) > 4:
            return term, term[:-1]
        return (term,)
    return sum(any(part in text for part in variants(term)) for term in terms)


def _best_quote(body: str, terms: list[str]) -> str:
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ0-9])", body)
    if not sentences:
        return body[:420]
    best_index = max(range(len(sentences)), key=lambda index: _match_count(sentences[index], terms))
    quote = sentences[best_index]
    if best_index + 1 < len(sentences) and len(quote) + len(sentences[best_index + 1]) + 1 <= 420:
        quote += " " + sentences[best_index + 1]
    return quote[:420].strip()


def ask(db: sqlite3.Connection, query: str, limit: int = 5) -> dict:
    """Return verbatim evidence. Never synthesize unsupported claims."""
    query = query.strip()[:300]
    terms = _terms(query)
    if not terms:
        return {"query": query, "status": "empty_query", "evidence": []}
    expression = " OR ".join('"' + term.replace('"', '') + '"' for term in terms)
    rows = db.execute(
        """SELECT c.id, c.document_id, c.heading, c.page, c.body, d.name,
                  bm25(chunks_fts, 1.0, 2.2) AS score
           FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
           JOIN documents d ON d.id = c.document_id
           WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?""",
        (expression, min(max(limit * 4, 8), 40)),
    ).fetchall()
    evidence = []
    for row in rows:
        quote = _best_quote(row["body"], terms)
        overlap = _match_count(row["heading"] + " " + quote, terms)
        if overlap < min(2, len(terms)):
            continue
        evidence.append(
            {
                "citation": len(evidence) + 1,
                "document_id": row["document_id"],
                "chunk_id": row["id"],
                "source": row["name"],
                "heading": row["heading"],
                "page": row["page"],
                "quote": quote,
                "context": row["body"],
            }
        )
        if len(evidence) >= limit:
            break
    return {"query": query, "status": "found" if evidence else "no_match", "evidence": evidence}
