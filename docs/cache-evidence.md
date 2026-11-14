# Offline cache and coding-workload evidence

This development-only tool reads saved coding-wave JSON and sends no requests,
starts no server/model, executes no answers or generated validators, and changes
no cache, model, queue or memory setting:

```sh
python3 -m dev.benchmarks.serving.cache_evidence "$SAVED_CODING_WAVES" \
  --phase repeat --minimum-round 2
python3 -m unittest dev.tests.tools.test_cache_evidence
```

The input is a nonempty list of recorded waves. Each wave has `phase`, `round`,
`wall_s`, `requests`, and `before.engine` / `after.engine` status snapshots.
`--phase` and `--minimum-round` explicitly select the cohort; a round selection
requires known positive recorded rounds and rejects an empty result. The report
states selected/excluded wave counts. There is no automatic cold/warm inference.

## Metric contracts

- Request-scoped client TTFT, engine TTFT, engine queue delay, own engine TTFT,
  gateway wait and stream output rate remain separate. Each distribution records
  its own sample count. Unknown metrics remain null, never measured zero.
- Client time left after gateway wait and native TTFT is calculated on each
  matched request before taking percentiles. It includes upload/retries,
  preparation and transport; it is not pure network time or a causal breakdown.
  Negative inconsistent residuals remain unknown. Recorded retry counts and
  configured backoff are reported separately; configured sleep is not a measured
  duration that can be subtracted to manufacture an engine-speed gain.
- Cache counters are interval deltas, with unchanged process, model, cache/KV
  identity, context, RAM and cache limits. Restart/config changes or any observed
  counter regression invalidate all deltas for that interval. Missing individual
  counters stay null. Integer counters retain integer precision.
- Prefix lookup hit fraction uses delta hits divided by delta hits plus cold
  misses. Request cached-prompt fraction uses reported usage. These are different
  observations. Process interval counters are not attributed to individual
  requests, nor proof that no other traffic ran during the interval.
- In the current status implementation, `cache.kv_disk_hit_tokens` is restored
  page count times page size. It is restored capacity, not necessarily distinct
  usable prompt tokens and not a valid fraction of logical `kv_hit_tokens`.
  The report keeps these quantities separate.
- Aggregate output tokens divided by summed client wave wall time includes
  client/validator overhead and assumes recorded waves are sequential. It is not
  engine throughput. It becomes unknown when any required count/time is missing
  or a computed rate is nonfinite. Per-stream rate is reported separately.
- Recorded executable validation counts are retained alongside unknown,
  truncated and other/missing finishes. A validation pass on a truncated response
  does not count as a complete passing answer. This is not a new correctness
  execution or general model-accuracy estimate.
- Reports omit answer text, request IDs, source paths and model/instance identity
  values. Only phase labels, numeric observations and diagnostic field names are
  emitted. Raw fixtures remain private and are not bundled into this change.

Fifteen model-free tests cover deltas versus lifetime ratios, zero versus missing,
restarts/config/identity changes, counter regression and integer precision,
matched-request percentile arithmetic, invalid/overflowing observations,
truncation/unknown validation, retries, cohort selection, privacy/no network,
and the real CLI's valid/malformed-input behavior.

## Existing warm-coding records, analysed 2026-11-14

This reanalyses the November 11 matched full-stack ABBA records; it runs no new
model benchmark. The selected cohort is repeated coding requests, rounds two and
three, 16 responses per arm (64 total). The order was old/four workers,
new/eight, new/eight, old/four. Model, context and request fixtures were fixed in
that experiment; queue/runtime stacks differed, so it is not an isolated kernel
or runtime comparison.

| Observation | Old/four-worker arms | New/eight-worker arms |
| --- | --- | --- |
| Client TTFT median, each arm | 1.146 / 1.176 s | 0.291 / 0.269 s |
| Median reported cached-prompt fraction, every arm | 99.9187% | 99.9187% |
| Recorded upload retries, summed across arms | 16 | 0 |
| Recorded complete validation passes | 31/32 | 31/32 |
| SSD KV restored tokens during selected intervals | 0 | 0 |
| State evictions / governor denials during intervals | 0 / 0 | 0 / 0 |

Each arm's two selected intervals passed the identity/config/counter checks.
Cache reuse was already high, and this warm subset exercised no SSD restore
path. Its results cannot qualify a larger SSD cache, cold restore, cache-pressure
behavior or a model-accuracy improvement. Historical speed findings include
queue/gateway changes and must not be attributed to the test-only fusion.
Raw derived reports remain local under ignored `build/`.

## Next improvement round

1. Review and qualify the existing disabled foreground-aware admission work,
   using the same M5-only eight-worker stack as its control. Focus on p95
   foreground TTFT while reporting aggregate throughput and per-stream decode
   independently. Preserve idle capacity for useful concurrent work and verify
   cancellation, fairness and bounded bulk waiting. Reuse the existing patch
   rather than introduce a duplicate queue policy.
2. Examine state-retention/SSD-restore costs in recorded mixed-context pressure
   intervals before proposing a cache policy. Lifetime state churn is evidence
   to investigate, not proof of the cause of a particular slow request. The
   current warm cohort provides no SSD-pressure qualification.
3. Keep residual-update/capture fusion test-only until actual buffer lifetimes,
   all capture rows/slots, logits, speculative acceptance, recurrent state,
   cancellation and restore behavior can be qualified. Existing finite operator
   parity does not establish any end-to-end speed or accuracy gain.
4. Keep Flash-Next and its weights unchanged. Accuracy work should first strengthen
   independent repository-grounded coding validators, retain failures/truncations,
   and compare identical tasks. A small difference in pass counts is not a
   demonstrated model-quality improvement.

No deployment or model benchmark is authorized by these instructions. Flash-Next,
96 GiB RAM, 512 GiB cache, disabled fusion and M5-only routing remain the operating
constraints. A future authorized experiment should use fixed input/output budgets,
matched ABBA controls, complete responses, separate queue/engine measurements,
existing noise/regression rules and before/after production-health checks.
