import copy
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dev.benchmarks.serving import cache_evidence as evidence


def status(hits=100, misses=20, **fields):
    result = {
        "instance": {"id": "one", "model": "model"},
        "maximum_context_tokens": 262144,
        "memory_governor": {"limit_bytes": 96 << 30},
        "disk": {"limit_bytes": 512 << 30},
        "identity": {"cache": {"layout": "same"}, "kv": {"format": "int8"}},
        "cache": {"hits": hits, "cold_misses": misses},
    }
    result.update(fields)
    return result


def request(client_ms=100, native_ms=60, gateway_ms=10, **fields):
    result = {
        "ttft_s": client_ms / 1000,
        "finish_reason": "stop",
        "gateway": {"wait_s": gateway_ms / 1000},
        "usage": {
            "completion_tokens": 10,
            "prompt_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 80},
        },
        "validation": {"pass": True},
        "metrics": {
            "request_latency": {
                "ttft_ms": native_ms,
                "start_to_first_token_ms": 40,
                "queue_to_start_ms": 20,
            }
        },
    }
    result.update(fields)
    return result


def wave(rows=None):
    return {
        "phase": "warm",
        "wall_s": 2,
        "requests": rows if rows is not None else [request()],
        "before": {"engine": status()},
        "after": {"engine": status(109, 21)},
    }


