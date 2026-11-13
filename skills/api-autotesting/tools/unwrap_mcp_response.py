#!/usr/bin/env python3
"""Normalize an explicitly selected MCP content envelope without losing metadata.

Raw JSON is preserved by default. Use --mode mcp-content only when the input is
known to be a persisted MCP content result. This utility performs local parsing
only and never accesses the network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

_MAX_WRAPPER_DEPTH = 3
_MODES = ("raw-json", "mcp-content")


def _windows_long_path(absolute_path: str) -> str:
    """Add the Windows extended-length prefix to a long absolute path."""
    if absolute_path.startswith("\\\\?\\") or len(absolute_path) < 240:
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def _io_path(value: str) -> str:
    """Normalize a path and apply Windows long-path handling when needed."""
    if os.name == "nt" and value.startswith("\\\\?\\"):
        return value
    absolute = os.path.abspath(value)
    if os.name == "nt":
        return _windows_long_path(absolute)
    return absolute


def _is_content_block(value: Any) -> bool:
    """A content block has a string type; extra metadata fields are allowed."""
    return isinstance(value, dict) and isinstance(value.get("type"), str)


def _normalize_content_block(block: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON text when possible while preserving every block field."""
    block_type = block.get("type")
    if not isinstance(block_type, str):
        raise ValueError("MCP content block type must be a string")

    normalized = dict(block)
    if block_type == "text":
        text_value = block.get("text")
        if not isinstance(text_value, str):
            raise ValueError("MCP text content block must contain string text")
        try:
            normalized["text"] = json.loads(text_value)
        except json.JSONDecodeError:
            normalized["text"] = text_value
    return normalized


def _normalize_content_list(blocks: list[Any]) -> list[dict[str, Any]]:
    """Normalize text blocks and preserve non-text/unknown blocks unchanged."""
    normalized: list[dict[str, Any]] = []
    for block in blocks:
        if not _is_content_block(block):
            raise ValueError("MCP content must be a list of objects with string type fields")
        normalized.append(_normalize_content_block(block))
    return normalized


def _normalize_mcp_envelope(value: Any, depth: int = 0) -> tuple[Any, bool]:
    """Normalize only explicit MCP content/result envelopes; retain outer metadata."""
    if depth > _MAX_WRAPPER_DEPTH:
        raise ValueError("MCP result wrapper nesting exceeds the supported depth")

    if isinstance(value, dict):
        if "content" in value:
            content = value["content"]
            if not isinstance(content, list):
                raise ValueError("MCP content field must be a list")
            normalized = dict(value)
            normalized["content"] = _normalize_content_list(content)
            return normalized, True

        if "result" in value:
            result = value["result"]
            if not isinstance(result, (dict, list)):
                raise ValueError("MCP result field must contain an object or content list")
            normalized_result, found = _normalize_mcp_envelope(result, depth + 1)
            if found:
                normalized = dict(value)
                normalized["result"] = normalized_result
                return normalized, True
            raise ValueError("MCP result field does not contain a recognized content envelope")

        if _is_content_block(value):
            return _normalize_content_block(value), True

        raise ValueError("input is not a recognized MCP content envelope")

    if isinstance(value, list):
        return _normalize_content_list(value), True

    raise ValueError("input is not a recognized MCP content envelope")


def decode_payload(raw_text: str, mode: str = "raw-json") -> tuple[Any, bool]:
    """Decode raw JSON unchanged or normalize a caller-selected MCP envelope."""
    if mode not in _MODES:
        raise ValueError(f"unsupported mode: {mode}")

    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError("input is not valid JSON") from exc

    if mode == "raw-json":
        return value, False
    return _normalize_mcp_envelope(value)


def summarize_payload(payload: Any, input_bytes: int, normalized: bool) -> dict[str, Any]:
    """Return metadata only; never include payload values or field names."""
    if isinstance(payload, dict):
        kind = "json_object"
        count = len(payload)
    elif isinstance(payload, list):
        kind = "json_array"
        count = len(payload)
    else:
        kind = type(payload).__name__
        count = None

    return {
        "input_bytes": input_bytes,
        "mcp_content_normalized": normalized,
        "payload_kind": kind,
        "top_level_count": count,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_output_roots() -> list[Path]:
    """Only permit ignored workspace scratch output or the OS temp directory."""
    project_root = Path(__file__).resolve().parents[3]
    return [
        (project_root / ".qa-work" / "api-autotesting").resolve(strict=False),
        Path(tempfile.gettempdir()).resolve(strict=False),
    ]


def _validate_output_path(
    output_path: str,
    allowed_roots: Iterable[Path] | None = None,
) -> Path:
    target = Path(_io_path(output_path)).resolve(strict=False)
    roots = list(allowed_roots) if allowed_roots is not None else _allowed_output_roots()
    resolved_roots = [Path(root).resolve(strict=False) for root in roots]
    if not any(_is_within(target, root) for root in resolved_roots):
        raise ValueError("output path must be under .qa-work/api-autotesting or the OS temp directory")
    return target


def write_payload(
    payload: Any,
    input_path: str,
    output_path: str,
    allowed_output_roots: Iterable[Path] | None = None,
) -> None:
    """Write normalized JSON to an approved path without replacing any file."""
    source_path = Path(_io_path(input_path)).resolve(strict=True)
    if not source_path.is_file():
        raise ValueError("input path must refer to a regular file")

    target_path = _validate_output_path(output_path, allowed_output_roots)
    if source_path == target_path:
        raise ValueError("output path must differ from input path")

    if target_path.exists() and os.path.samefile(source_path, target_path):
        raise ValueError("output path must not refer to the input file")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    # Resolve again after directory creation so a pre-existing symlink cannot
    # redirect output outside the approved scratch/temp roots.
    target_path = _validate_output_path(str(target_path), allowed_output_roots)
    if source_path == target_path:
        raise ValueError("output path must differ from input path")
    if target_path.exists() and os.path.samefile(source_path, target_path):
        raise ValueError("output path must not refer to the input file")

    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with target_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Exact input path returned by the MCP/tool runtime")
    parser.add_argument(
        "--mode",
        choices=_MODES,
        default="raw-json",
        help="raw-json preserves the complete JSON; mcp-content normalizes an explicit MCP content envelope",
    )
    parser.add_argument(
        "--output",
        help="Optional normalized JSON output under .qa-work/api-autotesting or the OS temp directory",
    )
    args = parser.parse_args(argv)

    try:
        input_path = Path(_io_path(args.input)).resolve(strict=True)
        if not input_path.is_file():
            raise ValueError("input path must refer to a regular file")
        with input_path.open("r", encoding="utf-8-sig") as handle:
            raw_text = handle.read()

        payload, normalized = decode_payload(raw_text, mode=args.mode)
        if args.output:
            write_payload(payload, str(input_path), args.output)

        summary = summarize_payload(payload, len(raw_text.encode("utf-8")), normalized)
        summary["output_written"] = bool(args.output)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
