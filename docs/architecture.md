# Architecture contract

This document defines implementation boundaries for contributors and agents. Read it before changing code, as required by [AGENTS.md](../AGENTS.md). It records the current Rust/Python separation and the procedure for changes.

This contract does not authorize work outside the current task. It does not establish release acceptance.

| Status | Meaning |
| --- | --- |
| Required | Rust + Python, one EXE launch entry on Windows, an FSD frontend, and DDD microservices organized by business capability |
| Implemented | React/TypeScript UI, Tauri/Rust host, separate Python business/OCR processes, local HTTP APIs, independent service storage, and a bundled Python runtime |
| Acceptance incomplete | Real-game mechanics and recommendations, visible native GUI, matching source/artifact evidence, and the complete Windows release checks on two clean machines |
| Experimental | Explicit `--startup-policy on-demand` with owner-controlled service activation, while `eager` remains the default |
| Deferred | Selected-pack loading, persistent OCR helpers, and production JavaScript splitting in the [performance plan](performance-plan.md) |

The [design](design.md) defines product requirements and evidence requirements. The [implementation reference](implementation.md) describes source behavior. The [roadmap](roadmap.md) defines acceptance conditions. The [validation record](validation.md) preserves dated results.

A test result applies to its recorded source or artifact. An older installer cannot establish acceptance of changed source.

## Ownership by component and file

Rust owns native desktop operations and the lifetime of desktop service processes. Python owns business decisions, persistent domain data, OCR control, and research tools. Each business capability has its own API, model, and data owner.

| Owner and source | Owns | Must not own |
| --- | --- | --- |
| Frontend: [frontend/src](../frontend/src/) | FSD presentation, input editing, explicit confirmation, workflow composition, and display of service results | Game formulas, equipment verdicts, service processes, or direct database access |
| Rust host: [main.rs](../desktop/src/main.rs), [supervisor.rs](../desktop/src/supervisor.rs) | Desktop entry, portable paths, session credentials, instance lock, bundle integrity, service startup/readiness, and bounded process cleanup | Game rules, OCR field interpretation, domain storage, or a second evaluator |
| Rust capture: [capture.rs](../desktop/src/capture.rs), [game_window.rs](../desktop/src/game_window.rs) | Region/window selection, passive OS metadata checks, capture geometry, and source information | Game-memory access, gameplay control, verified game-build inference, or confirmed item facts |
| Python OCR: [services/ocr](../services/ocr/) | Private captures, bounded Windows OCR helper calls, raw text/regions, and unconfirmed observations | Profile confirmation, item value, or game rules |
| Python Profile: [services/profile](../services/profile/) | Local API observations, descriptive observation summaries, confirmed item/build/inventory facts, revisions, and `profile.sqlite3` | Pack changes, equipment recommendations, route rankings, or another service's database |
| Python GameKnowledge: [services/knowledge](../services/knowledge/) | Immutable packs with explicit game scope, evidence, validation, pack index, and content hashes | Player-owned item instances, Profile revisions, or invented rules |
| Python EquipmentEvaluation: [services/evaluation](../services/evaluation/) | Complete-build comparison, eligibility/retention explanations, evaluator versions, frozen replay, and `evaluation.sqlite3` | Profile changes, published pack changes, or assumed mechanics |
| Python AcquisitionPlanning: [services/planning](../services/planning/) | Measured XP/time trials, source prerequisites, sample estimates, and `planning.sqlite3` | Evaluation ownership, raw weights as drop probabilities, or an unmeasured global optimum |
| Python gateway: [gateway.py](../gateway.py) | Authenticated routing, frontend assets, service status, and requests to the runtime owner | Domain calculations, confirmation decisions, database reads, or desktop service supervision |
| Python tooling: [scripts](../scripts/) | Reproduction, evidence checks, build/validation tools, and the native OCR helper | Product workflows that bypass service APIs or claims of validated mechanics from extraction alone |

Python uses the standard library and installed Windows capabilities at runtime. Prefer these facilities to new dependencies. Build tools have separate dependencies. The [development guide](development.md) describes their requirements.

### Shared infrastructure and exceptions

