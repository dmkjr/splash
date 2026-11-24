# SiteKings Coder rebase onto Splash 1.7.2

Build the runtime, Metal library, and HTTP frontend together from the candidate.
Keep the existing Coder IQ1_M GGUF, model IDs and aliases, 96 GiB memory limit,
256K maximum context, four physical lanes, and the Next Queue worker settings.
Keep admission, fusion, and M4 routing disabled. Retain the deployed BF16
activations and state precision, exact cached states, and reasoning defaults.

Explicitly set `--foreground-turn-tokens 32` and `--short-prefill-cohorts`.
Use persistent caching on the Samsung with the 512 GiB cache limit and
600 GiB daily write limit. An explicitly configured cache path fails visibly
if it cannot be opened. The signed service must be able to reopen the cache
unattended after a restart.

The rebase retains upstream 1.7.2 shared-head checkpoint retention and
write-behind, long-reply state retention, and background priority aging.
Warm-cohort sponsorship ends if the engine demotes a request to background.

## Release checks

- Verify the current signed package is available for rollback, Splash serves
  the expected Coder weights and aliases, and Next Queue is healthy and idle.
- Qualify the candidate in an isolated cache namespace. Check Samsung free
  space and cache identity before sharing or migrating existing cache data.
  Preserve the rollback package and its cache.
- Compare with the signed production build using matched warm Hermes turns
  with fixed generation lengths, long prefills, and held-back coding checks.
  Gate the rollout on warm p95 TTFT, aggregate decode throughput, and verified
  fixes. Include admission wait in TTFT and report RAM hits separately from
  SSD restores. Inspect cache writes per wave because 1.7.2 also persists
  eligible prompt heads. The signed 1.7.1 rollout measured 7.8% lower warm p95 TTFT,
  0.06% lower throughput, and 29/31 held-back checks on both builds.
  Use the signed 1.7.1 currently running on the M5 as the baseline here.
- Verify the signed service reopens the Samsung unattended, reports persistent
  caching and reuse, serves the old aliases, and Next Queue accepts and finishes
  work. Roll back if performance, correctness, or service health regresses.

Build-time verification includes native argument and status tests, scheduler
tests, integrated engine tests, synthetic Metal continuation parity for dense
and Flash-Next models, cache-directory tests, and Python launcher/server tests.
