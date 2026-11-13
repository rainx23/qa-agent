"""Focused tests for identity, revision and version-history primitives."""
import copy
import hashlib
import importlib.util
import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import artifacts  # noqa: E402
import manifest  # noqa: E402
import xmind  # noqa: E402




REQ_ID = "900661"
CASE_A = "QA-900661-0123456789"
CASE_B = "QA-900661-abcdef1234"
MD_ONE = """# 900661｜示例需求

## 核心业务
### 查询后展示匹配结果
<!-- qa_case_id: QA-900661-0123456789 -->
- **优先级**：P1
1. **操作**：进入页面并查询
   - **预期**：展示匹配结果
"""


def parsed_with(*case_ids):
    cases = []
    for index, case_id in enumerate(case_ids, 1):
        cases.append({
            "title": f"场景{index}",
            "case_id": case_id,
            "priority": "P1",
            "precondition": None,
            "test_data": None,
            "steps": [{"action": "执行查询", "expected": ["展示正确结果"]}],
        })
    return {"requirement": {"id": REQ_ID, "name": "示例需求"},
            "groups": [{"name": "核心业务", "cases": cases}] if cases else []}


def snapshot_item(case_id=CASE_A, revision=1, status="unchanged", fingerprint=None):
    return {
        "case_id": case_id,
        "revision": revision,
        "status": status,
        "content_sha256": fingerprint or hashlib.sha256(case_id.encode()).hexdigest(),
    }


def make_manifest(version_id, artifacts_list=None, snapshot=None, changes=None):
    date = version_id[:8]
    data = {
        "schema_version": "1",
        "requirement": {"id": REQ_ID, "name": "示例需求"},
        "version_id": version_id,
        "created_at": f"{date[:4]}-{date[4:6]}-{date[6:8]}T10:00:00+08:00",
        "delivery_status": "complete",
        "artifacts": artifacts_list or [{
            "category": "sql", "role": "query",
            "path": f"sql/{version_id}/query.sql",
            "source_version": version_id, "change": "added",
            "sha256": hashlib.sha256(b"payload").hexdigest(),
        }],
        "case_snapshot": snapshot or [],
        "case_count": sum(x["status"] != "retired" for x in (snapshot or [])),
        "retired_case_count": sum(x["status"] == "retired" for x in (snapshot or [])),
        "validation": {},
    }
    if changes is not None:
        data["case_changes"] = changes
    return data


def write_manifest(root, data, payloads=None):
    version_path = Path(root) / "versions" / data["version_id"]
    version_path.mkdir(parents=True, exist_ok=True)
    for relative, payload in (payloads or {}).items():
        target = Path(root) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    target = version_path / "manifest.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def publish_for_test(*args, **kwargs):
    """Supply the current baseline explicitly for low-level unit-test publishers."""
    root = Path(args[0] if args else kwargs["requirement_root"])
    if "expected_base_version" not in kwargs:
        versions = manifest._version_directory_ids(root) if root.exists() else set()
        kwargs["expected_base_version"] = (
            max(versions, key=manifest._version_parts) if versions else None
        )
    return manifest.publish_version(*args, **kwargs)


def _concurrent_publish_worker(
    name, root, staged_artifacts, created_at, expected_base_version,
    result_queue, lock_acquired=None, release_lock=None, attempted=None,
):
    if lock_acquired is not None:
        original = manifest._publish_version_locked

        def pause_after_lock(*args, **kwargs):
            lock_acquired.set()
            if not release_lock.wait(20):
                raise RuntimeError("test did not release publisher lock")
            return original(*args, **kwargs)

        manifest._publish_version_locked = pause_after_lock

    if attempted is not None:
        attempted.set()
    try:
        result = manifest.publish_version(
            root, REQ_ID, "示例需求", staged_artifacts,
            created_at=created_at,
            expected_base_version=expected_base_version,
        )
        result_queue.put({
            "name": name, "result": "PASS", "version_id": result["version_id"],
        })
    except Exception as exc:
        result_queue.put({"name": name, "result": "FAIL", "error": str(exc)})


class IdentityAndRevisionTests(unittest.TestCase):
    def test_requirement_directory_name_sanitizes_windows_characters(self):
        expected = "900661-模拟模块_环节_优化"
        self.assertEqual(
            manifest.requirement_directory_name(REQ_ID, "模拟模块/环节:优化?"),
            expected,
        )
        with self.assertRaisesRegex(manifest.ManifestError, "清理后为空"):
            manifest.requirement_directory_name(REQ_ID, "///")
        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["directory-name", REQ_ID, "模拟模块/环节:优化?"])
        self.assertEqual(status, 0)
        self.assertTrue(output.getvalue().isascii())
        self.assertEqual(json.loads(output.getvalue())["directory_name"], expected)

    def test_module_directory_and_archive_path_preserve_original_bracketed_title(self):
        requirement_name = "【模拟模块】示例查询条件调整"
        self.assertEqual(manifest.module_directory_name(requirement_name), "【模拟模块】")
        self.assertEqual(
            manifest.requirement_archive_relative_path("900548", requirement_name),
            "【模拟模块】/900548-【模拟模块】示例查询条件调整",
        )
        self.assertEqual(
            manifest.module_directory_name("前缀【示例子模块】后缀【模拟模块】"),
            "【示例子模块】",
        )
        self.assertEqual(manifest.module_directory_name("没有模块标识的需求"), "【未分类】")
        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["directory-name", "900548", requirement_name])
        self.assertEqual(status, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["module_name"], "【模拟模块】")
        self.assertEqual(
            payload["archive_relative_path"],
            "【模拟模块】/900548-【模拟模块】示例查询条件调整",
        )

    def test_safe_relative_path_rejects_windows_normalized_components(self):
        for value in (
            "sql/.. /.. /escape.txt",
            "sql/escape.txt.",
            "sql/escape.txt ",
            "sql/CON.txt",
        ):
            with self.subTest(value=value):
                with self.assertRaises(manifest.ManifestError):
                    manifest._safe_relative_path(value, "test.path")

    def test_generated_ids_have_required_shape_and_are_unique(self):
        values = manifest.generate_case_ids(REQ_ID, count=100)
        self.assertEqual(len(values), len(set(values)))
        self.assertTrue(all(manifest.CASE_ID_RE.fullmatch(x) for x in values))

    def test_generator_retries_historical_collision(self):
        from unittest.mock import patch
        with patch.object(manifest.secrets, "token_hex",
                          side_effect=["0123456789", "abcdef1234"]):
            values = manifest.generate_case_ids(REQ_ID, {CASE_A}, 1)
        self.assertEqual(values, [CASE_B])

    def test_case_fingerprint_is_stable_and_excludes_group_order(self):
        case = parsed_with(CASE_A)["groups"][0]["cases"][0]
        self.assertEqual(manifest.case_fingerprint(case),
                         manifest.case_fingerprint(copy.deepcopy(case)))
        changed_group = dict(case, group="另一个分组", order=99)
        self.assertEqual(manifest.case_fingerprint(case),
                         manifest.case_fingerprint(changed_group))

    def test_first_delivery_starts_every_revision_at_one(self):
        snapshot, changes = manifest.build_case_snapshot(parsed_with(CASE_A, CASE_B))
        self.assertEqual([x["revision"] for x in snapshot], [1, 1])
        self.assertEqual([x["status"] for x in snapshot], ["added", "added"])
        self.assertEqual(changes, {"added": [CASE_A, CASE_B]})

    def test_semantic_update_increments_only_selected_revision(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(CASE_A, 2), snapshot_item(CASE_B, 4)],
        }
        snapshot, changes = manifest.build_case_snapshot(
            parsed_with(CASE_A, CASE_B), previous,
            historical_ids={CASE_A, CASE_B}, changes={"updated": [CASE_B]},
        )
        self.assertEqual([x["revision"] for x in snapshot], [2, 5])
        self.assertEqual([x["status"] for x in snapshot], ["unchanged", "updated"])
        self.assertEqual(changes["updated"], [{
            "case_id": CASE_B, "from_revision": 4, "to_revision": 5,
        }])

    def test_unchanged_revision_can_keep_new_raw_fingerprint(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(CASE_A, 3)],
        }
        parsed = parsed_with(CASE_A)
        parsed["groups"][0]["cases"][0]["title"] = "仅标点与排版调整后的标题。"
        snapshot, changes = manifest.build_case_snapshot(
            parsed, previous, historical_ids={CASE_A}, changes={},
        )
        self.assertEqual(snapshot[0]["revision"], 3)
        self.assertEqual(snapshot[0]["status"], "unchanged")
        self.assertNotEqual(snapshot[0]["content_sha256"],
                            previous["case_snapshot"][0]["content_sha256"])
        self.assertIsNone(changes)

    def test_new_case_must_be_explicitly_classified_as_added(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(CASE_A)],
        }
        with self.assertRaisesRegex(manifest.ManifestError, "明确列入"):
            manifest.build_case_snapshot(
                parsed_with(CASE_A, CASE_B), previous, historical_ids={CASE_A},
            )
        snapshot, changes = manifest.build_case_snapshot(
            parsed_with(CASE_A, CASE_B), previous,
            historical_ids={CASE_A}, changes={"added": [CASE_B]},
        )
        self.assertEqual(snapshot[1]["revision"], 1)
        self.assertEqual(changes["added"], [CASE_B])

    def test_historical_id_not_in_latest_snapshot_cannot_be_reused(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(CASE_A)],
        }
        with self.assertRaisesRegex(manifest.ManifestError, "禁止复用"):
            manifest.build_case_snapshot(
                parsed_with(CASE_A, CASE_B), previous,
                historical_ids={CASE_A, CASE_B}, changes={"added": [CASE_B]},
            )

    def test_missing_old_case_requires_explicit_retirement(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(CASE_A), snapshot_item(CASE_B)],
        }
        with self.assertRaisesRegex(manifest.ManifestError, "意外缺失"):
            manifest.build_case_snapshot(parsed_with(CASE_A), previous,
                                         historical_ids={CASE_A, CASE_B})

    def test_retirement_preserves_id_revision_and_reason(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(CASE_A, 7)],
        }
        snapshot, changes = manifest.build_case_snapshot(
            parsed_with(), previous, historical_ids={CASE_A},
            changes={"retired": [{"case_id": CASE_A, "reason": "需求明确取消该业务功能"}]},
        )
        self.assertEqual(snapshot[0]["case_id"], CASE_A)
        self.assertEqual(snapshot[0]["revision"], 7)
        self.assertEqual(snapshot[0]["status"], "retired")
        self.assertEqual(snapshot[0]["retirement_reason"], "需求明确取消该业务功能")
        self.assertEqual(changes["retired"][0]["case_id"], CASE_A)

    def test_retired_identity_cannot_be_reactivated(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [dict(snapshot_item(CASE_A), status="retired",
                                   retirement_reason="历史退役")],
        }
        with self.assertRaisesRegex(manifest.ManifestError, "不得重新启用"):
            manifest.build_case_snapshot(parsed_with(CASE_A), previous,
                                         historical_ids={CASE_A})

    def test_split_or_merge_lineage_is_preserved(self):
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(CASE_A)],
        }
        snapshot, _ = manifest.build_case_snapshot(
            parsed_with(CASE_A, CASE_B), previous,
            historical_ids={CASE_A}, changes={"added": [CASE_B]},
            lineage={CASE_B: [CASE_A]},
        )
        self.assertEqual(snapshot[1]["derived_from"], [CASE_A])

    def test_lineage_rejects_unknown_source(self):
        with self.assertRaisesRegex(manifest.ManifestError, "真实历史"):
            manifest.build_case_snapshot(
                parsed_with(CASE_A), None, lineage={CASE_A: [CASE_B]},
            )


class ManifestStructureAndHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_valid_manifest(self):
        version = "20261031-v1"
        entries, _ = testcase_artifacts(version, self.root / "stage-valid")
        data = make_manifest(version, entries, [snapshot_item(CASE_A)])
        self.assertIs(manifest.validate_manifest(data), data)

    def test_manifest_accepts_analysis_and_legacy_directories_for_test_impact_category(self):
        version = "20261031-v1"
        digest = hashlib.sha256(b"analysis report").hexdigest()
        for directory in ("analysis", "test-impact-analysis"):
            with self.subTest(directory=directory):
                item = {
                    "category": "test-impact-analysis",
                    "role": "submission-impact",
                    "path": f"{version}/{directory}/submission-impact.md",
                    "source_version": version,
                    "change": "added",
                    "sha256": digest,
                }
                data = make_manifest(version, [item], [])
                self.assertIs(manifest.validate_manifest(data), data)

    def test_manifest_rejects_unmapped_directory_for_test_impact_category(self):
        version = "20261031-v1"
        item = {
            "category": "test-impact-analysis",
            "role": "submission-impact",
            "path": f"{version}/analytics/submission-impact.md",
            "source_version": version,
            "change": "added",
            "sha256": hashlib.sha256(b"analysis report").hexdigest(),
        }
        data = make_manifest(version, [item], [])
        with self.assertRaisesRegex(manifest.ManifestError, "允许的目录"):
            manifest.validate_manifest(data)

    def test_manifest_requires_beijing_offset(self):
        data = make_manifest("20261031-v1")
        data["created_at"] = "2026-10-31T10:00:00"
        with self.assertRaisesRegex(manifest.ManifestError, "北京时间"):
            manifest.validate_manifest(data)

    def test_manifest_rejects_path_traversal(self):
        data = make_manifest("20261031-v1")
        data["artifacts"][0]["path"] = "20261031-v1/testcases/../../secret.txt"
        with self.assertRaisesRegex(manifest.ManifestError, "路径穿越"):
            manifest.validate_manifest(data)

    def test_manifest_rejects_invalid_status_type_without_raw_type_error(self):
        data = make_manifest("20261031-v1")
        data["case_snapshot"] = [dict(snapshot_item(CASE_A), status=[])]
        data["case_count"] = 1
        with self.assertRaises(manifest.ManifestError):
            manifest.validate_manifest(data)

    def test_manifest_rejects_duplicate_case_ids(self):
        version = "20261031-v1"
        entries, _ = testcase_artifacts(version, self.root / "stage-duplicate")
        data = make_manifest(version, entries,
                             [snapshot_item(CASE_A), snapshot_item(CASE_A)])
        data["case_count"] = 2
        with self.assertRaisesRegex(manifest.ManifestError, "重复"):
            manifest.validate_manifest(data)

    def test_history_orders_by_date_then_same_day_sequence(self):
        for version in ("20261030-v1", "20261030-v2", "20261030-v3",
                        "20261031-v1", "20261031-v2"):
            write_manifest(self.root, make_manifest(version))
        latest = manifest.load_latest_manifest(self.root, verify_files=False)
        self.assertEqual(latest["version_id"], "20261031-v2")
        self.assertEqual(manifest.next_version_id(self.root, "20261031"), "20261031-v3")
        self.assertEqual(manifest.next_version_id(self.root, "20261101"), "20261101-v1")

    def test_history_requires_full_case_identity_snapshot(self):
        parsed = artifacts.parse_markdown(MD_ONE)
        snapshot, changes = manifest.build_case_snapshot(parsed)
        v1 = "20261031-v1"
        items, payloads = testcase_artifacts(v1, self.root / "stage-history-v1")
        write_manifest(self.root, make_manifest(v1, items, snapshot, changes), payloads)
        v2 = "20261031-v2"
        carried = [dict(item, change="unchanged") for item in items]
        sql_payload = b"select 2;"
        sql_item = {
            "category": "sql", "role": "query", "path": f"sql/{v2}/query.sql",
            "source_version": v2, "change": "added",
            "sha256": hashlib.sha256(sql_payload).hexdigest(),
        }
        write_manifest(self.root, make_manifest(v2, carried + [sql_item], []),
                       {f"sql/{v2}/query.sql": sql_payload})
        with self.assertRaisesRegex(manifest.ManifestError, "历史 Case ID 未在当前"):
            manifest.load_latest_manifest(self.root, verify_files=False)

    def test_history_revision_must_increment_from_previous_manifest(self):
        parsed = artifacts.parse_markdown(MD_ONE)
        snapshot, changes = manifest.build_case_snapshot(parsed)
        v1 = "20261031-v1"
        items, payloads = testcase_artifacts(v1, self.root / "stage-revision-v1")
        write_manifest(self.root, make_manifest(v1, items, snapshot, changes), payloads)
        v2 = "20261031-v2"
        carried = [dict(item, change="unchanged") for item in items]
        sql_payload = b"select 3;"
        sql_item = {
            "category": "sql", "role": "query", "path": f"sql/{v2}/query.sql",
            "source_version": v2, "change": "added",
            "sha256": hashlib.sha256(sql_payload).hexdigest(),
        }
        wrong_snapshot = [snapshot_item(
            CASE_A, 3, status="updated", fingerprint=hashlib.sha256(b"new").hexdigest(),
        )]
        wrong_changes = {"updated": [{
            "case_id": CASE_A, "from_revision": 2, "to_revision": 3,
        }]}
        write_manifest(self.root, make_manifest(v2, carried + [sql_item],
                                                 wrong_snapshot, wrong_changes),
                       {f"sql/{v2}/query.sql": sql_payload})
        with self.assertRaisesRegex(manifest.ManifestError, "Revision 更新与上一正式版本不连续"):
            manifest.load_latest_manifest(self.root, verify_files=False)

    def test_version_directory_without_manifest_fails_closed(self):
        (self.root / "versions" / "20261031-v1").mkdir(parents=True)
        with self.assertRaisesRegex(manifest.ManifestError, "缺少 manifest"):
            manifest.load_latest_manifest(self.root, verify_files=False)

    def test_legacy_version_first_history_remains_readable_but_is_read_only(self):
        root = self.root / "legacy-output"
        version = "20261031-v1"
        payload = b"legacy SQL payload"
        relative_path = f"{version}/sql/query.sql"
        item = {
            "category": "sql",
            "role": "query",
            "path": relative_path,
            "source_version": version,
            "change": "added",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        version_root = root / version
        (version_root / "sql").mkdir(parents=True)
        (version_root / "sql" / "query.sql").write_bytes(payload)
        (version_root / "manifest.json").write_text(
            json.dumps(make_manifest(version, [item], []), ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(
            manifest.load_latest_manifest(root, verify_files=True)["version_id"],
            version,
        )

        updated_source = self.root / "updated-query.sql"
        updated_source.write_bytes(b"new SQL payload")
        with self.assertRaisesRegex(manifest.ManifestError, "只读兼容"):
            publish_for_test(
                root,
                REQ_ID,
                "示例需求",
                [{
                    "category": "sql",
                    "role": "query",
                    "path": "sql/query.sql",
                    "source_path": str(updated_source),
                }],
                created_at="2026-11-01T10:00:00+08:00",
            )
        self.assertTrue((root / version / "manifest.json").is_file())
        self.assertFalse((root / "versions").exists())
        self.assertEqual(manifest.verify_history_artifact_files(root), 1)

    def test_baseline_resolves_markdown_and_checks_identity_snapshot(self):
        parsed = artifacts.parse_markdown(MD_ONE)
        snapshot, changes = manifest.build_case_snapshot(parsed)
        version = "20261031-v1"
        entries, payloads = testcase_artifacts(version, self.root / "stage-baseline")
        data = make_manifest(version, entries, snapshot, changes)
        write_manifest(self.root, data, payloads)
        baseline = manifest.resolve_latest_case_baseline(self.root)
        self.assertEqual(baseline["parsed"]["requirement"]["id"], REQ_ID)
        self.assertEqual(baseline["parsed"]["groups"][0]["cases"][0]["case_id"], CASE_A)

    def test_baseline_hash_mismatch_is_rejected(self):
        parsed = artifacts.parse_markdown(MD_ONE)
        snapshot, changes = manifest.build_case_snapshot(parsed)
        version = "20261031-v1"
        entries, payloads = testcase_artifacts(version, self.root / "stage-tampered")
        data = make_manifest(version, entries, snapshot, changes)
        md_relative = f"testcases/{version}/testcases.md"
        payloads[md_relative] = payloads[md_relative] + b"tampered"
        write_manifest(self.root, data, payloads)
        with self.assertRaisesRegex(manifest.ManifestError, "SHA-256"):
            manifest.resolve_latest_case_baseline(self.root)

    def test_sql_only_version_keeps_latest_testcase_baseline_reference(self):
        parsed = artifacts.parse_markdown(MD_ONE)
        snapshot, changes = manifest.build_case_snapshot(parsed)
        v1 = "20261031-v1"
        first_items, first_payloads = testcase_artifacts(v1, self.root / "stage-v1")
        first = make_manifest(v1, first_items, snapshot, changes)
        write_manifest(self.root, first, first_payloads)

        sql_payload = b"select 1;"
        v2 = "20261031-v2"
        sql_rel = f"sql/{v2}/query.sql"
        carried = [dict(item, change="unchanged") for item in first_items]
        sql_item = {
            "category": "sql", "role": "query", "path": sql_rel,
            "source_version": v2, "change": "added",
            "sha256": hashlib.sha256(sql_payload).hexdigest(),
        }
        second = make_manifest(v2, carried + [sql_item],
                               [dict(snapshot[0], status="unchanged")])
        write_manifest(self.root, second, {sql_rel: sql_payload})
        baseline = manifest.resolve_latest_case_baseline(self.root)
        self.assertEqual(baseline["markdown_path"], self.root / first_items[0]["path"])
        self.assertEqual(baseline["parsed"]["groups"][0]["cases"][0]["case_id"], CASE_A)

    def test_cli_id_output_is_ascii_json(self):
        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["ids", str(self.root), REQ_ID, "--count", "2"])
        self.assertEqual(status, 0)
        self.assertTrue(output.getvalue().isascii())
        self.assertEqual(len(json.loads(output.getvalue())["case_ids"]), 2)




ORACLE_ONE = {
    "schema_version": "1",
    "requirement": {"id": REQ_ID, "name": "示例需求"},
    "sources": [{"id": "S1", "description": "需求正文", "locator": "需求正文"}],
    "obligations": [{
        "id": "O1", "source_ids": ["S1"],
        "rule": "查询结果受当前筛选条件约束",
        "expected_outcome": "仅展示匹配结果",
        "certainty": "confirmed",
    }],
    "open_questions": [],
}


def stage_bundle(directory, markdown=MD_ONE, oracle=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    md_path = directory / "testcases.md"
    xmind_path = directory / "testcases.xmind"
    oracle_path = directory / "oracle.json"
    md_path.write_text(markdown, encoding="utf-8")
    xmind.export_xmind(markdown, xmind_path)
    oracle_data = ORACLE_ONE if oracle is None else oracle
    oracle_path.write_text(json.dumps(oracle_data, ensure_ascii=False), encoding="utf-8")
    return [
        {"category": "testcases", "role": "markdown",
         "path": "testcases/testcases.md", "source_path": str(md_path)},
        {"category": "testcases", "role": "xmind",
         "path": "testcases/testcases.xmind", "source_path": str(xmind_path)},
        {"category": "testcases", "role": "oracle",
         "path": "testcases/oracle.json", "source_path": str(oracle_path)},
    ]




def testcase_artifacts(version, directory, markdown=MD_ONE):
    specs = stage_bundle(directory, markdown)
    items, payloads = [], {}
    for spec in specs:
        relative = f"{spec['path'].split('/')[0]}/{version}/{'/'.join(spec['path'].split('/')[1:])}"
        payload = Path(spec["source_path"]).read_bytes()
        items.append({
            "category": spec["category"],
            "role": spec["role"],
            "path": relative,
            "source_version": version,
            "change": "added",
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        payloads[relative] = payload
    return items, payloads


class ManifestPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "output" / "900661-示例需求"

    def publish_first(self, status="complete"):
        specs = stage_bundle(self.base / "stage-v1")
        return publish_for_test(
            self.root, REQ_ID, "示例需求", specs,
            delivery_status=status,
            created_at="2026-10-31T10:00:00+08:00",
        )

    def stage_p2_artifacts(self, directory, report_text, manual_text=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        report_path = directory / "impact-analysis.md"
        report_path.write_text(report_text, encoding="utf-8")
        specs = [{
            "category": "test-impact-analysis",
            "role": "impact-analysis",
            "path": "analysis/impact-analysis.md",
            "source_path": str(report_path),
        }]
        if manual_text is not None:
            manual_path = directory / "manual-verification.md"
            manual_path.write_text(manual_text, encoding="utf-8")
            specs.append({
                "category": "test-impact-analysis",
                "role": "manual-verification",
                "path": "analysis/manual-verification.md",
                "source_path": str(manual_path),
            })
        return specs

    def test_first_publish_creates_immutable_manifest_and_all_three_artifacts(self):
        result = self.publish_first("partial")
        self.assertEqual(result["version_id"], "20261031-v1")
        data = result["manifest"]
        self.assertEqual(data["delivery_status"], "partial")
        self.assertEqual(data["case_count"], 1)
        self.assertEqual(data["case_snapshot"][0]["revision"], 1)
        self.assertEqual(data["case_snapshot"][0]["status"], "added")
        self.assertEqual(data["case_changes"]["added"], [CASE_A])
        self.assertEqual(data["validation"]["markdown_oracle"], "STRUCTURE_PASS")
        self.assertEqual(data["validation"]["xmind_readback"], "XMIND_READBACK_PASS")
        self.assertTrue((self.root / "versions" / "20261031-v1" / "manifest.json").is_file())
        self.assertTrue((self.root / "testcases" / "20261031-v1" / "testcases.md").is_file())
        self.assertTrue((self.root / "testcases" / "20261031-v1" / "testcases.xmind").is_file())
        self.assertTrue((self.root / "testcases" / "20261031-v1" / "oracle.json").is_file())
        self.assertFalse((self.root / ".qa-work").exists())
        self.assertEqual(manifest.load_latest_manifest(self.root)["version_id"], "20261031-v1")

    def test_publish_rejects_manifest_markdown_requirement_identity_mismatch(self):
        mismatches = (
            (
                "name",
                MD_ONE.replace("示例需求", "另一个需求"),
                dict(ORACLE_ONE, requirement={"id": REQ_ID, "name": "另一个需求"}),
                "需求名称",
            ),
            (
                "id",
                MD_ONE.replace("# 900661｜示例需求", "# 123456｜示例需求").replace(
                    "QA-900661-0123456789", "QA-123456-0123456789",
                ),
                dict(ORACLE_ONE, requirement={"id": "123456", "name": "示例需求"}),
                "需求编号",
            ),
        )
        for label, markdown, oracle, expected_error in mismatches:
            with self.subTest(identity=label):
                root = self.base / "identity-mismatch" / label
                specs = stage_bundle(
                    self.base / f"stage-identity-{label}",
                    markdown=markdown,
                    oracle=oracle,
                )
                with self.assertRaisesRegex(
                    manifest.ManifestError,
                    f"正式发布 Markdown {expected_error}与 Manifest 不一致",
                ):
                    publish_for_test(
                        root, REQ_ID, "示例需求", specs,
                        created_at="2026-10-31T10:00:00+08:00",
                    )
                self.assertFalse((root / "versions" / "20261031-v1").exists())

    def test_publish_rejects_markdown_oracle_requirement_mismatch(self):
        oracle = copy.deepcopy(ORACLE_ONE)
        oracle["requirement"]["name"] = "另一个需求"
        specs = stage_bundle(
            self.base / "stage-oracle-mismatch",
            markdown=MD_ONE,
            oracle=oracle,
        )
        with self.assertRaisesRegex(
            manifest.ManifestError,
            "正式用例产物一致性校验失败：Markdown 与 Oracle 的需求编号/名称不一致",
        ):
            publish_for_test(
                self.root, REQ_ID, "示例需求", specs,
                created_at="2026-10-31T10:00:00+08:00",
            )
        self.assertFalse((self.root / "versions" / "20261031-v1").exists())

    def test_history_validate_rejects_manifest_markdown_requirement_identity_mismatch(self):
        for field, value, expected_error in (
            ("name", "另一个需求", "需求名称"),
            ("id", "123456", "需求编号"),
        ):
            with self.subTest(identity=field):
                root = self.base / "history-identity-mismatch" / field
                specs = stage_bundle(self.base / f"stage-history-{field}")
                publish_for_test(
                    root, REQ_ID, "示例需求", specs,
                    created_at="2026-10-31T10:00:00+08:00",
                )
                manifest_path = root / "versions" / "20261031-v1" / "manifest.json"
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if field == "name":
                    data["requirement"]["name"] = value
                else:
                    data["requirement"]["id"] = value
                    for item in data["case_snapshot"]:
                        item["case_id"] = item["case_id"].replace(
                            f"QA-{REQ_ID}-", f"QA-{value}-",
                        )
                    for case_id_index, case_id in enumerate(data["case_changes"]["added"]):
                        data["case_changes"]["added"][case_id_index] = case_id.replace(
                            f"QA-{REQ_ID}-", f"QA-{value}-",
                        )
                manifest_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                output = __import__("io").StringIO()
                from unittest.mock import patch
                with patch.object(manifest.sys, "stdout", output):
                    status = manifest.main(["validate", str(root)])
                self.assertEqual(status, 1)
                self.assertIn(
                    f"历史验签 Markdown {expected_error}与 Manifest 不一致",
                    json.loads(output.getvalue())["error"],
                )

    def test_analysis_directory_mapping_preserves_legacy_history_and_p1_artifacts(self):
        legacy_report = self.base / "stage-impact-v1" / "submission-impact.md"
        legacy_report.parent.mkdir(parents=True, exist_ok=True)
        legacy_report.write_text("legacy analysis v1", encoding="utf-8")
        first_specs = stage_bundle(self.base / "stage-v1")
        first_specs.append({
            "category": "test-impact-analysis",
            "role": "submission-impact",
            "path": "test-impact-analysis/submission-impact.md",
            "source_path": str(legacy_report),
        })
        first = publish_for_test(
            self.root, REQ_ID, "示例需求", first_specs,
            created_at="2026-10-31T10:00:00+08:00",
        )
        p1_markdown = self.root / "testcases" / first["version_id"] / "testcases.md"
        original_p1_markdown = p1_markdown.read_bytes()
        legacy_path = self.root / "analysis" / first["version_id"] / "submission-impact.md"
        original_legacy_report = legacy_path.read_bytes()

        canonical_report = self.base / "stage-impact-v2" / "submission-impact.md"
        canonical_report.parent.mkdir(parents=True, exist_ok=True)
        canonical_report.write_text("canonical analysis v2", encoding="utf-8")
        second = publish_for_test(
            self.root, REQ_ID, "示例需求", [{
                "category": "test-impact-analysis",
                "role": "submission-impact",
                "path": "analysis/submission-impact.md",
                "source_path": str(canonical_report),
            }],
            created_at="2026-10-31T10:05:00+08:00",
        )

        self.assertEqual(first["version_id"], "20261031-v1")
        self.assertEqual(second["version_id"], "20261031-v2")
        analysis_item = next(
            item for item in second["manifest"]["artifacts"]
            if item["category"] == "test-impact-analysis"
        )
        self.assertEqual(analysis_item["path"], "analysis/20261031-v2/submission-impact.md")
        self.assertEqual(analysis_item["category"], "test-impact-analysis")
        self.assertEqual((self.root / analysis_item["path"]).read_text(encoding="utf-8"),
                         "canonical analysis v2")
        self.assertEqual(legacy_path.read_bytes(), original_legacy_report)
        self.assertEqual(p1_markdown.read_bytes(), original_p1_markdown)
        p1_item = next(
            item for item in second["manifest"]["artifacts"]
            if item["category"] == "testcases" and item["role"] == "markdown"
        )
        self.assertEqual(p1_item["source_version"], first["version_id"])
        self.assertEqual(p1_item["change"], "unchanged")
        self.assertEqual(
            [{key: value for key, value in item.items() if key != "status"}
             for item in second["manifest"]["case_snapshot"]],
            [{key: value for key, value in item.items() if key != "status"}
             for item in first["manifest"]["case_snapshot"]],
        )
        self.assertTrue(all(item["status"] == "unchanged"
                            for item in second["manifest"]["case_snapshot"]))
        self.assertTrue((self.root / "versions" / first["version_id"] / "manifest.json").is_file())
        self.assertEqual(manifest.load_latest_manifest(self.root)["version_id"], second["version_id"])

    def test_revision_update_keeps_case_id_and_reuses_unchanged_oracle(self):
        self.publish_first()
        original_md = (self.root / "testcases" / "20261031-v1" / "testcases.md").read_bytes()
        changed_md = MD_ONE.replace("展示匹配结果", "展示符合筛选条件的结果")
        specs = stage_bundle(self.base / "stage-v2", changed_md)
        specs = [x for x in specs if x["role"] in {"markdown", "xmind"}]
        result = publish_for_test(
            self.root, REQ_ID, "示例需求", specs,
            case_changes={"updated": [CASE_A]},
            created_at="2026-10-31T10:05:00+08:00",
        )
        data = result["manifest"]
        self.assertEqual(result["version_id"], "20261031-v2")
        self.assertEqual(data["case_snapshot"][0]["case_id"], CASE_A)
        self.assertEqual(data["case_snapshot"][0]["revision"], 2)
        self.assertEqual(data["case_changes"]["updated"], [{
            "case_id": CASE_A, "from_revision": 1, "to_revision": 2,
        }])
        oracle = next(x for x in data["artifacts"] if x["role"] == "oracle")
        self.assertEqual(oracle["source_version"], "20261031-v1")
        self.assertEqual(oracle["change"], "unchanged")
        self.assertFalse((self.root / "testcases" / "20261031-v2" / "oracle.json").exists())
        self.assertEqual((self.root / "testcases" / "20261031-v1" / "testcases.md").read_bytes(),
                         original_md)

    def test_sql_only_release_keeps_latest_case_baseline_and_full_inventory(self):
        self.publish_first()
        sql_source = self.base / "query.sql"
        sql_source.write_text("select 1;", encoding="utf-8")
        result = publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "query", "path": "sql/query.sql",
              "source_path": str(sql_source)}],
            created_at="2026-10-31T10:10:00+08:00",
        )
        data = result["manifest"]
        self.assertEqual(result["version_id"], "20261031-v2")
        self.assertEqual(len(data["artifacts"]), 4)
        self.assertEqual(data["case_snapshot"][0]["status"], "unchanged")
        md_item = next(x for x in data["artifacts"] if x["role"] == "markdown")
        self.assertEqual(md_item["source_version"], "20261031-v1")
        self.assertEqual(md_item["change"], "unchanged")
        baseline = manifest.resolve_latest_case_baseline(self.root)
        self.assertEqual(baseline["markdown_path"],
                         self.root / "testcases" / "20261031-v1" / "testcases.md")

    def test_p2_manual_verification_retirement_preserves_history_and_p1_artifacts(self):
        first_specs = stage_bundle(self.base / "p1-stage-v1")
        first_specs.extend(self.stage_p2_artifacts(
            self.base / "p2-stage-v1",
            "# P2 report round 1\n",
            "# Manual verification\n\n- MV-001 / CHK-001 / PENDING\n",
        ))
        first = publish_for_test(
            self.root, REQ_ID, "示例需求", first_specs,
            created_at="2026-10-31T10:00:00+08:00",
        )
        old_manual = next(
            item for item in first["manifest"]["artifacts"]
            if item["category"] == "test-impact-analysis"
            and item["role"] == "manual-verification"
        )
        old_manual_path = self.root / old_manual["path"]
        old_manual_bytes = old_manual_path.read_bytes()
        second_specs = self.stage_p2_artifacts(
            self.base / "p2-stage-v2", "# P2 report round 2\n"
        )
        second = publish_for_test(
            self.root, REQ_ID, "示例需求", second_specs,
            retire_artifacts=[{
                "category": "test-impact-analysis",
                "role": "manual-verification",
            }],
            created_at="2026-10-31T10:10:00+08:00",
        )
        latest = second["manifest"]
        latest_keys = {(item["category"], item["role"]) for item in latest["artifacts"]}
        self.assertNotIn(("test-impact-analysis", "manual-verification"), latest_keys)
        self.assertIn(("test-impact-analysis", "impact-analysis"), latest_keys)
        self.assertEqual(
            {item["role"] for item in latest["artifacts"] if item["category"] == "testcases"},
            {"markdown", "xmind", "oracle"},
        )
        self.assertEqual(
            [(item["case_id"], item["revision"], item["content_sha256"]) for item in latest["case_snapshot"]],
            [(item["case_id"], item["revision"], item["content_sha256"]) for item in first["manifest"]["case_snapshot"]],
        )
        self.assertTrue(all(item["status"] == "unchanged" for item in latest["case_snapshot"]))
        self.assertTrue(old_manual_path.is_file())
        self.assertEqual(old_manual_path.read_bytes(), old_manual_bytes)
        old_manifest = json.loads(
            (self.root / "versions" / "20261031-v1" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertTrue(any(
            item["category"] == "test-impact-analysis"
            and item["role"] == "manual-verification"
            for item in old_manifest["artifacts"]
        ))

    def test_p2_partial_round_without_new_manual_file_keeps_old_reference(self):
        first_specs = stage_bundle(self.base / "p1-stage-v1")
        first_specs.extend(self.stage_p2_artifacts(
            self.base / "p2-stage-v1",
            "# P2 report round 1\n",
            "# Manual verification\n\n- MV-001 / CHK-001 / PENDING\n",
        ))
        publish_for_test(
            self.root, REQ_ID, "示例需求", first_specs,
            created_at="2026-10-31T10:00:00+08:00",
        )
        second_specs = self.stage_p2_artifacts(
            self.base / "p2-stage-v2", "# P2 partial report round 2\n"
        )
        second = publish_for_test(
            self.root, REQ_ID, "示例需求", second_specs,
            delivery_status="partial",
            created_at="2026-10-31T10:10:00+08:00",
        )
        manual = next(
            item for item in second["manifest"]["artifacts"]
            if item["category"] == "test-impact-analysis"
            and item["role"] == "manual-verification"
        )
        self.assertEqual(manual["change"], "unchanged")
        self.assertEqual(manual["source_version"], "20261031-v1")
        self.assertEqual(manual["path"], "analysis/20261031-v1/manual-verification.md")
        self.assertEqual(second["manifest"]["delivery_status"], "partial")
        self.assertIn("MV-001", (self.root / manual["path"]).read_text(encoding="utf-8"))

    def test_p2_manual_verification_update_preserves_existing_mv_identity_and_history(self):
        first_specs = stage_bundle(self.base / "p1-stage-v1")
        first_specs.extend(self.stage_p2_artifacts(
            self.base / "p2-stage-v1",
            "# P2 report round 1\n",
            "# Manual verification\n\n- MV-001 / CHK-001 / PENDING\n",
        ))
        publish_for_test(
            self.root, REQ_ID, "示例需求", first_specs,
            created_at="2026-10-31T10:00:00+08:00",
        )
        old_manual_path = self.root / "analysis/20261031-v1/manual-verification.md"
        old_manual_bytes = old_manual_path.read_bytes()
        second_specs = self.stage_p2_artifacts(
            self.base / "p2-stage-v2",
            "# P2 report round 2\n",
            "# Manual verification\n\n- MV-001 / CHK-003 / PENDING (updated)\n- MV-002 / CHK-004 / PENDING (new)\n",
        )
        second = publish_for_test(
            self.root, REQ_ID, "示例需求", second_specs,
            created_at="2026-10-31T10:10:00+08:00",
        )
        manual = next(
            item for item in second["manifest"]["artifacts"]
            if item["category"] == "test-impact-analysis"
            and item["role"] == "manual-verification"
        )
        self.assertEqual(manual["change"], "updated")
        self.assertEqual(manual["source_version"], "20261031-v2")
        updated_text = (self.root / manual["path"]).read_text(encoding="utf-8")
        self.assertIn("MV-001 / CHK-003", updated_text)
        self.assertIn("MV-002 / CHK-004", updated_text)
        self.assertTrue(old_manual_path.is_file())
        self.assertEqual(old_manual_path.read_bytes(), old_manual_bytes)

    def test_delivery_status_change_can_publish_manifest_only(self):
        self.publish_first("partial")
        result = publish_for_test(
            self.root, REQ_ID, "示例需求", [], delivery_status="complete",
            created_at="2026-10-31T10:10:00+08:00",
        )
        self.assertEqual(result["version_id"], "20261031-v2")
        self.assertEqual(result["manifest"]["delivery_status"], "complete")
        self.assertEqual(list((self.root / "versions" / "20261031-v2").iterdir()), [
            self.root / "versions" / "20261031-v2" / "manifest.json"
        ])

    def test_noop_does_not_create_a_new_formal_version(self):
        self.publish_first()
        with self.assertRaisesRegex(manifest.ManifestError, "没有实质内容"):
            publish_for_test(
                self.root, REQ_ID, "示例需求", [],
                created_at="2026-10-31T10:10:00+08:00",
            )
        self.assertFalse((self.root / "versions" / "20261031-v2").exists())

    def test_non_monotonic_publish_time_fails_before_commit(self):
        self.publish_first()
        for timestamp, message, expected_path in (
            ("2026-10-31T09:59:00+08:00", "不能早于最新版本", "20261031-v2"),
            ("2026-10-30T10:00:00+08:00", "不能早于最新正式版本", "20261030-v1"),
        ):
            with self.subTest(timestamp=timestamp):
                with self.assertRaisesRegex(manifest.ManifestError, message):
                    publish_for_test(
                        self.root, REQ_ID, "示例需求", [],
                        delivery_status="partial", created_at=timestamp,
                    )
                self.assertFalse((self.root / expected_path).exists())
                self.assertFalse((self.root / ".qa-work").exists())
                self.assertEqual(
                    manifest.load_latest_manifest(self.root)["version_id"],
                    "20261031-v1",
                )

    def test_publish_rejects_resolved_staging_destination_outside_temp_root(self):
        source = self.base / "staging-source.sql"
        source.write_text("select 14;", encoding="utf-8")
        outside = self.base / "outside"
        real_resolve = Path.resolve

        def resolve_with_escape(path, *args, **kwargs):
            if path.name == "escape.txt":
                return outside / "escape.txt"
            return real_resolve(path, *args, **kwargs)

        from unittest.mock import patch
        with patch.object(Path, "resolve", resolve_with_escape):
            with self.assertRaisesRegex(manifest.ManifestError, "规范化后越界"):
                publish_for_test(
                    self.root, REQ_ID, "示例需求",
                    [{"category": "sql", "role": "query", "path": "sql/escape.txt",
                      "source_path": str(source)}],
                    created_at="2026-10-31T10:00:00+08:00",
                )
        self.assertFalse((outside / "escape.txt").exists())
        self.assertFalse((self.root / "versions" / "20261031-v1").exists())
        self.assertFalse((self.root / ".qa-work").exists())

    def _publish_retirement_chain(self):
        self.publish_first()
        sql_source = self.base / "retirement-audit.sql"
        sql_source.write_text("select 13;", encoding="utf-8")
        publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "query", "path": "sql/archive.sql",
              "source_path": str(sql_source)}],
            case_changes={"retired": [{
                "case_id": CASE_A, "reason": "需求确认该用例覆盖的功能整体下线",
            }]},
            retire_artifacts=[
                {"category": "testcases", "role": "markdown"},
                {"category": "testcases", "role": "xmind"},
                {"category": "testcases", "role": "oracle"},
            ],
            created_at="2026-10-31T10:05:00+08:00",
        )
        followup_sql = self.base / "post-retirement.sql"
        followup_sql.write_text("select 15;", encoding="utf-8")
        publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "audit", "path": "sql/audit.sql",
              "source_path": str(followup_sql)}],
            created_at="2026-10-31T10:10:00+08:00",
        )

    def _assert_history_validation_fails(self, expected_message):
        from unittest.mock import patch
        output = __import__("io").StringIO()
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "FAIL")
        self.assertIn(expected_message, result["error"])

    def test_validate_rejects_tampered_fingerprint_on_first_retirement(self):
        self._publish_retirement_chain()
        path = self.root / "versions" / "20261031-v2" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["case_snapshot"][0]["content_sha256"] = "0" * 64
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        self._assert_history_validation_fails(
            "用例退役状态、原因或内容指纹与上一正式版本不一致",
        )

    def test_validate_rejects_tampered_fingerprint_in_carried_retirement_snapshot(self):
        self._publish_retirement_chain()
        path = self.root / "versions" / "20261031-v3" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["case_snapshot"][0]["content_sha256"] = "f" * 64
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        self._assert_history_validation_fails(
            "已退役 Case ID 的身份、状态或内容指纹发生变化",
        )

    def test_last_active_case_can_be_retired_while_historical_artifacts_are_preserved(self):
        self.publish_first()
        historical_files = [
            self.root / "testcases" / "20261031-v1" / "testcases.md",
            self.root / "testcases" / "20261031-v1" / "testcases.xmind",
            self.root / "testcases" / "20261031-v1" / "oracle.json",
        ]
        self.assertTrue(all(path.is_file() for path in historical_files))
        sql_source = self.base / "retirement-audit.sql"
        sql_source.write_text("select 13;", encoding="utf-8")
        reason = "需求确认该用例覆盖的功能整体下线"

        result = publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "query", "path": "sql/archive.sql",
              "source_path": str(sql_source)}],
            case_changes={"retired": [{"case_id": CASE_A, "reason": reason}]},
            retire_artifacts=[
                {"category": "testcases", "role": "markdown"},
                {"category": "testcases", "role": "xmind"},
                {"category": "testcases", "role": "oracle"},
            ],
            created_at="2026-10-31T10:05:00+08:00",
        )

        data = result["manifest"]
        self.assertEqual(result["version_id"], "20261031-v2")
        self.assertEqual(data["case_count"], 0)
        self.assertEqual(data["retired_case_count"], 1)
        self.assertEqual(data["case_snapshot"][0]["case_id"], CASE_A)
        self.assertEqual(data["case_snapshot"][0]["revision"], 1)
        self.assertEqual(data["case_snapshot"][0]["status"], "retired")
        self.assertEqual(data["case_snapshot"][0]["retirement_reason"], reason)
        self.assertEqual(data["case_changes"]["retired"], [
            {"case_id": CASE_A, "reason": reason},
        ])
        self.assertFalse(any(x["category"] == "testcases" for x in data["artifacts"]))
        self.assertTrue(all(path.is_file() for path in historical_files))
        baseline = manifest.resolve_latest_case_baseline(self.root)
        self.assertIsNone(baseline["markdown_path"])
        self.assertIsNone(baseline["parsed"])

        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_HISTORY_PASS")
        followup_sql = self.base / "post-retirement.sql"
        followup_sql.write_text("select 15;", encoding="utf-8")
        followup = publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "audit", "path": "sql/audit.sql",
              "source_path": str(followup_sql)}],
            created_at="2026-10-31T10:10:00+08:00",
        )
        self.assertEqual(followup["version_id"], "20261031-v3")
        self.assertEqual(followup["manifest"]["case_count"], 0)
        self.assertEqual(followup["manifest"]["retired_case_count"], 1)
        self.assertEqual(followup["manifest"]["case_snapshot"][0]["status"], "retired")
        self.assertIsNone(manifest.resolve_latest_case_baseline(self.root)["markdown_path"])
        self.assertTrue(all(path.is_file() for path in historical_files))

        output = __import__("io").StringIO()
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_HISTORY_PASS")

    def test_p2_manual_verification_artifact_retirement_preserves_history(self):
        report_v1 = self.base / "impact-v1.md"
        manual_v1 = self.base / "manual-v1.md"
        report_v1.write_text("# P2 report v1\n", encoding="utf-8")
        manual_v1.write_text("# MV-001 PENDING\n", encoding="utf-8")
        first = publish_for_test(self.root, REQ_ID, "示例需求", [
            {"category": "test-impact-analysis", "role": "impact-analysis", "path": "analysis/impact-analysis.md", "source_path": str(report_v1)},
            {"category": "test-impact-analysis", "role": "manual-verification", "path": "analysis/manual-verification.md", "source_path": str(manual_v1)},
        ], created_at="2026-10-31T10:00:00+08:00")
        old_manual = self.root / "analysis" / first["version_id"] / "manual-verification.md"
        report_v2 = self.base / "impact-v2.md"
        report_v2.write_text("# P2 report v2 - no manual items\n", encoding="utf-8")
        second = publish_for_test(self.root, REQ_ID, "示例需求", [
            {"category": "test-impact-analysis", "role": "impact-analysis", "path": "analysis/impact-analysis.md", "source_path": str(report_v2)},
        ], retire_artifacts=[{"category": "test-impact-analysis", "role": "manual-verification"}],
           created_at="2026-10-31T10:10:00+08:00")
        self.assertEqual(second["version_id"], "20261031-v2")
        self.assertFalse(any(item["role"] == "manual-verification" for item in second["manifest"]["artifacts"]))
        self.assertTrue(old_manual.is_file())
        self.assertEqual(len(manifest._read_history(self.root)), 2)

    def test_p2_partial_followup_keeps_previous_manual_verification_artifact(self):
        report_v1 = self.base / "partial-impact-v1.md"
        manual_v1 = self.base / "partial-manual-v1.md"
        report_v1.write_text("# P2 report v1\n", encoding="utf-8")
        manual_v1.write_text("# MV-001 PENDING\n", encoding="utf-8")
        first = publish_for_test(self.root, REQ_ID, "示例需求", [
            {"category": "test-impact-analysis", "role": "impact-analysis", "path": "analysis/impact-analysis.md", "source_path": str(report_v1)},
            {"category": "test-impact-analysis", "role": "manual-verification", "path": "analysis/manual-verification.md", "source_path": str(manual_v1)},
        ], created_at="2026-10-31T10:00:00+08:00")
        report_v2 = self.base / "partial-impact-v2.md"
        report_v2.write_text("# P2 partial report v2\n", encoding="utf-8")
        second = publish_for_test(self.root, REQ_ID, "示例需求", [
            {"category": "test-impact-analysis", "role": "impact-analysis", "path": "analysis/impact-analysis.md", "source_path": str(report_v2)},
        ], delivery_status="partial", created_at="2026-10-31T10:10:00+08:00")
        active = [item for item in second["manifest"]["artifacts"] if item["role"] == "manual-verification"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["change"], "unchanged")
        self.assertTrue((self.root / "analysis" / first["version_id"] / "manual-verification.md").is_file())
    def test_failed_xmind_validation_cleans_temporary_version(self):
        self.publish_first()
        changed_md = MD_ONE.replace("展示匹配结果", "展示另一种结果")
        specs = stage_bundle(self.base / "stage-bad", changed_md)
        xmind_spec = next(x for x in specs if x["role"] == "xmind")
        Path(xmind_spec["source_path"]).write_bytes(b"not a zip")
        with self.assertRaisesRegex(manifest.ManifestError, "一致性校验失败"):
            publish_for_test(
                self.root, REQ_ID, "示例需求", specs,
                case_changes={"updated": [CASE_A]},
                created_at="2026-10-31T10:05:00+08:00",
            )
        self.assertFalse((self.root / "versions" / "20261031-v2").exists())
        self.assertFalse((self.root / ".qa-work").exists())
        self.assertEqual(manifest.load_latest_manifest(self.root)["version_id"], "20261031-v1")

    def test_manifest_commit_failure_rolls_back_new_category_directory(self):
        self.publish_first()
        sql_source = self.base / "rollback.sql"
        sql_source.write_text("select 99;", encoding="utf-8")
        original_rename = manifest.os.rename

        def fail_manifest_commit(source, target):
            source_path = Path(source)
            if (
                source_path.parent == self.root / "versions"
                and source_path.name.startswith(".20261031-v2-")
            ):
                raise OSError("simulated manifest commit failure")
            return original_rename(source, target)

        from unittest.mock import patch
        with patch.object(manifest.os, "rename", side_effect=fail_manifest_commit):
            with self.assertRaisesRegex(OSError, "simulated manifest commit failure"):
                publish_for_test(
                    self.root,
                    REQ_ID,
                    "示例需求",
                    [{
                        "category": "sql",
                        "role": "query",
                        "path": "sql/query.sql",
                        "source_path": str(sql_source),
                    }],
                    created_at="2026-10-31T10:05:00+08:00",
                )
        self.assertFalse((self.root / "sql" / "20261031-v2").exists())
        self.assertFalse((self.root / "versions" / "20261031-v2").exists())
        self.assertFalse((self.root / ".qa-work").exists())
        self.assertEqual(manifest.load_latest_manifest(self.root)["version_id"], "20261031-v1")

    def test_publish_cli_returns_ascii_json(self):
        specs = stage_bundle(self.base / "stage-cli")
        spec_path = self.base / "publish-spec.json"
        spec_path.write_text(json.dumps({
            "requirement": {"id": REQ_ID, "name": "示例需求"},
            "delivery_status": "complete",
            "expected_base_version": None,
            "artifacts": specs,
            "created_at": "2026-10-31T10:00:00+08:00",
        }, ensure_ascii=False), encoding="utf-8")
        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["publish", str(self.root), str(spec_path)])
        self.assertEqual(status, 0)
        self.assertTrue(output.getvalue().isascii())
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_PUBLISH_PASS")




    def test_sql_only_first_then_case_release_initializes_case_history(self):
        sql_source = self.base / "first-query.sql"
        sql_source.write_text("select 1;", encoding="utf-8")
        first = publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "query", "path": "sql/query.sql",
              "source_path": str(sql_source)}],
            created_at="2026-10-31T09:00:00+08:00",
        )
        self.assertEqual(first["version_id"], "20261031-v1")
        specs = stage_bundle(self.base / "first-testcases")
        second = publish_for_test(
            self.root, REQ_ID, "示例需求", specs,
            created_at="2026-10-31T09:10:00+08:00",
        )
        self.assertEqual(second["version_id"], "20261031-v2")
        self.assertEqual(second["manifest"]["case_snapshot"][0]["revision"], 1)
        self.assertEqual(second["manifest"]["case_changes"]["added"], [CASE_A])

    def test_inspect_and_validate_cli(self):
        self.publish_first()
        from unittest.mock import patch
        for command, expected in (
            ("inspect", "MANIFEST_BASELINE_READY"),
            ("validate", "MANIFEST_HISTORY_PASS"),
        ):
            output = __import__("io").StringIO()
            with patch.object(manifest.sys, "stdout", output):
                status = manifest.main([command, str(self.root)])
            self.assertEqual(status, 0)
            self.assertTrue(output.getvalue().isascii())
            self.assertEqual(json.loads(output.getvalue())["result"], expected)

    def test_updated_revision_requires_a_changed_case_fingerprint(self):
        case = parsed_with(CASE_A)["groups"][0]["cases"][0]
        previous = {
            "requirement": {"id": REQ_ID},
            "case_snapshot": [snapshot_item(
                CASE_A, 2, fingerprint=manifest.case_fingerprint(case),
            )],
        }
        with self.assertRaisesRegex(manifest.ManifestError, "指纹未变化"):
            manifest.build_case_snapshot(
                parsed_with(CASE_A), previous, historical_ids={CASE_A},
                changes={"updated": [CASE_A]},
            )




    def test_validate_rejects_tampered_latest_case_snapshot_fingerprint(self):
        self.publish_first()
        manifest_path = self.root / "versions" / "20261031-v1" / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["case_snapshot"][0]["content_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("内容指纹与 Manifest 不一致", result["error"])

    def test_validate_rejects_tampered_superseded_case_snapshot_fingerprint(self):
        self.publish_first()
        sql_source = self.base / "fingerprint-history.sql"
        sql_source.write_text("select 9;", encoding="utf-8")
        publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "query", "path": "sql/query.sql",
              "source_path": str(sql_source)}],
            created_at="2026-10-31T10:05:00+08:00",
        )
        manifest_path = self.root / "versions" / "20261031-v1" / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["case_snapshot"][0]["content_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 1)
        self.assertIn("内容指纹与 Manifest 不一致", json.loads(output.getvalue())["error"])

    def test_validate_rejects_unregistered_source_artifact_reference(self):
        self.publish_first()
        sql_source = self.base / "source-chain.sql"
        sql_source.write_text("select 10;", encoding="utf-8")
        publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{"category": "sql", "role": "query", "path": "sql/query.sql",
              "source_path": str(sql_source)}],
            created_at="2026-10-31T10:05:00+08:00",
        )
        rogue = self.root / "testcases" / "20261031-v1" / "rogue.txt"
        rogue.write_text("not in source manifest", encoding="utf-8")
        latest_path = self.root / "versions" / "20261031-v2" / "manifest.json"
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        markdown = next(x for x in latest["artifacts"]
                        if x["category"] == "testcases" and x["role"] == "markdown")
        markdown["path"] = "20261031-v1/testcases/rogue.txt"
        markdown["sha256"] = manifest.sha256_file(rogue)
        latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 1)
        self.assertIn("来源追溯与来源 Manifest", json.loads(output.getvalue())["error"])

    def test_publish_rejects_corrupt_superseded_history_before_commit(self):
        self.publish_first()
        changed_md = MD_ONE.replace("展示匹配结果", "展示历史版本更新结果")
        specs = stage_bundle(self.base / "stage-history-integrity", changed_md)
        specs = [x for x in specs if x["role"] in {"markdown", "xmind"}]
        publish_for_test(
            self.root, REQ_ID, "示例需求", specs,
            case_changes={"updated": [CASE_A]},
            created_at="2026-10-31T10:05:00+08:00",
        )
        old_md = self.root / "testcases" / "20261031-v1" / "testcases.md"
        old_md.write_bytes(old_md.read_bytes() + b"corrupted")
        sql_source = self.base / "history-integrity.sql"
        sql_source.write_text("select 11;", encoding="utf-8")

        with self.assertRaisesRegex(manifest.ManifestError, "历史正式产物 SHA-256 不一致"):
            publish_for_test(
                self.root, REQ_ID, "示例需求",
                [{"category": "sql", "role": "query", "path": "sql/query.sql",
                  "source_path": str(sql_source)}],
                created_at="2026-10-31T10:10:00+08:00",
            )
        self.assertFalse((self.root / "versions" / "20261031-v3").exists())
        self.assertFalse((self.root / ".qa-work").exists())
        self.assertEqual(manifest.load_latest_manifest(self.root)["version_id"], "20261031-v2")

    def test_publish_rejects_windows_normalized_paths_before_creating_work_area(self):
        source = self.base / "path-source.sql"
        source.write_text("select 12;", encoding="utf-8")
        for unsafe_path in ("sql/.. /.. /escape.txt", "sql/escape.txt."):
            with self.subTest(path=unsafe_path):
                with self.assertRaises(manifest.ManifestError):
                    publish_for_test(
                        self.root, REQ_ID, "示例需求",
                        [{"category": "sql", "role": "query", "path": unsafe_path,
                          "source_path": str(source)}],
                        created_at="2026-10-31T10:00:00+08:00",
                    )
                self.assertFalse(self.root.exists())
                self.assertFalse((self.base / "escape.txt").exists())

    def test_validate_cli_detects_corrupt_superseded_historical_artifact(self):
        self.publish_first()
        changed_md = MD_ONE.replace("展示匹配结果", "展示更新后的结果")
        specs = stage_bundle(self.base / "stage-history-v2", changed_md)
        specs = [x for x in specs if x["role"] in {"markdown", "xmind"}]
        publish_for_test(
            self.root, REQ_ID, "示例需求", specs,
            case_changes={"updated": [CASE_A]},
            created_at="2026-10-31T10:05:00+08:00",
        )
        old_md = self.root / "testcases" / "20261031-v1" / "testcases.md"
        old_md.write_bytes(old_md.read_bytes() + b"corrupted")
        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("历史正式产物 SHA-256 不一致", result["error"])


class IncrementalHistoryReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "output" / "900661-示例需求"

    def publish_first(self, status="complete"):
        specs = stage_bundle(self.base / "stage-v1")
        return publish_for_test(
            self.root, REQ_ID, "示例需求", specs,
            delivery_status=status,
            created_at="2026-10-31T10:00:00+08:00",
        )

    def test_inspect_reads_history_once_and_returns_manifest_path(self):
        self.publish_first()
        from unittest.mock import patch
        output = __import__("io").StringIO()
        with patch.object(manifest, "_read_history", wraps=manifest._read_history) as read_history:
            with patch.object(manifest.sys, "stdout", output):
                status = manifest.main(["inspect", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(read_history.call_count, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "MANIFEST_BASELINE_READY")
        self.assertEqual(
            Path(result["manifest_path"]),
            self.root / "versions" / "20261031-v1" / "manifest.json",
        )

    def test_validate_reads_history_once_and_keeps_full_history_checks(self):
        self.publish_first()
        from unittest.mock import patch
        output = __import__("io").StringIO()
        with patch.object(manifest, "_read_history", wraps=manifest._read_history) as read_history:
            with patch.object(manifest.sys, "stdout", output):
                status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(read_history.call_count, 1)
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_HISTORY_PASS")

    def test_ids_uses_latest_manifest_snapshot_without_history_rescan(self):
        self.publish_first()
        from unittest.mock import patch
        baseline = self.root / "versions" / "20261031-v1" / "manifest.json"
        output = __import__("io").StringIO()
        with patch.object(
            manifest, "_read_history",
            side_effect=AssertionError("baseline ID lookup must not rescan all history"),
        ):
            with patch.object(manifest.sys, "stdout", output):
                status = manifest.main([
                    "ids", str(self.root), REQ_ID, "--count", "2",
                    "--baseline-manifest", str(baseline),
                ])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(len(result["case_ids"]), 2)
        self.assertTrue(set(result["case_ids"]).isdisjoint({CASE_A}))

    def test_ids_rejects_stale_baseline_manifest_after_new_version(self):
        self.publish_first()
        sql_source = self.base / "stale-baseline.sql"
        sql_source.write_text("select 1;", encoding="utf-8")
        publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{
                "category": "sql", "role": "query", "path": "sql/query.sql",
                "source_path": str(sql_source),
            }],
            created_at="2026-10-31T10:05:00+08:00",
        )
        from unittest.mock import patch
        output = __import__("io").StringIO()
        stale_manifest = self.root / "versions" / "20261031-v1" / "manifest.json"
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main([
                "ids", str(self.root), REQ_ID, "--count", "1",
                "--baseline-manifest", str(stale_manifest),
            ])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("不是最新正式版本", result["error"])

    def test_publish_reuses_preloaded_history_for_version_and_postcommit_checks(self):
        self.publish_first()
        changed_md = MD_ONE.replace("展示匹配结果", "展示更新后的匹配结果")
        specs = stage_bundle(self.base / "stage-v2-history-reuse", changed_md)
        from unittest.mock import patch
        with patch.object(manifest, "_read_history", wraps=manifest._read_history) as read_history:
            result = publish_for_test(
                self.root, REQ_ID, "示例需求", specs,
                case_changes={"updated": [CASE_A]},
                created_at="2026-10-31T10:05:00+08:00",
            )
        self.assertEqual(read_history.call_count, 1)
        self.assertEqual(result["version_id"], "20261031-v2")
        output = __import__("io").StringIO()
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_HISTORY_PASS")


    def test_inspect_rejects_corrupt_historical_fingerprint(self):
        self.publish_first()
        sql_source = self.base / "history-cache.sql"
        sql_source.write_text("select 1;", encoding="utf-8")
        publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{
                "category": "sql", "role": "query", "path": "sql/query.sql",
                "source_path": str(sql_source),
            }],
            created_at="2026-10-31T10:05:00+08:00",
        )
        original_read_history = manifest._read_history

        def corrupt_only_in_memory(root):
            records = original_read_history(root)
            records[0]["manifest"]["case_snapshot"][0]["content_sha256"] = "0" * 64
            return records

        from unittest.mock import patch
        output = __import__("io").StringIO()
        with patch.object(manifest, "_read_history", side_effect=corrupt_only_in_memory):
            with patch.object(manifest.sys, "stdout", output):
                status = manifest.main(["inspect", str(self.root)])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("内容指纹与 Manifest 不一致", result["error"])

    def test_inspect_parses_shared_historical_markdown_path_once(self):
        self.publish_first()
        sql_source = self.base / "history-cache-shared.sql"
        sql_source.write_text("select 2;", encoding="utf-8")
        publish_for_test(
            self.root, REQ_ID, "示例需求",
            [{
                "category": "sql", "role": "query", "path": "sql/query.sql",
                "source_path": str(sql_source),
            }],
            created_at="2026-10-31T10:05:00+08:00",
        )
        from unittest.mock import patch
        output = __import__("io").StringIO()
        with patch.object(
            artifacts, "parse_markdown", wraps=artifacts.parse_markdown,
        ) as parse_markdown:
            with patch.object(manifest.sys, "stdout", output):
                status = manifest.main(["inspect", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_BASELINE_READY")
        self.assertEqual(parse_markdown.call_count, 1)

    def test_publish_rejects_stale_baseline_after_concurrent_commit(self):
        self.publish_first()
        changed_md = MD_ONE.replace("展示匹配结果", "展示并发更新后的结果")
        update_specs = stage_bundle(self.base / "stage-concurrent-b", changed_md)
        sql_source = self.base / "concurrent-a.sql"
        sql_source.write_text("select 3;", encoding="utf-8")
        stale_specs = [{
            "category": "sql", "role": "query", "path": "sql/query.sql",
            "source_path": str(sql_source),
        }]

        context = multiprocessing.get_context("spawn")
        b_locked = context.Event()
        release_b = context.Event()
        a_attempted = context.Event()
        results = context.Queue()
        writer_b = context.Process(
            target=_concurrent_publish_worker,
            args=(
                "B", str(self.root), update_specs, "2026-10-31T10:05:00+08:00",
                "20261031-v1", results, b_locked, release_b, None,
            ),
        )
        writer_a = context.Process(
            target=_concurrent_publish_worker,
            args=(
                "A", str(self.root), stale_specs, "2026-11-01T10:00:00+08:00",
                "20261031-v1", results, None, None, a_attempted,
            ),
        )
        try:
            writer_b.start()
            self.assertTrue(b_locked.wait(10), "B did not acquire the requirement lock")
            writer_a.start()
            self.assertTrue(a_attempted.wait(10), "A did not attempt publication")
        finally:
            release_b.set()

        writer_b.join(25)
        writer_a.join(25)
        if writer_b.is_alive():
            writer_b.terminate()
            writer_b.join()
        if writer_a.is_alive():
            writer_a.terminate()
            writer_a.join()
        self.assertEqual(writer_b.exitcode, 0)
        self.assertEqual(writer_a.exitcode, 0)

        observed = {item["name"]: item for item in (
            results.get(timeout=5), results.get(timeout=5),
        )}
        self.assertEqual(observed["B"]["result"], "PASS")
        self.assertEqual(observed["B"]["version_id"], "20261031-v2")
        self.assertEqual(observed["A"]["result"], "FAIL")
        self.assertIn("发布基线已变化", observed["A"]["error"])
        self.assertEqual(len(list(self.root.parent.glob(".qa-publish-*.lock"))), 1)

        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_HISTORY_PASS")

    def test_publish_cli_requires_explicit_expected_base_version(self):
        self.root.mkdir(parents=True, exist_ok=True)
        specs = stage_bundle(self.base / "stage-missing-base")
        spec_path = self.base / "missing-base.json"
        spec_path.write_text(json.dumps({
            "requirement": {"id": REQ_ID, "name": "示例需求"},
            "delivery_status": "complete",
            "artifacts": specs,
        }, ensure_ascii=False), encoding="utf-8")
        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["publish", str(self.root), str(spec_path)])
        self.assertEqual(status, 1)
        self.assertIn("必须显式声明 expected_base_version", json.loads(output.getvalue())["error"])
        self.assertFalse(any(
            entry.is_dir() and manifest.VERSION_RE.fullmatch(entry.name)
            for entry in self.root.iterdir()
        ))


class BugReceiptArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "requirement"
        self.version = "20261105-v1"
        data = make_manifest(self.version)
        write_manifest(
            self.root,
            data,
            {f"sql/{self.version}/query.sql": b"payload"},
        )
        self.receipt = {
            "creation_status": "success",
            "bug_id": "900001",
            "title": "【模拟模块】样本列表页面，汇总与列表不一致",
            "content": "复现步骤：\\n1. 进入样本列表页面并查询。\\n实际结果：汇总与列表不一致。\\n期望结果：汇总与列表口径一致。",
            "assigned_to": "900777",
            "assignee_name": "测试指派人",
            "pri": 3,
            "severity": 3,
            "env": "GRAY",
            "type": "codeerror",
            "submitted_at": "2026-11-05T12:00:00+08:00",
            "evidence": ["人工验证记录：汇总与列表数量不一致", "代码定位：src/example.py:20"],
            "requirement_basis": "需求 900687 明确要求汇总与列表使用一致的业务口径。",
            "code_locator": "repo/src/example.py:20",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_register_success_writes_receipt_and_updates_latest_manifest(self):
        result = manifest.register_bug_receipt(self.root, self.version, self.receipt)
        self.assertEqual(result["result"], "BUG_RECEIPT_REGISTERED")
        receipt_path = self.root / "analysis" / self.version / "bug-submissions" / "BUG-900001.md"
        self.assertTrue(receipt_path.is_file())
        receipt_text = receipt_path.read_text(encoding="utf-8")
        self.assertIn("BUG-900001", receipt_text)
        self.assertIn("900687", receipt_text)
        self.assertIn("测试指派人（900777）", receipt_text)
        self.assertIn("创建结果：成功", receipt_text)

        data = json.loads((self.root / "versions" / self.version / "manifest.json").read_text(encoding="utf-8"))
        item = next(x for x in data["artifacts"] if x["role"] == "bug-submission-900001")
        self.assertEqual(item["category"], "test-impact-analysis")
        self.assertEqual(item["path"], f"analysis/{self.version}/bug-submissions/BUG-900001.md")
        self.assertEqual(item["sha256"], hashlib.sha256(receipt_path.read_bytes()).hexdigest())

        output = __import__("io").StringIO()
        from unittest.mock import patch
        with patch.object(manifest.sys, "stdout", output):
            status = manifest.main(["validate", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["result"], "MANIFEST_HISTORY_PASS")

    def test_failed_or_unknown_create_result_never_writes_receipt(self):
        manifest_before = (self.root / "versions" / self.version / "manifest.json").read_bytes()
        for state in ("failed", "unknown"):
            with self.subTest(state=state):
                candidate = dict(self.receipt, creation_status=state)
                with self.assertRaisesRegex(manifest.ManifestError, "仅 creation_status=success"):
                    manifest.register_bug_receipt(self.root, self.version, candidate)
        self.assertEqual((self.root / "versions" / self.version / "manifest.json").read_bytes(), manifest_before)
        self.assertFalse((self.root / "analysis" / self.version / "bug-submissions").exists())

    def test_duplicate_bug_receipt_is_rejected_without_overwrite(self):
        manifest.register_bug_receipt(self.root, self.version, self.receipt)
        receipt_path = self.root / "analysis" / self.version / "bug-submissions" / "BUG-900001.md"
        before = receipt_path.read_bytes()
        with self.assertRaisesRegex(manifest.ManifestError, "已存在，拒绝覆盖"):
            manifest.register_bug_receipt(self.root, self.version, self.receipt)
        self.assertEqual(receipt_path.read_bytes(), before)

    def test_only_latest_version_can_receive_bug_receipt(self):
        with self.assertRaisesRegex(manifest.ManifestError, "只能向当前最新版本归档"):
            manifest.register_bug_receipt(self.root, "20261104-v1", self.receipt)
        self.assertFalse((self.root / "analysis" / self.version / "bug-submissions").exists())

    def test_invalid_success_payload_does_not_create_archive_directory(self):
        invalid = dict(self.receipt, evidence=[])
        with self.assertRaisesRegex(manifest.ManifestError, "evidence 必须"):
            manifest.register_bug_receipt(self.root, self.version, invalid)
        self.assertFalse((self.root / "analysis" / self.version / "bug-submissions").exists())


if __name__ == "__main__":
    unittest.main()
