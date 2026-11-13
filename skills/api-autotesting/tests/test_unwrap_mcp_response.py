import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "unwrap_mcp_response.py"
SPEC = importlib.util.spec_from_file_location("unwrap_mcp_response", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DecodePayloadTests(unittest.TestCase):
    def test_raw_json_object_with_type_text_and_extra_fields_is_preserved(self):
        raw = '{"type":"text","text":"keep-me","id":123}'
        payload, normalized = MODULE.decode_payload(raw)
        self.assertEqual(payload, {"type": "text", "text": "keep-me", "id": 123})
        self.assertFalse(normalized)

    def test_raw_business_array_with_image_type_is_preserved(self):
        raw = '[{"type":"image","business_value":"keep"}]'
        payload, normalized = MODULE.decode_payload(raw)
        self.assertEqual(payload, [{"type": "image", "business_value": "keep"}])
        self.assertFalse(normalized)

    def test_explicit_mcp_content_preserves_block_metadata(self):
        raw = json.dumps({
            "content": [
                {"type": "text", "text": '{"ok":true}', "id": 123},
                {"type": "image", "data": "synthetic-image", "id": 456},
            ],
            "isError": False,
            "trace": "synthetic-trace",
        })
        payload, normalized = MODULE.decode_payload(raw, mode="mcp-content")
        self.assertTrue(normalized)
        self.assertEqual(payload["content"][0], {"type": "text", "text": {"ok": True}, "id": 123})
        self.assertEqual(payload["content"][1], {"type": "image", "data": "synthetic-image", "id": 456})
        self.assertFalse(payload["isError"])
        self.assertEqual(payload["trace"], "synthetic-trace")

    def test_mcp_content_preserves_business_object_inside_text(self):
        business = {"type": "text", "text": "keep-me", "id": 123}
        raw = json.dumps({"content": [{"type": "text", "text": json.dumps(business)}]})
        payload, _ = MODULE.decode_payload(raw, mode="mcp-content")
        self.assertEqual(payload["content"][0]["text"], business)

    def test_bare_mcp_content_list_is_supported(self):
        raw = json.dumps([{"type": "text", "text": '{"value":7}', "id": "block-1"}])
        payload, normalized = MODULE.decode_payload(raw, mode="mcp-content")
        self.assertTrue(normalized)
        self.assertEqual(payload, [{"type": "text", "text": {"value": 7}, "id": "block-1"}])

    def test_single_mcp_content_block_is_supported(self):
        raw = json.dumps({"type": "text", "text": '{"value":7}', "id": 9})
        payload, normalized = MODULE.decode_payload(raw, mode="mcp-content")
        self.assertTrue(normalized)
        self.assertEqual(payload, {"type": "text", "text": {"value": 7}, "id": 9})

    def test_standard_result_content_envelope_is_supported(self):
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": "request-1",
            "result": {"content": [{"type": "text", "text": '{"ok":true}'}], "isError": False},
        })
        payload, normalized = MODULE.decode_payload(raw, mode="mcp-content")
        self.assertTrue(normalized)
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], "request-1")
        self.assertEqual(payload["result"]["content"][0]["text"], {"ok": True})

    def test_nested_result_envelope_within_depth_limit_is_supported(self):
        value = {"content": [{"type": "text", "text": "plain"}]}
        for _ in range(MODULE._MAX_WRAPPER_DEPTH):
            value = {"result": value}
        payload, normalized = MODULE.decode_payload(json.dumps(value), mode="mcp-content")
        self.assertTrue(normalized)
        self.assertEqual(payload["result"]["result"]["result"]["content"][0]["text"], "plain")

    def test_nested_result_envelope_over_depth_limit_is_rejected(self):
        value = {"content": [{"type": "text", "text": "plain"}]}
        for _ in range(MODULE._MAX_WRAPPER_DEPTH + 1):
            value = {"result": value}
        with self.assertRaisesRegex(ValueError, "nesting exceeds"):
            MODULE.decode_payload(json.dumps(value), mode="mcp-content")

    def test_unhashable_block_type_is_a_controlled_value_error(self):
        raw = '[{"type":[],"text":"x"}]'
        with self.assertRaisesRegex(ValueError, "string type"):
            MODULE.decode_payload(raw, mode="mcp-content")
        payload, _ = MODULE.decode_payload(raw, mode="raw-json")
        self.assertEqual(payload, [{"type": [], "text": "x"}])

    def test_malformed_content_envelope_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "must be a list"):
            MODULE.decode_payload('{"content":{"type":"text","text":"x"}}', mode="mcp-content")

    def test_invalid_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            MODULE.decode_payload("not-json")

    def test_summary_does_not_include_payload_values_or_keys(self):
        payload, normalized = MODULE.decode_payload('{"secret_value":"do-not-print"}')
        summary = MODULE.summarize_payload(payload, 40, normalized)
        serialized = json.dumps(summary)
        self.assertNotIn("do-not-print", serialized)
        self.assertNotIn("secret_value", serialized)
        self.assertEqual(summary["payload_kind"], "json_object")
        self.assertEqual(summary["top_level_count"], 1)


