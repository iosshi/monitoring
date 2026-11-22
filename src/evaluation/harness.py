"""Run the HTML-diff baseline and the production pipeline on identical JSONL rows.

Each row contains: id, url, product_description, significance_criteria,
previous_html, current_html, previous_snapshot (object or null),
expected_status (initialized/significant/insignificant/uncertain), expected_fields (list).
The HTML is fixture data: the harness never fetches live pages or writes to the
production snapshot database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.extraction.llm_client import GroqClient
from src.extraction.prompts import SYSTEM_PROMPT
from src.extraction.schemas import CompetitorOffer
from src.ingestion.page_validator import validate_page
from src.pipeline import run_pipeline

HARNESS_VERSION = "1.0.0"
EXPECTED = {"initialized", "significant", "insignificant", "uncertain", "error"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSONL at {path}:{line_no}: {error}") from error
        required = {"id", "url", "product_description", "significance_criteria",
                    "previous_html", "current_html", "expected_status", "expected_fields"}
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{path}:{line_no}: missing fields {sorted(missing)}")
        if row["expected_status"] not in EXPECTED:
            raise ValueError(f"{path}:{line_no}: unsupported expected_status")
        if not isinstance(row["expected_fields"], list):
            raise ValueError(f"{path}:{line_no}: expected_fields must be a list")
        rows.append(row)
    if not rows:
        raise ValueError(f"No evaluation rows in {path}")
    return rows


def _baseline(row: dict[str, Any]) -> dict[str, Any]:
    # KT2 baseline: byte-for-byte HTML diff. Any changed byte is a change alert.
    started = time.perf_counter()
    baseline_current_html = row.get("baseline_current_html", row["current_html"])
    changed = row["previous_html"] != baseline_current_html
    return {"status": "significant" if changed else "insignificant",
            "fields": ["html"] if changed else [], "error": None,
            "model_calls": 0, "cost_usd": 0.0,
            "elapsed_seconds": time.perf_counter() - started}


def _production(row: dict[str, Any], request_interval_seconds: float = 0.0) -> dict[str, Any]:
    previous = row.get("previous_snapshot")
    snapshot = CompetitorOffer.model_validate(previous) if previous else None
    def fixture_fetcher(_url: str) -> str:
        return row["current_html"]
    started = time.perf_counter()
    client = None
    try:
        page_is_valid, _reason = validate_page(row["current_html"])
        if page_is_valid and request_interval_seconds > 0:
            time.sleep(request_interval_seconds)
        client = GroqClient(retry_delay_floor_seconds=request_interval_seconds)
        result = run_pipeline(
            url=row["url"],
            product_description=row["product_description"],
            significance_criteria=row["significance_criteria"],
            previous_snapshot_override=snapshot,
            fetcher=fixture_fetcher,
            analyzer_factory=lambda: client,
            persist=False,
        )
        input_rate = os.getenv("GROQ_INPUT_USD_PER_MILLION")
        output_rate = os.getenv("GROQ_OUTPUT_USD_PER_MILLION")
        cost = None
        if client.call_count and input_rate is not None and output_rate is not None:
            cost = (client.total_prompt_tokens * float(input_rate)
                    + client.total_completion_tokens * float(output_rate)) / 1_000_000
        return {"status": result.status.value,
                "fields": [change.field for change in result.changes],
                "error": None, "model_calls": client.call_count, "cost_usd": cost,
                "input_tokens": client.total_prompt_tokens,
                "output_tokens": client.total_completion_tokens,
                "elapsed_seconds": time.perf_counter() - started}
    except Exception as error:
        return {"status": "error", "fields": [],
                "error": f"{type(error).__name__}: {error}",
                "model_calls": client.call_count if client else 0, "cost_usd": None,
                "elapsed_seconds": time.perf_counter() - started}


def _binary_metrics(expected: list[bool], predicted: list[bool]) -> dict[str, Any]:
    tp = sum(a and b for a, b in zip(expected, predicted))
    fp = sum((not a) and b for a, b in zip(expected, predicted))
    fn = sum(a and (not b) for a, b in zip(expected, predicted))
    tn = sum((not a) and (not b) for a, b in zip(expected, predicted))
    return {"precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "true_positive": tp, "false_positive": fp,
            "false_negative": fn, "true_negative": tn}


def evaluate(rows: list[dict[str, Any]], runner: Callable, *,
             field_capable: bool = True) -> dict[str, Any]:
    outputs = []
    for row in rows:
        actual = runner(row)
        expected_fields = set(row["expected_fields"])
        predicted_fields = set(actual["fields"])
        outputs.append({"id": row["id"], "expected_status": row["expected_status"],
                        "expected_fields": sorted(expected_fields), **actual,
                        "source_expected": row.get("source_expected"),
                        "note": row.get("note"),
                        "field_exact_match": (expected_fields == predicted_fields
                                               if field_capable else None),
                        "status_correct": row["expected_status"] == actual["status"]})

    expects_significant = [r["expected_status"] == "significant" for r in rows]
    predicts_significant = [o["status"] == "significant" for o in outputs]
    expects_change = [bool(r["expected_fields"]) for r in rows]
    predicts_change = [bool(o["fields"]) for o in outputs]
    total_elapsed = sum(o.get("elapsed_seconds", 0) for o in outputs)
    known_costs = [o["cost_usd"] for o in outputs if o.get("cost_usd") is not None]
    field_scores = [o["field_exact_match"] for o in outputs
                    if o["field_exact_match"] is not None]
    return {
        "metrics": {
            "change_detection": _binary_metrics(expects_change, predicts_change),
            "significance_classification": _binary_metrics(expects_significant, predicts_significant),
            "status_accuracy": sum(o["status_correct"] for o in outputs) / len(outputs),
            "field_exact_match_rate": (sum(field_scores) / len(field_scores)
                                       if field_scores else None),
        },
        "run": {"examples": len(rows), "elapsed_seconds": total_elapsed,
                "model_calls": sum(o.get("model_calls") or 0 for o in outputs),
                "known_cost_usd": sum(known_costs) if len(known_costs) == len(rows) else None},
        "examples": outputs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eval_jsonl", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    parser.add_argument("--label", default="manual")
    parser.add_argument("--baseline-only", action="store_true",
                        help="Run the deterministic HTML-diff baseline without calling Groq")
    parser.add_argument("--request-interval-seconds", type=float, default=0.0,
                        help="Minimum spacing between model requests and retry floor (for example 15 on an 8k TPM tier)")
    args = parser.parse_args()
    if not args.baseline_only and not os.getenv("GROQ_API_KEY"):
        parser.error("GROQ_API_KEY is required for system evaluation; set it in .env or the environment")
    if args.request_interval_seconds < 0:
        parser.error("--request-interval-seconds must be non-negative")
    rows = _read_jsonl(args.eval_jsonl)
    eval_hash = hashlib.sha256(args.eval_jsonl.read_bytes()).hexdigest()
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    prompt_hash = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    run = {
        "metadata": {"harness_version": HARNESS_VERSION, "eval_file": str(args.eval_jsonl),
                     "eval_sha256": eval_hash, "model": model,
                     "system_prompt_sha256": prompt_hash, "temperature": 0,
                     "seed": None, "label": args.label,
                     "request_interval_seconds": args.request_interval_seconds,
                     "started_at": datetime.now(timezone.utc).isoformat(),
                     "cost_note": "Cost is calculated from Groq usage and the two GROQ_*_USD_PER_MILLION environment rates; null when rates or usage are unavailable."},
        "baseline": evaluate(rows, _baseline, field_capable=False),
        "system": (None if args.baseline_only else evaluate(
            rows, lambda row: _production(row, args.request_interval_seconds))),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir / f"{stamp}-{args.label}.json"
    output.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
