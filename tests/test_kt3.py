import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from src.evaluation import harness, prepare_eval, scenario_harness
from src.extraction.schemas import AnalysisResult, CompetitorOffer
from src.extraction.schemas import AnalysisRequest
from src.extraction.llm_client import (
    APIConnectionError,
    APITimeoutError,
    GroqClient,
    _retry_delay,
)
from src.pipeline import run_pipeline


URL = "https://example.test/item"
CRITERIA = ["Изменение цены от 5% значимо"]


def valid_html(text="Цена 1000 RUB. " * 10):
    return f"<html><title>Товар</title><body>{text}</body></html>"


def snapshot(price=1000):
    return CompetitorOffer(source_url=URL, product_name="Товар", price=price,
                           currency="RUB", availability="in stock")


def result(status="initialized", current=None):
    return AnalysisResult(status=status, current_snapshot=current,
                          changes=[], explanation="ok")


class PipelineTests(unittest.TestCase):
    def run_fake(self, *, llm_result, previous=None, persist=False, html=None):
        analyzer = Mock()
        analyzer.analyze.return_value = llm_result
        return run_pipeline(
            URL, "Товар", CRITERIA, previous_snapshot_override=previous,
            fetcher=lambda _url: html or valid_html(),
            analyzer_factory=lambda: analyzer, persist=persist,
        ), analyzer

    @patch("src.pipeline.save_snapshot")
    @patch("src.pipeline.get_latest_snapshot", return_value=None)
    @patch("src.pipeline.init_db")
    def test_initialized_result_persists_snapshot(self, init_db, get_latest, save):
        current = snapshot()
        actual, analyzer = self.run_fake(llm_result=result(current=current), persist=True)
        self.assertEqual(actual.status.value, "initialized")
        init_db.assert_called_once()
        get_latest.assert_called_once_with(URL)
        save.assert_called_once_with(current)
        analyzer.analyze.assert_called_once()

    @patch("src.pipeline.save_snapshot")
    @patch("src.pipeline.init_db")
    def test_uncertain_result_does_not_replace_existing_snapshot(self, init_db, save):
        old = snapshot(1200)
        actual, _ = self.run_fake(llm_result=result("uncertain"), previous=old, persist=True)
        self.assertEqual(actual.status.value, "uncertain")
        save.assert_not_called()

    @patch("src.pipeline.save_snapshot")
    @patch("src.pipeline.init_db")
    def test_fixture_mode_does_not_touch_database(self, init_db, save):
        self.run_fake(llm_result=result(current=snapshot()))
        init_db.assert_not_called()
        save.assert_not_called()

    def test_blocked_page_stops_before_model_call(self):
        analyzer_factory = Mock()
        blocked = valid_html("Access denied. " * 20)
        with self.assertRaisesRegex(RuntimeError, "Page validation failed"):
            run_pipeline(URL, "Товар", CRITERIA, fetcher=lambda _url: blocked,
                         analyzer_factory=analyzer_factory, persist=False)
        analyzer_factory.assert_not_called()

    def test_oversized_page_stops_before_model_call(self):
        analyzer_factory = Mock()
        html = valid_html("x" * 100_001)
        with self.assertRaisesRegex(RuntimeError, "100000-character context budget"):
            run_pipeline(URL, "Товар", CRITERIA, fetcher=lambda _url: html,
                         analyzer_factory=analyzer_factory, persist=False)
        analyzer_factory.assert_not_called()

    def test_status_must_match_snapshot_history(self):
        with self.assertRaisesRegex(ValueError, "Expected INITIALIZED"):
            self.run_fake(llm_result=result("significant", current=snapshot()))


