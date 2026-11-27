# Coder tail checkpoints on M5 Max

This port brings Splash #784 and #785 (stack head `40870d0`) onto the
Coder 1.7.3 runtime at `703a5047`. It keeps a recent recovery point for
follow-up prompts that trim the previous turn and lets the memory ledger
reclaim older checkpoints before consuming that recovery point.

## Matched ABBA benchmark

A was the signed production Coder engine. B was the same engine source with
the checkpoint port. Both used the same HTTP frontend, Coder IQ1_M weights,
96 GiB engine budget, 256K context, exact cached states and a fresh, isolated
16 GiB SSD cache per wave. Each wave seeded an approximately 17K-token repo
context from `runtime/model/Runtime.cpp`, then issued four concurrent warm
follow-ups with different amounts of the prior turn removed. Each follow-up
was capped at 32 output tokens and asked for a `read_file` tool call.

| Metric | A | B |
|---|---:|---:|
| Median time to first valid tool call | 3.666 s | 0.911 s |
| Slowest time to first valid tool call | 4.584 s | 0.983 s |
| Median cold seed elapsed time | 9.168 s | 7.438 s |
| Mean reused prompt tokens per follow-up | 14,576 | 16,792 |
| Aggregate follow-up output rate | 23.6 tok/s | 110.1 tok/s |
| Valid tool calls | 8/8 | 8/8 |
| Engine-reported cache writes per wave | 939,982,848 bytes | 939,982,848 bytes |

| Wave | Arm | Cold seed elapsed | Valid tool call latency in request order |
|---|---|---:|---|
| 0 | A | 8.488 s | 2.774 / 2.773 / 4.584 / 4.584 s |
| 1 | B | 7.686 s | 0.978 / 0.542 / 0.978 / 0.841 s |
| 2 | B | 7.189 s | 0.983 / 0.542 / 0.983 / 0.845 s |
| 3 | A | 9.848 s | 2.760 / 2.760 / 4.558 / 4.558 s |

Output rate divides the generated tokens by the sum of the two wave runtimes
per arm, measured to the last response in each wave. It includes request
latency and warm prefill. This sample measures forced tool-call completion.
Held-back coding correctness, raw decode speed, and physical SSD writes
remain unmeasured here.

The release port's architecture budget carries the exact 297-line increase
from the upstream feature. It changes the source check only, leaving the
benchmarked engine implementation intact.
