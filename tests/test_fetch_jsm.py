import unittest

from scripts.fetch_jsm import adf_to_text, redact


class FetchJsmTests(unittest.TestCase):
    def test_adf_to_text(self):
        adf = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "質問です"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "回答です"}]},
            ],
        }
        self.assertIn("質問です", adf_to_text(adf))
        self.assertIn("回答です", adf_to_text(adf))

    def test_redacts_common_secrets_and_email(self):
        value = "email=user@example.com token: abcdef123 AKIAABCDEFGHIJKLMNOP"
        redacted = redact(value)
        self.assertNotIn("user@example.com", redacted)
        self.assertNotIn("abcdef123", redacted)
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", redacted)


if __name__ == "__main__":
    unittest.main()