class EvaluationHarnessTests(unittest.TestCase):
    def test_html_baseline_flags_cosmetic_change(self):
        row = {"previous_html": "<p>price 100</p>",
               "current_html": "<p>price 100</p><span>banner</span>"}
        actual = harness._baseline(row)
        self.assertEqual(actual["status"], "significant")
        self.assertEqual(actual["fields"], ["html"])
        self.assertGreaterEqual(actual["elapsed_seconds"], 0)

    def test_metrics_compute_precision_recall_and_cost(self):
        rows = [
            {"id": "a", "expected_status": "significant", "expected_fields": ["price"]},
            {"id": "b", "expected_status": "insignificant", "expected_fields": []},
            {"id": "c", "expected_status": "significant", "expected_fields": ["price"]},
        ]
        predictions = iter([
            {"status": "significant", "fields": ["price"], "elapsed_seconds": 1,
             "model_calls": 1, "cost_usd": 0.01},
            {"status": "significant", "fields": ["html"], "elapsed_seconds": 2,
             "model_calls": 0, "cost_usd": 0.0},
            {"status": "uncertain", "fields": [], "elapsed_seconds": 3,
             "model_calls": 3, "cost_usd": 0.03},
        ])
        actual = harness.evaluate(rows, lambda _row: next(predictions))
        self.assertEqual(actual["metrics"]["change_detection"]["true_positive"], 1)
        self.assertEqual(actual["metrics"]["change_detection"]["false_positive"], 1)
        self.assertEqual(actual["metrics"]["change_detection"]["false_negative"], 1)
        self.assertEqual(actual["metrics"]["significance_classification"]["precision"], 0.5)
        self.assertEqual(actual["metrics"]["significance_classification"]["recall"], 0.5)
        self.assertEqual(actual["run"]["model_calls"], 4)
        self.assertAlmostEqual(actual["run"]["known_cost_usd"], 0.04)

    def test_baseline_does_not_claim_field_level_accuracy(self):
        rows = [{"id": "a", "expected_status": "significant",
                 "expected_fields": ["price"]}]
        actual = harness.evaluate(rows, lambda row: harness._baseline({
            "previous_html": "old", "current_html": "new"}), field_capable=False)
        self.assertIsNone(actual["metrics"]["field_exact_match_rate"])

    def test_baseline_uses_original_html_when_page_shell_is_added(self):
        row = {"previous_html": "<div>same</div>",
               "current_html": "<html><body>wrapped</body></html>",
               "baseline_current_html": "<div>same</div>"}
        self.assertEqual(harness._baseline(row)["status"], "insignificant")

    def test_downloaded_eval_converts_to_80_rows_with_source_label_counts(self):
        source_rows = prepare_eval.read_source(prepare_eval.DEFAULT_SOURCE)
        rows, counts = prepare_eval.convert(source_rows)
        self.assertEqual(len(rows), 80)
        self.assertEqual(counts, {"significant": 39, "insignificant": 26, "error": 15})
        self.assertEqual([row["id"] for row in rows], [f"{i:02}" for i in range(1, 81)])
        self.assertTrue(all(row["expected_fields"] for row in rows
                            if row["expected_status"] == "significant"))
        self.assertEqual(sum(bool(row["expected_fields"]) for row in rows), 45)
        below_threshold_price_ids = [row["id"] for row in rows
                                     if row["expected_status"] == "insignificant"
                                     and row["expected_fields"] == ["price"]]
        self.assertEqual(below_threshold_price_ids,
                         ["02", "66", "67", "68", "69", "70"])

    def test_eval_page_shells_pass_validator_and_error_fixtures_fail(self):
        from src.ingestion.page_validator import validate_page
        rows, _ = prepare_eval.convert(prepare_eval.read_source(prepare_eval.DEFAULT_SOURCE))
        for row in rows:
            valid, _reason = validate_page(row["current_html"])
            if row["expected_status"] == "error":
                self.assertFalse(valid, row["id"])
            else:
                self.assertTrue(valid, row["id"])

    def test_jsonl_validation_rejects_missing_fields(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text(json.dumps({"id": "incomplete"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing fields"):
                harness._read_jsonl(path)

    @patch.dict("os.environ", {"GROQ_INPUT_USD_PER_MILLION": "2",
                               "GROQ_OUTPUT_USD_PER_MILLION": "4"})
    @patch("src.evaluation.harness.GroqClient")
    def test_fixture_system_runner_reports_usage_cost_and_attempts(self, groq_client):
        client = groq_client.return_value
        client.call_count = 2
        client.total_prompt_tokens = 10
        client.total_completion_tokens = 20
        client.analyze.return_value = result(current=snapshot())
        row = {"url": URL, "product_description": "Товар",
               "significance_criteria": CRITERIA, "current_html": valid_html(),
               "previous_snapshot": None}
        actual = harness._production(row)
        self.assertEqual(actual["status"], "initialized")
        self.assertEqual(actual["model_calls"], 2)
        self.assertAlmostEqual(actual["cost_usd"], 0.0001)
        self.assertEqual(actual["input_tokens"], 10)
        self.assertEqual(actual["output_tokens"], 20)


class ScenarioHarnessTests(unittest.TestCase):
    def test_all_six_scripted_scenarios_pass_and_budget_defers_steps(self):
        results = [scenario_harness.replay(scenario)
                   for scenario in scenario_harness.SCENARIOS]
        self.assertEqual(len(results), 6)
        self.assertTrue(all(item["passed"] for item in results))
        budget = next(item for item in results if item["scenario"] == "step_budget_exhaustion")
        self.assertEqual(budget["executed_steps"], 3)
        self.assertEqual(budget["deferred_steps"], 2)
        failure = next(item for item in results if item["scenario"] == "fetch_failure_mid_chain")
        self.assertEqual(failure["outcomes"][1]["status"], "error")
        self.assertTrue(failure["outcomes"][1]["snapshot_retained"])


class BatchTests(unittest.TestCase):
    @patch("src.batch.run_pipeline")
    @patch("src.batch.load_products")
    def test_batch_preserves_config_order_and_isolates_failures(self, load_products, run):
        load_products.return_value = [
            {"url": "https://example.test/a", "product_description": "A",
             "significance_criteria": CRITERIA},
            {"url": "https://example.test/b", "product_description": "B",
             "significance_criteria": CRITERIA},
        ]
        first_result = SimpleNamespace(status=SimpleNamespace(value="initialized"),
                                       changes=[], explanation="ok")
        def fake_run(**kwargs):
            if kwargs["url"].endswith("/a"):
                return first_result
            raise RuntimeError("fixture failure")
        run.side_effect = fake_run
        from src.batch import run_batch
        with patch("src.batch.traceback.print_exc"):
            report = run_batch(max_workers=2)
        self.assertEqual([item["product"] for item in report["results"]], ["A", "B"])
        self.assertEqual([item["status"] for item in report["results"]],
                         ["initialized", "error"])
        self.assertEqual(report["successful"], 1)
        self.assertEqual(report["failed"], 1)

    @patch("src.batch.load_products", return_value=[])
    def test_batch_rejects_non_positive_worker_budget(self, _load_products):
        from src.batch import run_batch
        with self.assertRaisesRegex(ValueError, "max_workers"):
            run_batch(max_workers=0)


class GroqRetryTests(unittest.TestCase):
    def test_rate_limit_retry_delay_respects_suggestion_and_configured_floor(self):
        self.assertEqual(_retry_delay(Exception("Please try again in 45ms"), 1), 1.0)
        self.assertEqual(_retry_delay(Exception("Please try again in 30 seconds"), 1), 30.0)
        self.assertEqual(_retry_delay(Exception("rate limited"), 1, floor_seconds=15), 15.0)

    def make_client(self, side_effect):
        client = GroqClient.__new__(GroqClient)
        create = Mock(side_effect=side_effect)
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        client.model = "fixture-model"
        client.max_attempts = 3
        client.retry_delay_floor_seconds = 0.0
        client.call_count = 0
        client.last_usage = None
        client.total_prompt_tokens = 0
        client.total_completion_tokens = 0
        return client, create

    def test_transient_connection_error_retries_and_returns_result(self):
        expected = AnalysisResult(status="initialized", current_snapshot=None,
                                  changes=[], explanation="ok")
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=expected.model_dump_json()))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )
        transient = APIConnectionError(request=Mock())
        client, create = self.make_client([transient, response])
        request = AnalysisRequest(source_url=URL, product_description="Товар",
                                  significance_criteria=CRITERIA,
                                  page_text="Описание страницы товара.")
        with patch("src.extraction.llm_client.time.sleep") as sleep, \
             patch("builtins.print"):
            actual = client.analyze(request)
        self.assertEqual(actual.status.value, "initialized")
        self.assertEqual(client.call_count, 2)
        self.assertEqual(client.total_prompt_tokens, 11)
        self.assertEqual(client.total_completion_tokens, 7)
        self.assertEqual(create.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_blank_change_string_is_dropped_before_schema_validation(self):
        payload = json.loads(AnalysisResult(
            status="initialized", current_snapshot=None, changes=[],
            explanation="ok",
        ).model_dump_json())
        payload["changes"] = [""]
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps(payload)))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )
        client, create = self.make_client([response])
        request = AnalysisRequest(source_url=URL, product_description="Товар",
                                  significance_criteria=CRITERIA,
                                  page_text="Описание страницы товара.")

        actual = client.analyze(request)

        self.assertEqual(actual.changes, [])
        self.assertEqual(client.call_count, 1)
        self.assertEqual(create.call_count, 1)

    def test_schema_failure_retries_with_validation_feedback(self):
        malformed = json.loads(AnalysisResult(
            status="initialized", current_snapshot=None, changes=[],
            explanation="ok",
        ).model_dump_json())
        malformed["changes"] = ["not an object"]
        valid = AnalysisResult(status="initialized", current_snapshot=None,
                               changes=[], explanation="ok").model_dump_json()
        responses = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps(malformed)))], usage=None),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=valid))], usage=None),
        ]
        client, create = self.make_client(responses)
        request = AnalysisRequest(source_url=URL, product_description="Товар",
                                  significance_criteria=CRITERIA,
                                  page_text="Описание страницы товара.")

        with patch("src.extraction.llm_client.time.sleep"), \
             patch("builtins.print"):
            actual = client.analyze(request)

        self.assertEqual(actual.status.value, "initialized")
        self.assertEqual(client.call_count, 2)
        retry_messages = create.call_args_list[1].kwargs["messages"]
        self.assertIn("не прошёл проверку схемы", retry_messages[-1]["content"])
        self.assertEqual(retry_messages[-2]["content"], json.dumps(malformed))

    def test_timeout_is_retried(self):
        expected = AnalysisResult(status="initialized", current_snapshot=None,
                                  changes=[], explanation="ok")
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=expected.model_dump_json()))],
            usage=None,
        )
        client, create = self.make_client([
            APITimeoutError(request=Mock()), response,
        ])
        request = AnalysisRequest(source_url=URL, product_description="Товар",
                                  significance_criteria=CRITERIA,
                                  page_text="Описание страницы товара.")

        with patch("src.extraction.llm_client.time.sleep") as sleep, \
             patch("builtins.print"):
            actual = client.analyze(request)

        self.assertEqual(actual.status.value, "initialized")
        self.assertEqual(client.call_count, 2)
        self.assertEqual(create.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_exhausted_transient_errors_raise_original_error_after_three_attempts(self):
        errors = [APIConnectionError(request=Mock()) for _ in range(3)]
        client, create = self.make_client(errors)
        request = AnalysisRequest(source_url=URL, product_description="Товар",
                                  significance_criteria=CRITERIA,
                                  page_text="Описание страницы товара.")
        with patch("src.extraction.llm_client.time.sleep") as sleep, \
             patch("builtins.print"):
            with self.assertRaises(APIConnectionError):
                client.analyze(request)
        self.assertEqual(client.call_count, 3)
        self.assertEqual(create.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])


if __name__ == "__main__":
    unittest.main()
