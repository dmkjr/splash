"""Offline diagnosis of saved coding-wave results; never starts a server/model.

python3 -m dev.benchmarks.serving.cache_evidence RESULTS.json
Input: recorded waves with requests, wall_s, before.engine and after.engine.
Output contains phase labels and numeric evidence, never answers or request IDs.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path

from dev.benchmarks.serving.check import quantile
from dev.benchmarks.serving.clients import dig

COUNTERS = (
    "cache.hits",
    "cache.cold_misses",
    "cache.kv_hit_tokens",
    "cache.kv_disk_hit_tokens",
    "cache.reused_tokens",
    "cache.lost_state_misses",
    "cache.resource_replay_tokens",
    "cache.priority_suspensions",
    "cache.resource_resumptions",
    "state.evictions",
    "disk.kv_restores",
    "disk.kv_restore_failures",
    "disk.read_bytes",
    "disk.written_bytes",
    "memory_governor.denied_reservations",
)
CONFIG = (
    "instance.model",
    "maximum_context_tokens",
    "memory_governor.limit_bytes",
    "disk.limit_bytes",
    "identity.cache",
    "identity.kv",
)


def number(value):
    if type(value) is int:
        return 0 <= value <= sys.float_info.max
    return type(value) is float and math.isfinite(value) and value >= 0


def finite_ratio(numerator, denominator):
    try:
        result = numerator / denominator
    except (OverflowError, ZeroDivisionError):
        return None
    return result if number(result) else None


def distribution(values):
    values = sorted(v for v in values if number(v))
    return {
        "samples": len(values),
        "p50": statistics.median(values) if values else None,
        "p95": quantile(values, 0.95) if values else None,
        "max": max(values) if values else None,
    }


def interval(before, after):
    problems = []
    first, last = dig(before, "instance.id"), dig(after, "instance.id")
    if not isinstance(first, str) or not first or first != last:
        problems.append("missing_or_changed_engine_instance")
    for path in CONFIG:
        if dig(before, path) is None or dig(before, path) != dig(after, path):
            problems.append("missing_or_changed_config:" + path)
    changes = {}
    for path in COUNTERS:
        a, b = dig(before, path), dig(after, path)
        if type(a) is int and type(b) is int and min(a, b) >= 0:
            if b < a:
                problems.append("counter_regressed:" + path)
            else:
                changes[path] = b - a
        else:
            changes[path] = None
    # Never combine pre/post-restart counters or treat missing fields as zero.
    if problems:
        changes = dict.fromkeys(COUNTERS)
    hits, misses = changes["cache.hits"], changes["cache.cold_misses"]
    fraction = (
        hits / (hits + misses)
        if hits is not None and misses is not None and hits + misses
        else None
    )
    return {
        "valid": not problems,
        "problems": problems,
        "counter_deltas": changes,
        "prefix_probe_hit_fraction": fraction,
        "scope": "process_interval; not attributed to individual requests",
    }


def request_evidence(row):
    timing = dig(row, "metrics.request_latency") or {}
    observed_s = row.get("ttft_s")
    observed = observed_s * 1000 if number(observed_s) else None
    native = dig(timing, "ttft_ms")
    own = dig(timing, "start_to_first_token_ms")
    queue = dig(timing, "queue_to_start_ms")
    gateway_s = dig(row, "gateway.wait_s")
    gateway = gateway_s * 1000 if number(gateway_s) else None
    # Compute residual for each matched request, never by subtracting percentiles.
    residual = (
        observed - native - gateway
        if all(number(v) for v in (observed, native, gateway))
        else None
    )
    if residual is not None and residual < 0:
        residual = None  # inconsistent scopes, not a negative network time
    retries = row.get("upload_retries")
    retry_count = None
    backoff = None
    if isinstance(retries, list) and all(
        isinstance(r, dict) and number(r.get("delay_s")) for r in retries
    ):
        retry_count = len(retries)
        backoff = sum(r["delay_s"] for r in retries) * 1000
    stages = {
        "client_ttft_ms": observed,
        "engine_ttft_ms": native,
        "engine_own_ttft_ms": own,
        "engine_queue_ms": queue,
        "gateway_wait_ms": gateway,
        "unattributed_client_ms": residual,
        "stream_output_tps": dig(timing, "stream_tokens_per_second"),
        "configured_upload_backoff_ms": backoff,
    }
    validation = dig(row, "validation.pass")
    finish = row.get("finish_reason")
    matched = dig(row, "usage.prompt_tokens_details.cached_tokens")
    prompt = dig(row, "usage.prompt_tokens")
    cached_fraction = (
        matched / prompt
        if number(matched) and number(prompt) and prompt > 0 and matched <= prompt
        else None
    )
    return {
        "stages": {k: v if number(v) else None for k, v in stages.items()},
        "upload_retries": retry_count,
        "stopped": finish == "stop",
        "truncated": finish == "length",
        "validation": validation if type(validation) is bool else None,
        "cached_prompt_fraction": cached_fraction,
    }


def analyze(waves, phase=None, minimum_round=None):
    if not isinstance(waves, list) or not waves:
        raise ValueError("expected a nonempty list of saved coding waves")
    if phase is not None and (
        not isinstance(phase, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", phase)
    ):
        raise ValueError("invalid phase selection")
    if minimum_round is not None and (
        type(minimum_round) is not int or minimum_round < 1
    ):
        raise ValueError("minimum round must be positive")
    selected = 0
    groups = {}
    for wave in waves:
        if (
            not isinstance(wave, dict)
            or not isinstance(wave.get("requests"), list)
            or not all(isinstance(r, dict) for r in wave["requests"])
        ):
            raise ValueError("each wave must contain a request-record list")
        if phase is not None and wave.get("phase") != phase:
            continue
        if minimum_round is not None:
            if type(wave.get("round")) is not int or wave["round"] < 1:
                raise ValueError("round selection requires positive recorded rounds")
            if wave["round"] < minimum_round:
                continue
        selected += 1
        label = wave.get("phase", "unlabeled")
        if not isinstance(label, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,48}", label
        ):
            label = "unlabeled"
        group = groups.setdefault(
            label, {"rows": [], "intervals": [], "wall_s": [], "token_totals": []}
        )
        group["rows"].extend(request_evidence(row) for row in wave["requests"])
        group["intervals"].append(
            interval(dig(wave, "before.engine") or {}, dig(wave, "after.engine") or {})
        )
        wall = wave.get("wall_s")
        tokens = [dig(row, "usage.completion_tokens") for row in wave["requests"]]
        group["wall_s"].append(wall if number(wall) and wall > 0 else None)
        group["token_totals"].append(
            sum(tokens)
            if tokens and all(type(n) is int and 0 <= n <= 2**64 - 1 for n in tokens)
            else None
        )
    if not selected:
        raise ValueError("selection contains no saved waves")
    phases = {}
    for label, group in groups.items():
        rows = group["rows"]
        validated = [r for r in rows if r["validation"] is not None]
        valid_throughput = all(
            v is not None for v in group["wall_s"] + group["token_totals"]
        )
        keys = request_evidence({})["stages"]
        phases[label] = {
            "requests": len(rows),
            "stopped": sum(r["stopped"] for r in rows),
            "truncated": sum(r["truncated"] for r in rows),
            "other_or_missing_finish": sum(
                not r["stopped"] and not r["truncated"] for r in rows
            ),
            "upload_retry_coverage_requests": sum(
                r["upload_retries"] is not None for r in rows
            ),
            "upload_retry_requests": sum(
                r["upload_retries"] is not None and r["upload_retries"] > 0
                for r in rows
            ),
            "upload_retry_events": sum(
                r["upload_retries"] for r in rows if r["upload_retries"] is not None
            ),
            "reported_validation": {
                "evaluated": len(validated),
                "passed": sum(r["validation"] for r in validated),
                "unknown": len(rows) - len(validated),
                "complete_and_passed": sum(
                    r["stopped"] and r["validation"] is True for r in rows
                ),
            },
            "latency_and_speed": {
                k: distribution([r["stages"][k] for r in rows]) for k in keys
            },
            "cached_prompt_fraction": distribution(
                [r["cached_prompt_fraction"] for r in rows]
            ),
            "observed_output_tokens_per_wave_wall_s": finite_ratio(
                sum(group["token_totals"]), sum(group["wall_s"])
            )
            if valid_throughput
            else None,
            "intervals": group["intervals"],
        }
    return {
        "schema": 1,
        "scope": "offline_saved_coding_waves",
        "selection": {
            "phase": phase,
            "minimum_round": minimum_round,
            "input_waves": len(waves),
            "selected_waves": selected,
            "excluded_waves": len(waves) - selected,
        },
        "phases": phases,
        "limits": [
            "No workload, benchmark, model or validation code was executed.",
            "Validation outcomes are recorded test results, not a general model-accuracy estimate.",
            "Wave wall time includes client/validator overhead; aggregate rate is not engine throughput.",
            "Unattributed client time includes retries, preparation and transport; it is not pure network time.",
            "Process interval counters do not prove per-request attribution or exclusive workload traffic.",
            "kv_disk_hit_tokens counts restored page capacity; it is not a fraction of logical KV lookup tokens.",
            "Missing metrics remain null; intervals spanning a restart, config change or counter regression are invalid.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--phase")
    parser.add_argument("--minimum-round", type=int)
    args = parser.parse_args()
    try:
        report = analyze(
            json.loads(args.results.read_text()), args.phase, args.minimum_round
        )
    except (OSError, ValueError, TypeError):
        parser.exit(2, "cache-evidence: invalid or unreadable saved coding-wave data\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
