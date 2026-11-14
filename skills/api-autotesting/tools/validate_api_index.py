#!/usr/bin/env python3
"""Read-only consistency checks for API automation indexes and execution evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _finding(items: list[dict[str, str]], severity: str, code: str, path: str, message: str) -> None:
    items.append({"severity": severity, "code": code, "path": path, "message": message})


def _load_json(path: Path, findings: list[dict[str, str]]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _finding(findings, "ERROR", "JSON_READ_FAILED", str(path), str(exc))
        return None


def _same_id(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return False
    return str(left) == str(right)


def _same_id_list(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    if any(isinstance(value, (dict, list)) or value is None for value in left + right):
        return False
    return sorted(str(value) for value in left) == sorted(str(value) for value in right)


def _report_parts(evidence: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the report payload and its execution envelope without version fallbacks."""
    if evidence.get("report_id") is not None:
        return evidence, evidence
    nested_report = evidence.get("report")
    if isinstance(nested_report, dict):
        return nested_report, evidence
    historical_report = evidence.get("historical_formal_report")
    if isinstance(historical_report, dict):
        return historical_report, evidence
    return evidence, evidence


def _report_field(evidence: dict[str, Any], field: str) -> Any:
    report, envelope = _report_parts(evidence)
    if field in report and report.get(field) is not None:
        return report[field]
    execution = envelope.get("execution")
    if isinstance(execution, dict) and execution.get(field) is not None:
        return execution[field]
    # The outer current_version belongs to the Case snapshot, never to an old report.
    if field == "case_id" and envelope.get(field) is not None:
        return envelope[field]
    return None


def _report_id(evidence: dict[str, Any]) -> Any:
    report, _ = _report_parts(evidence)
    if report.get("report_id") is not None:
        return report["report_id"]
    return report.get("id")


def _report_results(evidence: dict[str, Any]) -> list[dict[str, Any]] | None:
    report, _ = _report_parts(evidence)
    for source in (report, evidence):
        for key in ("scenario_results", "step_results"):
            value = source.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return None


def _report_evidence(
    report_id: Any, evidence_by_id: dict[str, list[tuple[Path, dict[str, Any]]]]
) -> tuple[Path, dict[str, Any]] | None:
    matches = evidence_by_id.get(str(report_id), [])
    if not matches:
        return None
    formal_matches = [item for item in matches if _report_field(item[1], "report_type") == 10]
    if formal_matches:
        # Prefer the evidence record that actually carries per-Step results.
        for item in formal_matches:
            if _report_results(item[1]) is not None:
                return item
        return formal_matches[0]
    return matches[0]


def _compare_projection(
    findings: list[dict[str, str]],
    *,
    index_entry: dict[str, Any],
    interface_platform: dict[str, Any],
    index_field: str,
    platform_field: str,
    path: str,
) -> None:
    if platform_field not in interface_platform:
        return
    expected = interface_platform.get(platform_field)
    actual = index_entry.get(index_field)
    if isinstance(actual, list) or isinstance(expected, list):
        equal = _same_id_list(actual, expected)
    else:
        equal = _same_id(actual, expected)
    if not equal:
        _finding(
            findings, "ERROR", "INDEX_PLATFORM_FIELD_MISMATCH", path,
            f"Index {index_field}={actual!r} does not match authoritative platform {platform_field}={expected!r}.",
        )