class CacheEvidenceTests(unittest.TestCase):
    def test_interval_hit_ratio_uses_deltas_not_lifetime_ratio(self):
        result = evidence.analyze([wave()])["phases"]["warm"]
        self.assertEqual(result["intervals"][0]["prefix_probe_hit_fraction"], 0.9)
        self.assertEqual(result["observed_output_tokens_per_wave_wall_s"], 5)
        self.assertEqual(result["cached_prompt_fraction"]["p50"], 0.8)

    def test_missing_and_zero_counters_remain_distinct(self):
        result = evidence.interval(status(), status())
        self.assertIsNone(result["prefix_probe_hit_fraction"])
        self.assertEqual(result["counter_deltas"]["cache.hits"], 0)
        self.assertIsNone(result["counter_deltas"]["state.evictions"])

    def test_restart_missing_identity_config_change_and_reset_invalidate_all_deltas(
        self,
    ):
        for kind in ["restart", "missing", "config", "reset", "cache_identity"]:
            with self.subTest(kind=kind):
                before, after = status(), status(109, 21)
                if kind == "restart":
                    after["instance"]["id"] = "two"
                if kind == "missing":
                    before["instance"].pop("id")
                if kind == "config":
                    after["disk"]["limit_bytes"] *= 2
                if kind == "reset":
                    after["cache"]["hits"] = 0
                if kind == "cache_identity":
                    after["identity"]["kv"]["format"] = "bf16"
                result = evidence.interval(before, after)
                self.assertFalse(result["valid"])
                self.assertTrue(
                    all(x is None for x in result["counter_deltas"].values())
                )

    def test_counter_values_preserve_integer_precision(self):
        before, after = status(2**60), status(2**60 + 3)
        self.assertEqual(
            evidence.interval(before, after)["counter_deltas"]["cache.hits"], 3
        )

    def test_latency_residual_is_computed_before_percentiles(self):
        rows = [request(1000, 100, 0), request(900, 800, 0)]
        result = evidence.analyze([wave(rows)])["phases"]["warm"]["latency_and_speed"]
        self.assertEqual(result["unattributed_client_ms"]["p95"], 900)
        self.assertNotEqual(
            result["unattributed_client_ms"]["p95"],
            result["client_ttft_ms"]["p95"]
            - result["engine_ttft_ms"]["p95"]
            - result["gateway_wait_ms"]["p95"],
        )

    def test_negative_residual_and_invalid_numbers_are_unknown(self):
        self.assertIsNone(
            evidence.request_evidence(request(1, 60, 10))["stages"][
                "unattributed_client_ms"
            ]
        )
        for bad in [True, -1, float("nan"), float("inf"), 10**1000]:
            with self.subTest(value=str(bad)[:20]):
                self.assertIsNone(
                    evidence.request_evidence({"ttft_s": bad})["stages"][
                        "client_ttft_ms"
                    ]
                )

    def test_failed_truncated_and_unvalidated_answers_are_retained(self):
        rows = [
            request(),
            request(finish_reason="length"),
            request(validation={"pass": False}),
            {"finish_reason": "error"},
        ]
        result = evidence.analyze([wave(rows)])["phases"]["warm"]
        self.assertEqual(
            (
                result["requests"],
                result["truncated"],
                result["other_or_missing_finish"],
            ),
            (4, 1, 1),
        )
        self.assertEqual(
            result["reported_validation"],
            {"evaluated": 3, "passed": 2, "unknown": 1, "complete_and_passed": 1},
        )
        self.assertIsNone(result["observed_output_tokens_per_wave_wall_s"])

    def test_impossible_cached_fraction_is_unknown(self):
        row = request()
        row["usage"]["prompt_tokens_details"]["cached_tokens"] = 101
        self.assertIsNone(evidence.request_evidence(row)["cached_prompt_fraction"])

    def test_offline_report_omits_answers_and_private_ids(self):
        data = wave(
            [
                request(
                    output="PRIVATE_CODE",
                    job_id="PRIVATE_JOB",
                    request_sha256="PRIVATE_HASH",
                )
            ]
        )
        original = copy.deepcopy(data)
        with mock.patch.object(
            socket, "socket", side_effect=AssertionError("network call")
        ):
            report = json.dumps(evidence.analyze([data]), allow_nan=False)
        for text in ["PRIVATE_CODE", "PRIVATE_JOB", "PRIVATE_HASH"]:
            self.assertNotIn(text, report)
        self.assertEqual(data, original)

    def test_invalid_schema_and_empty_input_are_rejected(self):
        for bad in [None, {}, [], [None], [{"requests": [1]}]]:
            with self.assertRaises(ValueError):
                evidence.analyze(bad)

    def test_round_selection_is_explicit_and_rejects_unknown_rounds(self):
        cold, warm = wave(), wave()
        cold["round"], warm["round"] = 1, 2
        result = evidence.analyze([cold, warm], phase="warm", minimum_round=2)
        self.assertEqual(result["selection"]["excluded_waves"], 1)
        self.assertEqual(result["phases"]["warm"]["requests"], 1)
        for data, phase, minimum in [
            ([wave()], None, 2),
            ([wave()], "absent", None),
            ([wave()], None, 0),
        ]:
            with self.assertRaises(ValueError):
                evidence.analyze(data, phase, minimum)

    def test_overflowing_throughput_is_unknown(self):
        data = wave()
        data["wall_s"] = 1e-320
        report = evidence.analyze([data])
        self.assertIsNone(
            report["phases"]["warm"]["observed_output_tokens_per_wave_wall_s"]
        )
        json.dumps(report, allow_nan=False)

    def test_recorded_upload_retries_remain_visible(self):
        rows = [
            request(upload_retries=[{"delay_s": 2}, {"delay_s": 1}]),
            request(upload_retries=[]),
            request(),
        ]
        result = evidence.analyze([wave(rows)])["phases"]["warm"]
        self.assertEqual(
            (
                result["upload_retry_coverage_requests"],
                result["upload_retry_requests"],
                result["upload_retry_events"],
            ),
            (2, 1, 2),
        )
        self.assertEqual(
            result["latency_and_speed"]["configured_upload_backoff_ms"]["p95"], 3000
        )

    def test_unknown_retry_record_does_not_become_zero(self):
        row = evidence.request_evidence(request(upload_retries=[{"delay_s": -1}]))
        self.assertIsNone(row["upload_retries"])
        self.assertIsNone(row["stages"]["configured_upload_backoff_ms"])

    def test_cli_reads_saved_fixture_and_rejects_malformed_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text(json.dumps([wave()]))
            command = [
                sys.executable,
                "-m",
                "dev.benchmarks.serving.cache_evidence",
                str(path),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["scope"], "offline_saved_coding_waves"
            )
            path.write_text("bad JSON")
            self.assertEqual(
                subprocess.run(command, capture_output=True, timeout=10).returncode, 2
            )


if __name__ == "__main__":
    unittest.main()
