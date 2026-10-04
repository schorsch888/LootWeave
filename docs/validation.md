# Local validation record

Recorded on 2026-10-04 UTC. This is developer-machine evidence, not release acceptance. The source tree and generated binaries are separate validation scopes.

## Source snapshot before runtime optimization

This section records the earlier source/artifact checks; runtime performance verification is reported separately below.

| Check | Observed result | Scope |
| --- | --- | --- |
| Python regressions | 348 run: 347 passed, 1 skipped (34.660 s including discovery) | Domains, APIs, storage, replay, runtime, maintenance, capture-clock binding, OCR/window provenance, research metadata and trial history; the skip requires Windows symlink privileges |
| Windows Rust guards | 10 passed | Actual capture/window/supervisor modules: passive metadata, boot permit, job cleanup, bundle integrity and address isolation; excludes Tauri IPC/GUI |
| Original Frostwyrm validator (default evidence) | Passed read-only source identity checks | 11 hashes, 3 objects, 2 links, 1 managed effect, 14 layouts, 2 enums, 9 methods; `online_validated=false`, `m1_accepted=false` |
| Frostwyrm lifecycle validator (`--evidence` record) | Passed read-only source identity and selected boundary checks | 12 hashes, 3 objects, 2 links, 1 managed effect, 15 field layouts, 2 enums, 15 methods, 5 direct relative links, 1 PE exception bound ([Microsoft](https://learn.microsoft.com/en-us/cpp/build/exception-handling-x64)), 1 prior-record hash/scope check; `online_validated=false`, `m1_accepted=false` |
| Frostwyrm method-slot validator (`--evidence` record) | Passed original metadata checks on the installed matching build | Retains the selected lifecycle checks and adds 2 types, 4 method declarations and 2 concrete metadata targets; native dispatch and online acceptance remain unpassed |
| Frostwyrm module-pointer validator (`--evidence` record) | Passed matching installed-build image/token-pointer checks | Retains selected lifecycle/slot checks, adds 1 metadata image and 2 x64 module pointer entries; runtime registration/class dispatch and online acceptance remain unpassed |
| Frostwyrm code-registration validator (`--evidence` record) | Passed matching installed-build registration/address checks | Retains selected lifecycle/slot/module checks; 16 hashed methods, 2 PE exception bounds, 1 metadata image-count check, 1 registration structure, 1 selected module entry and 1 address reference; executed registration/class dispatch and online acceptance remain unpassed |
| Frontend | TypeScript and current production build passed | Current React/FSD source, including capture-time review and source-clock error handling |
| Confirmation component checks | 14 passed without DOM/browser input | Exact UTC capture-time display, manual/legacy metadata, rejected statuses, request retry, busy/error recovery and translations |
| React server rendering | 32 actual cards passed: 8 current and 24 historical | Original pins, mechanism uncertainty and historical presentation; no browser interaction or native IPC |
| Planning component checks | 27 passed without DOM/browser input | Current source IDs/events, scope, counts, edit/confirmation, failure/retry states and XP display; fixture adapters do not verify React scheduling/native UI |
| Archived browser flows | 24 passed in 32.040 s on engine 0.1.3 | 18 real-service and 6 simulated Deskrawl IPC; not rerun for 0.1.4; actual native commands and clean-machine distribution remain pending |
| Hidden native WebView | Final 20 sequential cycles passed in 174.931 s | Own invisible, initially unfocused, nonfocusable windows; passive DOM and authenticated invalid-request IPC guards, explicit CDP release and fixed-handle natural exit records; initial shutdown timeout remains unresolved; excludes visible GUI and keyboard acceptance |
| Architecture | Zero findings | FSD import boundaries and independent Python services |
| Archived OCR evidence | 200 exact BMP reconstructions and parser replays per version; v7's 30 crops verified; 16 evidence regressions passed | [Original v6](../fixtures/ocr-critical-fields-v6/README.md) and [v7](../fixtures/ocr-critical-fields-v7/README.md); complete 600-field denominator per version; v7 95.33%, human/game coverage pending, M2 unaccepted |
| Publication patterns | Zero findings | Public text only; not a substitute for independent publication review |

The Deskrawl source adapter matches the executable basename, checks process creation identity and window ownership, and requires an explicitly selected session-scoped window binding. Coordinates are physical pixels relative to the client area. Before and after GDI region capture, the same process/window must remain visible, restored, foreground and at the detected client bounds. Moving/resizing requires detection again; stale bindings and out-of-client regions are rejected.

The UI gives three seconds to return manually to the game, leaves raw input editable after failure, and discards stale asynchronous results. Capture provenance remains unconfirmed; game version/build are unknown. Profile confirmation rejects a declared capture game that conflicts with the snapshot game, and each new image requires a fresh confirmation checkbox. This is foreground screen-region capture with pre/post checks, not an atomic Windows window-only capture API. Overlays and intervening focus changes still require manual review of the captured image and text. Executable identity does not verify game mechanics or the installed build.

The capture review shows the original submitted BMP at native pixel dimensions alongside uncorrected OCR text. Archived 0.1.3 browser checks verify exact image-byte correspondence, keyboard scrolling without mobile page overflow, original text surviving manual corrections, and image/observation/checkbox invalidation on failed recapture while retaining manual input. A delayed detection response reproduced an older window-list overwrite before the fix; detection generation and current context now both gate committing results. The image-review UI does not change OCR accuracy; parser measurements are recorded separately below.

The lifecycle evidence adds a selected static trace of a rebuild body clearing the equipment deflection count and target mode before later effect callbacks; a separate count pool has its own reset. Regression cases cover signed relative calls and backward tail jumps, reject bad opcodes/targets/ranges/duplicate edges, exercise inconsistent or ambiguous exception bounds, and detect tampered prior-record evidence. This does not establish complete equip/unequip coverage, slot mapping, duplicate or stacking behavior, ownership, or online behavior. The record validator checks identities and selected control-flow boundaries, not a complete lifecycle model; M1 remains unaccepted.

The separate [method-slot record](../research/deskrawl-frostwyrm-method-slots.json) checks original IL2CPP metadata v39 for the selected base and concrete effect types. Four declarations retain declaring type, token, virtual/abstract flags, parameter count and slot; two concrete vtable entries point to the corresponding own method definitions. Both callbacks use slots 4 and 5. Six portable regression methods use fictional metadata and check version/width/stride/range changes, overlap, strings, ownership, false claims, duplicate selections and wrong concrete targets; a concrete method cannot opt out of its target check. The actual installed build passed all added checks. In a controlled comparison, the prior checker ignored the newly introduced metadata section and accepted a claimed slot 99; the extended checker rejected it, and accepted the original slot 4. This is validation of the new section, not a claim that older metadata assertions were supported. The prior record and pack versions remain unchanged. The new `0.4.0-research` pack remains non-executable; native class layout, indirect dispatch, live events, duplicates and online behavior require independent evidence.

Measured leveling trials use manually entered start/end levels in the selected experience system; Paragon ranges begin blank rather than reusing character levels. Archived browser regressions verify range/type isolation, ranking invalidation after edits, rejection of missing/inverted ranges or blank XP, disabled controls during saving, and idempotent retry after persistence succeeds but comparison fails. These are fictional measurements through real local services, not measured Deskrawl route efficiency.

In the preceding metadata stage, the first 314-test run had one failure before the process-reclamation assertions: the controlled OCR helper/descendant markers did not appear within the existing deadline. An unchanged-test diagnostic run passed all eight lifecycle cases (9.759 s); the failed case reported available OCR and created both markers during that diagnostic run. The original failure cause remains unconfirmed. The fixture now checks OCR availability explicitly and retains request error codes and marker states on startup failure; timeouts, retained native-handle reclamation and unrelated-process isolation assertions are unchanged. The final full run passed 313 cases with one symlink-privilege skip (68.269 s). This does not establish that the intermittent startup failure is resolved. Private local records preserve the initial failure, diagnostic observations, final source hashes and results. The final read-only resource snapshot measured 6,807 MiB available memory and 77% committed bytes, with no matching controlled service/helper signatures; it is a point-in-time observation, not a leak or release-acceptance benchmark.

## Public synthetic OCR evidence reproduction

The complete [v6](../fixtures/ocr-critical-fields-v6/README.md) and [v7](../fixtures/ocr-critical-fields-v7/README.md) fixtures preserve their original 200-region manifests, native OCR observations/geometry, parsed fields and reports, together with frozen renderer/parser sources and file identities. V7 also includes all 30 native numeric-region observations. Public copies retain the original bytes; repository attributes disable newline conversion for these immutable snapshots. No game/player material, machine paths or fonts are included.

For each dataset, the evidence auditor checks all 600 scores including sign/unit equality, rejection/missing denominators, exact raw-text spans, confirmation flags, balanced language/scale/quality coverage, dimensional totals and recorded latency percentiles. It replays all 200 observations through the corresponding frozen parser. Nine v6 regressions reject omitted regions, duplicate identities/images, changed scope/renderer truth, promoted rejections, sign/unit loss, altered source mapping/confirmation and favorable aggregate/latency/target substitutions. Seven v7 regressions additionally exercise observation image/state, crop presence/identity/geometry/language, original native-word mapping and exact frozen result replay.

Using the disclosed Windows fonts, Pillow 12.3.0 and FreeType 2.14.3, each frozen generator recreated all 200 images with identical BMP hashes/dimensions and a byte-identical manifest. V6 reconstruction plus audit took 3.239 s; v7 took 3.652 s. These are tooling durations, not native OCR latency. The current full Python suite ran 314 tests: 313 passed and one Windows symlink-privilege case skipped in 68.269 s including discovery. Frozen source/JSON identities are checked by portable CI tests; authoritative remote CI remains pending.

Evidence integrity passes for both archived datasets. V6 retains its original 550/600 (91.67%) result; current frozen v7 measured 572/600 (95.33%). Neither integrity checks nor overall numerical targets establish independent human review or actual game/layout accuracy. Both datasets have now been examined; future algorithm/model/renderer changes need a fresh unseen set. M2 remains unaccepted.

## Optional numeric-region recognition

The current adapter can make one additional English helper call for at most three numeric crops selected from unique, mapped primary rows. Only ambiguous fields with known units, valid geometry and no existing reader conflict qualify. Recovered numbers retain the original image/text/span and record projected original-pixel bounds plus `native_numeric_region` provenance. Readable primary values are retained while crop corroboration determines ambiguity. Multiple contradictory English candidates mark a readable field ambiguous without selecting a candidate; explicit primary signs cannot be replaced by an opposite sign or an unsigned negative reading. Every value requires confirmation. A timeout, malformed result or helper failure leaves the primary observation usable and records `numeric_region_error`. The helper is limited to six seconds and the remaining twelve-second request budget. Crop bitmaps and the input stream are disposed; service-owned process cleanup also applies.

Fifteen numeric-region regression methods passed, including real Windows helper checks for two and three regions and duplicate rejection, multiple conflicting numeric candidates, explicit/Unicode sign disagreements, signed zero and failed optional reads. The earlier native regression exposed a Windows PowerShell JSON-array wrapping bug; typed array assignment processes each region. Its initial failed diagnostic remains private and preserved. This host also failed to open a controlled BMP through Windows Storage in its configured temporary directory, so the native fixture uses an owned workspace-local temporary directory. Packaged data paths remain outside this verification scope.

The earlier bounded-crop adapter was measured on all 200 previously examined v1 tuning images. A frozen baseline parsed each identical primary text/geometry/English reference, while the adaptive interpretation could use actual native crops: 556/600 became 568/600 (12 improvements, zero losses; 43 to 31 rejected/missing; one unflagged error in both). It issued 200 primary and 31 numeric helper calls, with no worker/optional-read errors; P95 was 1.749 s for that earlier adapter. Final-source replay of those same saved observations/crops retained 568 correct, changed the sole unflagged error into ambiguity and recorded 32 rejected/missing fields. The replay supplies no new native latency. A broader readable-value crop policy lost 18 correct fields and was rejected; the adopted policy preserves readable values and requests crops only for bounded ambiguous candidates. These are tuning evidence, excluded from M2 acceptance; current native accuracy/latency comes from fresh v7 below.

Current OCR source SHA-256: application `7b9c9f1a52f59ac73cb5ddc70604492a7c8cd084131409bb226ed865e0d58e08`; domain `7edf81f6a3961fae83a06529dcac00bc0a8df2af0fa257557c0c371503ca6d72`; PowerShell adapter `73217003b26335e88bb5af473fb657c22cdade4fac5d35a3de210ab8676c1e3c`. The benchmark/frozen v7 renderer SHA-256 is `55e88d9fd7e5b15023eb9c16c61880b53f58ff2d3c0f34475b31cdf19d60231d`. The archived v6 parser, observations, report and renderer bytes remain unchanged.

## OCR holdout-v7

The current adapter was frozen before generating previously unseen `synthetic-critical-fields-v7`: 200 original synthetic regions/600 critical fields, balanced across two languages, five scales and four quality conditions. None of its BMP hashes overlap v1 tuning or holdouts v1–v6. The [public observations](../fixtures/ocr-critical-fields-v7/observations.json) preserve every field score and request timing; the [report](../fixtures/ocr-critical-fields-v7/report.json) includes missing/rejected fields and sign/unit errors in its complete denominator.

| Stratum | Correct / all critical fields | Rejected or missing |
| --- | --- | --- |
| Overall | 572 / 600 (95.33%) | 28 |
| English | 299 / 300 (99.67%) | 1 |
| Chinese | 273 / 300 (91%) | 27 |
| Scale 0.75 | 113 / 120 (94.17%) | 7 |
| Scale 1.0 | 111 / 120 (92.5%) | 9 |
| Scale 1.25 | 119 / 120 (99.17%) | 1 |
| Scale 1.5 | 113 / 120 (94.17%) | 7 |
| Scale 2.0 | 116 / 120 (96.67%) | 4 |
| Clean | 147 / 150 (98%) | 3 |
| Low contrast | 140 / 150 (93.33%) | 10 |
| Blurred | 146 / 150 (97.33%) | 4 |
| Downsampled | 139 / 150 (92.67%) | 11 |

Every stratum had zero unflagged errors. Twenty-six observations received 30 numeric crops with zero optional-read errors. Whole-request P50/P95 was 0.922/1.780 s; total native measurement time was 220.922 s. The timings include primary and optional helper startup, BMP validation and parsing. The developer host ran Windows 10.0.26300 on a Ryzen 9 5900X with about 32 GiB RAM; these measurements do not cover clean-machine distribution.

Truth SHA-256: `c6ab5608f97c2f727ecc1b5a9c9fc869eec0b641ea2593291b0aae060ac34cc6`. Application/domain/adapter identities match the final source listed above. Overall accuracy ≥95% and P95 ≤3 s passed for this dataset. Chinese and poorer-quality strata remain below 95%; three generic labels do not establish real-game/layout coverage, and independent human truth review remains pending. Every observation is unconfirmed. **M2 remains unaccepted.**

V7 has now been examined and sealed; it is historical evaluation/replay evidence for later changes. A changed parser, model or renderer requires a fresh unseen holdout. V6/v7 have different seeds and cannot prove a controlled improvement.

## Service and helper process lifecycle

A controlled Windows reproduction showed that an actual OCR service could exit with code 0 after parent EOF while its active PowerShell helper remained alive. Three native regression paths failed before the change: parent EOF during recognition, forced worker termination with a helper descendant, and forced termination during capabilities startup. Test cleanup reclaimed those controlled processes; no game or real recognition was exercised in the reproduction.

Windows services now establish a process-lifetime [job object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) before application initialization. Its handle is anonymous and non-inherited, retained until OS process exit; descendant membership follows normal process creation. Normal exit and forced worker termination close the owner's lease and reclaim helpers. Rust first assigns its outer job, then releases a one-byte stdin permit before Python creates the nested service scope. Missing/invalid permits or job setup failures publish no readiness. Developer launches clear the inherited desktop permit flag. Eight lifecycle regressions passed, including actual kernel-handle liveness/exit checks, nested-job operation and a sibling process that remains alive.

The lightweight Rust harness compiles the actual capture, window and supervisor modules with one compiler job and one test thread. All ten checks passed with source identities unchanged during the run, including the actual boot-permit write, rejection of a missing control pipe and live-before-close/bounded-exit job cleanup. Earlier attempts retained a missing test dependency failure and an incorrect nonzero-exit-code assertion. On this host, job reclamation returned exit code 0; the passing test verifies liveness and bounded termination rather than inferring cleanup from that code.

Current service lifecycle source SHA-256: `08086c6f2298e6e7df6bf087ef86b891f243c4ee81443d0e42e4a6e80895b502`; service entry: `3719ee0ab397a52dd772c3302b9601a08f67b45597b3a2c008b8cd8eb882c9c6`; Rust supervisor: `a1d90a9cf067784b65efa29a4e2dbf78162d744e33eff66a95740c5c34d543c1`. These process-lifecycle modules are unchanged by the numeric-region and evaluation work. The final OCR source identities match the frozen v7 measurement; older holdouts retain their historical adapters.

Test suites, the frontend build and React server-rendering check ran sequentially. Archived read-only OS checks after the earlier evaluation validation found no matching test workers, OCR helpers or headless browser processes. Available physical memory was 4,855 MiB and host committed memory was 74% of its limit. The archived 0.1.3 browser run completed 24 flows in 32.040 s, with no page errors and runtime exit code 0; its separate subsequent host readings were 8,715 MiB available and 60% committed. These developer-host readings do not establish per-application leak rates, the packaged idle-memory budget, twenty cold-start cycles or two-clean-machine acceptance. The full Rust/Tauri host and frozen sidecar rebuild remains deferred.

## Evaluation comparison and historical replay

Engine `0.1.4` preserves unknown capability states through whole-item comparison. Previously, an active mechanism becoming unknown could be listed as definitely lost and a required mechanism as definitely missing, even while the result was blocked. Providers are now aggregated separately by actor/capability: any active provider yields active; otherwise any unknown provider yields unknown; otherwise the state is inactive. Only active-to-inactive and inactive-to-active transitions produce definite losses and gains. Unknown required states appear in `comparison.uncertain_mechanisms` with before/after states and stay out of known-missing rows. Original rule/input sources and conservative unknown-rule blockers remain.

Eight [frozen 0.1.3 cases](../fixtures/evaluation-0.1.3.json), recorded before the fix, cover four unknown transitions, a companion transition, an active alternative and definite loss/gain controls. A matrix of 162 validated fictional configurations covers both actors and all nine two-provider state pairs on each side of replacement. All 162 explicit 0.1.3 replays match their original hashes; all 162 current summaries match a separately specified nine-entry state oracle. Eighty-seven loss/gain/missing list decisions changed, excluding version pins and additive fields; this counts decisions, not configurations. Original/current domain SHA-256: `9ac4378118f374988d2fdf7a2052c9faeeded0be427e80f9ff5e57658dd94f39` / `127b71e63800b5afc0854cc621e836ccc82bd21a6ec5b5f1f42c80c55a8087ad`; fixture SHA-256: `94cad8d0ad4c0a951e2ba9338ad9d803345ef44c4c69ad5e50137a8e76dba21c`. Five directed regression methods also check provenance, ordering, incompatible scopes and historical/current results. A real HTTP regression verifies idempotency and ten exact current replays after Profile and Knowledge stop.

`node scripts/check_evaluation_render.mjs` uses the installed frontend dependencies to compile the actual evaluation component with Vite and render it through React on the server. All 32 cards passed: eight current results and 24 frozen historical results. It checks version pins, owner/state labels, unknown transitions excluded from definite changes and the original 0.1.3 presentation. No browser, desktop input, game process or native IPC is exercised. These synthetic source and presentation checks do not establish M3 real-game acceptance.

Engine `0.1.3` distinguishes a required capability missing from a compatible knowledge pack from a known capability missing in the build. The former produces `unknown_required_capability`, blocks retention/comparison verdicts and is excluded from known-missing rows. Known unmet goals still appear. An incompatible scope cannot establish mechanism absence: it executes no rules, emits no deltas/missing mechanisms and sets `comparison.scope_compatible=false`; the UI shows the scope warning. Historical results without that additive field retain their original presentation. Four directed regression methods reproduced 23 failing subcases before the change; all pass. A real loopback HTTP regression verifies unknown-goal deduplication, idempotency and ten exact replays after Profile and Knowledge stop.

Six [frozen 0.1.2 cases](../fixtures/evaluation-0.1.2.json) preserve actual pre-fix hashes for unknown current/future/no-use goals, mixed known/unknown goals, incompatible scope and a known-goal control. A paired matrix of 36 validated fictional combinations covered three candidate uses, four goal sets and three build scopes. Explicit 0.1.2 replay matched the archived original hashes for all 36; then-current 0.1.3 requirement/scope decisions matched the manually specified oracle for all 36. Twenty-four retention/status/missing/blocker decisions changed, excluding version pins and additive fields from that count. Archived 0.1.2/0.1.3 domain SHA-256: `53f8d976ae81bbae6be08a034c3444ebed5810604dd70c8c1eff37269bb6db88` / `9ac4378118f374988d2fdf7a2052c9faeeded0be427e80f9ff5e57658dd94f39`; historical fixture SHA-256: `11ebfd8d12cfe44de9404f6fdd6f75118300e5e9dcc5b15a46ff8037e177543c`. This is source-level fictional correctness evidence, not real-game acceptance.

Engine `0.1.2` fixed capability aggregation after rule resolution: the prior name-only projection could report no change when the hero lost a mechanism still available to a companion, or treat the companion's mechanism as a fulfilled hero requirement. Loss/gain/missing rows retain actor/capability identity. Unqualified requirements apply to the hero; identical providers for the same actor represent one capability. Three directed regression methods reproduced ten failing subcases before that change; all pass. A real loopback HTTP regression checks the unmet hero requirement despite an active companion mechanism, then replays ten times after source services stop.

Six [frozen 0.1.1 cases](../fixtures/evaluation-0.1.1.json) cover hero/companion losses, both ownership transfers, a companion-only hero requirement and a same-owner alternative provider. Together with the four 0.1.0, six 0.1.2 and eight 0.1.3 cases, all 24 historical cases replay ten times each with source APIs unavailable, retaining original pins, shapes and hashes. New requests pin 0.1.4; old request IDs still return their stored results.

The earlier controlled matrix of 96 validated fictional combinations covered all 16 before/after actor-presence combinations, three condition states and two hero-requirement states. Explicit 0.1.1 replay matched the archived original hashes for all 96, and engine 0.1.2 matched the independent presence/state oracle for all 96. Fourteen loss/gain/requirement/status decisions changed. Original 0.1.1/0.1.2 domain SHA-256: `8c4b844a4c974054e2979fb4895a545ab7d3542065c95de44fd7f23be49ddc48` / `53f8d976ae81bbae6be08a034c3444ebed5810604dd70c8c1eff37269bb6db88`; historical fixture SHA-256: `8b37e162b11b61503498f4c7b8fdf1bac6e413fd5fbd768862b0f4c1358d26e5`. These are archived measurements from the original 0.1.1/0.1.2 sources.

The archived 0.1.3 browser run passed all 24 flows in 32.040 s with no page errors: eighteen used real local application services, and six simulated Deskrawl native process/window/capture IPC. It checked companion-loss labels, unknown-goal and incompatible-scope rendering, plus original 0.1.1 rendering/replay from a frozen fixture seeded before startup; all later history reads/replays used real HTTP. The simulated successful capture supplied a synthetic BMP to the actual OCR worker. No real game process or native capture was exercised. Browser interaction has not been rerun for current 0.1.4 source.

The earlier browser attempts remain archived: navigation reported `ERR_INSUFFICIENT_RESOURCES`, confirmation timed out, and a later attempt hit an uncaught Playwright Chromium-protocol assertion. A contemporaneous host reading showed 99% committed memory, about 574 MiB remaining commit capacity and 603 MiB available physical memory. Those attempts are not passing evidence; the timeout's cause remains unproven. After memory recovered, another run completed ten flows and stopped because its browser keyboard helper operated before asynchronous draft validation enabled confirmation. The helper was corrected to wait for the enabled state; the complete archived 0.1.3 run then passed. Control-lock assertions inspect disabled states in one browser call. Failure diagnostics remain bounded and redact the session credential/runtime URL. Current evaluation checks use server rendering with no input automation.

Earlier source-level test suites also ran sequentially. After the earlier 0.1.3 browser run, available physical memory was 9,304 MiB and committed memory was 73% of the host limit; no matching test workers or headless Playwright Edge processes remained. Those archived host readings do not measure per-application leaks or satisfy the packaged desktop memory gate. The current lifecycle-specific evidence is recorded above.

Engine `0.1.1` corrected three actor-ownership paths: embedded effects default to the hero, set thresholds count only matching owners, and required skills belong to the rule actor. Four domain regression methods reproduced seven failures and one error before that fix. Four [archived synthetic cases](../fixtures/evaluation-0.1.0.json) retain pre-fix hashes without changing their `0.1.0` pin. Those new requests pinned `0.1.1` at the time; unavailable engines are rejected. A real loopback HTTP test confirms an unspecified embedded actor and companion runes, preserves input provenance, then replays ten times after Profile and Knowledge stop.

The earlier controlled comparison against the archived original domain source covered 72 validated fictional ownership combinations. Explicit `0.1.0` replay matched all 54 completed results and 18 original exceptions; `0.1.1` completed all 72, resolving those 18 crashes and changing 42 other results. Original/0.1.1 domain SHA-256: `4cd73e14e7511696ac82b370fc00f56e496248904e76a94e3170644e255cf994` / `8c4b844a4c974054e2979fb4895a545ab7d3542065c95de44fd7f23be49ddc48`. Historical fixture SHA-256: `b7ae721bd8774142556eabfb33e6b626caebb3677aca3b10649853cbad20ff11`. Local comparison reports remain ignored; historical fixtures and executable regressions are public repository candidates.

The current Tauri host and NSIS installer have been rebuilt locally and their frozen services pass headless checks. The lightweight Rust check excludes command permissions and GUI; actual new window IPC remains pending. The extended native IPC probe has not been run against the new package.

## Acquisition sample integrity (preceding stage)

The pre-fix local-source probe accepted counts above the JavaScript exact-integer range; a 401-digit count produced `OverflowError` and HTTP 500. The initial 18-case component baseline passed 5 cases and failed 13, including missing API source IDs/version scope, blank/unsafe counts, stale estimates and submission state. The current shared count guard rejects blank, fractional, exponent and out-of-range draft strings; normal decimal counts remain exact. The sample API accepts at most `2**53 - 1` attempts and integer successes within that count, consistent with [RFC 8259 section 6](https://www.rfc-editor.org/rfc/rfc8259.html#section-6). Two added Python regressions cover finite boundary results, exact JSON round trips, HTTP 400 for unsafe counts and a normal request after rejection. Counts larger than that range previously accepted by this endpoint are now rejected; sample estimates are not persisted, so this change requires no storage migration.

The preceding 24-case Node check exercises the actual acquisition component and shared validation using fixture state/HTTP adapters. Source IDs and target events, returned version/content scope, blank/unsafe/rounded numbers, cleared confirmations/results after edits, inflight controls, failed requests and small/near-one percentages pass. This is isolated component evidence, without DOM, browser, desktop input, native IPC or real-game acceptance. Run `pnpm --dir frontend check:acquisition` after installing the locked frontend dependencies; the command is also configured in CI, which has not been run remotely for this tree. At that stage, the updated frontend passed TypeScript and production build (12.392 s for the complete command; Vite 1.22 s, 25 modules, JavaScript 263.24 kB). The final full Python run passed 315 cases with one symlink-privilege skip, and the existing pure React check passed 32 current/historical cards. The final resource snapshot found no matching controlled services/helpers/component-check processes, with 5,179 MiB available memory and 81% committed bytes. These are developer-host observations, not P95, leak or clean-machine release acceptance. M5 real-game acquisition rules and independent review remain unaccepted.

## Trial numeric integrity and history (preceding stage)

A fresh probe against the preceding source saved a 401-digit XP value and a trial with 100 XP over 1e-308 seconds as confirmed records; each then made route comparison return HTTP 500. Pooling two otherwise finite 1e308-second records produced an infinite total and a false zero rate, and its result could not be serialized as canonical JSON. The probes used an isolated database and authenticated loopback HTTP, with no player records or game process.

The trial API now rejects new XP/level values outside the exact-integer range and nonfinite individual rates with HTTP 400 before insertion. Structurally valid historical measurements remain stored byte-for-byte and are reclassified as uncertain when unusable, excluding them from rankings. Pooled totals outside the finite/exact range produce an explicit unknown, nullable unsupported totals and a null rate; the route stays pending confirmation and cannot become the best measured candidate. Valid finite boundary rates and actual zero XP retain their measurements.

Retry identity compares original inputs rather than derived measurement status or unknowns. The same inputs can receive an updated classification without replacing stored history; changed inputs under the same trial ID still return HTTP 409. A SQLite immediate transaction reserves the writer before the identity lookup and insert, so concurrent identical saves persist one row and return equal results. Storage v1 and existing payload bytes remain unchanged; responses add route unknowns and allow unsupported totals to be null. Returning to the earlier comparison logic would reintroduce the demonstrated legacy-record failure, so rollback must retain these guards or disable route comparison.

Seven added Python regression methods cover numeric rejection, finite boundaries, aggregate overflow, unchanged legacy payloads, ten repeat comparisons, classification-independent retries, concurrent saves and authenticated HTTP recovery after rejected input. The focused Planning run passed 59 tests. The full sequential run passed 322 of 323 tests in 31.121 s including discovery, with the existing Windows symlink-privilege skip; tested source hashes were unchanged throughout.

The Node check now passes 27 cases: the preceding 24 checks plus legacy/aggregate warnings and small positive route-rate rendering. It uses the actual Planning components with fixture hook/HTTP adapters, without DOM, browser, desktop input, React scheduling or native IPC. The frontend passed TypeScript and production build (1.788 s for the complete command; Vite 153 ms, 25 modules, JavaScript 263.96 kB). The pure React check also passed all 32 current/historical evaluation cards, and architecture checks found zero issues. A final read-only signature snapshot found no matching controlled service/helper/component-check processes, with 5,115 MiB available memory and 84% committed bytes; this single host reading is not a leak, P95 or clean-machine acceptance result. Remote CI, real Deskrawl M5 trials and independent review remain unaccepted. The full Tauri/NSIS rebuild remains deferred.

## Frostwyrm metadata image and native module pointers (preceding stage)

A fresh read-only probe of the matching installed binary and metadata found one module-prefix candidate matching the selected assembly name and both previously recorded method addresses. The original metadata image contains both selected types. The new record binds concrete method definitions 42325/42326 through their method tokens and module pointer indices 1170/1171 to the already hashed native bodies. The prior three research records and four research packs retain their original bytes/hashes; 0.5.0-research adds the image/module evidence while keeping rules empty and online/M1 acceptance false.

Seven added portable regression methods use fictional PE/metadata bytes. They cover image identity/member ranges, prefix/name/table bounds, token/index/target mismatches, missing/duplicate/abstract bindings, metadata-image coupling and the new pack's source/history pins. All 26 related research regressions passed. The four installed-source invocations also passed: the current module record adds one image and two native token-pointer checks to the selected lifecycle/slot checks. A controlled false-index claim was rejected by the current checker; the prior checker ignored the added module section because it was not supported. This does not establish a prior claim of module-pointer validation.

Initial development failures remain recorded locally: binary/set values were mistakenly sent to the JSON equality helper, a test confused the manifest's raw file hash with the API's canonical content hash, and two catalog expectations still counted the old version set. The legacy comparison loader also initially lacked its package context and stopped before running the comparison or full suite. These were corrected with their failure records preserved. The first full run had one stale catalog-count failure (328 passed, one failed and one privilege skip); the final full run passed 329 of 330 tests in 31.550 s including discovery, with the existing Windows symlink-privilege skip and unchanged tested source hashes.

Real loopback HTTP verifies that the new research pack still blocks executable mechanics, preserves its version pin and replays ten times after Profile and Knowledge stop. All five research versions remain explicit, and mutation of returned API copies cannot replace cached history. The frontend, OCR, evaluator, storage and Rust modules are unchanged; preceding frontend/27-component/32-card checks retain their original source scope, without a new browser/native run. Current architecture and publication preflight results are recorded in the source table.

The final read-only signature snapshot found no matching controlled service/helper/component-check processes, with 4,952 MiB available memory and 84% committed bytes. This is a single host reading, not a leak or release benchmark. Native runtime registration-root use, class-vtable materialization, indirect dispatch, complete event/ownership coverage and online effects still require evidence. M1 remains unaccepted; the full Tauri/NSIS rebuild and two-clean-machine distribution gate remain deferred/unpassed. Selecting an older explicit research pack preserves its original scope; an older checker cannot validate the new image/module sections.


## Frostwyrm code-registration tail and selected module entry

A fresh read-only search initially found no module table when it assumed native module order matched metadata order. Name-based discovery then found one 95-entry array containing the same image-name set, with a different order. The selected Assembly-CSharp module is at native array index 6, while the original metadata image index is 3. The published checker validates the declared count/full range and selected pointer; the exploratory whole-name-set finding is not a claim that all 95 module structures were validated.

The new record hashes a 136-byte x64 v39 code-registration structure, validates its final count/pointer pair and binds the selected array entry to the previously checked module prefix. A selected RIP-relative address encoding resolves to this structure inside a hashed, PE exception-bounded native body. The body has no asserted exported identity or complete semantic review. An initial reference probe incorrectly required subsequent store destinations to have file-backed bytes and failed with an unmapped-range error; virtual-section-only destinations were then recorded as such. The checker does not claim those stores were executed or inspect process memory. Failed probes remain preserved locally.

Seven added portable regression methods use fictional bytes and cover different metadata/native ordering, profile prerequisites, hash/count/table-pointer mismatches, full-array bounds and selected targets, hashed/bounded address references, original image-count identity and research/history pins. All 33 related regressions passed. All five installed-source invocations passed; the newest adds one metadata image-count, registration-structure, selected module-entry and address-reference check to the prior scope. A controlled claim substituting metadata image index 3 for native module index 6 was rejected. The preceding checker ignored the unsupported registration section; it did not claim that validation.

The full sequential Python run passed 336 of 337 tests in 30.314 s including discovery, with the existing Windows symlink-privilege skip and unchanged tested source hashes. Actual loopback HTTP confirms the new research version remains quarantined, all six research versions are explicit and ten exact replays work after Profile and Knowledge stop. The prior 26 byte-protected artifacts remain unchanged; the manifest only appends the new pack. Frontend, OCR, evaluator, storage and Rust behavior are unchanged, so preceding frontend/27-component/32-card/10-Rust evidence retains its original scope. No new browser interaction or complete Tauri/NSIS build was performed.

The final read-only snapshot found no matching controlled process signatures, with 5,138 MiB available memory and 85% committed bytes. This is a point-in-time observation, not a leak, latency or release benchmark. Per user direction, local progress does not depend on named-owner/reviewer assignments. Actual executed registration, class-vtable dispatch, complete event/ownership coverage and online mechanics still lack evidence; M1 remains unaccepted. At that stage, the full native rebuild was deferred; the current MVP build is recorded below. The two-clean-machine gate remains unpassed. Rollback selects an older explicit research version with its original scope; older checkers do not validate the new registration sections.

## Delivered Windows MVP and capture-source clock

The delivered Windows x64 MVP at source commit `fcc9ed1`, its release host, frozen Python 3.12.14 services and NSIS installer were generated on 2026-10-04 UTC. The installer is 225,902,968 bytes (215.44 MiB), with SHA-256 `c40abc84f1dae4a282be2b37a58373746a04885efad88a596e0923289fbf27ab`. Host SHA-256: `a1f4e90e94e1f33a697374488ac4858dfb254dc5c43947b59754e7762ac46728`; sidecar integrity-manifest SHA-256: `d462cc2f0d0ee456e74a8379e13088da8657ce74f79c0b5706465adb200f23ff`. The package embeds Python, that source revision's frontend assets and the configured offline WebView2 installer. Subsequent hidden-verification source and Rust-only host builds are separate artifacts and have not replaced this installer.

The single-job build completed. Its broad worktree guard initially reported a changed file set: investigation found only two newly generated Tauri command permission files, exactly matching the commands declared in the existing build script; no pre-existing source bytes changed. All 29 protected historical artifacts, including the knowledge index, remain byte-identical. The new permission files are retained with the source.

The actual release host passed two headless start/exit cycles with Python absent from the child's PATH, local API authorization, persistent replay, cross-entry single-instance ownership, active-backup rejection, native backup/restore, all six worker faults, forced-host job cleanup and restart recovery. The two recorded readiness times were 7.9091 and 2.9827 s; maximum measured headless working set was 206.51 MiB and private commit 125.65 MiB. These are a small developer-machine sample with warm OS caches, excluding WebView, and do not satisfy the 20-cycle/two-clean-environment gate.

A separate packaged check verified atomic rejection of mismatched capture evidence, corrected retry using the same request ID, evaluation/replay and exact correspondence of served HTML/JS/CSS to the current production build. Its first private probe used a nonexistent fixture field and failed before confirmation; the corrected probe passed without changing product source. The original failure record remains preserved. All owned workers exited after these checks.

Profile now compares every evidence record linked to its original observation against a known native capture millisecond, with exact timezone-equivalent UTC equality. It rejects mismatches before writing or consuming the confirmation ID. Missing historical clocks remain unguessed, separately dated evidence stays separate, and stored revision bytes/hashes are preserved. Old incompatible or unavailable provenance blocks new evaluations while cached history and frozen replay remain readable. Evaluator 0.1.4 is unchanged. The UI displays the source UTC time and requires the user to review the evidence time; it does not rewrite historical facts. Nine unit cases, two real HTTP cases and 14 direct component checks passed. The initial evaluation-render launch lacked an available default Python command; using the explicit harness interpreter passed all 32 cards.

Visible GUI and successful real-window capture IPC, installed OCR on real game layouts, real Deskrawl mechanics and two-clean-machine offline install/removal remain unaccepted. These MVP checks used no mouse/keyboard or game input automation. GitHub Actions has not been run for this change.

## Hidden native verification

A separate Rust-only release host was built with `--hidden-ui`: the verification window is invisible, initially unfocused and nonfocusable. Host SHA-256: `0077d12cffe477de545fa162871281e8401bf60c4e1a052b59b577dd1bc83769` (10,932,736 bytes). The frozen services, frontend and delivered MVP installer retain their prior identities. The verifier rejects the known old host before creating output or starting it. A first successful compile lacked the contiguous short argument literal after optimization and was safely rejected before launch; the final build has a stable hidden-mode diagnostic marker. Exact source/host identities accompany the private records; a binary marker alone is not proof of arbitrary executable behavior.

The final normal verifier completed 20 sequential fresh-profile start/close cycles in 174.931 s. Each cycle checked frozen frontend DOM readiness, URL/session cleanup, capture authorization and zero-dimension rejection, passive Deskrawl metadata/binding guards, and that the owned native window was hidden and nonforeground at readiness and closure. No keys, clicks, focus changes, screenshots or desktop/game pixels were sent or read. The probe now explicitly disconnects its own CDP transport before native window closure; it does not terminate the native browser. All 20 probe reports confirm disconnection, and all 380 observed host/descendant handles confirm natural exit and close. Per-run natural-exit and cleanup records contain only this test's owned process identities.

Measured hidden WebView readiness P95 was 8.5476 s; maximum aggregate idle working set was 643.87 MiB and private commit 377.14 MiB. The installed WebView2 runtime was 154.0.4258.53 on the developer Windows host. These samples use warm OS caches, include test-client startup, and may double-count shared working-set pages. Hidden DOM readiness does not establish visible painting, visible GUI cold-start P95, keyboard accessibility, positive real-window capture, installed OCR on game layouts, or two-clean-machine distribution acceptance.

The first hidden cohort passed its first four complete cycles; its fifth passive IPC probe also passed, but an observed descendant exceeded the unchanged eight-second natural-exit deadline. The test failed and cleaned up its own remaining handles. That original failure is retained. An unchanged diagnostic verifier then passed 20 cycles without a missed deadline; the final verifier adds explicit client disconnection and per-process exit evidence and also passes 20. The specific initial survivor and root cause were not established. Neither successful rerun is presented as proof that the initial timeout was fixed, and repeatable shutdown acceptance remains open. The deadlines and coverage assertions were not relaxed.

Python domain/frontend code, the capture/window/supervisor modules, evaluator 0.1.4 and all 29 protected historical artifacts are unchanged. Rust compilation/format checks, Python harness parsing, Node syntax, architecture and public-document checks pass; forbidden interactive probe modes and the delivered old host reject before connecting or launching. Visible GUI and keyboard cases require manual acceptance. Remote CI has not run for this tree.

## Earlier desktop build

Windows 11 build 10.0.26300, AMD Ryzen 9 5900X, 24 logical processors; WebView2 154.0.4258.53. Harnesses used Python 3.12.14 and Node 24.19.0. Frozen workers ran with a Windows-only PATH and no separately installed Python dependency.

| Earlier scope | Result | Limit |
| --- | --- | --- |
| Rust headless host, 20 start/exit cycles and worker/host faults | Passed; readiness P95 3.4799 s; maximum working set 209.14 MiB; private commit 126.08 MiB | Excludes WebView; predates current window and native maintenance changes |
| Genuine Tauri WebView, 20 fresh-profile start/close cycles | Passed; measured readiness P95 10.9699 s; maximum working set 694.76 MiB; private commit 559.07 MiB | Installed WebView and warm OS caches; includes test-client startup; predates window commands |
| NSIS with embedded Python and offline WebView installer | Generated locally | Not installed/uninstalled on two clean environments; current source changes are not included |

Earlier host identities: headless SHA-256 `85668fce0000ab6bc0a9ff8b69868a17ac89c6199f902e698ec4825053e70f79`; GUI SHA-256 `e47c82bd69c441e9bc453ec43871367bbc32496c18e3827e1d052bee042a0ec1`. Build directory paths and private readiness messages are not published. Path-remapping is configured for future Rust builds; the previously generated executable must not be treated as an accepted distribution artifact.

The headless harness additionally covers cross-entry instance ownership and native backup/restore. The delivered MVP host passes those checks; later native verification uses a separate hidden/passive host, while visible GUI and successful window capture remain unaccepted. GitHub Actions is configured but has not been run for this working tree.

## OCR holdout-v6 (archived)

The parser was frozen before generating independent `holdout-v6`, dataset version `synthetic-critical-fields-v6`: 200 synthetic regions and 600 critical fields across two languages × five scales × four quality conditions. Truth SHA-256: `8b1948c474dc028f2f99c83ae5be36fe02db41b116d6a1e59f531984f4880b21`; domain SHA-256: `cd3868433f60eb6e4676c43cf0badb147b7e708fc9118cf4ed60cf234bfc9b87`; generator SHA-256: `1d371e6fb38c46742f3688717e9ac7bde23ea12ca08b2b0948f5acbac8734a37`. Native OCR/PowerShell and input dimensions are unchanged. No v6 BMP hash overlaps the v1 tuning set or holdouts v1–v5.

| Measure | Observation |
| --- | --- |
| Overall exact field accuracy | 550/600, 91.6667% |
| Missing or rejected | 50/600, 8.3333% |
| Incorrect, not flagged ambiguous | 0/600, 0% |
| Request latency P50 / P95 | 0.852041050005937 s / 0.903408699989086 s |
| Total measurement time | 171.86850919999415 s |
| Accuracy target | At least 95%; not met (M2 remains No-go) |
| Latency target | At most 3 s; met on this developer host |

| Language | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| en-US | 298/300 (99.3333%) | 2/300 (0.6667%) | 0/300 |
| zh-Hans-CN | 252/300 (84%) | 48/300 (16%) | 0/300 |

| Scale | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| 0.75 | 112/120 (93.3333%) | 8/120 (6.6667%) | 0/120 |
| 1.0 | 109/120 (90.8333%) | 11/120 (9.1667%) | 0/120 |
| 1.25 | 108/120 (90%) | 12/120 (10%) | 0/120 |
| 1.5 | 113/120 (94.1667%) | 7/120 (5.8333%) | 0/120 |
| 2.0 | 108/120 (90%) | 12/120 (10%) | 0/120 |

| Quality | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| clean | 133/150 (88.6667%) | 17/150 (11.3333%) | 0/150 |
| low_contrast | 138/150 (92%) | 12/150 (8%) | 0/150 |
| blurred | 144/150 (96%) | 6/150 (4%) | 0/150 |
| downsampled | 135/150 (90%) | 15/150 (10%) | 0/150 |

Missing and rejected values count as incorrect. These three generic fields are not game screenshots or real-game OCR evidence. All 200 input hashes, 600 scoring rows, 598 parsed raw-text spans, grouped totals and latency percentiles were mechanically checked against the archived report; the sealed files were not changed. Twelve regions (36 fields) were visually spot-checked by Codex against rendered values, signs and units. Full independent human ground-truth review remains pending. Exit code 1 means that a measured target was missed; there were no OCR worker errors. Different holdout seeds and parser versions are not controlled accuracy comparisons.

The current parser keeps within-line fields bound to their original lines and associates separate label/value lines only by mutually unique native row geometry. Competing labels, multiple values, unknown same-row text, invalid/Boolean bounds and missing geometry prevent association. Value text/span and `label_source` text/span remain separate original evidence. English numeric reading never supplies field identity; a label-only level can use an uncontested standalone English number on the same row to its right. Primary signs, explicit units and ambiguity checks remain in force. Thirty-six directed OCR tests passed; the new cases failed before the change.

A paired replay on the same 200 v1 tuning inputs and identical native outputs changed 550/600 to 556/600, with six improved and zero lost fields, missing/rejected decreasing from 49 to 43, and one unflagged error remaining. Five fields used separate label/value rows. This is tuning-only and supplies no new native timing or acceptance. The independent v6 holdout emitted no `label_source` fields; it does not independently exercise the split-row path. A separate paired native inversion experiment on 41 tuning regions/123 fields changed 109 to 108 correct (zero improved, one lost, one unflagged in both); inversion was not adopted.

The benchmark defaults to `.local/ocr-holdout-v7`. Dataset version `synthetic-critical-fields-v7` is a label, not a child directory. Nonempty output directories are rejected, adapter bytes are frozen before generation and drift is checked after measurement. A new output directory alone does not change the seed; independent evaluation requires a frozen algorithm and previously unviewed dataset version/seed. The archived v6 result above retains its original source, seed and timing.

## Previous OCR holdout-v5 (archived)

The parser was frozen before generating independent `holdout-v5`, dataset version `synthetic-critical-fields-v5`: 200 synthetic regions and 600 critical fields across two languages × five scales × four quality conditions. Truth SHA-256: `ef956b7779141ed9071b8e13d223c4c7f21df034bd8d5c19f68d829a774ab785`; domain SHA-256: `53cc0c4886fcb8e9dd24c48b76f3f64eace3487cd3a9d68b51d517ca6a8271be`. Native OCR/PowerShell and input dimensions are unchanged. The v5 BMPs do not overlap v3 or the v1 tuning set.

| Measure | Observation |
| --- | --- |
| Overall exact field accuracy | 549/600, 91.5% |
| Missing or rejected | 51/600, 8.5% |
| Incorrect, not flagged ambiguous | 0/600, 0% |
| Request latency P50 / P95 | 0.8637886500073364 s / 0.9114356000209227 s |
| Total measurement time | 174.59557510001468 s |
| Accuracy target | At least 95%; not met (M2 remains No-go) |
| Latency target | At most 3 s; met on this developer host |

| Language | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| en-US | 296/300 (98.6667%) | 4/300 (1.3333%) | 0/300 |
| zh-Hans-CN | 253/300 (84.3333%) | 47/300 (15.6667%) | 0/300 |

| Scale | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| 0.75 | 108/120 (90%) | 12/120 (10%) | 0/120 |
| 1.0 | 107/120 (89.1667%) | 13/120 (10.8333%) | 0/120 |
| 1.25 | 112/120 (93.3333%) | 8/120 (6.6667%) | 0/120 |
| 1.5 | 110/120 (91.6667%) | 10/120 (8.3333%) | 0/120 |
| 2.0 | 112/120 (93.3333%) | 8/120 (6.6667%) | 0/120 |

| Quality | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| clean | 141/150 (94%) | 9/150 (6%) | 0/150 |
| low_contrast | 124/150 (82.6667%) | 26/150 (17.3333%) | 0/150 |
| blurred | 146/150 (97.3333%) | 4/150 (2.6667%) | 0/150 |
| downsampled | 138/150 (92%) | 12/150 (8%) | 0/150 |

Missing and rejected values count as incorrect in the denominator. The three manually generated generic fields are not game screenshots or evidence of real-game OCR accuracy; all observations remain subject to human confirmation. Twelve regions (36 fields) were visually spot-checked by Codex against the rendered values, signs and units; this limited check does not replace full independent human ground-truth review, which remains pending. The benchmark returns exit code 1 when a target is missed; this is not a worker crash.

The v5 parser mapped native OCR line text back to original raw text and recorded global spans. Parsed fields stayed bound to their source line; duplicate fields across lines were ambiguous. Unmappable line text was skipped, preventing reproduced cross-row value assignments. Three regression methods reproduced six failing subcases before that line-binding fix; a positive duplicate/span case passed. That change alone did not claim a controlled OCR accuracy improvement.

The earlier unintegrated cropping experiment on 20 Chinese tuning regions/60 fields, balanced over five scales and four qualities, changed 48 to 51 correct (four improved, one lost and zero unflagged in both); its extra experimental subprocesses did not measure product latency. The earlier line-binding-only parser replay on the same 200 v1 tuning inputs and identical native outputs remained 550/600, with zero improved/lost, 49 rejected and one unflagged in both. These examined tuning results are not acceptance evidence.

## Previous OCR holdout-v4 (archived)

The parser was frozen before generating independent `holdout-v4`: 200 synthetic regions and 600 critical fields, with two languages × five scales × four quality conditions. Truth SHA-256: `28cf2e0fd8b313a83e8b0fb8d694f623e0d9a03db3f595a3352a9a84f4ae955a`; domain SHA-256: `251fb8efd0c131498db19d154c1a3c9e8e9b758afa543fa99d0c3cea4ead31a9`. The native OCR/PowerShell measurement path and input dimensions are unchanged. No input BMP hash overlaps v3 or the v1 tuning set.

| Measure | Observation |
| --- | --- |
| Overall exact field accuracy | 550/600, 91.6667% |
| Missing or rejected | 50/600, 8.3333% |
| Incorrect, not flagged ambiguous | 0/600, 0% |
| Request latency P50 / P95 | 0.8631859000015538 s / 0.9170031999819912 s |
| Total measurement time | 174.13030319998506 s |
| Accuracy target | At least 95%; not met (M2 remains No-go) |
| Latency target | At most 3 s; met on this developer host |

| Language | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| en-US | 296/300 (98.6667%) | 4/300 (1.3333%) | 0/300 (0%) |
| zh-Hans-CN | 254/300 (84.6667%) | 46/300 (15.3333%) | 0/300 (0%) |

| Scale | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| 0.75 | 108/120 (90%) | 12/120 (10%) | 0/120 |
| 1.0 | 108/120 (90%) | 12/120 (10%) | 0/120 |
| 1.25 | 111/120 (92.5%) | 9/120 (7.5%) | 0/120 |
| 1.5 | 110/120 (91.6667%) | 10/120 (8.3333%) | 0/120 |
| 2.0 | 113/120 (94.1667%) | 7/120 (5.8333%) | 0/120 |

| Quality | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| clean | 142/150 (94.6667%) | 8/150 (5.3333%) | 0/150 |
| low_contrast | 129/150 (86%) | 21/150 (14%) | 0/150 |
| blurred | 144/150 (96%) | 6/150 (4%) | 0/150 |
| downsampled | 135/150 (90%) | 15/150 (10%) | 0/150 |

Missing and rejected fields remain in the denominator. These are manually rendered generic fields, not game screenshots or a measure of actual-game accuracy; all OCR observations still require human confirmation. Twelve selected regions were visually checked against renderer text, while full independent ground-truth review remains pending. The benchmark exit code 1 reports a missed target, not a worker crash.

The parser fix rejects spaced decimal fragments in primary and English numeric parsing. A whole unreadable primary lexeme with an explicit known unit can be reviewed against the independent English number. Original text and span are preserved; a readable primary value/sign remains the source, disagreement remains ambiguous, and manual confirmation is required. Three regression methods reproduced nine failing subcases before the fix.

A separate tuning-only paired study used the same 200 original v1 BMPs and identical native OCR outputs: frozen baseline 529/600, current parser 550/600, 21 improved, zero lost, one unflagged error unchanged, and missing/rejected fields 70→49. This is tuning evidence, not acceptance. It is separate from v4. The generator refuses nonempty output directories, captures adapter source bytes before generation, and defaults to `.local/ocr-holdout-v4` (dataset version `synthetic-critical-fields-v4`); a new directory alone does not change the seed. Independent acceptance requires a frozen algorithm and a previously unviewed dataset version/seed.

## Previous OCR holdout-v3 (archived)

The then-current parser was frozen before generating independent `holdout-v3`: 200 synthetic regions and 600 labeled critical fields across English/Chinese, five scales and four quality conditions. Truth SHA-256: `4c18a5cb24ca9dfd321a4844e34d2765538788bff6da85796fefc2228ed80aa8`. Adapter domain SHA-256: `ab14615747e5347dcb36458e52b668f43a70f85a17a62d8381ac85bcbecc5715`. The native OCR script and original input dimensions are unchanged.

| Measure | Observation |
| --- | --- |
| Overall exact field accuracy | 526/600, 87.6667% |
| Missing or rejected | 72/600, 12% |
| Incorrect, not flagged ambiguous | 2/600, 0.3333% |
| Request latency P95 | 0.9111881 s |
| Accuracy target | At least 95%; not met |
| Latency target | At most 3 s; met on this developer host |

| Language | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| en-US | 298/300 (99.33%) | 2/300 (0.67%) | 0/300 (0.00%) |
| zh-Hans-CN | 228/300 (76.00%) | 70/300 (23.33%) | 2/300 (0.67%) |

| Scale | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| 0.75 | 107/120 (89.17%) | 13/120 (10.83%) | 0/120 (0.00%) |
| 1.0 | 103/120 (85.83%) | 17/120 (14.17%) | 0/120 (0.00%) |
| 1.25 | 107/120 (89.17%) | 13/120 (10.83%) | 0/120 (0.00%) |
| 1.5 | 106/120 (88.33%) | 12/120 (10.00%) | 2/120 (1.67%) |
| 2.0 | 103/120 (85.83%) | 17/120 (14.17%) | 0/120 (0.00%) |

| Quality | Exact correct | Missing/rejected | Unflagged errors |
| --- | --- | --- | --- |
| clean | 125/150 (83.33%) | 25/150 (16.67%) | 0/150 (0.00%) |
| low_contrast | 127/150 (84.67%) | 22/150 (14.67%) | 1/150 (0.67%) |
| blurred | 142/150 (94.67%) | 8/150 (5.33%) | 0/150 (0.00%) |
| downsampled | 132/150 (88.00%) | 17/150 (11.33%) | 1/150 (0.67%) |

Accuracy includes exact value, sign and unit. Missing and rejected fields stay in the denominator, and all recognized fields require human confirmation. These are three generic synthetic labels, not game screenshots or arbitrary affix/layout coverage. Twelve review-sheet regions were visually spot-checked against renderer inputs; full independent ground-truth review remains open. An examined holdout cannot be reused as independent acceptance evidence after tuning. A new output directory alone does not change the seed.

The parser now rejects fragments of split, malformed or scientific-notation numeric tokens. A legible primary reading retains its sign and source; an agreeing English read is `numeric_corroboration`. Only recovery of an unreadable primary token uses `numeric_source`. The original lexeme and span remain available, explicit primary units are required, and numeric-reader disagreements stay ambiguous. New regression cases reproduced the prior partial-number and provenance failures before the fix.

The dataset generator refuses nonempty output directories before writing images or reports. Each native measurement archives input hashes, actual parsed fields, raw text, line bounds, the English reference and the frozen adapter source. Source drift during measurement is rejected. Native benchmark exit code 1 indicates that its measured targets failed; it is not a crashed OCR worker.

Earlier `holdout-v2` recorded 513/600 (85.5%), English 287/300 (95.6667%), Chinese 226/300 (75.3333%), 80 missing/rejected and 7 unflagged errors, with P95 0.9389323 s. Its truth SHA-256 is `780319d8609f2957327d196a2362f43e2e60389ebd122729474da2eb24cc57cc`. It has a different seed and earlier parser, so the difference from v3 is not a controlled improvement measurement.

A separate, examined v1 tuning experiment paired 40 regions: native original size scored 99/120, while cubic 2x scaling scored 94/120; the scaling change was not adopted. After the parser fixes, the same 40-region subset scored 103/120, and the full 200-region tuning set scored 529/600 (88.1667%). These tuning results are not acceptance evidence.

## Open gates

M1 real Deskrawl mechanics remain research-only. M2 remains unaccepted: v7's overall synthetic numerical targets passed, while Chinese/poorer-quality strata, actual game/layout coverage and independent truth review remain unresolved. M4 remains **No-go**: two clean standard-user Windows environments are unavailable, and offline install/uninstall coverage remains unpassed. Visible GUI/keyboard and successful real-window capture validation, the initial descendant-timeout investigation, path privacy acceptance, signing, independent rights/release review and future schema migration/rollback also remain open. Backup/restore for existing storage v1 is covered by Python regressions; no migration has shipped.

Private player captures, machine reports and development screenshots remain ignored under `.local`. Complete original synthetic v6/v7 records described above are public; they contain no game/player material. Reproduction commands and boundaries are in [implementation](implementation.md), with acceptance requirements in the [roadmap](roadmap.md).
