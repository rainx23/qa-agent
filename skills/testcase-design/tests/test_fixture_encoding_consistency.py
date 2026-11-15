"""Ensure public test fixtures do not retain unredacted Base64 stdout/stderr."""

import base64
import json
import unittest
from pathlib import Path


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures/p4-batch5/incremental-rejection-probes-20261107.json"
)


class FixtureEncodingConsistencyTests(unittest.TestCase):
    def test_base64_fields_match_redacted_utf8_text(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
        checked = 0

        def visit(value):
            nonlocal checked
            if isinstance(value, dict):
                for key, encoded in value.items():
                    if key.endswith("_b64") and isinstance(encoded, str):
                        text = value.get(key[:-4] + "_utf8")
                        if isinstance(text, str):
                            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
                            self.assertTrue(decoded == text, f"Mismatch for {key}")
                            checked += 1
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(fixture)
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
