import json
import os
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from app.server import create_handler, seed_if_empty
from app.rag import RAGError
from app.store import connect, delete_document, list_documents


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "api.sqlite"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(db_path))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, path, method="GET", body=None):
        payload = json.dumps(body).encode() if body is not None else None
        request = Request(
            self.base + path,
            data=payload,
            method=method,
            headers={"Content-Type": "application/json"} if payload is not None else {},
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_document_lifecycle_and_search(self):
        status, added = self.request("/api/documents", "POST", {"name": "runbook.md", "content": "# Deploy\n\nRollback the release if error rates exceed five percent."})
        self.assertEqual(status, 201)
        document_id = added["id"]
        status, result = self.request("/api/ask", "POST", {"query": "When should we rollback the release?"})
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["evidence"][0]["document_id"], document_id)
        status, source = self.request(f"/api/documents/{document_id}")
        self.assertEqual(source["name"], "runbook.md")
        self.assertEqual(status, 200)
        status, removed = self.request(f"/api/documents/{document_id}", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(removed["deleted"])
        self.assertEqual(self.request("/api/ask", "POST", {"query": "rollback"})[1]["status"], "no_match")

    def test_rejects_unsupported_files(self):
        status, response = self.request("/api/documents", "POST", {"name": "program.exe", "content": "test"})
        self.assertEqual(status, 400)
        self.assertIn(".txt", response["error"])

    def test_rag_requires_server_side_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            status, health = self.request("/api/health")
            self.assertEqual(status, 200)
            self.assertFalse(health["rag_available"])
            status, response = self.request("/api/ask", "POST", {"query": "hello", "mode": "rag"})
        self.assertEqual(status, 400)
        self.assertIn("OPENAI_API_KEY", response["error"])

    def test_rag_response_is_exposed_without_key(self):
        fake = {"mode": "rag", "query": "hello", "status": "no_answer", "answer": "Not enough evidence.", "citations": [], "evidence": []}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-test-key"}):
            with patch("app.server.answer_with_sources", return_value=fake) as mocked:
                status, response = self.request("/api/ask", "POST", {"query": "hello", "mode": "rag"})
        self.assertEqual(status, 200)
        self.assertEqual(response, fake)
        self.assertEqual(mocked.call_args.args[2], "secret-test-key")
        self.assertNotIn("secret-test-key", json.dumps(response))

    def test_rag_provider_failure_returns_safe_error(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-test-key"}):
            with patch("app.server.answer_with_sources", side_effect=RAGError("secret-test-key upstream failure")):
                status, response = self.request("/api/ask", "POST", {"query": "hello", "mode": "rag"})
        self.assertEqual(status, 502)
        self.assertNotIn("secret-test-key", json.dumps(response))

    def test_sample_data_is_loaded_only_once(self):
        db_path = Path(self.temp.name) / "seed.sqlite"
        seed_if_empty(db_path)
        with closing(connect(db_path)) as db:
            ids = [item["id"] for item in list_documents(db)]
            self.assertEqual(len(ids), 3)
            for document_id in ids:
                delete_document(db, document_id)
        seed_if_empty(db_path)
        with closing(connect(db_path)) as db:
            self.assertEqual(list_documents(db), [])


if __name__ == "__main__":
    unittest.main()
