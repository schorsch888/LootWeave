# Design baseline

The goal is to explain an item's use, replacement, and retention value from its game version, actual rolls, complete build, and intended use. A local development implementation runs with synthetic rules; real-game support and desktop release gates remain unaccepted. See the [implementation record](implementation.md). Publish what readers need to understand, reproduce, validate, and maintain it. Delivery gates are in the [roadmap](roadmap.md).

## Current state and boundaries

| Category | Status |
| --- | --- |
| Locally reported fact | Research reports record parsing and serialized-number validation for 1,593 selected static objects from Deskrawl build `25690430` |
| Evidence limitation | Selected reports and independent tools describe the method and results. Full reproduction requires lawfully obtained matching game files and regenerated intermediates; no bundled source assets or product acceptance claim |
| Requirements | Local Windows product, one EXE launch entry, FSD frontend, DDD backend microservices organized by business capability, Rust + Python; no player-supplied stat weights |
| Implementation | React/TypeScript FSD frontend, Tauri/Rust host and independent Python business/OCR services; synthetic behavior is tested, distribution and game acceptance remain under validation |
| Unknowns | Complete combat formulas, trigger uptime, online overrides, and final drop probabilities; complete serialized fields do not establish complete mechanics |

The first validation scenario is online Deskrawl sorcerer leveling. Static definitions for four classes do not mean recommendations for all four are validated. Diablo II, III, and IV require separate edition, season, version, and mode research; similarly named systems do not share formulas by default.

## Product scope

Text or screenshot observations become confirmed equipment and build facts before evaluation. Outputs are **keep, candidate, low current relevance, or needs confirmation**, with applicability conditions, evidence, and missing inputs. Low current relevance does not imply no other use; keeping an item does not imply equipping it now.

A replacement recomputes the complete configuration: skills, talents, paragon, legendary effects, rune sets, companions, resource cycles, and survival requirements. Until formulas are independently validated, explain mechanism changes without claiming true DPS or percentage improvement.

Acquisition planning can later explain sources, eligibility, prerequisites, and reacquisition difficulty. Compare routes using comparable measured outcomes and complete elapsed time. Raw weights are not final probabilities for a particular item.

For real-time Deskrawl capture, confirm the process and explicitly select its window. Bind the region to the client area and recheck process identity, visibility, minimization, foreground and geometry at capture time. OS process/window metadata is separate from game memory. Game absence or capture failure must preserve text input and historical replay; a detected window does not verify a game version or its rules.

Do not inject into the game, access process memory or DMA, modify game files or player saves, automate gameplay, or sell/dispose of items.

## Core data

| Record | Required facts and invariant |
| --- | --- |
| GameContext | Game, edition/version/season, mode, and available content; unknown versions cannot silently use the latest rules |
| ItemInstance | Actual affix rolls, special effects, upgrades, sockets, embedded items, and unrevealed properties; separate from an item template |
| BuildSnapshot | Skills, talents, paragon, account unlocks, equipment, runes, companions, panel observations, temporary state, revision, and capture time |
| EvaluationIntent | Current/future use, target content, resource/survival requirements, permitted build changes, and budget |
| OwnedOptions | Known inventory, supporting items, materials, and feasible modifications; unscanned inventory is not empty inventory |
| MechanicDefinition | Effect source, actor/target, triggers, conditions, parameters/units, stacking/exclusions, duration, version, and evidence IDs |
| EvidenceRecord | Source/version, capture or extraction method, OCR region/text, player confirmation, verification state, conflicts, and applicability; linked to both rules and input facts |

Conditions use active, inactive, and unknown states. Unknown triggers are not assumed active. Aggregate capability state separately for each actor: any active provider establishes presence; otherwise any unknown provider keeps it unknown; all inactive providers establish absence. An unknown state cannot establish a definite loss, gain or unmet requirement. Show uncertain before/after states with their rule and input sources, and retain blockers until confirmation. Preserve sources for temporary buffs and panel totals; do not add equipment or talent contributions again before attribution is resolved. Unnamed icons, class, unlock level, or the highest elemental panel value cannot establish the actual build.