- [contracts.py](../contracts.py) defines wire fields, identifiers, serialization, hashes, and error categories. Keep business models and game formulas in their owning service.
- [transport.py](../transport.py), [storage.py](../storage.py), and [process_lifecycle.py](../process_lifecycle.py) supply HTTP, storage operations, and cleanup of helper processes. They do not grant access to another service's data.
- [runtime_control.py](../runtime_control.py) defines bounded `status` and `ensure` operations for the gateway. Desktop control uses versioned inherited pipes. Development uses the same owner interface in process. Business decisions remain in their services.
- Each service's `domain.py` contains business rules. Keep HTTP, SQLite, and subprocess I/O out of domain code. Put API handling, storage access, and permitted clients in `app.py`. Apply the same restrictions to extracted domain modules.
- [service.py](../service.py) selects one capability per process and supplies its clients. It may import service entry points for this purpose. Business services must not import each other's implementation.
- [runtime.py](../runtime.py) supplies the development browser launcher and frozen CLI dispatch. The installed desktop uses Rust supervision directly. Do not run the development launcher as a second supervisor beneath Rust.
- [maintenance.py](../maintenance.py) supplies offline backup and restore. Backup holds the instance lock and copies validated databases and private captures. Restore validates the backup and writes to a new destination. Never overwrite existing state. This exception does not permit online queries or changes across service databases.

Python may use OS facilities for OCR, helper cleanup, and maintenance. Rust may validate transport and lifecycle data. These operations do not transfer ownership of business facts.

## Permitted communication

| Caller | Callee and mechanism | Boundary |
| --- | --- | --- |
| Frontend | Rust Tauri commands | Authorized capture and window detection with source information, without equipment decisions |
| Frontend | Gateway `/api/{service}/...` | Authenticated JSON requests to the owning service, without direct storage or domain calls |
| Gateway | Profile, Knowledge, Evaluation, Planning, OCR `/v1/...` | Request forwarding and health reporting that preserve service results and errors |
| Gateway | Runtime owner through [runtime_control.py](../runtime_control.py) | Status and allowlisted service activation, while Rust owns desktop processes |
| Evaluation | Profile and Knowledge `/v1/...` | Read an explicit Profile revision and pack version/hash, then save frozen copies in Evaluation storage |
| Planning | Knowledge `/v1/...` | Read versioned source/eligibility evidence, while Planning owns trials and samples |
| Rust supervisor | Frozen Python entry points | CLI/environment configuration, private readiness pipes, authenticated health checks, and process lifetime |
| OCR | [windows_ocr.ps1](../scripts/windows_ocr.ps1) | Bounded Windows recognition inside the OCR process scope, without confirmation or game rules |
| Owned producer or frontend | Gateway → Profile `POST /v1/live/samples` | Authenticated observation input, without automatic confirmation or new network listeners |

Profile, Knowledge, and OCR do not call other business services. Do not read another owner's database or pack directory. Evaluation and Planning obtain packs through Knowledge.

Business services run in separate processes and use HTTP APIs. The Rust host does not use PyO3 or an embedded Python interpreter. Services do not share business objects or a message bus. Follow the change procedure before adding such a mechanism.

The data flow is capture/manual input → observation → user confirmation → Profile revision → compatible KnowledgePack → pinned Evaluation request → explanation/replay.

The UI submits these steps. OCR and the gateway must not promote observations to confirmed facts. Planning has a separate workflow.

### Owned live API input

Profile owns the `lootweave-live/1` model, validation, descriptive summaries, observation storage, and draft conversion.
Producers and the frontend call Profile through the existing authenticated gateway. Profile makes no outbound request for live observations.
The [protocol guide](live-api.md) defines the input contract. The API does not automatically obtain game data.

Rust retains native capture, desktop operations, and service lifetime. Python retains validation, statistics, and storage.
React presents results and manages explicit review. No extra listener, supervisor, interpreter embedding, or foreign database access is introduced.

Profile owns separate sample and frozen-preview caches. Each retains at most 16 entries and eight MiB for 600 seconds.
These bounds describe encoded cache content, not total process memory. Sample publication and polling do not write SQLite.
Draft conversion saves the frozen source observation. Explicit confirmation creates a normal revision with existing replay pins.

The read response can omit unchanged values after a content-hash check. Ten views share one observation.
Python describes supplied events and records. Planning still owns accepted trials, comparable outcomes, and route analysis.
Source estimates and future previews remain separate from confirmed build facts. Missing data remains unknown.

The producer declares game context and field units. Only held equipment can become a candidate.
Future drops and unopened chest contents cannot establish ownership. Source time, class, context, and draft hashes bind confirmation.
Later samples cannot replace a selected draft or earlier confirmed revision. The frontend checks source ID and hash before loading a draft.

The owned API replaces earlier external connection routes. Port and pairing-token fields are rejected.
Storage version 1 remains unchanged. Historical observations and revisions retain their original bytes and evidence support.

Rollback must retain support for `live_api_confirmation` where those revisions exist. Older services cannot validate that evidence kind.
Tests cover authentication, bounded input, source ordering, context binding, unknown statistics, duplicate instances, immutable previews, and confirmation retries.

### Wire and data rules

