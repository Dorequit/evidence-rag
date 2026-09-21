"""Small local HTTP API and web UI for EvidenceDesk (Python standard library)."""

from __future__ import annotations

import argparse
import base64
import json
import os
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .rag import RAGError, answer_with_sources
from .store import add_document, ask, connect, delete_document, get_document, list_documents


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
DEFAULT_DB = ROOT / "data" / "evidencedesk.sqlite"
SEED = ROOT / "seed"


def seed_if_empty(db_path: Path) -> None:
    with closing(connect(db_path)) as db:
        seeded = db.execute("SELECT value FROM settings WHERE key = 'seeded'").fetchone()
        if seeded:
            return
        if list_documents(db):
            with db:
                db.execute("INSERT INTO settings(key, value) VALUES ('seeded', '1')")
            return
        for path in sorted(SEED.glob("*.md")):
            add_document(db, path.name, path.read_text(encoding="utf-8"), "markdown")
        with db:
            db.execute("INSERT INTO settings(key, value) VALUES ('seeded', '1')")


def create_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "EvidenceDesk/1.0"

        def _json(self, status: int, data: object) -> None:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _body(self) -> dict:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 7_000_000:
                raise ValueError("Request must be between 1 byte and 7 MB.")
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                raise ValueError("Send application/json.")
            value = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object.")
            return value

        def _document_id(self, path: str) -> int | None:
            part = path.removeprefix("/api/documents/")
            return int(part) if part.isdigit() else None

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/health":
                return self._json(200, {"status": "ok", "default_mode": "extractive", "rag_available": bool(os.getenv("OPENAI_API_KEY"))})
            if path == "/api/documents":
                with closing(connect(db_path)) as db:
                    return self._json(200, {"documents": list_documents(db)})
            if path.startswith("/api/documents/"):
                document_id = self._document_id(path)
                if document_id is None:
                    return self._json(404, {"error": "Document not found."})
                with closing(connect(db_path)) as db:
                    document = get_document(db, document_id)
                return self._json(200, document) if document else self._json(404, {"error": "Document not found."})
            static_files = {
                "/": ("index.html", "text/html"),
                "/styles.css": ("styles.css", "text/css"),
                "/app.js": ("app.js", "text/javascript"),
                "/favicon.svg": ("favicon.svg", "image/svg+xml"),
            }
            if path in static_files:
                filename, mime = static_files[path]
                payload = (STATIC / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime + "; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self._json(404, {"error": "Not found."})

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            try:
                body = self._body()
                if path == "/api/ask":
                    query = body.get("query", "")
                    if not isinstance(query, str):
                        raise ValueError("query must be text.")
                    mode = body.get("mode", "extractive")
                    if mode not in {"extractive", "rag"}:
                        raise ValueError("mode must be extractive or rag.")
                    with closing(connect(db_path)) as db:
                        result = ask(db, query)
                    if mode == "rag":
                        api_key = os.getenv("OPENAI_API_KEY", "")
                        if not api_key:
                            return self._json(400, {"error": "RAG mode is unavailable. Set OPENAI_API_KEY on the server."})
                        return self._json(200, answer_with_sources(result["query"], result, api_key))
                    return self._json(200, result)
                if path == "/api/documents":
                    name = body.get("name", "")
                    if not isinstance(name, str):
                        raise ValueError("name must be text.")
                    extension = Path(name).suffix.lower()
                    if extension not in {".txt", ".md", ".pdf"}:
                        raise ValueError("Use a .txt, .md, or .pdf document.")
                    if extension == ".pdf":
                        if body.get("encoding") != "base64":
                            raise ValueError("PDF upload requires base64 encoding.")
                        if not isinstance(body.get("content"), str):
                            raise ValueError("PDF content must be a base64 string.")
                        try:
                            from pypdf import PdfReader
                            from pypdf.errors import PdfReadError
                        except ImportError as exc:
                            raise ValueError("PDF support needs the optional pypdf package.") from exc
                        from io import BytesIO

                        binary = base64.b64decode(body.get("content", ""), validate=True)
                        if len(binary) > 5_000_000:
                            raise ValueError("PDF exceeds the 5 MB limit.")
                        try:
                            reader = PdfReader(BytesIO(binary))
                        except PdfReadError as exc:
                            raise ValueError("PDF could not be read.") from exc
                        if len(reader.pages) > 100:
                            raise ValueError("PDF exceeds the 100-page limit.")
                        content = "\f".join(page.extract_text() or "" for page in reader.pages)
                        kind = "pdf"
                    else:
                        content = body.get("content", "")
                        if not isinstance(content, str):
                            raise ValueError("content must be text.")
                        kind = "markdown" if extension == ".md" else "text"
                    with closing(connect(db_path)) as db:
                        document_id, created = add_document(db, name, content, kind)
                    return self._json(201 if created else 200, {"id": document_id, "created": created})
                return self._json(404, {"error": "Not found."})
            except RAGError:
                return self._json(502, {"error": "The answer service is unavailable. Try the offline evidence search."})
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError, base64.binascii.Error) as exc:
                return self._json(400, {"error": str(exc)})

        def do_DELETE(self) -> None:
            path = urlsplit(self.path).path
            if not path.startswith("/api/documents/"):
                return self._json(404, {"error": "Not found."})
            document_id = self._document_id(path)
            if document_id is None:
                return self._json(404, {"error": "Document not found."})
            with closing(connect(db_path)) as db:
                deleted = delete_document(db, document_id)
            return self._json(200, {"deleted": True}) if deleted else self._json(404, {"error": "Document not found."})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EvidenceDesk locally")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=Path(os.getenv("EVIDENCEDESK_DB", DEFAULT_DB)))
    args = parser.parse_args()
    seed_if_empty(args.db)
    server = ThreadingHTTPServer((args.host, args.port), create_handler(args.db))
    print(f"EvidenceDesk running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