Store observations, confirmed facts, and derived results separately. Unrecognized affixes, ambiguity, conflicting rules, or unrevealed properties block a definite discard conclusion. Check consistency across capture times. Recognition reliability and mechanic evidence are separate; do not invent uncalibrated confidence percentages.

Each evaluation pins the game context, item/build/intent revisions, knowledge pack, and evaluator version, and retains reason references for replay.

## Local architecture

The FSD frontend, DDD backend microservices, and use of both Rust and Python are requirements. The component breakdown below is implemented; remaining deployment, distribution and game-support gates need validation.

The [architecture contract](architecture.md) defines file ownership, permitted calls, Rust/Python responsibilities, and infrastructure exceptions. It also defines the procedure and checks for boundary changes. Follow that contract for code changes. The table below summarizes component responsibilities.

| Component | Responsibility and boundary |
| --- | --- |
| React/TypeScript + FSD | Confirmation, configuration, and comparison UI; no duplicate game formulas |
| Rust host | Windows capture entry, service startup/health checks, recovery, and shutdown |
| Python OCR worker | Images to regions, original text, and structured observations; no direct authoritative facts or equipment verdicts |
| Profile service | Actual items, character/inventory snapshots, confirmation state, and revisions |
| GameKnowledge service | Versioned mechanics, evidence, adapters, and KnowledgePacks |
| EquipmentEvaluation service | Conditional effects, complete-build comparison, retention reasons, and replay |

Profile, Knowledge, Evaluation and Planning own independent APIs, domain models and storage. They communicate through versioned contracts rather than reading one another's databases. Initial deployment is entirely local under a Rust supervisor; one desktop distribution can bundle independently deployable services. OCR and capture are infrastructure, not class-specific services. Docker/Kubernetes are not required. Planning is a separate context for measured XP/time trials, source eligibility and sample estimates; real-game source adapters remain unaccepted.

Flow: capture → confirm observations → Profile revision → compatible knowledge pack → pinned evaluation request → explanation/comparison. Use revision checks, idempotent writes, and bounded timeouts; failures must not duplicate confirmations or silently change rule versions.