def _check_report_result(
    findings: list[dict[str, str]],
    *,
    scenario: dict[str, Any],
    scenario_path: str,
    result_field: str,
    expected: dict[str, Any],
    report_id: Any,
    evidence: dict[str, Any],
) -> None:
    """Check one declared result; never substitute another field's result."""
    scenario_path = f"{scenario_path}:{result_field}"
    results = _report_results(evidence)
    if results is None:
        _finding(
            findings, "WARNING", "REPORT_STEP_RESULTS_UNAVAILABLE", scenario_path,
            f"Report {report_id} has no readable scenario_results/step_results; scenario result cannot be independently matched.",
        )
        return

    scenario_key = scenario.get("scenario_key")
    result_id = expected.get("result_id")
    matched = None
    if scenario_key is not None:
        matched = next((item for item in results if item.get("scenario_key") == scenario_key), None)
    if matched is None and result_id is not None:
        matched = next((item for item in results if _same_id(item.get("result_id"), result_id)), None)
    if matched is None:
        _finding(
            findings, "ERROR", "SCENARIO_RESULT_MAPPING_MISSING", scenario_path,
            f"Scenario {scenario_key!r} result for report {report_id} is absent from report evidence.",
        )
        return
    if result_id is not None and matched.get("result_id") is not None and not _same_id(result_id, matched.get("result_id")):
        _finding(findings, "ERROR", "SCENARIO_RESULT_ID_MISMATCH", scenario_path, f"Scenario {scenario_key!r} result_id differs from report evidence.")
    expected_status = expected.get("status")
    actual_status = matched.get("status")
    if expected_status is not None and actual_status is not None and expected_status != actual_status:
        _finding(findings, "ERROR", "SCENARIO_RESULT_STATUS_MISMATCH", scenario_path, f"Scenario {scenario_key!r} status differs from report evidence.")
    elif expected_status is not None and actual_status is None:
        _finding(findings, "WARNING", "SCENARIO_RESULT_STATUS_UNKNOWN", scenario_path, f"Report {report_id} does not expose a status for scenario {scenario_key!r}.")


