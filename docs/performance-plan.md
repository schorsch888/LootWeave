# Runtime performance plan

Status: source implementation and the declared development experiment completed on 2026-10-05. P0 tools, experimental P1/P2 and P4 behavior are implemented. Twenty candidate workflows/cleanup checks passed and initial idle private commit fell, but primary P95 failed the comparison rule; default promotion is deferred and both launchers retain `eager`. Explicit `--startup-policy on-demand` remains available. P3/P5 and production splitting remain deferred. Matching package checks are recorded separately in the [results](performance-results.md) and [validation record](validation.md); the [design](design.md) and [M4](roadmap.md#m4-one-entry-exe-and-local-lifecycle) retain their invariants and release gates.

Reduce the wait for the usable workbench and unnecessary background resource use, while keeping first-use latency, correctness and process cleanup measurable. Start with measurement, then defer OCR and Planning startup, then separate window readiness from service readiness. Advance data loading, frontend splitting and OCR reuse only where measurements justify them.

## Reviewed baseline evidence

This table describes the original eager implementation, reproduced by source snapshot `eade0dc`. Links show corresponding files, which may now contain the changed implementation; the table does not describe current startup behavior.

| Observation | Source | Implication to measure |
| --- | --- | --- |
| The Rust supervisor verifies the bundle, then starts Profile, Knowledge, Evaluation, Planning, OCR and Gateway sequentially, waiting for each readiness response | [supervisor.rs](../desktop/src/supervisor.rs) | Attribute verification, process creation and readiness separately before choosing the next bottleneck |
| The desktop creates its WebView only after `Supervisor::start` returns | [main.rs](../desktop/src/main.rs) | Optional service startup lies before window creation |
| Gateway receives a fixed service URL map and requires Profile, Knowledge and Evaluation at construction; the developer launcher owns Gateway in process | [gateway.py](../gateway.py), [runtime.py](../runtime.py) | Deferred services require routing and lifecycle changes in both launch paths |
| Knowledge reads, hashes, validates and retains every pack; its index contains filenames and file hashes, without catalog summaries | [Knowledge](../services/knowledge/app.py), [index](../knowledge-packs/index.json) | A catalog that can be read independently is a prerequisite for lazy pack parsing |
| The workbench imports its features eagerly and polls service health every five seconds | [Workbench](../frontend/src/pages/workbench/index.tsx) | Feature activation and idle polling are candidates; their cost is not yet established |
| OCR probes capabilities during construction and starts a PowerShell helper for recognition and optional numeric regions | [OCR](../services/ocr/app.py) | Measure initialization separately from recognition before considering helper reuse |
| Services already select their own imports, and packaging already uses a Python directory bundle | [service.py](../service.py), [build_desktop.py](../scripts/build_desktop.py) | Preserve these existing mechanisms |

The [historical hidden native verification](validation.md#hidden-native-verification) records readiness P95 of 8.5476 seconds, maximum aggregate idle working set of 643.87 MiB and private commit of 377.14 MiB. Those samples used warm OS caches, included test-client startup and may double-count shared working-set pages. They do not establish visible cold-start performance or identify which component dominates. The delivered installer and later Rust-only verifier also have different identities; do not combine their results as one baseline. No improvement percentage is established.

## Scope and invariants

- Keep the Windows single-EXE entry, FSD frontend, DDD services with independent storage, and Rust + Python. Rust owns packaged process lifecycle; the Python launcher implements equivalent development behavior. Gateway routes infrastructure requests without owning game rules.
- Preserve session authorization, loopback and origin checks, bundle verification before worker execution, single-instance ownership, bounded deadlines and descendant cleanup. A status read must never start a dormant service.
- Keep manual confirmation, synthetic evaluation and frozen history usable when optional capabilities are dormant or fail. Preserve request IDs and atomic writes; an ambiguous response must not cause an unguarded repeated write.
- Preserve explicit game, edition, build, mode and season isolation; pack hashes, evaluator versions and historical bytes; unknown-condition blockers; original OCR evidence and human confirmation. Performance work does not validate real-game mechanics.
- Keep telemetry local and bounded: durations, versions, synthetic fixture IDs and failure categories. Public results require content review and must exclude personal paths, credentials, real character data and screenshots. Game interaction, memory access and save access remain out of scope.

The initial work needs no database migration or evaluator change. Dynamic native-library plugins, hot code replacement, service consolidation, a new UI framework and a general evaluation-result cache are outside this plan. Existing historical results already provide frozen replay. Any additional result cache would require complete input, intent, scope, pack and evaluator identities.

## Delivery sequence

Stages define reviewable contracts, observed checks and rollback points. The prerequisite implementation and runtime changes are separate PRs. P0/P1/P2/P4 have focused regressions and comparable measurements; P1/P2 contracts below describe the explicit experiment, whose default promotion was rejected by the declared latency gate. Roles indicate responsibility for future evidence and fixes.

### P0 — Establish an attributable baseline

Owner: desktop/release, with verification. No dependency on later optimization stages.

Extend the existing [desktop verifier](../scripts/check_desktop.py) and [native verifier](../scripts/check_native_ui.py) for phase timing and process-tree resource samples. Add bounded timing records at bundle verification, worker spawn/readiness, OCR capability discovery, catalog response and frontend readiness. Use one orchestrator clock for end-to-end durations and process-local monotonic clocks for phase durations; do not subtract unrelated process clocks. Keep the hidden verifier passive, hidden and nonfocusable. Visible painting and keyboard usability need separate observation.

Record source and artifact hashes, Python/WebView2 versions, hardware and OS, input identities, cache conditions, startup failures and cleanup outcomes. Reuse the current full-start policy as the control. Collect two control cohorts before choosing optimizations, then compare control and candidate under matching conditions with a declared run order.

Acceptance:

- Report window visibility, core-workbench readiness, first complete comparison, first OCR, repeated OCR and shutdown separately; a visible loading window does not count as a usable workbench.
- For development comparisons, run at least 20 launches per policy and report all durations, P50, nearest-rank P95, maximum and failures. Keep first-use and warm-use samples separate. Failed or timed-out runs remain explicit failures and prevent a passing acceptance claim.
- Sample the entire owned process tree, including WebView descendants: idle CPU, aggregate working set and private commit, plus peak memory during work. Measure a fixed 60-second idle interval after readiness and again after one OCR/Planning use; disclose sampling frequency and shared-page accounting.
- Define an actual cold-cache procedure before reporting cold-start results. A new process or WebView profile with warm OS caches is a development cohort, not cold-start acceptance.
- Record the baseline variability and the primary metric, comparison rule and allowed regressions for each experiment before collecting candidate results. Defer a change if its measured benefit cannot be distinguished from that variability. Do not invent a percentage saving or silently relax M4 budgets.

### P1 — Start OCR and Planning on demand

Owner: desktop/runtime, with frontend and verification. Depends on P0.

Keep Profile, Knowledge, Evaluation and Gateway in the initial core startup policy. Leave OCR and Planning dormant until an explicit feature request needs them. In particular, initial rendering and health checks must not trigger optional startup. Manual text confirmation already uses Profile directly and must keep that path.

Change boundaries: [supervisor.rs](../desktop/src/supervisor.rs), [runtime.py](../runtime.py), [gateway.py](../gateway.py), [shared API](../frontend/src/shared/api/index.ts), and existing runtime/lifecycle tests.

Proposed lifecycle contract:

1. The owner maintains an allowlisted service registry with `dormant`, `starting`, `ready`, `failed` and `stopping` states. Concurrent callers join one startup attempt per service. A generation identifies that attempt so a late readiness reply cannot replace a newer state.
   Dependent workers pin the generations/URLs used at construction. A failed or replaced dependency invalidates their route; explicit recovery recreates the dependent with current URLs and preserves stored requests/history. An already-ready Evaluation child remains owned for frozen collection/detail/replay only during an upstream fault; new evaluation routes are blocked and frozen reads do not restart dependencies.
2. Gateway asks the owner to ensure a capability and receives its validated loopback URL only after the existing ownership handshake and health check. Reuse the packaged Gateway's inherited parent pipes for bounded, versioned control messages after its readiness message; the development Gateway uses an equivalent owner callback. Preserve EOF shutdown, serialize pipe writes, reject unsupported contract versions, and accept no caller-supplied executable paths or arguments.
3. The frontend waits for the shared capability-start operation with its own bounded deadline, then issues the original business request with its existing request ID and request deadline. Startup must not consume the entire recognition budget. Do not blindly repeat writes that may already have executed.
4. Gateway reports dormant services separately from failures, updates routing only for the current ready generation and invalidates failed routes. Explicit retry may start one new attempt; polling must not produce restart loops.
5. Closing the application prohibits new starts, reclaims children from incomplete attempts and waits for owned descendants. Preserve Windows Job Object ownership and the existing exit deadlines. Once started, optional services remain alive until app exit in this first stage; idle eviction is a separate measured decision.

Acceptance: a fresh launch and complete manual confirmation/evaluation/replay flow create no OCR or Planning worker; concurrent first requests create exactly one worker per requested capability; optional failure leaves the core flow usable; timeout, retry, stale readiness, port conflict, parent EOF and close-during-start cases terminate cleanly. Verify the same behavior through development and packaged entry points. Compare both initial idle savings and first-use delays against P0.

### P2 — Separate window readiness from core readiness

Owner: desktop and frontend. Depends on P1's registry and lifecycle contract.

After bundle verification, let Gateway serve the static shell before core services are ready, then create the WebView. Start core services outside the UI event loop. Start Profile and Knowledge concurrently only after their independent startup prerequisites are confirmed; Evaluation waits for both validated URLs. Retain explicit startup deadlines and visible failure/retry states.

Remove Gateway's construction-time requirement for all core URLs while preserving per-route readiness checks. Split the workbench's shell from catalog/demo-dependent content. Enable each action only when its actual dependencies are ready. Keep typed drafts intact when another capability becomes ready or fails. Exit must remain responsive during every startup phase.

Acceptance: delayed Knowledge or failed OCR cannot prevent the shell from appearing; unavailable core dependencies prevent confirmation/evaluation until ready; core failure is explicit; keyboard focus and loading states remain usable. Time first visible paint separately from core readiness and the first successful comparison. Preserve hidden-verifier boundaries and record visible checks independently. A faster shell alone cannot pass the optimization gate if the usable workflow regresses.

### P3 — Load selected knowledge versions with bounded caching

Owner: knowledge, with verification. Depends on P0; schedule after the lifecycle stages if pack parsing or memory use warrants it.

Add a derived catalog containing the existing API summaries, explicit pack/version identity, file SHA-256 and canonical pack hash. Generate and verify it against complete packs using repository tooling. Keep historical pack bytes and the existing index unchanged, and retain compatibility with the current index-only layout. Catalog entries describe candidates; they cannot authorize unvalidated rules.

At runtime, read the catalog first. On first use of an exact pack/version, verify its path, indexed file hash, schema, scope and catalog agreement before returning executable content. Cache validated content with a declared byte budget and eviction policy, coalesce concurrent loads, and return independent API values so callers cannot mutate cached history. Reload and revalidate evicted entries. Never substitute another game or the latest version for a missing request.

Acceptance: use synthetic catalogs of disclosed sizes to measure scaling; test unknown/duplicate versions, changed or missing files, conflicting metadata, concurrent loading, eviction/reload and returned-value mutation. Frozen evaluations must replay unchanged. Report cold load and cache-hit latency plus retained bytes. Keep full bundle integrity checks: deferred JSON parsing does not remove their startup I/O cost. If the current seven-pack catalog shows no meaningful benefit, retain eager loading and record P3 as deferred.

### P4 — Defer secondary UI and reduce idle polling

Owner: frontend, with runtime. Depends on P0 and P1; use P2's readiness states where applicable.

Conditionally mount secondary Planning and history panels when opened, and use dynamic imports through their FSD public APIs if bundle analysis supports splitting. Preserve drafts, confirmation invalidation, pending request IDs and selected history across panel changes. Show loading/error states with a retry path. Merely wrapping immediately mounted components in `lazy` does not defer their first use; see [React lazy](https://react.dev/reference/react/lazy).

Replace overlapping interval requests with at most one health request in flight, scheduled after completion. Slow polling while hidden and refresh on return without hiding active-operation failures. Keep dormant services dormant. Current source uses 500 ms during visible active core startup, five seconds after readiness/failure and 30 seconds hidden, preserving the prior ready-service detection interval and avoiding a five-second initial gate delay. Resource effects still need measurement.

Production code splitting reduced the entry from 264.97 kB to 257.09 kB but increased total JavaScript to 272.56 kB; an aborted first chunk fetch stayed cached as failed on a same-import retry. Splitting is deferred without additional manifest/loader machinery. Conditional mount-once panels remain; the final readiness/control implementation is one 270.43 kB entry, so no JavaScript saving is claimed.

Acceptance: unopened panels cause no feature fetch or optional startup; open/close/reopen preserves intended draft and confirmation state; failed chunk loading is recoverable; repeated visibility changes leave one poller; status requests never overlap. Run relevant component checks and inspect the production bundle, then compare startup bytes, interaction latency and idle CPU. Large-list virtualization remains deferred until realistic list sizes show a rendering bottleneck.

### P5 — Reuse OCR initialization only if justified

Owner: OCR/desktop, with verification. Depends on P0 and P1; optional after the preceding results.

If measurements show helper startup/model initialization dominates repeated OCR, evaluate one bounded helper session with an explicit idle lifetime. Preserve the current concurrency bound, per-request image/language identity, numeric-crop limits, deadlines and cancellation semantics. Measure first-use latency and retained memory as well as warm throughput. Keep the current per-request helper policy available for rollback. Prefer the Python standard library; this stage does not assume moving OCR or game rules into Rust.

Acceptance: compare the same synthetic inputs under fresh, warm, failed and restarted helpers; language switching and cancellation must not leak prior request state. Original text/image associations, signs, units, conflicts and human confirmation remain intact. Re-run active-helper termination and descendant cleanup cases. Examined OCR datasets support regression only; changed recognition behavior needs a fresh holdout for a new accuracy claim. Retain the existing helper policy if savings do not justify memory or lifecycle costs.

## Verification and rollout

Run these existing commands from the repository root for each implemented stage, using an available Python installation:

```sh
python -m unittest discover -s tests -v
python scripts/check_architecture.py
python scripts/check_public_docs.py
python -m compileall -q scripts
```

For frontend changes, install the locked dependencies as described in the [implementation guide](implementation.md), then run the existing production build and relevant checks:

```sh
pnpm --dir frontend build
pnpm --dir frontend check:confirmation
pnpm --dir frontend check:acquisition
pnpm --dir frontend check:ui
node scripts/check_evaluation_render.mjs
node scripts/check_frontend_runtime.mjs
```

Extend [runtime tests](../tests/test_runtime.py), [lifecycle tests](../tests/test_process_lifecycle.py), [service tests](../tests/test_services.py) and native supervisor checks with the acceptance cases above. Focused source tests now cover the implemented behavior; matching package checks and comparable measurements remain separate gates. Packaged lifecycle/native verification additionally requires rebuilt matching host, sidecar and frontend artifacts, Windows and WebView2; OCR measurement requires installed Windows languages and synthetic inputs. Missing prerequisites mean those checks were not run. Do not run an old installer as evidence for changed source.

| Gate | Required evidence |
| --- | --- |
| Behavior | Complete manual flow, frozen replay, optional-service failures and state transitions pass on the changed source and matching artifacts |
| Resource improvement | Comparable P0/control and candidate samples meet the predeclared comparison rule, including first-use delays and memory after activation; no claim from an isolated host-memory reading |
| Lifecycle | Twenty start/exit cycles and each changed worker/host fault path reclaim all owned descendants within the existing deadlines; retain every failure record |
| M4 release | Two clean Windows x64 environments, standard accounts and offline dependency cases; cold-start P95 at most 15 seconds over 20 runs, OCR P95 at most 3 seconds over at least 100 regions, and total idle memory at most 700 MiB |

For this plan's memory reporting, disclose the conservative sum of owned-process working sets and private commit separately; shared working-set pages may be counted more than once. Measure idle before and after activating optional capabilities, and state which cohort is compared with the existing M4 budget. No metric redefinition or timeout increase can silently make a failing gate pass.

Apply stages incrementally and keep the previous matched artifact set available locally. If a stage fails its correctness, latency, memory or cleanup criteria, revert that stage's policy and rebuild the matching host/sidecar/frontend. Do not edit historical records or allow old services to read incompatible storage. Update the [validation record](validation.md) only with actual results and scope; retain [M4](roadmap.md#m4-one-entry-exe-and-local-lifecycle) as unaccepted while its environment or visible-GUI gates remain open.

Use [benchmark_runtime.py](../scripts/benchmark_runtime.py) and the [experiment protocol](performance-experiment.md) for comparable cohorts. The tool requires Windows counters, a built frontend and installed OCR languages for OCR observations. It retains failures, separates activation from request latency and writes private/raw plus reviewable sanitized summaries under ignored `.local/runtime-benchmark`. Native headless mode additionally requires matching `--executable` and `--resources`; it excludes WebView/visible GUI and cannot establish cold-start acceptance. Each cohort has at least 20 launches, with two fixed 60-second idle windows on its first cycle.

```powershell
python scripts/benchmark_runtime.py --policy on-demand --cohort candidate --cycles 20 --source-revision <reviewed-revision>
```

The [observed results](performance-results.md) defer default promotion because startup-tail improvement did not exceed control variability. P3 is deferred because seven-pack initialization P95 was 9.4 ms; P5 lacks isolated helper-setup and retained-cost evidence. Catalog/cache budgets and helper idle lifetime are needed only if new measurements justify those stages. M4 and visible-GUI/clean-machine acceptance remain open; publication does not establish those gates.
