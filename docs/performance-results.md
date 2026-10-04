# Runtime performance results

The explicit on-demand experiment did not pass the predeclared startup-latency comparison. Default promotion is deferred: both launchers retain `eager`, and `--startup-policy on-demand` remains an explicit experiment. Initial idle private commit fell in the measured headless workflow, but the startup tail did not improve beyond control variability. The [plan](performance-plan.md), [experiment](performance-experiment.md) and unchanged [M4 gates](roadmap.md#m4-one-entry-exe-and-local-lifecycle) define the scope.

## Method and identities

Run order on 2026-10-05 was [control A](../fixtures/runtime-performance/control-a.json), [control B](../fixtures/runtime-performance/control-b.json), then [candidate](../fixtures/runtime-performance/candidate-on-demand.json), with 20 fresh-state attempts each. Controls used unchanged eager source `eade0dc33451d55436d2b22acc0ee94dfe8d9be8`; the explicit candidate used `7afdd6ed9a4304c2d29d09d4b9d4e96088039a34`. The follow-up restores the default without changing explicit on-demand behavior. Every synthetic manual comparison and frozen replay passed; all 60 attempts reclaimed their owned processes.

The builder used Python 3.12.14, Windows 11 build 10.0.26300, AMD Ryzen 9 5900X and 24 logical processors. No coordinated builds or test suites ran during collection. OS caches remained warm. Installed native languages were de-DE, en-US and zh-Hans-CN; the original synthetic LEVEL 70 BMP used en-US. BMP SHA-256: `f3170d498becf25be01aa38aa670e37cdc7ad990c92546fcd56171ca35a1e1ed`. Synthetic pack hash: `60c1d4a208213bf850ce19fd6edb997766787ae0f4dab6be09f5b97ea8a2abd6`. The selected summaries retain runtime/gateway/service source hashes and identical demo/index/facts/intent identities. Native EXE, installer, WebView and interpreter/frontend binary hashes were not collected by this development cohort.

The [benchmark](../scripts/benchmark_runtime.py) must run from a clean clone with the [locked frontend and Windows prerequisites](implementation.md). Export the control revision with `git archive` into an ignored local directory and build its frontend with the same lockfile/toolchain. Substitute the exported directory and the same Python executable for these placeholders:

```powershell
python scripts/benchmark_runtime.py --runtime-root <control-export> --python <same-python> --policy legacy --cohort control-a --source-revision eade0dc33451d55436d2b22acc0ee94dfe8d9be8 --cycles 20
python scripts/benchmark_runtime.py --runtime-root <control-export> --python <same-python> --policy legacy --cohort control-b --source-revision eade0dc33451d55436d2b22acc0ee94dfe8d9be8 --cycles 20
python scripts/benchmark_runtime.py --runtime-root . --python <same-python> --policy on-demand --cohort candidate-on-demand --source-revision <reviewed-candidate-revision> --cycles 20
```

Before the candidate, the ensure HTTP observer changed from 30 to 10 seconds, allowing delivery beyond the unchanged eight-second owner deadline. Legacy controls issue no ensure request. Bounded HTTP status/error-code capture was added for candidate failures; controls recorded only the error category. Business observers, fixtures, sampling and comparison thresholds stayed unchanged. Publication copies rename the legacy `acceptance_passed` field to `workflow_checks_passed`; its value describes workflow completion only. Original private summaries remain unchanged. See the [evidence guide](../fixtures/runtime-performance/README.md).

## Observations and verdicts

P95 uses nearest rank, retaining failures. Manual completion means launch through synthetic confirmation/evaluation, without a human or WebView. Faster shell readiness does not establish a usable GUI improvement.

| Metric | Control A | Control B | Candidate |
| --- | ---: | ---: | ---: |
| Manual completion P95, seconds | 5.0676 | 6.4375 | 4.9235 |
| Initial idle private commit maximum, MiB | 105.8945 | 104.9883 | 76.6094 |
| Post-use idle private commit maximum, MiB | 109.1094 | 109.4336 | 109.5781 |
| OCR activation plus first request P95, seconds | 3.1513 | 2.2128 | 2.7974 |
| Planning activation plus first request P95, seconds | 0.0377 | 0.0395 | 1.4558 |
| Shutdown P95, seconds | 0.2701 | 0.3774 | 0.2601 |
| Workflow/cleanup failures | 3 OCR / 0 | 0 / 0 | 0 / 0 |

| Predeclared gate | Candidate observation | Verdict |
| --- | ---: | --- |
| Manual completion P95 <3.6976023 s | 4.9235146 s | Fail |
| Initial idle private commit <104.08203125 MiB | 76.609375 MiB | Pass |
| Post-use idle private commit <=109.7578125 MiB | 109.578125 MiB | Pass |
| OCR activation plus first request P95 <=3 s | 2.7973532 s | Pass |
| Planning activation plus first request P95 <=3 s | 1.4557726 s | Pass |
| Shutdown P95 <=5 s | 0.2601040 s | Pass |
| Zero candidate workflow/cleanup failures | 0 of 20 | Pass |

The faster control P95 minus candidate P95 is only 0.1440 seconds; control P95s differ by 1.3700 seconds. The conservative comparison therefore rejects a startup improvement claim. Candidate manual completion's standard median/P95/maximum were 2.1533/4.9235/6.9464 seconds; its nearest-rank P50 was 2.1485 seconds. Core readiness's median/P95/maximum were 1.5833/3.6121/4.6897 seconds.

Candidate initialization tails included Profile P95/maximum of 1946.8/2442.3 ms and Evaluation 969.6/1592.2 ms. Knowledge initialization across seven packs was 8.6 ms median, 9.4 ms P95 and 10.2 ms maximum; catalog response median/P95 was 37.6/46.8 ms. P3 stays deferred because parsing does not dominate these observations; large-catalog scaling and retained-pack memory are unmeasured. OCR capability discovery median/P95 was 707.9/731.2 ms; first/repeated business-request P95 was 1.7436/1.7349 seconds. Whole-request timings do not attribute helper initialization or establish reuse's retained-memory/lifecycle cost, so P5 stays deferred.

Each cohort has one 60-second idle interval per state in its first cycle, with 61 samples at 1 Hz, rather than 20 independent idle observations. Candidate initial/post-use summed working-set maxima were 150.133/219.063 MiB; CPU was 0.2344%/0.4687% of one logical processor. Across 20 cycles, sampled peak working-set median/P95/maximum were 294.359/296.977/297.328 MiB, and private commit was 165.664/168.215/168.574 MiB. Summed working sets may double-count shared pages, and 100 ms descendant discovery may miss brief helpers. This is not total desktop memory acceptance.

Control A retains three OCR HTTP failures at cycles 12–14. Their actual status/body was not recorded; the approximately three-second deadline explanation remains an inference. Control B and candidate had no failures. Control A's Planning P95 uses 17 observations because three attempts failed before that stage. Failed attempts and missing later-stage samples remain in the evidence; no failed attempt was replaced by a rerun.

## Implementation and remaining gates

Allowlisted activation, shared startup attempts, generation-bound dependency routes, explicit recovery, owned-child cleanup, source readiness controls, mount-once panels and serialized visibility-aware polling remain implemented. Already-running Evaluation preserves frozen list/detail/replay during upstream faults while new evaluations remain blocked. Runtime behavior is checked separately from quantitative improvement.

At the pre-integration `2034deed` source stage, production splitting was deferred after a small entry-byte benefit, increased total JavaScript and an actual chunk failure that stayed cached on retry. That stage measured a single 270430-byte JavaScript entry (SHA-256 `febecaf4049638b443d374f735e1b5ff3f281777dd9114331b81cedc7de23ca0`) and 6923-byte CSS; these are not current merged-frontend bundle measurements. Mount-once panels preserve drafts without claiming bundle savings.

The historical `fb67195` source checks, before the `923bca` health-deadline fix and later mainline integration, ran 400 Python tests (399 passed, one Windows symlink-privilege skip; including 13 base CI diagnostic and ten native maintenance verifier cases), 22 standalone native tests (two fixture entry points ignored by discovery and invoked as children), 16 frontend runtime checks, TypeScript/production build and 21 browser flows plus six simulated native flows. Those native simulations are not real-game capture; these counts describe that earlier source snapshot, not current integrated source. Separately, the matching development package built from product source `2034deed` passed 30 full Rust tests, 20 default eager and 20 explicit on-demand lifecycle/fault cycles, and 20 hidden passive WebView cycles; the [validation record](validation.md#matching-development-package) preserves that historical package's identity and limits.

Warm caches, excluded WebView/visible painting and a single builder mean these results do not establish M4 cold-start or clean-machine acceptance, OCR accuracy, independent human truth review or real-game mechanics. The release budgets remain unchanged. Promote on-demand only after a new declared comparison resolves the startup-tail uncertainty; keep eager available for rollback and rebuild matching artifacts after any policy change.
