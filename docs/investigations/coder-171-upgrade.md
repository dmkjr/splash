# SiteKings Coder upgrade to Splash 1.7.1

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

## Release checks

- Verify the current signed package is available for rollback, Splash serves
  the expected Coder weights and aliases, and Next Queue is healthy and idle.
- Qualify the candidate in an isolated cache namespace. Check Samsung free
  space and cache identity before sharing or migrating existing cache data.
  Preserve the rollback package and its cache.
- Compare with the signed production build using matched warm Hermes turns
  with fixed generation lengths, long prefills, and held-back coding checks.
  Gate the rollout on warm p95 TTFT, aggregate decode throughput, and verified
  fixes. The previous scheduler comparison measured 89.6% lower warm p95 TTFT,
  0.36% higher throughput, identical held-back correctness, and 2.37% higher
  long-prompt TTFT. These are historical results for the previous build.
- Verify the signed service reopens the Samsung unattended, reports persistent
  caching and reuse, serves the old aliases, and Next Queue accepts and finishes
  work. Roll back if performance, correctness, or service health regresses.

Build-time verification includes native argument and status tests, scheduler
tests, integrated engine tests, synthetic Metal continuation parity for dense
and Flash-Next models, cache-directory tests, and Python launcher/server tests.
