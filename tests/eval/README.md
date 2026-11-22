# KT2 evaluation data

`kt2_original.csv` is the CSV linked from §5.1 of `design_doc_kt2.md`. The public export was retrieved from the link on 2026-11-21. `kt2_frozen.jsonl` is the harness-ready conversion; run `python -m src.evaluation.prepare_eval` to recreate it from the archived source.

The source contains 80 examples. Its actual labels are 39 `significant`, 26 `noise`, and 15 `error`. These counts do **not** match the percentages written in §5.1 of KT2 (40% / 25% / 30%); keep the source labels unchanged and resolve that discrepancy with the team before presenting class percentages as aligned.

The source rows are HTML fragments, not complete pages. The converter preserves the original fragments in `previous_html` and `baseline_current_html`, so the raw HTML diff uses the source pair. For the model pipeline, non-error current fragments get a neutral HTML shell with filler text so they pass the production minimum-content check. Error fixtures remain unchanged and should be rejected by page validation. No URLs are fetched by conversion or evaluation.

The converter derives `previous_snapshot` from `before_html` with deterministic regular expressions and maps source labels `significant/noise/error` to `significant/insignificant/error`. Significant `expected_fields` are mapped from the source note; noise examples retain product-field changes detectable in both HTML snippets, including the six below-threshold price changes. Cosmetic-only changes have an empty field list. The status labels are the source's annotation; derived snapshots and field labels should be spot-checked by a human before treating field-level metrics as ground truth. The source notes, IDs, and labels are retained in each JSONL row and in per-example run output.

## Baseline-only run

The exact HTML diff can be run without Groq:

```powershell
.\.venv\Scripts\python.exe -m src.evaluation.harness tests/eval/kt2_frozen.jsonl --baseline-only --label kt2-baseline
```

The corrected baseline-only result is `runs/20261121T081602Z-kt2-baseline-corrected.json`. Change-detection precision is **0.5625** (45 TP, 35 FP), recall **1.0** (45 TP, 0 FN). The 45 positives include 39 significant changes plus 6 below-threshold price changes; false positives are the 20 cosmetic-only noise cases and 15 page errors. Significance classification remains precision **0.4875**, recall **1.0** (39 TP, 41 FP), because raw HTML diff calls every difference significant. Model calls: 0; model cost: $0. The recorded comparison time is only in-process string comparison time, not end-to-end site latency.

## Full comparison

The 2026-11-21 full run hit Groq's 8,000 TPM limit. After fixing retry error handling, use a conservative 15-second interval for the 65 valid-page requests (roughly 4 requests/minute before model response time):

```powershell
.\.venv\Scripts\python.exe -m src.evaluation.harness tests/eval/kt2_frozen.jsonl --label kt2-full --request-interval-seconds 15
```

`GROQ_API_KEY` is loaded from the project's `.env` if present. To calculate cost rather than leave it `null`, also set `GROQ_INPUT_USD_PER_MILLION` and `GROQ_OUTPUT_USD_PER_MILLION` to the current rates for the selected model. The script writes a timestamped JSON to `runs/` with baseline and system results, eval/prompt hashes, model, temperature, request interval, attempts, usage, duration, cost, and row-level outputs. It uses no live website requests and does not write to production SQLite. The interval is a conservative starting value for an 8k TPM tier; if the provider still returns 429, increase it or split the eval into smaller batches with cooldowns.

Run the full comparison only after spot-checking the converted previous snapshots and field labels. Some source examples labelled `error` represent model-output errors that cannot be recreated from the page snippet alone; with this harness they primarily exercise input-page rejection. The labels remain as supplied, so this is also a limitation to state when interpreting `status_accuracy`.

## Invalid full run from 2026-11-21

`runs/20261121T080134Z-kt2-full.json` is **not a valid quality comparison**. The provider returned 429 TPM errors; 50 of the 65 valid-page examples were then masked by an `UnboundLocalError` in `GroqClient` retry handling. Only 15 model responses completed, all before the rate-limit failures; the resulting metrics are not representative. The code now preserves the original exception, respects provider retry hints, and supports a request interval. The recorded `known_cost_usd` is `null`, so that run's cost is also unknown. Do not use its model-quality metrics in KT3.
