from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


DATASET_PATH = Path(__file__).resolve().parent / "data" / "research_dataset.json"


def load_research_dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def load_benchmark_cases() -> list[dict]:
    dataset = load_research_dataset()
    return [
        {
            "id": case["id"],
            "label": case["label"],
            "principal_id": case["principal_id"],
            "message": case["message"],
            "expected_actions": set(case["expected_actions"]),
            "language": case.get("language", "en"),
            "expected_write": case.get("expected_write"),
        }
        for case in dataset["cases"]
        if case.get("include_in_benchmark", False)
    ]


def build_dataset_summary() -> dict:
    dataset = load_research_dataset()
    labels = Counter(case["label"] for case in dataset["cases"])
    languages = Counter(case.get("language", "en") for case in dataset["cases"])
    benchmark_total = sum(1 for case in dataset["cases"] if case.get("include_in_benchmark", False))
    return {
        "version": dataset["version"],
        "total_cases": len(dataset["cases"]),
        "benchmark_cases": benchmark_total,
        "categories": list(dataset.get("categories", [])),
        "counts_by_label": dict(sorted(labels.items())),
        "counts_by_language": dict(sorted(languages.items())),
        "path": str(DATASET_PATH),
    }


def build_prompt_sets(limit: int = 5) -> tuple[list[str], list[str]]:
    dataset = load_research_dataset()
    prompts: list[str] = []
    attacks: list[str] = []
    for case in dataset["cases"]:
        expected_actions = set(case.get("expected_actions", []))
        message = case["message"]
        if any(action in {"allow", "allow_with_logging"} for action in expected_actions):
            if message not in prompts:
                prompts.append(message)
        else:
            if message not in attacks:
                attacks.append(message)
    return prompts[:limit], attacks[:limit]
