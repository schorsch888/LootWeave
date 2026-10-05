# Agent Instructions

## Start here

- Read [README](README.md), [design](docs/design.md), [architecture contract](docs/architecture.md), and [roadmap](docs/roadmap.md) before changing the project.
- For research work, read the [research guide](docs/research.md) and the selected evidence relevant to the task.
- The project contains research tools, selected evidence, and an experimental local implementation. Real-game support and a production Windows release remain unaccepted. Distinguish facts, constraints, proposals, unknowns, and unmeasured targets.
- Product implementation requires a task requesting it. Continue authorized work without repeated confirmation for routine, reversible local steps.

## Make focused changes

- Inspect the working-tree status and relevant diffs first; preserve existing user changes. Prefer `rg` for discovery and make the smallest justified change.
- Prefer the Python standard library over new dependencies.
- English is the primary documentation language. Keep `README.zh-CN.md` equivalent to `README.md`; keep this file, the design, and the roadmap in English only.
- Update the design and roadmap when scope or behavior changes.
- Delegate only independent work, with explicit file ownership; the primary agent integrates and reviews results. Use Luna for simple inventories and documentation scans, and 6.1-sol for implementation and complex repairs. Disclose unavailable models.

## Preserve domain boundaries

- Required architecture: preserve the Windows single-EXE entry point; use Feature-Sliced Design (FSD) for the frontend and Domain-Driven Design (DDD) microservices organized by business capability for the backend.
- Required implementation stack: Rust + Python. React/TypeScript, Tauri, and the Rust/Python split follow the [architecture contract](docs/architecture.md). Packaging, deployment on clean machines, and real-game support still require acceptance evidence.
- Before editing code, identify its owner, permitted callers, data owner, and affected contract. Rust owns desktop capture and supervision. Python owns OCR, business services, and their storage. Keep game rules and equipment decisions out of frontend and gateway code.
- Use versioned APIs between business services. Do not import another service's implementation or open its storage. Limit shared helpers to wire contracts and infrastructure. The architecture contract defines the exceptions for service composition and offline maintenance.
- For authorized ownership, IPC, deployment, or language changes, follow the architecture change procedure. Do not move or copy business rules into Rust during incidental cleanup or optimization. Preserve pinned replay. Record compatibility, checks, and remaining unknowns.
- Isolate rules by game, edition, build, mode, and season. Deskrawl is the first research target; Diablo II, III, and IV are future targets.
- Static definitions are not owned item instances. Field decoding does not establish complete mechanics, DPS, or final drop probabilities. Unknown prerequisites must block unsupported conclusions.
- Do not read or modify player saves, modify game files, inject into games, access process memory or DMA, control gameplay, or dispose of items automatically.

## Research and public files

- Select files by their value for understanding, reproducing, validating, or maintaining the project, not a fixed file count. Guides, reproducibility/verification scripts, dependency metadata, and selected sanitized evidence require content and rights review before publication. Exclude redundant drafts and reports.
- Never publish personal paths, machine identifiers, account details, credentials, real character snapshots, private screenshots, or save data. Use logical source references such as `repo://`, `game://`, and `steam://`, and placeholders in examples.
- Keep original game resources, bulk extracted databases, decompiled intermediates, and downloaded tools local. Follow the research guide for lawful source prerequisites and reproduction; missing inputs mean the source check was not performed.
- Public evidence must state source/build, method, scope, actual results, and unknowns. Separate historical checks from current results. Source hashes identify inputs; they do not establish validation or redistribution rights.
- Use relative links to included repository files. Repository commands must reference scripts available in a clean clone; document external tools and source prerequisites explicitly without presenting them as bundled artifacts.
- Project code and documentation use [Apache-2.0](LICENSE). Preserve required notices and review third-party rights separately; this license does not authorize redistributing game content or tools.

## Validate and deliver

Run these checks from the repository root, plus checks relevant to the change. They require Git and Python, not game files:

```sh
python -m unittest discover -s tests -v
python scripts/check_architecture.py
python scripts/check_public_docs.py
python -m compileall -q scripts
```

- Report what changed, checks actually run and their results, skipped checks or missing prerequisites, and remaining unknowns. Acceptance needs conditions and observed results; a commit or a documentation check does not prove product behavior or game mechanics.
- Do not commit, push, publish, create remote resources, or choose a license without authorization.
- Before an authorized commit, review actual staged paths, text, binary attachments, licensing scope, and public author/committer identity. Automated privacy checks do not replace this review.
- Push only the authorized branch; never mirror internal tool references or upload the entire `.git` directory.
