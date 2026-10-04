# LootWeave

English · [简体中文](README.zh-CN.md)

Connect item affixes, character builds, and game mechanics to explain how to use an item, whether to equip it, and why to keep it.

LootWeave is an open-source local Windows equipment decision assistant prototype. It does not ask players to assign stat weights. The current repository contains a runnable local development implementation; its only executable game knowledge pack is a synthetic fixture. Deskrawl is a research target, while Diablo II, III, and IV remain future candidates with separate version and mode rules.

**The available Windows MVP installer, `dist/LootWeave-MVP-0.1.0-20261004-windows-x64-setup.exe`, is the delivered artifact for source commit `fcc9ed1`, with embedded Python and an offline WebView2 installer. The hidden-test changes and Rust-only host work since that commit have not been rebuilt into this installer. Its developer-machine headless startup, persistence, replay and process-cleanup checks passed; two-clean-machine offline installation/removal and real-game acceptance remain unpassed.**

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

The local installer is `dist/LootWeave-MVP-0.1.0-20261004-windows-x64-setup.exe`. Open it, install LootWeave, then open the application. Node, pnpm and a separate Python installation are not needed to run the packaged app.

Start with the default fictional knowledge pack: review the example facts, confirm the snapshot, create a comparison and replay its saved result. Manual text, screenshot/OCR review, measured XP trials and observation-sample estimates are available. Deskrawl window detection and capture code is included; successful real-window capture, visible GUI and real-game mechanics remain unaccepted. OCR uses installed Windows language capabilities, with manual entry available when recognition is unavailable.

## Run locally

Requirements: Windows for native OCR and desktop packaging; Node.js 24 or newer; pnpm 11.19.0; and Python 3.12. Python runtime services have no third-party runtime dependencies. Install the frontend dependencies and build it, then launch the local development runtime:

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
python runtime.py
```

Deskrawl real-time capture now has source-level process/window checks and explicit selection. Regions use client-relative coordinates, with a countdown to return manually to the game. Detection does not verify its build or mechanics; text and historical replay remain usable without the game. `scripts/check_native_ui.py` runs hidden, non-focusable passive DOM/IPC checks only; it performs no keyboard, mouse, or focus operations. Hidden readiness does not establish visible painting, successful capture from a real game window, keyboard accessibility, cold-GUI P95, or two-machine acceptance. This harness and the current Rust-only host changes are not in the installer artifact above.

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

New evaluations use engine `0.1.4`. For each actor/capability, any active provider establishes presence; otherwise an unknown provider keeps the state unknown, and all inactive providers establish absence. Only active-to-inactive changes are definite losses, and only inactive-to-active changes are definite gains. Unknown requirements block conclusions and appear as pending confirmation, with their original rule/input sources preserved. Hero/companion ownership and scope checks remain. All 24 frozen records from `0.1.0` through `0.1.3` replay their original behavior, versions and hashes; new requests use the corrected engine.

Public [v7 evidence](fixtures/ocr-critical-fields-v7/README.md) contains all original inputs, native observations and 30 numeric crops. All 200 BMP hashes and the complete manifest reproduced exactly; the frozen parser replays every observation. Seven new evidence regressions detect altered state/image identity, missing or changed crops, original-word mapping and favorable totals. [Historical v6 evidence](fixtures/ocr-critical-fields-v6/README.md) remains unchanged. Examined datasets cannot become fresh acceptance sets for later algorithm changes.

Current Python regressions ran 348 tests: 347 passed and one Windows symlink-privilege case was skipped (34.660 s including discovery). TypeScript and the production frontend build passed. Direct React checks passed 14 confirmation cases, 27 Planning cases and 32 actual evaluation cards, without DOM or browser input. New source-clock checks reject mismatched capture evidence before writing, permit corrected retries and preserve historical payloads/replays; the evaluator remains 0.1.4. The host and frozen services built for the installer at `fcc9ed1` passed two headless start/exit cycles, all six worker fault checks, forced-host cleanup, persistence and backup/restore. Its served HTML, JavaScript and CSS matched that production build. These checks exclude visible GUI and two-clean-machine acceptance; a separate hidden native verifier passed 20 cycles with explicit CDP disconnection and natural process exit records. An earlier descendant-exit timeout remains unresolved; see the validation record for the evidence limits. See the [validation record](docs/validation.md) and [Roadmap](docs/roadmap.md).

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
pnpm --dir frontend build
node scripts/check_evaluation_render.mjs
```

These checks exercise repository contracts and the frontend build; they do not certify game mechanics, OCR quality on real screenshots, or clean-machine installation. Full Rust/Tauri tests require generated desktop resources. On Windows, `python scripts/check_window_guards.py` exercises the actual capture modules independently, using cached Rust dependencies and no Tauri host rebuild.

English documents are authoritative; the Chinese README is an equivalent translation. Contribute focused changes through [Issues](https://github.com/schorsch888/LootWeave/issues), stating evidence, checks run, and remaining unknowns. Do not submit personal data, real character snapshots, private screenshots, credentials, player saves, or raw game resources. See the [publication boundaries](docs/design.md#privacy-and-publication).

## License

LootWeave code and documentation are licensed under [Apache-2.0](LICENSE). This license does not grant rights to redistribute third-party game resources, downloaded tools, or other content owned by their respective licensors.
