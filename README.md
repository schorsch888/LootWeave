# LootWeave

English · [简体中文](README.zh-CN.md)

Connect item affixes, character builds, and game mechanics to explain how to use an item, whether to equip it, and why to keep it.

LootWeave is an open-source local Windows equipment decision assistant prototype. It does not ask players to assign stat weights. The current repository contains a runnable local development implementation; its only executable game knowledge pack is a synthetic fixture. Deskrawl is a research target, while Diablo II, III, and IV remain future candidates with separate version and mode rules.

## Source core workflow

The entry forms now support shoulder/back equipment and embedded sources such as gems. Changing or removing an embedded source resets effect-review status; existing source identities, actors, effects and evidence references are preserved.

The current source opens on a blank, real profile. Structured forms record uniquely identified owned inventory items, linked materials and currency balances, and player-reviewed preparation quotes for skill learning/removal or equipment changes. FSD forms are available for resources, quotes, and budgets. Quotes retain before/result state, context and class, level/rank/unlock requirements, costs or unknown costs, evidence and unknowns. Future plans select quote IDs and may set non-negative integer resource limits. Engine `0.1.7` combines selected known costs to show resource deficits and budget excess while preserving actual skill ranks, actors, and effects; unknown costs, unlocks, version/input changes, random results, or missing selected supporting quotes remain unconfirmed and never count as feasible. Preparation feasibility is reported separately from game-mechanic conclusions. Projections apply only to future plans and do not change current equipment or its build hash. Older profiles are not populated with inferred resources or quotes; SQLite remains schema v1 without migration. Deskrawl remains research-only, with no DPS or equip/retention recommendation accepted.
For OCR review, each non-empty raw line and every parsed field not represented by a complete matching raw-text line can be accepted or ignored separately. Review known/custom affix values and units, confirm `required_level` separately, then apply all reviewed fields to the candidate in one action; a same-ID affix is explicitly replaced. Screenshot evidence attaches only to mapped candidate fields, preserving raw text, other sources, and capture time. A new screenshot resets review, and an independent `observation_id` state gate cannot be bypassed by removing an unknown marker. Percent units stay unchanged, and duplicate targets block apply. The installed OCR models, parsing algorithm, and evaluator 0.1.7 are unchanged.

**The current local Windows installer is `dist/LootWeave-MVP-0.1.0-20261005-ocr-review-windows-x64-setup.exe` (226,036,621 bytes; SHA-256 `b846e6e0dc60c1c136ec547b75ec0108663ea49078029b9ba012e16382074834`), built from source commit `eb33ccf1d303cf9554735a1d6238878f02c8517c`. It includes this OCR equipment-review workflow and evaluator 0.1.7, with eager startup still the default. All 524 bundle files passed hash verification, and all three frontend files match the production build. The actual packaged Rust headless host passed six fictional OCR-affix checks (6.8597 s): original text/time/provenance, signed and legacy-percent differences, SQLite persistence and restart, and ten frozen replays before and after restart. The packaged preparation check passed eight checks (9.1709 s); the two-cycle lifecycle check passed thirteen with owned-process cleanup. The build took 227.831 s. Local regression passed 502 Python tests with one Windows symlink-privilege skip, 44 core, 22 confirmation, 16 runtime, 27 acquisition and 32 evaluation-render checks, TypeScript/Vite, architecture and both frozen OCR holdouts. All five earlier installers remain unchanged. Remote CI and merge status are tracked in the phase PR; real mechanics, visible GUI, OCR human holdout and two-machine release acceptance remain open.**

