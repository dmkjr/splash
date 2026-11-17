# Foreground decode turns on the deployed Flash-Next stack

This candidate is based on the deployed 9753a80 stack, including payload attribution, metadata and copy-lifecycle profiling, cache-directory EINTR recovery, and existing application fixes. It preserves the production eight-row speculative decoder and shaders. The separate upstream implementation targets the newer decoder and must be qualified independently.

`--foreground-turn-tokens` defaults to zero. Only equal-priority, unconstrained, text-only foreground requests may share a physical decode slot. Incoming requests must have at most 512 tokens left to prefill from their actual cache resume boundary. Four physical slots admit at most four pairs. Each pair retains both streams' live KV ownership and returns exact recurrent state, pending tape, penalties and host sampling state without replay or another allocation. Shorter and lower-concurrency work follows existing admission.

Banks are charged under optional governor rights. Refusal retains ordinary FIFO behavior. A bank reserves its original physical slot for its borrower and return; unrelated starts cannot steal that slot. Cancellation and deadlines retain suspension ownership through terminal cleanup. Orphan returns wait for a drained engine tick. Pressure recovery resolves pairs before replay suspension. Existing admission, fusion and M4 flags remain disabled.

## Targeted qualification, 2026-11-17

- Production engine suite: 461 passed, zero failed, including six added foreground-turn tests.
- Same 461 engine tests under ASan/UBSan: passed, zero failed.
- Native arguments and runtime status goldens: passed. Nonzero turn/parked status is checked separately.
- Python shared serve-option tests: nine passed.
- Architecture check: passed with the existing budget unchanged.
- M5 synthetic-weight native tests, normal and fully instrumented ASan/UBSan builds: dense and Flash-Next, FP32/BF16 state; full/partial speculative acceptance, thinking transitions, penalties, eight owners/four banks, allocation-free swaps, cancellation, original-slot reservations, SSD spill success and read failure recovery all passed.

The first compatibility run caught two priority-preemption regressions caused by recursively admitting after a preemption. Removing that recursion restored the existing GPU-command boundary and both regressions passed. Batched equal-priority lending remains independent of strict-priority preemption.

## Performance gate

No real-workload gain or production activation is claimed by these tests. A signed isolated candidate will compare flag zero versus 32 using the same binary, model, 96 GiB memory limit, 512 GiB external Samsung cache limit, eight queue workers, frozen production repository context, and eight coding tasks. ABBA ordering uses a cold round followed by three warm rounds per arm. SSE TTFT, total throughput, completion latency, sandboxed trusted/generated tests, cache reuse, disk payload/metadata counters and Samsung host-write/temperature readings are retained. Active parked-owner samples must demonstrate that the enabled arm actually exercised the feature. Production service identity, DB/history, configuration and health are restored afterward. Only a correctness-preserving throughput-safe improvement qualifies for activation.
