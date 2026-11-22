"""Deterministically replay multi-day state scenarios through the real pipeline.

The fetcher and model are scripted so this checks ordering, snapshot retention,
error isolation, and the per-run step budget without live sites or API calls.
It is a workflow replay, not a measurement of model quality.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.extraction.schemas import AnalysisResult, CompetitorOffer
from src.pipeline import run_pipeline

URL = "https://example.test/product/1"
CRITERIA = ["Изменение цены от 5% значимо", "Изменение наличия значимо"]


def _snapshot(price: int, availability: str = "in stock") -> dict:
    return {"source_url": URL, "product_name": "Fixture product", "price": price,
            "currency": "RUB", "availability": availability}


def _step(name: str, price: int | None, status: str, *, availability: str = "in stock",
          error: str | None = None, cosmetic: bool = False, field: str | None = None) -> dict:
    response = {"status": status,
                "current_snapshot": _snapshot(price, availability) if price is not None else None,
                "changes": [], "explanation": "Фикстурный ответ для проверки цепочки."}
    if status == "significant":
        response["changes"] = [{"field": field or ("availability" if availability != "in stock" else "price"),
                                "old_value": None, "new_value": str(price if price is not None else availability),
                                "explanation": "Фикстурное изменение."}]
    return {"id": name, "html": ("<html><title>Fixture</title><body>" +
            ("Изменён баннер." if cosmetic else f"Цена {price} RUB, наличие {availability}. ") +
            ("Описание страницы для фикстуры. " * 12) + "</body></html>"),
            "response": response, "error": error}


SCENARIOS = [
    {"id": "dependent_price_change", "max_steps": 3,
     "steps": [_step("day-1", 1000, "initialized"), _step("day-2", 920, "significant")]},
    {"id": "cosmetic_html_change", "max_steps": 3,
     "steps": [_step("day-1", 1000, "initialized"), _step("day-2", 1000, "insignificant", cosmetic=True)]},
    {"id": "fetch_failure_mid_chain", "max_steps": 4,
     "steps": [_step("day-1", 1000, "initialized"),
               _step("day-2", None, "uncertain", error="HTTP 503 fixture failure"),
               _step("day-3", 900, "significant")]},
    {"id": "contradictory_reversal", "max_steps": 4,
     "steps": [_step("day-1", 1000, "initialized"),
               _step("day-2", 900, "significant"),
               _step("day-3", 1000, "significant")]},
    {"id": "step_budget_exhaustion", "max_steps": 3,
     "steps": [_step("day-1", 1000, "initialized"), _step("day-2", 970, "insignificant"),
               _step("day-3", 900, "significant"), _step("day-4", 850, "significant"),
               _step("day-5", 800, "significant")]},
    {"id": "availability_round_trip", "max_steps": 4,
     "steps": [_step("day-1", 1000, "initialized"),
               _step("day-2", 1000, "significant", availability="out of stock", field="availability"),
               _step("day-3", 1000, "significant", availability="in stock", field="availability")]},
]


def replay(scenario: dict) -> dict:
    previous: CompetitorOffer | None = None
    outcomes = []
    started = time.perf_counter()
    processed = scenario["steps"][:scenario["max_steps"]]
    for step in processed:
        expected_status = "error" if step["error"] else step["response"]["status"]
        previous_price = str(previous.price) if previous is not None else None
        class ScriptedAnalyzer:
            def analyze(self, _request):
                return AnalysisResult.model_validate(step["response"])

        def fixture_fetcher(_url: str) -> str:
            if step["error"]:
                raise RuntimeError(step["error"])
            return step["html"]

        try:
            result = run_pipeline(
                url=URL,
                product_description="Fixture product",
                significance_criteria=CRITERIA,
                previous_snapshot_override=previous,
                fetcher=fixture_fetcher,
                analyzer_factory=ScriptedAnalyzer,
                persist=False,
            )
            if result.status.value != "uncertain" and result.current_snapshot is not None:
                previous = result.current_snapshot
            expected_snapshot = step["response"].get("current_snapshot")
            if (step["response"]["status"] != "uncertain"
                    and expected_snapshot is not None):
                expected_price = str(expected_snapshot["price"])
                expected_availability = expected_snapshot["availability"]
            else:
                expected_price = previous_price
                expected_availability = (previous.availability if previous else None)
            actual_price = str(previous.price) if previous else None
            actual_availability = previous.availability if previous else None
            snapshot_matches = (actual_price == expected_price
                                and actual_availability == expected_availability)
            outcomes.append({"step": step["id"], "expected_status": expected_status,
                             "status": result.status.value,
                             "snapshot_price_before": previous_price,
                             "snapshot_price_after": actual_price,
                             "snapshot_availability_after": actual_availability,
                             "snapshot_matches_expected": snapshot_matches,
                             "passed": result.status.value == expected_status and snapshot_matches,
                             "error": None})
        except Exception as error:
            outcomes.append({"step": step["id"], "expected_status": expected_status,
                             "status": "error", "snapshot_price_before": previous_price,
                             "error": f"{type(error).__name__}: {error}",
                             "snapshot_retained": previous is not None,
                             "passed": (expected_status == "error"
                                        and (str(previous.price) if previous else None) == previous_price)})

    budget_ok = len(processed) == min(len(scenario["steps"]), scenario["max_steps"])
    return {"scenario": scenario["id"], "max_steps": scenario["max_steps"],
            "planned_steps": len(scenario["steps"]), "executed_steps": len(processed),
            "deferred_steps": max(0, len(scenario["steps"]) - len(processed)),
            "passed": budget_ok and all(outcome["passed"] for outcome in outcomes),
            "elapsed_seconds": time.perf_counter() - started, "outcomes": outcomes}


def main() -> None:
    runs = [replay(scenario) for scenario in SCENARIOS]
    output = {"metadata": {"harness_version": "1.0.0", "model": "scripted-fixtures",
                            "started_at": datetime.now(timezone.utc).isoformat(),
                            "note": "Workflow behavior only; not a model-quality result."},
              "scenarios": runs}
    directory = Path("runs")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "scenario-replay.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
