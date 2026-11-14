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


if __name__ == "__main__":
    unittest.main()
