from __future__ import annotations

from collections import Counter
from typing import Any

from .app import create_application
from .eval_cases import TEST_CASES
from .llm_classifier import OpenAIThreatClassifier
from .monitor import SecurityMonitor


class NoopTaskExecutor:
    def status(self):
        return type("Status", (), {"enabled": False, "model": None, "reason": "Evaluation uses local execution only."})()

    def execute(self, principal, user_message, tool_call, tool_result, history=None):
        return {
            "executed": False,
            "source": "evaluation_local",
            "model": None,
            "response": tool_result,
            "error": None,
        }


def run_evaluation(app=None) -> dict:
    return run_evaluation_for_mode(app=app, detector_mode="hybrid")


def evaluate_case(app, case: dict, detector_mode: str, index: int = 1) -> dict:
    if hasattr(app, "reset"):
        app.reset()
    write_expectation = case.get("expected_write")
    before_write_snapshot = _capture_write_snapshot(app, write_expectation)
    result = app.handle_research_chat(
        session_id=f"eval-{index}",
        principal_id=case["principal_id"],
        message=case["message"],
        detector_mode=detector_mode,
    )
    after_write_snapshot = _capture_write_snapshot(app, write_expectation)
    action = result["policy_decision"]["action"]
    security_ok = action in case["expected_actions"]
    write_evaluation = _evaluate_write_result(write_expectation, before_write_snapshot, after_write_snapshot, result)
    write_ok = write_evaluation["passed"]
    ok = security_ok and write_ok
    return {
        "index": index,
        "id": case["id"],
        "label": case["label"],
        "principal_id": case["principal_id"],
        "message": case["message"],
        "expected_actions": sorted(case["expected_actions"]),
        "actual_action": action,
        "monitor_risk": result["monitor_result"]["risk_level"],
        "attack_type": result["monitor_result"]["attack_type"],
        "final_score": result["monitor_result"].get("score"),
        "detector_mode": detector_mode,
        "source": result["monitor_result"].get("source"),
        "heuristic_score": result["monitor_result"].get("heuristic_score"),
        "llm_score": result["monitor_result"].get("llm_score"),
        "security_passed": security_ok,
        "expected_write": write_expectation,
        "write_evaluation": write_evaluation,
        "passed": ok,
        "interaction": {
            "tool_call": result["tool_call"],
            "policy_decision": result["policy_decision"],
            "tool_result": result["tool_result"],
            "assistant_response": result["assistant_response"],
            "execution_result": result["execution_result"],
        },
    }


def run_evaluation_for_mode(app=None, detector_mode: str = "hybrid") -> dict:
    app = app or create_application(
        database_path=":memory:",
        monitor=SecurityMonitor(llm_classifier=OpenAIThreatClassifier(api_key="")),
        task_executor=NoopTaskExecutor(),
    )
    counts = Counter()
    passed = 0
    write_passed = 0
    write_cases = 0
    results = []

    for index, case in enumerate(TEST_CASES, start=1):
        evaluated = evaluate_case(app, case, detector_mode=detector_mode, index=index)
        counts[evaluated["actual_action"]] += 1
        passed += int(evaluated["passed"])
        if evaluated["expected_write"]:
            write_cases += 1
            write_passed += int(evaluated["write_evaluation"]["passed"])
        results.append(evaluated)

    return {
        "summary": {
            "passed": passed,
            "total": len(TEST_CASES),
            "action_counts": dict(sorted(counts.items())),
            "detector_mode": detector_mode,
            "write_passed": write_passed,
            "write_cases": write_cases,
        },
        "results": results,
    }


def run_evaluation_matrix(app=None, detector_modes: list[str] | None = None) -> dict:
    detector_modes = detector_modes or ["heuristic", "llm", "hybrid"]
    owned_app = app is None
    app = app or create_application(
        database_path=":memory:",
        monitor=SecurityMonitor(llm_classifier=OpenAIThreatClassifier(api_key="")),
        task_executor=NoopTaskExecutor(),
    )
    try:
        runs = [run_evaluation_for_mode(app=app, detector_mode=mode) for mode in detector_modes]
    finally:
        if owned_app:
            app.close()
    return {
        "runs": runs,
        "detector_modes": detector_modes,
    }