1. Keep service endpoints under `/v1/`. Check contract versions. The readiness envelope contains `service`, `url`, and `contract_version`. It is separate from business responses. Reject incompatible versions. Define compatibility for all producers and consumers before changing a contract.
2. Bind APIs to literal loopback. Require the launch credential on private requests. Validate Host/Origin. Bound request sizes and timeouts. Keep internal clients free of outbound proxies and redirects. Exclude credentials, complete private inputs, and screenshots from normal logs.
3. Exchange JSON data and stable error categories. Do not exchange language objects or use database schemas as service contracts. Reject duplicate JSON keys and non-finite numbers. Validate signs, units, and integer bounds as specified by each field. UI validation does not replace service validation.
4. Carry explicit context fields: `game_id`, `edition`, `game_build`, `mode`, `season`, `ruleset_id`, and content entitlements. Unknown or incompatible contexts must not select the latest pack automatically. A process/window identity does not verify this context.
5. Keep observations, confirmed facts, and results separate. Profile owns revision checks and confirmation idempotency. Evaluation and Planning own their request identities and conflict checks. Retries must not duplicate writes or reinterpret historical records.
6. Preserve the Evaluation pins: context, Profile revision/facts hash, candidate instance, intent revision/hash, pack version/hash, and evaluator version. Frozen inputs and result integrity permit replay without Profile or Knowledge online. Report a missing historical engine explicitly. New behavior must not rewrite prior results.
7. Keep rule definitions and evidence in Knowledge. Keep evaluation algorithms and historical engine selection in Evaluation. Keep planning calculations in Planning. Each rule or algorithm has one owner per version. Frozen replay copies and historical engines are intentional. Do not add competing implementations in Rust, UI, or gateway.

Preserve active/inactive/unknown condition states. Unknown inputs must block unsupported conclusions. Static templates are not owned items. Raw field differences do not establish DPS.