Use FSD layers and slices only when needed. Cross-slice imports target strictly lower layers; compose sibling slices above them, with App/Shared exceptions. A public API does not waive dependency rules. The [official FSD layer reference](https://fsd.how/docs/reference/layers/) supports this structure; scripts/check_architecture.py checks project imports.

Tauri is the implemented Rust desktop host. Its [sidecar documentation](https://v2.tauri.app/develop/sidecar/) covers Python CLI/API binaries built with PyInstaller. The directory bundle embeds CPython and avoids per-worker unpacking. OCR models are installed Windows capabilities. The configured NSIS Setup.exe installs a main EXE that starts local components. Validate WebView2 detection and offline installation; the [official Windows installer reference](https://v2.tauri.app/distribute/windows-installer/) documents NSIS and `offlineInstaller`. Configuration and local checks do not establish a clean-machine release.

Tauri is the current host choice. A failed packaging gate reopens that choice. Remote hosting has no current requirement.

Bind local APIs to loopback and validate session authorization and caller origin; keep credentials out of logs. Handle instance locks, port conflicts, health timeouts, retries, and child-process cleanup. Preserve text confirmation when OCR fails. Validate knowledge-update source, hash, and contract compatibility; back up before storage migrations. Rollback must not let old services read incompatible new storage.

## Runtime performance

The [runtime performance plan](performance-plan.md), [experiment protocol](performance-experiment.md) and [results](performance-results.md) distinguish implementation from acceptance. The default remains sequential `eager` after the candidate failed the predeclared startup-tail comparison. Explicit `--startup-policy on-demand` verifies the bundle, starts Gateway and serves the shell, then starts Profile/Knowledge concurrently and Evaluation after its dependencies; OCR and Planning remain dormant until needed. Status reads never start services. Measured headless idle-memory savings do not establish default-policy, visible-GUI or M4 acceptance.

Gateway requests an allowlisted service through bounded owner `status`/`ensure` operations. The desktop uses versioned inherited pipes; the developer launcher uses the same operations in process. Each attempt has a generation and shared outcome. Evaluation pins Profile/Knowledge generations; Planning pins Knowledge. Failed or replaced dependencies invalidate dependent routes until explicit recovery rebinds them. An already-ready Evaluation worker remains owned for allowlisted frozen collection/detail/replay reads during an upstream fault; it is historical-only and cannot accept new evaluations. Those frozen reads require no dependency start. No dispatched business write is automatically retried. Closing prohibits new starts and retains ownership of incomplete children until cleanup.

The frontend separates shell/demo, catalog and core readiness, gates confirmation/evaluation on their actual dependencies and preserves typed drafts. Secondary panels mount when first opened and remain mounted when hidden. Serialized status polling uses 500 ms during active visible core startup, five seconds after readiness/failure and 30 seconds hidden, with refresh on return. Production code splitting is deferred: an aborted chunk fetch stayed cached as failed on retry, while initial byte savings were small. Selected-pack loading and persistent OCR helpers also require measured justification. The existing M4 budgets and release gates remain unchanged.

## Deskrawl leveling route planning

Measured-route comparison is implemented in Planning; Deskrawl-specific map/entry rules remain unaccepted. Treat map and difficulty as one candidate; combine versioned entry rules with confirmed unlock status. Exclude confirmed inaccessible/unavailable entries; unknown access requires confirmation. Static enemy levels, placeholders, or map counts cannot establish playable routes or XP per minute.

Start with manual trial records. Compare cumulative **actual XP / complete elapsed time** under the same version, mode, character level, build, XP bonuses, and leveling objective. Include movement, waiting, recovery, and deaths. Across comparable trials use total XP divided by total time, retain variation and trial counts, and describe a single trial as such.

Track character and paragon XP separately; do not merge trials spanning their transition. Subtracting XP-bar readings across a level-up is invalid without verified level thresholds; request cumulative gained XP or mark the record uncertain. Reject zero time, negative XP, incompatible settings, or changed bonuses; retain old trials as history when retesting is needed.

With no comparable records, suggest trial candidates. With records, identify only the best **measured candidate**, leave untested maps unranked, and recommend retesting when results are close or unstable. Do not infer a global optimum from static levels or transplant this logic to other games without their own validation.

## Rule evidence and public verification

Rules retain source, applicable version, verification method, conflicts, and invalidation conditions. Distinguish official descriptions, local static fields, reproducible behavior experiments, community explanations, and screenshot inference. Authority does not establish current-version applicability; static configuration does not establish final online behavior.

KnowledgePacks isolate game/version scope, effect conditions, units, stacking, and evidence IDs. Updates create new versions without replacing historical evaluation inputs. Unknown or conflicting rules cannot be filled with assumed formulas.

The [research guide](research.md) must connect selected reports to their prerequisites, commands, expected checks, and limits. Publish enough to reproduce and independently verify each supported conclusion; require matching legal source material rather than bundling it. M1 adds versioned executable rules and public synthetic/sanitized fixtures. A report or source hash alone cannot substitute for reproducibility, and reproducing static fields does not validate a complete combat model.

## Privacy and publication

Retain documents, research scripts, dependency metadata, and selected sanitized evidence that serve understanding, reproduction, verification, or maintenance. Exclude redundant historical drafts and reports that add no unique evidence. There is no fixed publication file count; additions need a clear purpose and content review.

Keep original game resources, full regenerable extraction databases, decompiled intermediates, downloaded tools, and private captures local. Publication rights for third-party content remain separate from access or extraction rights. Link only to included public material and clearly identify any external prerequisites; do not describe private local outputs as publicly accessible evidence.

Published material must contain no personal paths, usernames, machine identifiers, credentials, real character snapshots, private screenshots, or player saves. Future fixtures use synthetic or authorized sanitized data. Logs retain versions, timing, and failure categories rather than complete private inputs. Process locally by default; optional sharing requires a separate design and user choice.

Review actual publication candidates, links, sensitive content, attachments, and redistribution rights. Ignore rules do not remove tracked files or history; automated checks cannot prove the absence of secrets or permission to redistribute. Collaboration rules are in [AGENTS.md](../AGENTS.md). Project code and documentation use [Apache-2.0](../LICENSE); that license does not relicense third-party game content or downloaded tools.
