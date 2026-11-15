import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "validate_api_index.py"
SPEC = importlib.util.spec_from_file_location("validate_api_index", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ApiIndexValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "interfaces").mkdir()
        (self.root / "evidence").mkdir()
        self.interface = {
            "api_code": "sample.api",
            "platform": {
                "case_id": 100, "case_version": 3, "formal_report_id": 900,
                "case_ids": [100], "historical_case_ids": [],
                "step_count": 1, "enabled_step_count": 1, "disabled_step_count": 0,
            },
            "scenarios": [{
                "scenario_key": "SCN-000001", "current_case_id": 100,
                "current_step_id": "step-1", "current_enabled": True,
                "formal_result": {"report_id": 900, "result_id": 901, "status": "SUCCESS"},
            }],
            "coverage_review": {"groups": [{"evidence_scope": {}}], "scenario_record_count": 1},
            "requirement_updates": [],
        }
        self.index_entry = {
            "api_code": "sample.api", "case_id": 100, "case_ids": [100],
            "historical_case_ids": [], "case_count": 1, "historical_case_count": 0,
            "case_version": 3, "total_step_count": 1, "active_step_count": 1,
            "disabled_step_count": 0, "latest_formal_report_id": 900,
            "last_formal_report_case_version": 3,
            "current_version_formal_status": "SUCCESS",
            "current_version_formal_report_id": 900,
            "latest_incremental_requirement": None,
        }
        self.report = {
            "report_id": 900, "report_type": 10, "case_id": 100, "case_version": 3,
            "scenario_results": [{"scenario_key": "SCN-000001", "result_id": 901, "status": "SUCCESS"}],
        }
        self.write_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def write_fixture(self):
        (self.root / "index.json").write_text(json.dumps({"interfaces": [self.index_entry]}), encoding="utf-8")
        (self.root / "interfaces" / "sample.api.json").write_text(json.dumps(self.interface), encoding="utf-8")
        (self.root / "evidence" / "run-900.json").write_text(json.dumps(self.report), encoding="utf-8")

    def codes(self):
        return {item["code"] for item in MODULE.validate_api_index(self.root)}

    def findings(self):
        return MODULE.validate_api_index(self.root)

    def test_consistent_index_and_current_report_pass(self):
        self.assertEqual(self.findings(), [])

    def test_nested_execution_case_version_is_used_not_outer_current_version(self):
        self.report = {
            "type": "case-reconciliation", "case_id": 100, "current_version": 9,
            "execution": {"case_id": 100, "case_version": 2, "report_type": 10},
            "report": {"id": 900, "case_id": 100, "report_type": 10},
        }
        self.index_entry["last_formal_report_case_version"] = 2
        self.index_entry["case_version"] = 2
        self.interface["platform"]["case_version"] = 2
        self.write_fixture()
        self.assertNotIn("LATEST_REPORT_VERSION_MISMATCH", self.codes())

    def test_current_version_is_never_used_as_report_version_fallback(self):
        self.report = {
            "case_id": 100, "current_version": 9, "report_id": 900, "report_type": 10,
        }
        self.write_fixture()
        self.assertIn("LATEST_REPORT_VERSION_UNKNOWN", self.codes())
        self.assertIn("CURRENT_REPORT_VERSION_UNKNOWN", self.codes())

    def test_missing_report_case_and_type_are_not_silently_accepted(self):
        self.report = {"report_id": 900, "scenario_results": []}
        self.write_fixture()
        self.assertIn("LATEST_REPORT_TYPE_UNKNOWN", self.codes())
        self.assertIn("LATEST_REPORT_CASE_UNKNOWN", self.codes())
        self.assertIn("LATEST_REPORT_VERSION_UNKNOWN", self.codes())

    def test_missing_index_current_report_projection_is_rejected(self):
        self.index_entry["current_version_formal_report_id"] = None
        self.write_fixture()
        self.assertIn("CURRENT_RUN_REPORT_MISSING", self.codes())

    def test_current_status_and_report_id_both_missing_must_error_when_platform_has_values(self):
        self.interface["platform"]["current_version_formal_status"] = "SUCCESS"
        self.interface["platform"]["current_version_formal_report_id"] = 900
        self.index_entry["current_version_formal_status"] = None
        self.index_entry["current_version_formal_report_id"] = None
        self.write_fixture()
        mismatches = [item for item in self.findings()
                      if item["code"] == "INDEX_PLATFORM_FIELD_MISMATCH"]
        self.assertEqual(len(mismatches), 2)

    def test_current_report_projection_absent_field_must_error_when_platform_has_value(self):
        self.interface["platform"]["current_version_formal_report_id"] = 900
        self.index_entry.pop("current_version_formal_report_id")
        self.write_fixture()
        self.assertIn("INDEX_PLATFORM_FIELD_MISMATCH", self.codes())

    def test_index_current_report_must_match_platform_formal_report(self):
        self.index_entry["current_version_formal_report_id"] = 899
        self.write_fixture()
        self.assertIn("CURRENT_REPORT_PLATFORM_MISMATCH", self.codes())
    def test_enabled_scenario_must_belong_to_current_case(self):
        self.interface["scenarios"][0]["current_case_id"] = 999
        self.write_fixture()
        self.assertIn("SCENARIO_CURRENT_CASE_MISMATCH", self.codes())

    def test_current_and_historical_case_ids_must_not_overlap(self):
        self.interface["platform"]["historical_case_ids"] = [100]
        self.index_entry["historical_case_ids"] = [100]
        self.write_fixture()
        self.assertIn("CURRENT_CASE_MARKED_HISTORICAL", self.codes())

    def test_step_counts_must_match_authoritative_platform_snapshot(self):
        self.index_entry["total_step_count"] = 999
        self.write_fixture()
        self.assertIn("INDEX_PLATFORM_FIELD_MISMATCH", self.codes())

    def test_historical_formal_result_is_checked_even_when_current_version_not_run(self):
        self.index_entry["current_version_formal_status"] = "NOT_RUN_AFTER_UPDATE"
        self.index_entry["current_version_formal_report_id"] = None
        self.interface["scenarios"][0]["formal_result"]["result_id"] = 999
        self.write_fixture()
        self.assertIn("SCENARIO_RESULT_ID_MISMATCH", self.codes())

    def test_two_scenarios_sharing_result_id_both_have_status_checked(self):
        duplicate = dict(self.interface["scenarios"][0])
        duplicate["scenario_key"] = "SCN-000002"
        duplicate["current_step_id"] = "step-2"
        duplicate["formal_result"] = {"report_id": 900, "result_id": 901, "status": "FAIL"}
        self.interface["scenarios"].append(duplicate)
        self.interface["coverage_review"]["scenario_record_count"] = 2
        self.write_fixture()
        mismatches = [item for item in self.findings()
                      if item["code"] == "SCENARIO_RESULT_STATUS_MISMATCH"]
        self.assertEqual(len(mismatches), 1)
        self.assertIn("scenarios[1]", mismatches[0]["path"])

    def test_formal_and_latest_result_of_same_scenario_are_checked_independently(self):
        self.interface["scenarios"][0]["latest_formal_result"] = {
            "report_id": 900, "result_id": 999, "status": "FAIL",
        }
        self.write_fixture()
        findings = self.findings()
        self.assertIn("SCENARIO_RESULT_ID_MISMATCH", {x["code"] for x in findings})
        self.assertIn("SCENARIO_RESULT_STATUS_MISMATCH", {x["code"] for x in findings})
        self.assertTrue(all("latest_formal_result" in x["path"] for x in findings
                            if x["code"] in {"SCENARIO_RESULT_ID_MISMATCH", "SCENARIO_RESULT_STATUS_MISMATCH"}))

    def test_invalid_latest_requirement_update_is_finding_not_exception(self):
        self.interface["requirement_updates"] = [None]
        self.index_entry["latest_incremental_requirement"] = {"id": 1}
        self.write_fixture()
        self.assertIn("LATEST_REQUIREMENT_UPDATE_INVALID", self.codes())

    def test_non_string_requirement_scenario_key_is_finding_not_exception(self):
        self.interface["requirement_updates"] = [{"added_scenario_keys": [{"bad": "key"}]}]
        self.write_fixture()
        self.assertIn("REQUIREMENT_SCENARIO_KEY_INVALID", self.codes())

    def test_null_scenario_is_finding_and_does_not_crash_following_checks(self):
        self.interface["scenarios"] = [None]
        self.interface["coverage_review"]["scenario_record_count"] = 1
        self.write_fixture()
        self.assertIn("SCENARIO_INVALID", self.codes())

    def test_duplicate_scenario_key_is_rejected(self):
        self.interface["scenarios"].append(dict(self.interface["scenarios"][0]))
        self.interface["coverage_review"]["scenario_record_count"] = 2
        self.interface["platform"]["step_count"] = 2
        self.interface["platform"]["enabled_step_count"] = 2
        self.index_entry["total_step_count"] = 2
        self.index_entry["active_step_count"] = 2
        self.write_fixture()
        self.assertIn("DUPLICATE_SCENARIO_KEY", self.codes())

    def test_enabled_scenario_requires_current_step_mapping(self):
        self.interface["scenarios"][0]["current_step_id"] = None
        self.write_fixture()
        self.assertIn("CURRENT_STEP_MAPPING_MISSING", self.codes())

    def test_latest_requirement_projection_must_match_interface_history(self):
        self.interface["requirement_updates"] = [{
            "requirement_id": 12, "version_id": "20261113-v1", "status": "PARTIAL",
            "added_scenario_keys": ["SCN-000001"],
        }]
        self.index_entry["latest_incremental_requirement"] = {"id": 13, "version": "20261113-v1", "status": "PARTIAL"}
        self.write_fixture()
        self.assertIn("LATEST_REQUIREMENT_PROJECTION_MISMATCH", self.codes())

    def test_direct_formal_report_takes_precedence_over_nested_historical_report(self):
        self.report = {
            "type": "formal-run-summary", "case_id": 100, "case_version": 2,
            "current_version": 9, "report_id": 900, "report_type": 10,
            "historical_formal_report": {"report_id": 899, "case_version": 1, "report_type": 10},
            "scenario_results": [{"scenario_key": "SCN-000001", "result_id": 901, "status": "SUCCESS"}],
        }
        self.index_entry["case_version"] = 2
        self.index_entry["last_formal_report_case_version"] = 2
        self.interface["platform"]["case_version"] = 2
        self.write_fixture()
        self.assertNotIn("LATEST_REPORT_VERSION_MISMATCH", self.codes())

    def test_summary_without_execution_envelope_warns_version_provenance(self):
        self.report["type"] = "formal-run-summary"
        self.report.pop("execution", None)
        self.write_fixture()
        self.assertIn("REPORT_EXECUTION_VERSION_PROVENANCE_UNVERIFIED", self.codes())

    def test_nested_report_uses_envelope_step_results(self):
        self.report = {
            "execution": {"case_id": 100, "case_version": 3, "report_type": 10},
            "report": {"id": 900, "case_id": 100, "report_type": 10},
            "step_results": [{"result_id": 901, "status": "SUCCESS"}],
        }
        self.write_fixture()
        self.assertNotIn("REPORT_STEP_RESULTS_UNAVAILABLE", self.codes())

    def test_nested_historical_formal_report_does_not_use_outer_current_version(self):
        self.report = {
            "case_id": 100, "current_version": 8,
            "historical_formal_report": {"id": 900, "case_version": 7, "report_type": 10},
        }
        self.index_entry["last_formal_report_case_version"] = 7
        self.interface["platform"]["case_version"] = 8
        self.index_entry["case_version"] = 8
        self.index_entry["current_version_formal_status"] = "NOT_RUN_AFTER_UPDATE"
        self.index_entry["current_version_formal_report_id"] = None
        self.interface["scenarios"][0]["formal_result"] = {
            "report_id": 900, "result_id": 901, "status": "SUCCESS",
        }
        self.report["historical_formal_report"]["scenario_results"] = [{
            "scenario_key": "SCN-000001", "result_id": 901, "status": "SUCCESS",
        }]
        self.write_fixture()
        self.assertNotIn("LATEST_REPORT_VERSION_MISMATCH", self.codes())

    def test_malformed_report_result_records_are_ignored_without_crash(self):
        self.report["scenario_results"] = [None, {"scenario_key": "SCN-000001", "result_id": 901, "status": "SUCCESS"}]
        self.write_fixture()
        self.assertEqual(self.findings(), [])

    def test_non_object_coverage_group_is_finding(self):
        self.interface["coverage_review"]["groups"] = [None]
        self.write_fixture()
        self.assertIn("GROUP_EVIDENCE_SCOPE_MISSING", self.codes())


    def test_id_comparison_rejects_boolean_values(self):
        self.assertFalse(MODULE._same_id(True, "True"))
        self.assertFalse(MODULE._same_id(True, 1))
        self.assertFalse(MODULE._same_id_list([True], ["True"]))
        self.assertTrue(MODULE._same_id(100, "100"))

    def test_boolean_report_id_does_not_match_string_report_id(self):
        self.report["report_id"] = True
        self.index_entry["latest_formal_report_id"] = "True"
        self.index_entry["current_version_formal_report_id"] = "True"
        self.interface["platform"]["formal_report_id"] = "True"
        self.interface["scenarios"][0]["formal_result"]["report_id"] = "True"
        self.write_fixture()
        self.assertIn("REPORT_ID_BOOLEAN", self.codes())
        self.assertIn("LATEST_FORMAL_REPORT_EVIDENCE_MISSING", self.codes())

    def test_duplicate_current_case_ids_even_when_projections_agree(self):
        self.interface["platform"]["case_ids"] = [100, "100"]
        self.index_entry["case_ids"] = [100, "100"]
        self.index_entry["case_count"] = 2
        self.write_fixture()
        duplicates = [f for f in self.findings() if f["code"] == "DUPLICATE_CASE_ID"]
        self.assertEqual(len(duplicates), 2)
        self.assertTrue(all(f["severity"] == "ERROR" for f in duplicates))

    def test_duplicate_historical_case_ids_are_detected(self):
        self.interface["platform"]["historical_case_ids"] = [200, "200"]
        self.index_entry["historical_case_ids"] = [200, "200"]
        self.index_entry["historical_case_count"] = 2
        self.write_fixture()
        self.assertIn("DUPLICATE_CASE_ID", self.codes())

    def test_two_evidence_files_conflicting_case_version_warn(self):
        alternate = dict(self.report, case_version=4)
        (self.root / "evidence" / "run-900-other.json").write_text(
            json.dumps(alternate), encoding="utf-8"
        )
        matches = [f for f in self.findings() if f["code"] == "REPORT_EVIDENCE_CONFLICT"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["severity"], "WARNING")

    def test_two_evidence_files_conflicting_step_result_warn(self):
        alternate = json.loads(json.dumps(self.report))
        alternate["scenario_results"][0]["status"] = "FAILURE"
        (self.root / "evidence" / "run-900-other.json").write_text(
            json.dumps(alternate), encoding="utf-8"
        )
        self.assertIn("REPORT_EVIDENCE_CONFLICT", self.codes())

    def test_matching_and_complementary_report_evidence_are_allowed(self):
        (self.root / "evidence" / "run-900-other.json").write_text(
            json.dumps({"report_id": 900, "report_type": 10, "case_id": 100}),
            encoding="utf-8"
        )
        self.assertNotIn("REPORT_EVIDENCE_CONFLICT", self.codes())

    def test_complementary_report_files_cover_distinct_scenarios(self):
        """One formal report may store per-scenario results in separate files."""
        self.interface["scenarios"].append({
            "scenario_key": "SCN-000002", "current_enabled": False,
            "formal_result": {"report_id": 900, "result_id": 902, "status": "SUCCESS"},
            "latest_formal_result": {"report_id": 900, "result_id": 902, "status": "SUCCESS"},
        })
        self.interface["coverage_review"]["scenario_record_count"] = 2
        self.write_fixture()
        alternate = {
            "report_id": 900, "report_type": 10, "case_id": 100, "case_version": 3,
            "scenario_results": [
                {"scenario_key": "SCN-000002", "result_id": 902, "status": "SUCCESS"}
            ],
        }
        (self.root / "evidence" / "run-900-other.json").write_text(
            json.dumps(alternate), encoding="utf-8"
        )
        self.assertEqual(self.findings(), [])

    def test_complementary_report_still_checks_result_status(self):
        self.report["scenario_results"] = []
        self.write_fixture()
        alternate = {
            "report_id": 900, "report_type": 10, "case_id": 100, "case_version": 3,
            "scenario_results": [
                {"scenario_key": "SCN-000001", "result_id": 901, "status": "FAILURE"}
            ],
        }
        (self.root / "evidence" / "run-900-other.json").write_text(
            json.dumps(alternate), encoding="utf-8"
        )
        self.assertIn("SCENARIO_RESULT_STATUS_MISMATCH", self.codes())

    def test_complementary_report_still_detects_missing_scenario(self):
        self.interface["scenarios"][0]["formal_result"]["result_id"] = 999
        self.interface["scenarios"][0]["scenario_key"] = "SCN-UNKNOWN"
        self.write_fixture()
        alternate = {"report_id": 900, "report_type": 10, "case_id": 100,
                     "case_version": 3, "scenario_results": []}
        (self.root / "evidence" / "run-900-other.json").write_text(
            json.dumps(alternate), encoding="utf-8"
        )
        self.assertIn("SCENARIO_RESULT_MAPPING_MISSING", self.codes())

    def test_conflicting_report_version_cannot_fill_formal_result(self):
        self.report["scenario_results"] = []
        self.write_fixture()
        alternate = {"report_id": 900, "report_type": 10, "case_id": 100,
                     "case_version": 4,
                     "scenario_results": [{"scenario_key": "SCN-000001",
                                           "result_id": 901, "status": "SUCCESS"}]}
        (self.root / "evidence" / "run-900-other.json").write_text(
            json.dumps(alternate), encoding="utf-8"
        )
        codes = self.codes()
        self.assertIn("REPORT_EVIDENCE_CONFLICT", codes)
        self.assertIn("SCENARIO_RESULT_MAPPING_MISSING", codes)
        self.assertNotIn("LATEST_REPORT_VERSION_MISMATCH", codes)
        self.assertNotIn("CURRENT_REPORT_VERSION_MISMATCH", codes)

    def test_debug_report_cannot_supply_formal_scenario_result(self):
        self.report["scenario_results"] = []
        self.write_fixture()
        alternate = {"report_id": 900, "report_type": 20, "case_id": 100,
                     "case_version": 3,
                     "scenario_results": [{"scenario_key": "SCN-000001",
                                           "result_id": 901, "status": "SUCCESS"}]}
        (self.root / "evidence" / "run-900-debug.json").write_text(
            json.dumps(alternate), encoding="utf-8"
        )
        self.assertIn("REPORT_EVIDENCE_CONFLICT", self.codes())
        self.assertIn("SCENARIO_RESULT_MAPPING_MISSING", self.codes())

    def test_unknown_identity_cannot_bridge_conflicting_report_versions(self):
        """Unknown identity must not connect versions 3 and 4 into one result set."""
        observed_codes = []
        for names in (("a-unknown", "b-version3", "c-version4"),
                      ("c-unknown", "b-version3", "a-version4")):
            with self.subTest(evidence_order=names):
                for path in (self.root / "evidence").glob("*.json"):
                    path.unlink()
                unknown = {"report_id": 900, "report_type": 10,
                           "scenario_results": []}
                version3 = {"report_id": 900, "report_type": 10, "case_id": 100,
                            "case_version": 3, "scenario_results": []}
                version4 = {"report_id": 900, "report_type": 10, "case_id": 100,
                            "case_version": 4, "scenario_results": [
                                {"scenario_key": "SCN-000001", "result_id": 901,
                                 "status": "SUCCESS"}]}
                for name, document in zip(names, (unknown, version3, version4)):
                    (self.root / "evidence" / f"{name}.json").write_text(
                        json.dumps(document), encoding="utf-8"
                    )
                findings = self.findings()
                codes = {item["code"] for item in findings}
                self.assertIn("REPORT_EVIDENCE_CONFLICT", codes)
                self.assertIn("SCENARIO_RESULT_MAPPING_MISSING", codes)
                observed_codes.append(codes)
        self.assertEqual(observed_codes[0], observed_codes[1])

    def test_conflicting_version_with_valid_current_result_keeps_current_scope(self):
        """Version 4 must not disqualify a valid version 3 result."""
        unknown = {"report_id": 900, "report_type": 10,
                   "scenario_results": []}
        (self.root / "evidence" / "a-unknown.json").write_text(
            json.dumps(unknown), encoding="utf-8"
        )
        other_version = {"report_id": 900, "report_type": 10, "case_id": 100,
                         "case_version": 4, "scenario_results": []}
        (self.root / "evidence" / "z-version4.json").write_text(
            json.dumps(other_version), encoding="utf-8"
        )
        codes = self.codes()
        self.assertIn("REPORT_EVIDENCE_CONFLICT", codes)
        self.assertNotIn("SCENARIO_RESULT_MAPPING_MISSING", codes)
        self.assertNotIn("LATEST_REPORT_VERSION_MISMATCH", codes)
        self.assertNotIn("CURRENT_REPORT_VERSION_MISMATCH", codes)

    def test_unknown_identity_results_cannot_fill_conflicted_version_scope(self):
        """An unscoped result is ambiguous when known versions disagree."""
        self.report["scenario_results"] = []
        self.write_fixture()
        (self.root / "evidence" / "a-unknown.json").write_text(
            json.dumps({"report_id": 900, "report_type": 10,
                        "scenario_results": [
                            {"scenario_key": "SCN-000001", "result_id": 901,
                             "status": "SUCCESS"}]}),
            encoding="utf-8",
        )
        (self.root / "evidence" / "z-version4.json").write_text(
            json.dumps({"report_id": 900, "report_type": 10, "case_id": 100,
                        "case_version": 4, "scenario_results": []}),
            encoding="utf-8",
        )
        codes = self.codes()
        self.assertIn("REPORT_EVIDENCE_CONFLICT", codes)
        self.assertIn("SCENARIO_RESULT_MAPPING_MISSING", codes)

    def test_unknown_anchor_cannot_bridge_conflicting_case_ids(self):
        self.report["scenario_results"] = []
        self.write_fixture()
        (self.root / "evidence" / "a-unknown.json").write_text(
            json.dumps({"report_id": 900, "report_type": 10,
                        "scenario_results": []}), encoding="utf-8",
        )
        (self.root / "evidence" / "b-other-case.json").write_text(
            json.dumps({"report_id": 900, "report_type": 10, "case_id": 200,
                        "case_version": 3, "scenario_results": [
                            {"scenario_key": "SCN-000001", "result_id": 901,
                             "status": "SUCCESS"}]}), encoding="utf-8",
        )
        codes = self.codes()
        self.assertIn("REPORT_EVIDENCE_CONFLICT", codes)
        self.assertIn("SCENARIO_RESULT_MAPPING_MISSING", codes)

    def test_unknown_anchor_cannot_bridge_debug_and_formal_reports(self):
        self.report["scenario_results"] = []
        self.write_fixture()
        (self.root / "evidence" / "a-unknown.json").write_text(
            json.dumps({"report_id": 900, "scenario_results": []}),
            encoding="utf-8",
        )
        (self.root / "evidence" / "b-debug.json").write_text(
            json.dumps({"report_id": 900, "report_type": 20, "case_id": 100,
                        "case_version": 3, "scenario_results": [
                            {"scenario_key": "SCN-000001", "result_id": 901,
                             "status": "SUCCESS"}]}), encoding="utf-8",
        )
        codes = self.codes()
        self.assertIn("REPORT_EVIDENCE_CONFLICT", codes)
        self.assertIn("SCENARIO_RESULT_MAPPING_MISSING", codes)

    def test_latest_current_report_case_selection_is_permutation_invariant(self):
        """Known current Case takes precedence over conflicting Case in all file orders."""
        from itertools import permutations

        matching = {
            "report_id": 900, "report_type": 10, "case_id": 100,
            "case_version": 3, "scenario_results": [
                {"scenario_key": "SCN-000001", "result_id": 901, "status": "SUCCESS"}
            ],
        }
        conflicting = {
            "report_id": 900, "report_type": 10, "case_id": 200,
            "case_version": 3, "scenario_results": [
                {"scenario_key": "SCN-000001", "result_id": 901, "status": "SUCCESS"}
            ],
        }
        unknown = {"report_id": 900, "report_type": 10, "scenario_results": []}
        for order in permutations((matching, conflicting, unknown)):
            with self.subTest(case_ids=[record.get("case_id") for record in order]):
                for evidence_path in (self.root / "evidence").glob("*.json"):
                    evidence_path.unlink()
                for filename, record in zip(("a.json", "b.json", "c.json"), order):
                    (self.root / "evidence" / filename).write_text(
                        json.dumps(record), encoding="utf-8"
                    )
                self.assertEqual(self.codes(), {"REPORT_EVIDENCE_CONFLICT"})

    def test_historical_latest_report_does_not_use_current_case_as_identity(self):
        """A distinct historical latest report must retain its own Case identity."""
        self.index_entry["latest_formal_report_id"] = 901
        self.index_entry["last_formal_report_case_version"] = 2
        self.interface["platform"]["formal_report_id"] = 901
        self.index_entry["historical_case_ids"] = [200]
        self.interface["platform"]["historical_case_ids"] = [200]
        self.index_entry["historical_case_count"] = 1
        self.write_fixture()
        history = {
            "report_id": 901, "report_type": 10, "case_id": 200,
            "case_version": 2, "scenario_results": []
        }
        (self.root / "evidence" / "historical.json").write_text(
            json.dumps(history), encoding="utf-8"
        )
        codes = self.codes()
        self.assertNotIn("LATEST_REPORT_CASE_NOT_RECOGNIZED", codes)
        self.assertNotIn("LATEST_REPORT_VERSION_MISMATCH", codes)

    def test_duplicate_identical_report_evidence_is_not_a_conflict(self):
        (self.root / "evidence" / "run-900-copy.json").write_text(
            json.dumps(self.report), encoding="utf-8"
        )
        self.assertNotIn("REPORT_EVIDENCE_CONFLICT", self.codes())

    def test_platform_enabled_steps_without_matching_local_step_mapping_warn(self):
        self.interface["platform"]["enabled_step_count"] = 2
        self.index_entry["active_step_count"] = 2
        self.write_fixture()
        matches = [f for f in self.findings() if f["code"] == "ENABLED_STEP_MAPPING_COUNT_DIFFERS"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["severity"], "WARNING")

    def test_multiple_scenarios_merged_to_same_step_do_not_warn(self):
        merged = dict(self.interface["scenarios"][0], scenario_key="SCN-000002")
        self.interface["scenarios"].append(merged)
        self.interface["coverage_review"]["scenario_record_count"] = 2
        self.write_fixture()
        self.assertNotIn("ENABLED_STEP_MAPPING_COUNT_DIFFERS", self.codes())

if __name__ == "__main__":
    unittest.main()
