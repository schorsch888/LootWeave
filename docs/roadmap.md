# Roadmap

The public deliverable is a design and research baseline, including selected evidence records and read-only research tools. This is not a shipped desktop product. **M1–M5 are unimplemented; their case counts, accuracy thresholds and performance budgets are proposed acceptance targets, not measured results.** Product implementation requires explicit authorization. No delivery dates are committed before estimation.

All implementation stages must preserve the FSD frontend, DDD backend microservices organized by business capability, Rust + Python stack, and Windows single-EXE entry point. React/TypeScript, Tauri, the Rust/Python responsibility split, deployment, and packaging remain proposals to validate.

| Stage | Dependencies | Deliverables | Accountable role |
| --- | --- | --- | --- |
| M0: Research and documentation baseline | Lawful source access and version identity | Current-state summary, design boundaries and acceptance plan | Knowledge lead; review by verification lead |
| M1: Reproducible rule pack | M0 boundaries and publishable evidence | First class/scenario pack, knowledge API contract, fixtures and validation record | Knowledge lead |
| M2: Capture and confirmed snapshots | M1 identity, version and observation contracts | Text input, screenshot/OCR confirmation and Profile service | Capture lead, with frontend lead |
| M3: Explainable equipment decisions | M1 rules and M2 confirmed snapshots | Retention reasons, complete-build replacement comparison, evaluation service and replay | Evaluation lead |
| M4: Windows EXE trial | M2/M3 end-to-end flow and service contracts | Bundled installer, Rust process supervision and clean-machine validation | Desktop/release lead |
| M5: Acquisition, leveling and other games | Stable M4 and independently validated capability rules | Acquisition/leveling guidance, statistical estimates and isolated game adapters | Acquisition lead; adapter lead per game |

Assign one named owner and an independent reviewer before starting each stage. M1/M2 work may overlap after their shared contracts stabilize; a minimal packaging feasibility check may start earlier. Each gate record must state scope/version, deliverables, reproducible checks, environment, sample coverage, targets versus observations, failures, unknowns and rollback. Unresolved critical assumptions keep the gate at **No-go**.

## M0: Current baseline

Local research recorded strict parsing of 1,593 selected static objects from Deskrawl build `25690430`, with zero recorded parse errors, and independent conversion checks for 3,080 Float, 67 Int and 196 Long fields. The selection includes 336 ItemData definitions, including non-equipment, 124 AbilityData definitions, including non-player abilities, 185 talents, 119 runes, 13 rune sets and 36 gems. These counts describe definitions, not supported product features. Static XP-penalty branches and their configuration binding were also reviewed locally; server behavior and measured route efficiency remain unresolved.

Selected reports, source identities and read-only tools are public; [research reproduction](research.md) documents their inputs and limits. Game assets, full generated databases and downloaded tools are excluded, so source checks require lawfully available matching game files. The repository ships no product rule pack, OCR flow, equipment evaluator or EXE. Field completeness and numerical conversion do not establish complete mechanics, real item rolls, DPS or final drop probabilities.

**Baseline acceptance:** publish necessary documentation, selective evidence and the research toolchain; check links, privacy, dependency setup and the separation of current facts from future targets. **Go:** prepare M1 contracts and lawful synthetic fixtures. **No-go:** claim source verification without matching inputs, redistribute game resources without authorization, or claim a working application. If the evidence boundary cannot be established, retain only the documented method and limitations.

## M1: Versioned rules and public evidence

Start with one validated Deskrawl online Sorcerer leveling scenario. Deliver a versioned KnowledgePack, GameKnowledge API contract, source mapping, compatibility policy and lawful public fixtures covering skills, talents, paragon, legendary effects, runes, statuses, resources and survival dependencies. Separate templates from actual item instances. Other classes remain unsupported until independently accepted.

**Acceptance targets:** at least 50 domain cases; every executable rule has a version scope and evidence ID. Critical unknown-condition, version-conflict and temporary-buff deduplication cases all pass. Replaying the same locked input 10 times produces identical results.

**Go:** the first scenario has publicly reviewable support, and missing rules prevent unwarranted conclusions. **No-go:** private raw data substitutes for public evidence, or unverified formulas produce DPS or recommendations for unsupported classes. Evidence conflicts or unclear rights require quarantining candidate rules and retaining the previous pack within its original version scope.

## M2: Capture, confirmation and snapshots

Deliver text entry, Windows region capture, an independent OCR worker, original-text/region mapping, confirmation and separately stored Profile revisions. Cover equipment, skills, talents, paragon, runes, companions and observation time. Store observations separately from confirmed facts; unnamed icons cannot establish identity. Capture failure must leave the text path usable.