def validate_api_index(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    index_path = root / "index.json"
    index = _load_json(index_path, findings)
    if not isinstance(index, dict):
        if not findings:
            _finding(findings, "ERROR", "INDEX_SHAPE_INVALID", str(index_path), "Index root must be a JSON object.")
        return findings

    entries = index.get("interfaces")
    if not isinstance(entries, list):
        _finding(findings, "ERROR", "INTERFACES_LIST_MISSING", str(index_path), "'interfaces' must be a JSON array.")
        return findings

    evidence_by_id: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    evidence_dir = root / "evidence"
    if evidence_dir.exists():
        for evidence_path in sorted(evidence_dir.glob("*.json")):
            evidence = _load_json(evidence_path, findings)
            if isinstance(evidence, dict):
                report_id = _report_id(evidence)
                if report_id is not None:
                    evidence_by_id.setdefault(str(report_id), []).append((evidence_path, evidence))

    seen_api_codes: set[str] = set()
    for position, entry in enumerate(entries):
        entry_path = f"index.json:interfaces[{position}]"
        if not isinstance(entry, dict):
            _finding(findings, "ERROR", "INDEX_ENTRY_INVALID", entry_path, "Each interface entry must be an object.")
            continue
        api_code = entry.get("api_code")
        if not isinstance(api_code, str) or not api_code.strip():
            _finding(findings, "ERROR", "API_CODE_MISSING", entry_path, "Interface entry has no API Code.")
            continue
        if api_code in seen_api_codes:
            _finding(findings, "ERROR", "DUPLICATE_API_CODE", entry_path, f"Duplicate API Code: {api_code}.")
            continue
        seen_api_codes.add(api_code)

        interface_path = root / "interfaces" / f"{api_code}.json"
        if not interface_path.is_file():
            _finding(findings, "ERROR", "INTERFACE_FILE_MISSING", str(interface_path), "Index entry has no matching interface record.")
            continue
        interface = _load_json(interface_path, findings)
        if not isinstance(interface, dict):
            continue
        if interface.get("api_code") != api_code:
            _finding(findings, "ERROR", "API_CODE_MISMATCH", str(interface_path), "Interface file API Code does not match its index entry.")

        platform = interface.get("platform")
        if not isinstance(platform, dict):
            _finding(findings, "ERROR", "PLATFORM_RECORD_INVALID", str(interface_path), "Interface platform must be an object.")
            platform = {}

        for index_field, platform_field in (
            ("case_id", "case_id"), ("case_version", "case_version"),
            ("latest_formal_report_id", "formal_report_id"),
            ("current_version_formal_report_id", "current_version_formal_report_id"),
            ("current_version_formal_status", "current_version_formal_status"),
            ("case_ids", "case_ids"), ("historical_case_ids", "historical_case_ids"),
            ("total_step_count", "step_count"), ("active_step_count", "enabled_step_count"),
            ("disabled_step_count", "disabled_step_count"),
        ):            _compare_projection(
                findings, index_entry=entry, interface_platform=platform,
                index_field=index_field, platform_field=platform_field, path=str(interface_path),
            )

        current_case_id = platform.get("case_id")
        if entry.get("current_version_formal_status") in {"SUCCESS", "PASS", "FORMAL_RUN_PASSED_CURRENT_VERSION", "FAILURE", "FAIL"} and platform.get("formal_report_id") is not None:
            if not _same_id(entry.get("current_version_formal_report_id"), platform.get("formal_report_id")):
                _finding(findings, "ERROR", "CURRENT_REPORT_PLATFORM_MISMATCH", str(index_path), "Current-version status claims a completed run, but its report ID differs from the platform latest formal_report_id.")
        historical_case_ids = platform.get("historical_case_ids", entry.get("historical_case_ids", []))
        if not isinstance(historical_case_ids, list):
            _finding(findings, "ERROR", "HISTORICAL_CASE_IDS_INVALID", str(interface_path), "historical_case_ids must be an array.")
            historical_case_ids = []
        if current_case_id is not None and any(_same_id(current_case_id, old_id) for old_id in historical_case_ids):
            _finding(findings, "ERROR", "CURRENT_CASE_MARKED_HISTORICAL", str(interface_path), "Current Case ID also appears in historical_case_ids.")

        if "case_count" in entry and isinstance(entry.get("case_ids"), list):
            if entry["case_count"] != len(entry["case_ids"]):
                _finding(findings, "ERROR", "CASE_COUNT_MISMATCH", str(index_path), f"{api_code} case_count does not match case_ids length.")
        if "historical_case_count" in entry and isinstance(entry.get("historical_case_ids"), list):
            if entry["historical_case_count"] != len(entry["historical_case_ids"]):
                _finding(findings, "ERROR", "HISTORICAL_CASE_COUNT_MISMATCH", str(index_path), f"{api_code} historical_case_count does not match historical_case_ids length.")

        scenarios = interface.get("scenarios", [])
        if not isinstance(scenarios, list):
            _finding(findings, "ERROR", "SCENARIOS_NOT_LIST", str(interface_path), "'scenarios' must be a JSON array.")
            scenarios = []
        scenario_keys: set[str] = set()
        valid_scenarios: list[tuple[int, dict[str, Any]]] = []
        for scenario_position, scenario in enumerate(scenarios):
            scenario_path = f"{interface_path}:scenarios[{scenario_position}]"
            if not isinstance(scenario, dict):
                _finding(findings, "ERROR", "SCENARIO_INVALID", scenario_path, "Scenario record must be an object.")
                continue
            valid_scenarios.append((scenario_position, scenario))
            scenario_key = scenario.get("scenario_key")
            if not isinstance(scenario_key, str) or not scenario_key.strip():
                _finding(findings, "ERROR", "SCENARIO_KEY_MISSING", scenario_path, "Scenario has no stable scenario_key.")
            elif scenario_key in scenario_keys:
                _finding(findings, "ERROR", "DUPLICATE_SCENARIO_KEY", scenario_path, f"Duplicate scenario_key: {scenario_key}.")
            else:
                scenario_keys.add(scenario_key)

            enabled = scenario.get("current_enabled")
            if enabled is not None and not isinstance(enabled, bool):
                _finding(findings, "ERROR", "CURRENT_ENABLED_NOT_BOOLEAN", scenario_path, "current_enabled must be boolean when present.")
            if enabled is True:
                if scenario.get("current_case_id") is None or scenario.get("current_step_id") is None:
                    _finding(findings, "ERROR", "CURRENT_STEP_MAPPING_MISSING", scenario_path, "Enabled scenario must map to current_case_id and current_step_id.")
                elif current_case_id is not None and not _same_id(scenario.get("current_case_id"), current_case_id):
                    _finding(findings, "ERROR", "SCENARIO_CURRENT_CASE_MISMATCH", scenario_path, "Enabled scenario maps to a Case other than the authoritative current Case.")

        coverage = interface.get("coverage_review")
        if coverage is not None and not isinstance(coverage, dict):
            _finding(findings, "ERROR", "COVERAGE_REVIEW_INVALID", str(interface_path), "coverage_review must be an object when present.")
        if isinstance(coverage, dict):
            groups = coverage.get("groups", [])
            if not isinstance(groups, list):
                _finding(findings, "ERROR", "COVERAGE_GROUPS_NOT_LIST", str(interface_path), "coverage_review.groups must be an array.")
            else:
                for group_position, group in enumerate(groups):
                    if not isinstance(group, dict) or not isinstance(group.get("evidence_scope"), dict):
                        _finding(findings, "ERROR", "GROUP_EVIDENCE_SCOPE_MISSING", f"{interface_path}:coverage_review.groups[{group_position}]", "Every coverage group must have an explicit evidence_scope object.")
            declared_count = coverage.get("scenario_record_count")
            if declared_count is not None and declared_count != len(scenarios):
                _finding(findings, "ERROR", "SCENARIO_COUNT_MISMATCH", str(interface_path), "coverage_review.scenario_record_count does not match scenarios array length.")

        requirement_updates = interface.get("requirement_updates", [])
        if not isinstance(requirement_updates, list):
            _finding(findings, "ERROR", "REQUIREMENT_UPDATES_NOT_LIST", str(interface_path), "'requirement_updates' must be a JSON array.")
            requirement_updates = []
        for update_position, update in enumerate(requirement_updates):
            update_path = f"{interface_path}:requirement_updates[{update_position}]"
            if not isinstance(update, dict):
                _finding(findings, "ERROR", "REQUIREMENT_UPDATE_INVALID", update_path, "Requirement update must be an object.")
                continue
            for key_field in (
                "added_scenario_keys", "updated_scenario_keys", "kept_scenario_keys",
                "retired_scenario_keys", "review_scenario_keys", "historical_only_scenario_keys",
            ):
                referenced = update.get(key_field, [])
                if not isinstance(referenced, list):
                    _finding(findings, "ERROR", "REQUIREMENT_SCENARIO_KEYS_NOT_LIST", update_path, f"{key_field} must be an array.")
                    continue
                malformed = [key for key in referenced if not isinstance(key, str) or not key.strip()]
                if malformed:
                    _finding(findings, "ERROR", "REQUIREMENT_SCENARIO_KEY_INVALID", update_path, f"{key_field} contains non-string or empty scenario keys.")
                missing = [key for key in referenced if isinstance(key, str) and key not in scenario_keys]
                if missing:
                    _finding(findings, "ERROR", "REQUIREMENT_SCENARIO_REFERENCE_MISSING", update_path, f"{key_field} references unknown scenario_key values: {missing[:5]}.")

        latest_projection = entry.get("latest_incremental_requirement")
        if requirement_updates:
            latest_update = requirement_updates[-1]
            if not isinstance(latest_update, dict):
                _finding(findings, "ERROR", "LATEST_REQUIREMENT_UPDATE_INVALID", str(interface_path), "Latest requirement_updates entry must be an object.")
            elif not isinstance(latest_projection, dict):
                _finding(findings, "ERROR", "LATEST_REQUIREMENT_PROJECTION_MISSING", str(index_path), f"{api_code} has requirement_updates but no latest_incremental_requirement projection.")
            else:
                for projection_field, update_field in (
                    ("id", "requirement_id"), ("version", "version_id"), ("status", "status"),
                    ("debug_report_id", "debug_report_id"), ("formal_report_id", "formal_report_id"),
                    ("summary_path", "summary_path"), ("plan_path", "plan_path"),
                ):
                    if update_field in latest_update and not _same_id(latest_projection.get(projection_field), latest_update.get(update_field)):
                        _finding(findings, "ERROR", "LATEST_REQUIREMENT_PROJECTION_MISMATCH", str(index_path), f"{api_code} latest_incremental_requirement.{projection_field} does not match the latest requirement_updates record.")
        elif latest_projection is not None:
            _finding(findings, "WARNING", "LEGACY_REQUIREMENT_PROJECTION", str(index_path), f"{api_code} has a latest_incremental_requirement but no requirement_updates history; preserve it as legacy until provenance is established.")

        latest_report_id = entry.get("latest_formal_report_id")
        latest_report = _report_evidence(latest_report_id, evidence_by_id) if latest_report_id is not None else None
        if latest_report_id is not None and latest_report is None:
            _finding(findings, "WARNING", "LATEST_FORMAL_REPORT_EVIDENCE_MISSING", str(index_path), f"{api_code} latest formal report {latest_report_id} has no local evidence file; report version remains UNKNOWN.")
        elif latest_report is not None:
            report_path, report = latest_report
            report_type = _report_field(report, "report_type")
            report_case_id = _report_field(report, "case_id")
            report_version = _report_field(report, "case_version")
            if report_type is None:
                _finding(findings, "WARNING", "LATEST_REPORT_TYPE_UNKNOWN", str(report_path), f"Report {latest_report_id} has no report_type evidence.")
            elif report_type != 10:
                _finding(findings, "ERROR", "LATEST_REPORT_NOT_FORMAL", str(report_path), f"Report {latest_report_id} is not report_type=10.")
            if report_case_id is None:
                _finding(findings, "WARNING", "LATEST_REPORT_CASE_UNKNOWN", str(report_path), f"Report {latest_report_id} has no Case ID evidence.")
            if report_version is None:
                _finding(findings, "WARNING", "LATEST_REPORT_VERSION_UNKNOWN", str(report_path), f"Report {latest_report_id} has no execution-time Case version evidence; current_version is not a substitute.")
            elif report.get("type") == "formal-run-summary" and not isinstance(report.get("execution"), dict):
                _finding(findings, "WARNING", "REPORT_EXECUTION_VERSION_PROVENANCE_UNVERIFIED", str(report_path), f"Report {latest_report_id} summary states Case version {report_version}, but no execution envelope independently binds that version to the run.")
            indexed_version = entry.get("last_formal_report_case_version")
            if report_version is not None and indexed_version is None:
                _finding(findings, "ERROR", "LATEST_REPORT_VERSION_PROJECTION_MISSING", str(index_path), f"{api_code} has report version evidence but last_formal_report_case_version is missing.")
            elif report_version is not None and not _same_id(report_version, indexed_version):
                _finding(findings, "ERROR", "LATEST_REPORT_VERSION_MISMATCH", str(index_path), f"{api_code} report {latest_report_id} evidence says Case version {report_version}, but index says {indexed_version}.")
            if report_case_id is not None and current_case_id is not None and not _same_id(report_case_id, current_case_id):
                # A latest report can belong to an older Case identity only when the Case has been replaced.
                current_and_historical = entry.get("historical_case_ids", [])
                if not isinstance(current_and_historical, list) or not any(_same_id(report_case_id, old_id) for old_id in current_and_historical):
                    _finding(findings, "WARNING", "LATEST_REPORT_CASE_NOT_RECOGNIZED", str(report_path), f"Latest report Case {report_case_id} is neither current nor listed as historical.")

        current_report_id = entry.get("current_version_formal_report_id")
        current_status = entry.get("current_version_formal_status")
        if current_status is None:
            _finding(findings, "WARNING", "CURRENT_VERSION_STATUS_UNKNOWN", str(index_path), f"{api_code} current-version formal execution status is missing.")
        if current_status == "NOT_RUN_AFTER_UPDATE" and current_report_id is not None:
            _finding(findings, "ERROR", "NOT_RUN_HAS_CURRENT_REPORT", str(index_path), f"{api_code} is NOT_RUN_AFTER_UPDATE but has a current-version formal report ID.")
        if current_status in {"SUCCESS", "PASS", "FORMAL_RUN_PASSED_CURRENT_VERSION", "FAILURE", "FAIL"} and current_report_id is None:
            _finding(findings, "ERROR", "CURRENT_RUN_REPORT_MISSING", str(index_path), f"{api_code} has current-version run status {current_status} but no current-version formal report ID.")
        if current_report_id is not None:
            current_report = _report_evidence(current_report_id, evidence_by_id)
            if current_report is None:
                _finding(findings, "WARNING", "CURRENT_REPORT_EVIDENCE_MISSING", str(index_path), f"{api_code} current-version report {current_report_id} has no local evidence file.")
            else:
                report_path, report = current_report
                report_version = _report_field(report, "case_version")
                report_case_id = _report_field(report, "case_id")
                report_type = _report_field(report, "report_type")
                if report_case_id is None:
                    _finding(findings, "WARNING", "CURRENT_REPORT_CASE_UNKNOWN", str(report_path), "Current-version report has no Case ID evidence.")
                elif current_case_id is not None and not _same_id(report_case_id, current_case_id):
                    _finding(findings, "ERROR", "CURRENT_REPORT_CASE_MISMATCH", str(report_path), "Current-version report belongs to a different Case ID.")
                if report_version is None:
                    _finding(findings, "WARNING", "CURRENT_REPORT_VERSION_UNKNOWN", str(report_path), "Current-version report has no execution-time Case version evidence.")
                elif entry.get("case_version") is None or not _same_id(report_version, entry.get("case_version")):
                    _finding(findings, "ERROR", "CURRENT_REPORT_VERSION_MISMATCH", str(report_path), "Current-version formal report does not belong to the current Case version.")
                if report_type is None:
                    _finding(findings, "WARNING", "CURRENT_REPORT_TYPE_UNKNOWN", str(report_path), "Current-version report has no report_type evidence.")
                elif report_type != 10:
                    _finding(findings, "ERROR", "CURRENT_REPORT_NOT_FORMAL", str(report_path), "Current-version report must be report_type=10.")

        # Every scenario/result-field declaration is checked, including duplicate result IDs.
        # Evidence files are loaded only once into evidence_by_id.
        for scenario_position, scenario in valid_scenarios:
            scenario_path = f"{interface_path}:scenarios[{scenario_position}]"
            for result_field in ("formal_result", "latest_formal_result"):
                result = scenario.get(result_field)
                if not isinstance(result, dict) or result.get("report_id") is None:
                    continue
                report_id = result["report_id"]
                report_record = _report_evidence(report_id, evidence_by_id)
                if report_record is None:
                    _finding(
                        findings, "WARNING", "SCENARIO_REPORT_EVIDENCE_MISSING",
                        f"{scenario_path}:{result_field}",
                        f"Scenario {scenario.get('scenario_key')!r} references report {report_id} without local evidence.",
                    )
                    continue
                _check_report_result(
                    findings, scenario=scenario, scenario_path=scenario_path,
                    result_field=result_field, expected=result,
                    report_id=report_id, evidence=report_record[1],
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only API automation index consistency checker.")
    parser.add_argument("--root", type=Path, default=Path("output/api-automation"), help="API automation index directory.")
    args = parser.parse_args()
    findings = validate_api_index(args.root)
    errors = [item for item in findings if item["severity"] == "ERROR"]
    warnings = [item for item in findings if item["severity"] == "WARNING"]
    print(f"API automation index check: {len(errors)} error(s), {len(warnings)} warning(s).")
    for item in findings:
        print(f'{item["severity"]} {item["code"]} {item["path"]}: {item["message"]}')
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
