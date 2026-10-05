# LootWeave

English · [简体中文](README.zh-CN.md)

**Equipment decisions grounded in item facts, character builds, and versioned evidence.**

LootWeave is an open-source research and design project for a local Windows equipment decision assistant. Its goal is to explain how an item can be used, whether it fits a build, and why it may be worth keeping, without asking players to assign stat weights.

> **Status: research and development.** This repository includes reproducibility tools, selected evidence, and experimental source. The only executable game knowledge pack uses fictional data. Real-game recommendations and a production Windows release have not passed acceptance.

[Get started](#get-started) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md) · [Roadmap](docs/roadmap.md)

## Why LootWeave

An item's value depends on its actual rolls, the complete build, and the intended use. LootWeave explores a workflow that:

- Records owned items and build facts, with manual confirmation of OCR observations.
- Separates reasons to keep an item from eligibility to equip it now.
- Records preparation quotes and explains resource or budget gaps separately from mechanic conclusions.
- Compares whole-build mechanisms and preserves the inputs and rules used for replay.
- Keeps missing or conflicting evidence visible instead of producing unsupported conclusions.

## Current status

| Area | Available scope | Acceptance limit |
| --- | --- | --- |
| Research | Selected Deskrawl evidence and read-only reproduction tools | Matching lawful source files are required; static decoding does not establish complete mechanics |
| Experimental workflow | Item/build entry, owned inventory/resources, preparation quotes and budgets, SQLite profiles, field differences, and frozen replay | Real-game DPS and keep/equip recommendations remain unaccepted |
| Capture and OCR | Durable unconfirmed captures, per-line accept/ignore review, and manual mapping to known/custom affixes | Automatic parsing covers three generic demonstration labels; real-game layout coverage and independent truth review remain open |
| Planning | Manually measured XP/time trials and sample-based estimates | No verified optimal route or final item-drop probabilities |
| Runtime | Eager startup by default; explicit on-demand experiment | The declared startup-latency comparison failed; visible cold-start acceptance remains open |
| Windows packaging | Installer and portable ZIP tooling, with a CI path for preview releases | Visible GUI and installation/removal on two clean machines remain unaccepted |

Game scopes are isolated by game, edition, build, mode, and season:

| Game scope | Status |
| --- | --- |
| `lootweave-fixture` | Entirely fictional; the `synthetic-leveling` pack is executable for development checks |
| Deskrawl build `25690430` | First research target: Sorcerer leveling; research packs contain no executable rules |
| Diablo II, III, and IV | Future research targets; no accepted adapters |

See the [implementation](docs/implementation.md) for source behavior and the [validation record](docs/validation.md) for dated results and artifact identities. Historical test results do not establish acceptance of the latest source or another build.

## Get started

To inspect and check the repository, install **Git and Python 3.12 or newer**. These commands need no game files or frontend build:

```powershell
git clone https://github.com/schorsch888/LootWeave.git
cd LootWeave
python -m unittest discover -s tests -v
python scripts/check_public_docs.py
python -m compileall -q scripts
```

The suite reports environment-dependent skips; review them with the results. Passing checks verifies the covered repository behavior, not game mechanics or release readiness.

- **Explore the design:** start with the [design baseline](docs/design.md) and [acceptance roadmap](docs/roadmap.md).
- **Try a Windows preview:** see the [preview instructions](#try-a-windows-preview) for downloads and data storage.
- **Try the experimental source:** follow the [development guide](docs/development.md) for prerequisites, launch steps, expected behavior, and troubleshooting.
- **Reproduce research:** follow the [research guide](docs/research.md). Matching game resources and external tools must be obtained separately.

Local installers and generated build outputs are excluded from the repository. Paths in validation records identify local artifacts; they are not downloads supplied by a clean clone.

## Try a Windows preview

Check [GitHub Releases](https://github.com/schorsch888/LootWeave/releases) for available MVP prereleases. Use the installer or portable ZIP from the same release, with its `build-manifest.json` and `SHA256SUMS.txt` to verify the source identity and file hashes. A preview is experimental; real-game and two-clean-machine acceptance remain open.

For the portable ZIP, extract the whole archive to a writable local folder and double-click `LootWeave.exe`. Python, WebView2, and C++ runtimes are bundled. Personal data stays in the adjacent `data/` folder. Exit the app before moving the folder; preserve `data/` when upgrading. The installer uses `%LOCALAPPDATA%/LootWeave`. Windows OCR needs installed language capabilities; manual entry remains available.

The [CI workflow](.github/workflows/checks.yml) uploads four verified release files for seven days after successful Windows packaging. Main pushes or manual runs targeting main publish prereleases only after both browser/contracts and Windows packaging jobs pass. See the [CI and release contract](docs/implementation.md#github-ci-and-releases); workflow configuration alone does not establish a successful run or a published preview. Historical local builds have separate identities in the [validation record](docs/validation.md).

## Documentation

| Document | Read it for |
| --- | --- |
| [Development guide](docs/development.md) | Source setup, checks, Windows builds, and troubleshooting |
| [Implementation](docs/implementation.md) | Current source behavior, service ownership, and contracts |
| [Design](docs/design.md) | Product boundaries, data model, architecture, and privacy |
| [Roadmap](docs/roadmap.md) | Milestones, dependencies, and acceptance conditions |
| [Research guide](docs/research.md) | Evidence catalog, prerequisites, reproduction, and limits |
| [Validation record](docs/validation.md) | Dated measurements, build identities, failures, and open gates |
| [Performance plan](docs/performance-plan.md) | Runtime implementation status and deferred work |
| [Performance results](docs/performance-results.md) | Recorded experiment, failed startup gate, and retained eager default |
| [Contributing](CONTRIBUTING.md) | Documentation conventions, evidence requirements, and review steps |

English is the primary documentation language; the Chinese README is an equivalent translation.

## Repository layout

| Path | Contents |
| --- | --- |
| [docs/](docs/) | Design, development, research, and validation guides |
| [research/](research/) | Selected evidence and source provenance |
| [scripts/](scripts/) and [tests/](tests/) | Reproduction tools and repository checks |
| [fixtures/](fixtures/) and [knowledge-packs/](knowledge-packs/) | Synthetic examples, frozen replay inputs, and scoped packs |
| [frontend/](frontend/) | Experimental React/TypeScript frontend organized with Feature-Sliced Design |
| [desktop/](desktop/) | Rust/Tauri Windows host |
| [services/](services/) | Python services organized by business capability, plus OCR infrastructure |
| [runtime.py](runtime.py) | Local development launcher |

The architecture requires Rust + Python, a Windows single-EXE entry point, an FSD frontend, and DDD backend microservices. The current host, framework, responsibility split, and packaging approach remain subject to validation; see the [design](docs/design.md#local-architecture).

## Contributing and help

Documentation corrections, reproducibility improvements, and scoped research contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), then use [Issues](https://github.com/schorsch888/LootWeave/issues) for questions, problems, or proposals. Include the relevant version, evidence, checks run, and remaining unknowns.

## Privacy and boundaries

Data is processed locally by default. The project does not read or modify player saves, modify game files, inject into games, access process memory or DMA, control gameplay, or dispose of items automatically.

Do not submit personal data, real character snapshots, private screenshots, credentials, player saves, raw game resources, or downloaded tools. The [publication rules](docs/design.md#privacy-and-publication) explain what can be included and what must stay local.

## License

Project code and documentation use [Apache-2.0](LICENSE). Third-party game content and tools retain their own terms; this license does not authorize their redistribution.