Deskrawl remains the first research target. Real-game acceptance is incomplete. Diablo II, III, and IV need separate adapters and evidence. The [design](design.md#core-data) defines the complete data rules.

## Desktop lifecycle and distribution

Rust uses `eager` startup by default. It starts Profile, Knowledge, Evaluation, Planning, OCR, and then the gateway. Explicit `--startup-policy on-demand` starts the gateway first. It starts Profile and Knowledge concurrently, followed by Evaluation. OCR and Planning start on an explicit capability request.

Both launchers implement this experiment. The [recorded comparison](performance-results.md) failed the primary startup-tail condition. The default therefore remains `eager`. Shell readiness does not establish core readiness or visible GUI acceptance.

The gateway sends bounded `status` and `ensure` operations to the runtime owner. Desktop control uses versioned inherited pipes to Rust. Development uses the owner interface in process. Status reads must not start dormant services.

Preserve startup-attempt generations and dependency generations. Invalidate affected routes after a dependency fails or changes. Explicit recovery must bind the current dependency generations. An existing Evaluation worker may retain access to frozen records during an upstream fault. Restrict that access to the permitted collection, detail, and replay routes.

Do not accept new evaluations through a historical-only worker. Do not retry dispatched business writes automatically. Reject new starts during shutdown. Retain ownership of incomplete children until cleanup finishes.

On Windows, Rust assigns each child to its outer Job Object before it permits business/OCR initialization. With `LOOTWEAVE_PARENT_JOB=1`, [service.py](../service.py) waits for the one-byte stdin permit. Python then establishes its nested service job before it initializes helpers.

Missing permits or ownership failures must publish no readiness. The gateway belongs to the host's outer job. It does not consume the service permit.

Rust owns startup, readiness validation, shutdown deadlines, and forced cleanup of its process tree. Python owns helpers within each service lifetime. Preserve cleanup after parent-pipe closure, startup failure, worker termination, and host faults. Stop only owned processes. Report recovery failures or unavailable services explicitly.

The development launcher creates independent service roots. It clears the desktop-parent flag. This development behavior does not transfer desktop supervision to Python.

One EXE is the user's launch entry. It does not require one process or one physical file. Both the NSIS installer and portable ZIP include a frozen Python directory runtime. Users must not need a separate Python installation.

The Rust host detects the portable marker and selects adjacent `sidecar/`, `webview2/`, and `data/` directories. The portable ZIP includes a fixed WebView2 runtime. The installer retains its regular application-data location. Choosing a directory does not give Rust ownership of domain database contents.

One distribution packages a compatible set of services. Each service retains its own API and storage. This packaging does not establish remote deployment or independent live upgrades.

Bundle hashes detect corruption. They do not authenticate the publisher. The [M4 conditions](roadmap.md#m4-one-entry-exe-and-local-lifecycle) require separate release evidence. This includes dependency rights, signing, offline WebView2 behavior, rollback, visible GUI, keyboard accessibility, and installation/removal on two clean machines.

Reject incompatible storage versions. Do not let an old service read a newer incompatible database during rollback. Tauri remains the selected host unless an authorized task changes that choice. A failed packaging gate can reopen the host decision. Any replacement must preserve Rust/Python, FSD, microservices, and the EXE entry.

Do not access player saves. Do not modify game files. Do not inject into games. Do not read process memory or DMA.

Do not control gameplay. Do not dispose of items automatically. Process data locally by default. Any future sharing needs a user-directed task and a privacy design.

## Frontend boundary

Use FSD layers only when needed: `app / pages / widgets / features / entities / shared`. Import lower slices through their public APIs. Do not import peer slices or higher layers. Compose sibling slices in a higher layer. App/Shared retain their layer exceptions.

Do not create unused slices. Keep game mechanics out of `shared`. The UI may parse input, reject malformed text, manage confirmation, and format service results.

Keep authoritative retention, equip eligibility, route rankings, and game-rule applicability in their business services. Transport types and friendly error messages do not transfer this ownership.

## Procedure for agent changes

1. Before editing, identify the owner, permitted callers, storage owner, affected contract, and intended behavior. Use the tables above. Inspect existing changes. Preserve unrelated work.
2. Put each change in its existing capability. OCR owns parsing corrections. Evaluation owns set-condition comparison. Planning/Knowledge own source prerequisites. Rust owns capture-window guards. Do not split services by language, class, or game.
3. For an authorized boundary change, first update this contract. Identify the reason, affected files/callers, data ownership, compatibility, validation, and rollback. Update the design and roadmap when necessary. Routine work inside these boundaries needs no additional approval. Incidental cleanup does not authorize an architecture change.
4. Before a Python-to-Rust calculation migration, measure the bottleneck. Compare simpler changes within the existing owner. Preserve rule ownership, evidence, pinned versions, and offline replay. Document any native helper as an architecture change. Supply equivalence tests, complete-workflow measurements including communication overhead, and a rollback plan. Do not assume gains from the language choice.
5. Run the baseline and affected checks below. Report commands, results, skipped prerequisites, and remaining unknowns. Do not claim game or release acceptance from documentation, static checks, old binaries, or synthetic fixtures.

Boundary changes include new service calls, IPC/FFI, shared state, ownership transfers, language migrations, and deployment changes. They must belong to the authorized task.

## Enforcement and acceptance evidence

Run these commands from the repository root:

```powershell
python -m unittest discover -s tests -v
python scripts/check_architecture.py
python scripts/check_public_docs.py
python -m compileall -q scripts
```

The [CI workflow](../.github/workflows/checks.yml) runs the architecture checker and repository checks. The architecture checker detects recognized FSD import violations and imports between Python services. It also rejects specified I/O imports in files named `domain.py`. [test_architecture.py](../tests/test_architecture.py) tests these checks.

The checker provides partial coverage. It does not detect business formulas in Rust/frontend code, dynamic imports, transitive I/O, or foreign database paths. It does not prove semantic consistency or payload compatibility. Review changed imports, call sites, storage paths, and rule ownership manually.

| Changed boundary | Required evidence |
| --- | --- |
| Service API, authorization, or storage ownership | Relevant HTTP/storage cases in [test_services.py](../tests/test_services.py) and producer/consumer compatibility tests |
| Rules, confirmation, or evaluator behavior | Affected domain/confirmation tests and pinned replay cases, including [test_history.py](../tests/test_history.py), with unknowns and unsupported scopes still blocked |
| Python supervision or helper lifetime | [test_runtime.py](../tests/test_runtime.py) and [test_process_lifecycle.py](../tests/test_process_lifecycle.py), with platform skips disclosed |
| Rust capture, host, or startup protocol | Matching native checks and rebuilt host/sidecar evidence from the [development guide](development.md#native-windows) |
| Backup/restore | [test_maintenance.py](../tests/test_maintenance.py), including active-instance rejection, unchanged source data, new destinations, and offline replay |
| UI workflow or payload | Frontend build and relevant [component/browser checks](development.md#frontend) |
| Portable paths or packaging | Matching archive-integrity and relocation results from [check_portable_desktop.py](../scripts/check_portable_desktop.py) |
| Performance or distribution | Disclosed environment/inputs, before/after measurements, process cleanup, and the remaining [M4 conditions](roadmap.md#m4-one-entry-exe-and-local-lifecycle) |

Python tests alone do not verify Rust behavior. Import checks alone do not verify UI interaction. Record dated results and artifact identities in the [validation record](validation.md). This contract does not claim that all boundaries or release conditions have passed.
