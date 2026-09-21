import tempfile
import unittest
from pathlib import Path

from app.store import add_document, ask, connect, delete_document, list_documents


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "test.sqlite")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_result_is_a_verbatim_citation_from_relevant_source(self):
        add_document(
            self.db,
            "security.md",
            "# Security\n\n## Key rotation\n\nRotate API keys every 90 days. Revoke the old key after verifying the new one.",
            "markdown",
        )
        add_document(
            self.db,
            "food.md",
            "# Kitchen\n\nStore fresh basil in a glass of water.",
            "markdown",
        )
        result = ask(self.db, "When should we rotate API keys?")
        self.assertEqual(result["status"], "found")
        first = result["evidence"][0]
        self.assertEqual(first["source"], "security.md")
        self.assertEqual(first["heading"], "Key rotation")
        self.assertIn("Rotate API keys every 90 days.", first["quote"])
        self.assertIn(first["quote"], first["context"])
        self.assertTrue(all(item["source"] != "food.md" for item in result["evidence"]))

    def test_no_match_does_not_invent_an_answer(self):
        add_document(self.db, "notes.txt", "The office opens on weekdays.")
        result = ask(self.db, "What is the PostgreSQL failover process?")
        self.assertEqual(result, {"query": "What is the PostgreSQL failover process?", "status": "no_match", "evidence": []})

    def test_duplicate_ingestion_and_deletion_update_index(self):
        first_id, created = add_document(self.db, "first.txt", "A unique satellite telemetry protocol.")
        second_id, second_created = add_document(self.db, "copy.txt", "A unique satellite telemetry protocol.")
        self.assertTrue(created)
        self.assertFalse(second_created)
        self.assertEqual(first_id, second_id)
        self.assertEqual(len(list_documents(self.db)), 1)
        self.assertEqual(ask(self.db, "satellite telemetry")["status"], "found")
        self.assertTrue(delete_document(self.db, first_id))
        self.assertEqual(ask(self.db, "satellite telemetry")["status"], "no_match")

    def test_pdf_page_marker_is_kept_for_citation(self):
        add_document(self.db, "manual.pdf", "Introduction.\fBackup restore validation happens monthly.", "pdf")
        result = ask(self.db, "restore validation")
        self.assertEqual(result["evidence"][0]["page"], 2)

    def test_sample_queries_surface_actionable_passages(self):
        seed_dir = Path(__file__).resolve().parents[1] / "seed"
        for path in seed_dir.glob("*.md"):
            add_document(self.db, path.name, path.read_text(encoding="utf-8"), "markdown")
        backups = ask(self.db, "How often are backups restored in tests?")
        self.assertIn("once a month", backups["evidence"][0]["quote"])
        incident = ask(self.db, "What is the incident escalation process?")
        self.assertIn("on-call engineer", incident["evidence"][0]["quote"])


if __name__ == "__main__":
    unittest.main()
