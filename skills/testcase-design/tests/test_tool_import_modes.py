"""P1 tool imports must work as scripts and namespace-package modules."""

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "skills" / "testcase-design" / "tools"
PACKAGE = "skills.testcase-design.tools"


class ToolImportModesTests(unittest.TestCase):
    def _run(self, *args):
        result = subprocess.run(
            [sys.executable, "-B", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)

    def test_direct_script_help(self):
        for name in ("xmind", "platform_payloads"):
            with self.subTest(tool=name):
                self._run(str(TOOLS / f"{name}.py"), "--help")

    def test_namespace_package_import(self):
        code = (
            "import importlib; "
            f"p={PACKAGE!r}; "
            "art=importlib.import_module(p+'.artifacts'); "
            "xmind=importlib.import_module(p+'.xmind'); "
            "payloads=importlib.import_module(p+'.platform_payloads'); "
            "assert xmind.parse_markdown is art.parse_markdown; "
            "assert payloads.parse_markdown is art.parse_markdown; "
            "assert xmind.ArtifactError is art.ArtifactError; "
            "assert payloads.ArtifactError is art.ArtifactError"
        )
        self._run("-c", code)

    def test_namespace_module_cli(self):
        for name in ("xmind", "platform_payloads"):
            with self.subTest(tool=name):
                self._run("-m", f"{PACKAGE}.{name}", "--help")


if __name__ == "__main__":
    unittest.main()
