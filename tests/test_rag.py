import json
import io
import unittest
from urllib.error import HTTPError

from app.rag import (
    MAX_SOURCE_CHARS,
    NO_ANSWER,
    RAGError,
    answer_with_sources,
    send_response,
)


def model_output(status, answer="", citations=None):
    value = {"status": status, "answer": answer, "citations": citations or []}
    return {
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}],
    }


def retrieval(context="Rotate the key every 90 days."):
    return {
        "query": "When should we rotate the key?",
        "status": "found",
        "evidence": [{
            "citation": 1,
            "document_id": 7,
            "chunk_id": 12,
            "source": "operations.md",
            "heading": "Key rotation",
            "page": 1,
            "quote": "Rotate the key every 90 days.",
            "context": context,
        }],
    }


class RAGTests(unittest.TestCase):
    def test_grounded_answer_uses_bounded_context_and_valid_citation(self):
        calls = []

        def transport(payload, key):
            calls.append((payload, key))
            return model_output("answer", "Rotate it every 90 days [S1].", ["S1"])

        result = answer_with_sources("When should we rotate the key?", retrieval("Rotate the key every 90 days. " * 100), "secret-test-key", transport)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["citations"], ["S1"])
        self.assertEqual(result["evidence"][0]["source_id"], "S1")
        payload, key = calls[0]
        self.assertEqual(key, "secret-test-key")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        sent = json.loads(payload["input"])
        self.assertLessEqual(len(sent["sources"][0]["passage"]), MAX_SOURCE_CHARS)
        self.assertNotIn("secret-test-key", json.dumps(payload))

    def test_no_retrieval_match_never_calls_api(self):
        def forbidden(_payload, _key):
            self.fail("The API must not be called without evidence")

        result = answer_with_sources("unrelated", {"status": "no_match", "evidence": []}, "dummy", forbidden)
        self.assertEqual(result["status"], "no_answer")
        self.assertEqual(result["answer"], NO_ANSWER)

    def test_model_can_abstain_even_with_lexical_match(self):
        result = answer_with_sources(
            "What is the root cause?", retrieval(), "dummy",
            lambda _payload, _key: model_output("no_answer"),
        )
        self.assertEqual(result["status"], "no_answer")
        self.assertEqual(result["citations"], [])

    def test_unknown_or_missing_inline_citation_is_rejected(self):
        for answer, citations in [("Unsupported [S9].", ["S9"]), ("No marker here.", ["S1"])]:
            with self.subTest(answer=answer):
                result = answer_with_sources(
                    "When?", retrieval(), "dummy",
                    lambda _payload, _key: model_output("answer", answer, citations),
                )
                self.assertEqual(result["status"], "no_answer")

    def test_provider_error_is_sanitized(self):
        def fail(_request, timeout):
            raise HTTPError("https://api.openai.com/v1/responses", 401, "secret-test-key invalid", None, None)

        with self.assertRaises(RAGError) as caught:
            send_response({"model": "gpt-4o-mini"}, "secret-test-key", opener=fail)
        self.assertNotIn("secret-test-key", str(caught.exception))

    def test_transport_posts_to_responses_api_with_key_in_header_only(self):
        captured = {}

        def fake_open(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["body"] = request.data.decode()
            captured["timeout"] = timeout
            return io.BytesIO(json.dumps(model_output("no_answer")).encode())

        response = send_response({"model": "gpt-4o-mini", "store": False}, "secret-test-key", opener=fake_open)
        self.assertEqual(response["status"], "completed")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(captured["authorization"], "Bearer secret-test-key")
        self.assertNotIn("secret-test-key", captured["body"])
        self.assertLessEqual(captured["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