**Acceptance targets:** at least 200 lawful, publishable synthetic or anonymized screenshot regions in a labeled holdout set excluded from tuning. Critical-field accuracy is at least 95% over **all** labeled critical fields; rejection, missing fields and nonrecognition count as incorrect. Numeric fields must match sign and unit as well as value. Report accuracy, rejection and unflagged-error rates by language, scaling and image quality. Every flagged ambiguity enters confirmation; all 10 cross-time snapshot cases trigger consistency checks. Manual ground truth must also expose errors that OCR failed to flag.

**Go:** users can correct errors and replay confirmed snapshots. **No-go:** guessed values or unconfirmed observations overwrite reliable facts. For layout drift or false acceptance, disable the affected OCR adapter, fall back to text confirmation and preserve previous revisions.

## M3: Retention and complete-build comparison

Deliver the EquipmentEvaluation service, condition resolution, replacement within the same scenario, current/future retention reasons and replay. Recompute skill, legendary, set, resource and survival dependencies for the complete configuration. The frontend follows FSD boundaries; users do not enter affix weights, and the highest elemental panel value cannot establish a build.

**Acceptance targets:** at least 60 domain regressions covering attack/element scope, statuses, effect ownership, legendary effects, set thresholds, resources, survival and future combinations. Every critical unknown blocks a definitive discard conclusion; every recommendation traces to its input and rules. At least 10 replacement cases demonstrate that ordinary stat gains cannot hide a lost set threshold or core mechanic. Ten replays of locked versions and configuration agree.

**Go:** retention and replacement are separately explained for the first scenario. **No-go:** panel totals and their sources are counted twice, conditions are misapplied, or unverified improvement percentages are presented. Disable affected rules, downgrade results to candidates/needs confirmation and rerun relevant regressions before restoring them.

## M4: One-entry EXE and local lifecycle

Validate the proposed Tauri sidecar, Python directory bundle, NSIS installer and offline WebView2 dependencies. The main EXE must start the local services without a separate user-installed Python runtime. A failed minimal packaging check reopens the desktop-host choice.

**Acceptance targets:** install, launch, uninstall and complete the offline core flow on at least two clean Windows x64 environments using standard accounts without preinstalled Python. Test WebView2 present, missing and offline cases. Twenty start/exit cycles leave no orphan processes; each service-crash case offers bounded recovery or explicit degradation. On disclosed hardware, OS, models and inputs: cold-start P95 ≤15 seconds over 20 runs, OCR P95 ≤3 seconds over 100 regions, and total idle memory ≤700 MiB. Budget changes require measured evidence.

Dependency/model rights and integrity, migration backup/rollback, local API authorization, redacted logs and a keyboard-accessible main flow must pass review; status cannot rely on color alone. **Go:** trial only accepted game/class/scenario scopes. **No-go:** developer-machine-only success, missing dependencies or services left running after exit. Roll back to a compatible release and rule pack; old services must not access incompatible new storage.

## M5: Acquisition, leveling and other games

First expose verified sources, eligibility and access requirements, distinguishing rarity, usefulness and replacement difficulty. Define the target event, attempt unit and sampling coverage before reporting estimates; raw weights are not final item-drop probabilities, and average waiting time is not a guaranteed drop.

For Deskrawl leveling, filter candidates using confirmed unlocks and compare cumulative XP actually earned over the complete elapsed time under comparable version, mode, level range, build and buffs. Without comparable measurements, offer trial candidates; “best” means only best among measured candidates, never inferred from static map levels.

**Acceptance targets:** at least 30 source/eligibility cases for the first acquisition adapter. All negative cases for weights treated as probabilities, unrecorded drops treated as no drops and stale-version samples pass. Every estimate displays version, target event, attempt unit, sample size, method, assumptions and uncertainty. Leveling cases cover XP spanning level-ups, level ranges, unknown entrances, unmeasured maps and changed builds/buffs.

Adapt Diablo II, III and IV separately, identifying version branch, season and mode first. Each game requires at least 40 isolation cases with zero cross-game rule leakage and its own applicable M1–M4 gates before claiming support; similarly named rune, progression or modification systems do not share formulas by default.

**Go:** release an independently accepted capability within its validated scope. **No-go:** old sources, matching system names, client weights or static levels stand in for current online mechanics or optimal routes. Disable the affected game/capability after patches or sampling failures while preserving lawful historical replay.

See the [design](design.md) for system boundaries, the [README](../README.md) for repository status, and [AGENTS.md](../AGENTS.md) for collaboration and publication rules.