The earlier `20261005-equipment` installer host from `eb1995dc` passed `scripts/check_desktop.py --cycles 2`: 13 background lifecycle checks in 34.563 seconds, including two normal start/exit cycles, six service-fault cleanup cases, forced-host Job cleanup, restart recovery, frozen replay across restart and source failure, instance locking, and backup/restore. The 34.563-second duration is whole-script elapsed time, not a startup latency metric. This does not measure visible GUI behavior. Its original source/artifact scope is preserved in [PR #4](https://github.com/schorsch888/LootWeave/pull/4).

## Runtime performance experiment

The [predeclared runtime experiment](docs/performance-experiment.md), [results](docs/performance-results.md) and [selected sanitized cohorts](fixtures/runtime-performance/README.md) retain 20 attempts per cohort. Explicit on-demand source `7afdd6e` reduced initial headless idle private commit to 76.6 MiB versus control maxima near 105 MiB, but manual-complete P95 was 4.924 seconds against a required <3.698 seconds. The primary gate failed, so both launchers keep eager as the default; use `--startup-policy on-demand` only as an explicit experiment. Lazy Knowledge parsing, OCR helper reuse and production JavaScript splitting remain deferred. These measured cohorts precede the current real-equipment workflow and do not measure visible desktop startup.

The matching development build of complete-equipment integration `96c6374` passed 20 eager and 20 explicit on-demand lifecycle/fault cycles plus 20 hidden passive WebView cycles. Artifact identities, historical `2034deed`/`ddbfa853` results and limitations are separated in [validation](docs/validation.md#complete-equipment-integration-96c6374). These local artifacts do not replace the delivered installer or establish release acceptance.

## Explore the project

| Entry | Purpose |
| --- | --- |
| [Implementation](docs/implementation.md) | Current implementation, development setup, and acceptance boundaries |
| [Validation](docs/validation.md) | Measured source/binary scopes and remaining release gates |
| [Design](docs/design.md) | Product scope, core data, architecture, evidence, and privacy boundaries |
| [Roadmap](docs/roadmap.md) | Dependencies, deliverables, and acceptance gates |
| [Research guide](docs/research.md) | Published evidence, tool prerequisites, reproduction commands, and limitations |

The React/TypeScript frontend uses feature-sliced folders under `frontend/src/{app,pages,features,entities,shared}`. A Rust/Tauri Windows host lives in `desktop`. Python services for profile, knowledge, evaluation, planning, and OCR run as separate HTTP processes and use SQLite storage. The root `contracts`, `storage`, and `transport` modules provide shared infrastructure; the gateway has no domain rules.

The implementation supports confirmed, complete snapshot revisions; keeps raw OCR observations separate from user-confirmed data; explains whole-item replacement; and can replay frozen evaluations. After capture, the review panel displays the original BMP region at native pixel dimensions and the uncorrected OCR text; the image viewer supports keyboard scrolling. Numeric parsing rejects split or incomplete numbers and scientific-notation fragments, while preserving original text, signs and units. Native OCR line text is mapped back to the original text with global spans; fields stay bound to their source line, duplicates across lines are ambiguous, and missing or unmapped native lines produce no parsed fields. Readable primary recognition remains the value source; consistent English recognition is recorded as `numeric_corroboration`, and `numeric_source` is used only when an unreadable number was actually recovered. Spaced decimal fragments are rejected so a whole unreadable primary lexeme with an explicit unit can be reviewed against an independent English number; disagreement remains ambiguous and every observation still needs human confirmation. Changing the game scope, source, window binding, region or language, or starting another capture clears the prior image and observation association, and requires confirmation again while preserving manually entered text. Late window-detection replies are ignored unless they match the current context and detection generation. Planning compares measured total XP and full elapsed time, and provides observation-sampling estimates with Wilson 95% intervals. Trials accept manually entered start and end character levels, or a separate Paragon level range, plus actual cumulative XP and complete elapsed time for that same range. Comparisons use matching confirmed scopes; changing a trial input clears the old ranking and requires consistency to be confirmed again. If saving a trial succeeds but comparison fails, retrying unchanged data reuses its trial ID. The system reports recorded results without inferring drops or an optimal map.

New trial records must keep XP and levels within the exact-integer range and produce a finite XP rate. Unusable historical measurements remain stored unchanged, are marked uncertain and are excluded from rankings; unsupported pooled totals remain pending confirmation. Retrying the same recorded inputs preserves the trial ID even when derived classification changes, and concurrent saves cannot duplicate the record. Small positive route rates remain visibly nonzero.

## Try the Windows MVP

The existing installer is `dist/LootWeave-MVP-0.1.0-20261005-ocr-review-windows-x64-setup.exe`; it supports OCR review but predates the save-before-review persistence fix. Build the portable ZIP below to use that source change.

### Portable ZIP (no installation)

The portable archive target is `dist/LootWeave-MVP-0.1.0-20261005-portable-windows-x64.zip`. After it is built, extract it to a writable local folder and double-click `LootWeave.exe`; no administrator rights or application installation are required. The build bundles Python and the Microsoft WebView2 Fixed Version runtime. Its `portable.json` marker automatically selects sibling `sidecar/`, `webview2/` and `data/` folders; SQLite, OCR and browser data stay under `data/`. Exit LootWeave before moving the folder; replace app/runtime files on upgrade while retaining `data/`. The regular installer continues to store data in `%LOCALAPPDATA%/LootWeave`. This build guidance does not assert portable artifact acceptance.
Screenshot capture is first stored as an unconfirmed observation in the updated source. Recapture, OCR failure, and manual saving preserve its original screenshot reference; only human-confirmed fields become snapshot facts. See Microsoft WebView2 [distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). Windows OCR uses installed language models; manual entry remains available if they are missing.

The existing installer starts with a blank profile. Record candidate and current equipment, review each captured line as an affix or explicitly ignore it, apply the reviewed fields, then confirm and save. Its source is the earlier `eb33ccf1d303cf9554735a1d6238878f02c8517c` build; it does not include the new save-before-review observation persistence fix. The portable ZIP described above is intended for that updated source workflow. Owned resources, preparation quotes, future plans, SQLite profile revisions, and frozen evaluations remain available. Missing Windows OCR language models still allow manual entry.

## Run locally

Requirements: Windows for native OCR and desktop packaging; Node.js 24 or newer; pnpm 11.19.0; and Python 3.12 or newer for services (local validation used Python 3.12.14; CI used 3.13.16). Python runtime services have no third-party runtime dependencies. Install the frontend dependencies and build it, then launch the local development runtime:

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
python runtime.py
```

Deskrawl real-time capture has source-level process/window checks and explicit selection. Regions use client-relative coordinates, with a countdown to return manually to the game. Detection does not verify its build or mechanics; text and historical replay remain usable without the game. `scripts/check_native_ui.py` is a repository-only developer harness for hidden, non-focusable passive DOM/IPC checks; it performs no keyboard, mouse, or focus operations and is not distributed in the installer. The current Rust-only host changes are included in the installer. Hidden readiness does not establish visible painting, successful capture from a real game window, keyboard accessibility, cold-GUI P95, or two-machine acceptance.

Windows OCR uses the operating system's native models. Install English (`en-US`) and Simplified Chinese (`zh-Hans-CN`) language support to enable both; if a model is unavailable or OCR fails, users can still enter and confirm item text manually.

For Windows x64 desktop packaging, install the pinned build dependencies and build the frontend first:

```powershell
python -m pip install -r requirements-build.txt
pnpm --dir frontend build
python scripts/build_desktop.py
```

The script creates a local PyInstaller sidecar directory and builds the Rust host. `--installer` produces the NSIS installer with embedded Python and the configured offline WebView2 component. Local packaging and headless checks do not complete two-clean-machine release acceptance.

## Game support and acceptance

The only executable knowledge pack is `synthetic-leveling` version `1.0.0`, scoped to the synthetic game ID `lootweave-fixture`; its data is entirely fictional and represents no real game. Deskrawl build `25690430` Sorcerer leveling remains `research_only`. The versioned `deskrawl-sorcerer-leveling` research pack adds selected Frostwyrm static/native and original metadata image/module-pointer/registration-address evidence through `0.6.0-research`; all six explicit research versions are available, earlier pack bytes remain unchanged, and every version has an empty `rules` array. Read-only validators check source identities, selected static traces and method-slot/image/token-pointer metadata and a selected registration tail/address reference; executed registration/class dispatch, online behavior and complete equip/unequip lifecycle remain unaccepted. M1 is not accepted. Deskrawl and Diablo II, III, and IV are not currently supported games.

Synthetic OCR holdout-v7 was generated after the current adapter was frozen: 200 regions and 600 critical fields across two languages, five scales and four quality conditions. It measured 572/600 (95.33%) correct, 28 rejected/missing fields, zero unflagged errors and whole-request P95 of 1.780 seconds. English scored 299/300 (99.67%) and Chinese 273/300 (91%); low-contrast and downsampled inputs scored 93.33% and 92.67%. Overall numerical targets passed. M2 remains unaccepted: these are three generic synthetic fields, actual game/layout coverage and independent human truth review remain pending, and every observation requires confirmation.

Current OCR can request one bounded English numeric-region helper call for at most three crops. It preserves original image/text, readable primary values, explicit signs, units and conflicts. Contradictory candidate readings remain ambiguous until a consistent crop corroborates them; helper failures preserve the primary observation for review. Fifteen numeric-region regressions include real two/three-crop WinRT checks, explicit sign conflicts and failed supplementary reads.

New evaluations use engine `0.1.7`. The 42 preserved synthetic examples for engines `0.1.0` through `0.1.6` each replay ten times with their original outputs; those historical replays do not establish acceptance of new game mechanics.

Public [v7 evidence](fixtures/ocr-critical-fields-v7/README.md) contains all original inputs, native observations and 30 numeric crops. All 200 BMP hashes and the complete manifest reproduced exactly; the frozen parser replays every observation. Seven new evidence regressions detect altered state/image identity, missing or changed crops, original-word mapping and favorable totals. [Historical v6 evidence](fixtures/ocr-critical-fields-v6/README.md) remains unchanged. Examined datasets cannot become fresh acceptance sets for later algorithm changes.

Integrated-source checks passed 468 Python tests (467 passed, one Windows symlink-privilege case skipped; 51.576 s), 24 direct core checks, 19 confirmation checks with temporary Profile SQLite, 16 runtime checks, 32 evaluation-card renders, 27 Planning checks, and TypeScript/Vite. These checks have a separate source scope from the 75163eff local installer and its 17 core/13 lifecycle checks; that installer excludes the later runtime integration. Visible GUI, real-game mechanics and two-clean-machine acceptance remain open. [PR #4](https://github.com/schorsch888/LootWeave/pull/4) preserves the preceding installer/source checks; earlier hidden child-process timeout evidence remains in the [validation record](docs/validation.md).

The research baseline validated 1,593 selected static objects from Deskrawl build `25690430`; this does not establish complete game mechanics, real player item rolls, or final combat/drop formulas. Reproduction requires lawfully obtained matching game files and regenerated local intermediates. Raw game resources, full extracted databases, and downloaded tools are not distributed here.

## Repository checks

From the repository root:

```powershell
python -m unittest discover -s tests -v
python scripts/check_architecture.py
python scripts/check_public_docs.py
python scripts/validate_ocr_holdout.py
python scripts/validate_ocr_holdout.py --version v7
python -m compileall -q services scripts contracts.py storage.py transport.py service.py gateway.py runtime.py version.py
pnpm --dir frontend check:core
pnpm --dir frontend build
node scripts/check_evaluation_render.mjs
```

These checks exercise repository contracts and the frontend build; they do not certify game mechanics, OCR quality on real screenshots, or clean-machine installation. Full Rust/Tauri tests require generated desktop resources. On Windows, `python scripts/check_window_guards.py` exercises the actual capture modules independently, using cached Rust dependencies and no Tauri host rebuild.

English documents are authoritative; the Chinese README is an equivalent translation. Contribute focused changes through [Issues](https://github.com/schorsch888/LootWeave/issues), stating evidence, checks run, and remaining unknowns. Do not submit personal data, real character snapshots, private screenshots, credentials, player saves, or raw game resources. See the [publication boundaries](docs/design.md#privacy-and-publication).

## License

LootWeave code and documentation are licensed under [Apache-2.0](LICENSE). This license does not grant rights to redistribute third-party game resources, downloaded tools, or other content owned by their respective licensors.