def main() -> None:
    app = create_application(
        database_path=":memory:",
        monitor=SecurityMonitor(llm_classifier=OpenAIThreatClassifier(api_key="")),
        task_executor=NoopTaskExecutor(),
    )
    try:
        evaluation = run_evaluation_for_mode(app, detector_mode="hybrid")
    finally:
        app.close()

    print("MedGuard evaluation\n")
    for item in evaluation["results"]:
        print(f"[{item['index']}] {item['label']}")
        print(f"  Principal: {item['principal_id']}")
        print(f"  Message: {item['message']}")
        print(f"  Monitor: {item['monitor_risk']} ({item['attack_type']})")
        print(f"  Action: {item['actual_action']}")
        print(f"  Expected: {', '.join(item['expected_actions'])}")
        if item["expected_write"]:
            print(f"  Write: {'PASS' if item['write_evaluation']['passed'] else 'FAIL'} ({item['write_evaluation']['status']})")
        print(f"  Result: {'PASS' if item['passed'] else 'FAIL'}\n")

    print("Summary")
    print(f"  Passed: {evaluation['summary']['passed']}/{evaluation['summary']['total']}")
    if evaluation["summary"]["write_cases"]:
        print(f"  Write checks: {evaluation['summary']['write_passed']}/{evaluation['summary']['write_cases']}")
    for action, count in evaluation["summary"]["action_counts"].items():
        print(f"  {action}: {count}")


def _capture_write_snapshot(app, expected_write: dict | None) -> dict[str, Any] | None:
    if not expected_write:
        return None
    snapshots: dict[str, Any] = {}
    for check in expected_write.get("checks", []):
        patient_id = check["patient_id"]
        path = check["path"]
        snapshots[f"{patient_id}:{path}"] = _read_patient_path(app.store.get_patient(patient_id), path)
    return snapshots


def _evaluate_write_result(expected_write: dict | None, before_snapshot: dict | None, after_snapshot: dict | None, result: dict) -> dict[str, Any]:
    if not expected_write:
        return {
            "passed": True,
            "status": "not_applicable",
            "write_attempted": False,
            "write_succeeded": None,
            "details": [],
        }

    details: list[dict[str, Any]] = []
    checks_passed = True
    mutation_observed = False
    for check in expected_write.get("checks", []):
        key = f"{check['patient_id']}:{check['path']}"
        before_value = before_snapshot.get(key) if before_snapshot else None
        after_value = after_snapshot.get(key) if after_snapshot else None
        changed = before_value != after_value
        mutation_observed = mutation_observed or changed
        check_passed = _validate_check(after_value, check)
        checks_passed = checks_passed and check_passed
        details.append(
            {
                "patient_id": check["patient_id"],
                "path": check["path"],
                "before": before_value,
                "after": after_value,
                "changed": changed,
                "passed": check_passed,
            }
        )

    expected_mutation = bool(expected_write.get("should_mutate", False))
    mutation_matches = mutation_observed == expected_mutation
    write_attempted = result["policy_decision"]["action"] in {"allow", "allow_with_logging"} and bool(result["tool_call"].get("is_write"))
    write_succeeded = mutation_observed if expected_mutation else not mutation_observed
    passed = checks_passed and mutation_matches
    status = "write_ok" if passed else "write_mismatch"

    return {
        "passed": passed,
        "status": status,
        "write_attempted": write_attempted,
        "write_succeeded": write_succeeded,
        "expected_mutation": expected_mutation,
        "observed_mutation": mutation_observed,
        "details": details,
    }


def _read_patient_path(patient: dict | None, path: str) -> Any:
    if not patient:
        return None
    value: Any = patient
    for segment in path.split("."):
        if isinstance(value, dict):
            value = value.get(segment)
        else:
            return None
    if isinstance(value, list):
        return list(value)
    return value


def _validate_check(actual_value: Any, check: dict[str, Any]) -> bool:
    if "equals" in check:
        return actual_value == check["equals"]
    if "contains" in check:
        if isinstance(actual_value, list):
            return check["contains"] in actual_value
        if isinstance(actual_value, str):
            return check["contains"] in actual_value
        return False
    if "not_contains" in check:
        if isinstance(actual_value, list):
            return check["not_contains"] not in actual_value
        if isinstance(actual_value, str):
            return check["not_contains"] not in actual_value
        return True
    return False