class PathSafetyTests(unittest.TestCase):
    def test_windows_long_path_prefix_for_drive_path(self):
        path = "C:\\" + ("long\\" * 50) + "file.json"
        result = MODULE._windows_long_path(path)
        self.assertTrue(result.startswith("\\\\?\\C:\\"))

    def test_windows_long_path_prefix_for_unc_path(self):
        path = "\\\\server\\share\\" + ("long\\" * 50) + "file.json"
        result = MODULE._windows_long_path(path)
        self.assertTrue(result.startswith("\\\\?\\UNC\\server\\share\\"))

    def test_existing_windows_prefix_is_not_duplicated(self):
        path = "\\\\?\\C:\\already-prefixed.json"
        self.assertEqual(MODULE._windows_long_path(path), path)

    def test_io_path_keeps_existing_windows_extended_prefix(self):
        path = "\\\\?\\C:\\already-prefixed.json"
        with mock.patch.object(MODULE.os, "name", "nt"):
            self.assertEqual(MODULE._io_path(path), path)

    def test_short_windows_path_is_not_prefixed(self):
        path = "C:\\short\\file.json"
        self.assertEqual(MODULE._windows_long_path(path), path)

    def test_output_outside_approved_roots_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            outside = Path(directory) / "outside" / "out.json"
            with self.assertRaisesRegex(ValueError, "output path must be under"):
                MODULE._validate_output_path(str(outside), [root])

    def test_output_inside_approved_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            target = root / "nested" / "out.json"
            result = MODULE._validate_output_path(str(target), [root])
            self.assertEqual(result, target.resolve(strict=False))

    def test_input_output_path_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            source.write_text('{"ok":true}', encoding="utf-8")
            alias = source.parent / "." / source.name
            with self.assertRaisesRegex(ValueError, "differ from input"):
                MODULE.write_payload({"ok": True}, str(source), str(alias), [Path(directory)])

    def test_output_is_created_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            root.mkdir()
            source = Path(directory) / "source.json"
            source.write_text('{"ok":true}', encoding="utf-8")
            output = root / "normalized.json"
            MODULE.write_payload({"ok": True}, str(source), str(output), [root])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"ok": True})
            with self.assertRaises(FileExistsError):
                MODULE.write_payload({"ok": True}, str(source), str(output), [root])

    def test_symlink_alias_to_input_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            source.write_text('{"ok":true}', encoding="utf-8")
            alias = Path(directory) / "source-link.json"
            try:
                alias.symlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            with self.assertRaisesRegex(ValueError, "differ from input"):
                MODULE.write_payload({"ok": True}, str(source), str(alias), [Path(directory)])


    def test_hardlink_alias_to_input_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            source.write_text('{"ok":true}', encoding="utf-8")
            alias = Path(directory) / "source-hardlink.json"
            try:
                os.link(source, alias)
            except OSError:
                self.skipTest("hardlink creation is unavailable")
            with self.assertRaisesRegex(ValueError, "must not refer to the input"):
                MODULE.write_payload({"ok": True}, str(source), str(alias), [Path(directory)])

class CliTests(unittest.TestCase):
    def _run_cli(self, args):
        return subprocess.run(
            [sys.executable, str(MODULE_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )

    def test_cli_normalizes_explicit_mcp_content_without_printing_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "mcp.json"
            payload_marker = "synthetic-private-payload"
            source.write_text(
                json.dumps({"content": [{"type": "text", "text": json.dumps({"sample_value": payload_marker})}]}),
                encoding="utf-8",
            )
            result = self._run_cli([str(source), "--mode", "mcp-content"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(payload_marker, result.stdout)
            self.assertNotIn("sample_value", result.stdout)
            summary = json.loads(result.stdout)
            self.assertTrue(summary["mcp_content_normalized"])

    def test_cli_invalid_encoding_returns_controlled_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.json"
            source.write_bytes(b"\xff\xfe\xff")
            result = self._run_cli([str(source)])
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("ERROR: UnicodeDecodeError:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cli_invalid_mcp_envelope_returns_controlled_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "wrong.json"
            source.write_text('{"ordinary":"business-object"}', encoding="utf-8")
            result = self._run_cli([str(source), "--mode", "mcp-content"])
            self.assertEqual(result.returncode, 2)
            self.assertIn("ERROR: ValueError:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cli_missing_input_uses_argparse_error(self):
        result = self._run_cli([])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr.lower())

    def test_cli_rejects_output_outside_approved_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            source.write_text('{"ok":true}', encoding="utf-8")
            project_root = Path(__file__).resolve().parents[3]
            output = project_root / (".qa-parser-outside-" + str(os.getpid()) + ".json")
            self.assertFalse(output.exists())
            result = self._run_cli([str(source), "--output", str(output)])
            self.assertEqual(result.returncode, 2)
            self.assertIn("output path must be under", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
