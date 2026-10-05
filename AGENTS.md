# Agent instructions

LootWeave has a local Windows prototype. Real-game support and release acceptance remain open.

## Start here

- Read [README](README.md), [design](docs/design.md), [architecture contract](docs/architecture.md), and [roadmap](docs/roadmap.md) before changes.
- For implementation, read the [implementation record](docs/implementation.md). For research, read the [research guide](docs/research.md) and related evidence.
- For all new or changed text, obey the [writing rules](docs/agent-writing.md), including ASD-STE100.

## Make focused changes

- Examine the working-tree status and related diffs first. Keep existing user changes.
- Keep changes in the approved task scope. Continue the approved work without repeated confirmation.
- Use `rg` to find files and text. Use the standard library or existing dependencies before you add dependencies.
- Use Luna for simple inventories and documentation scans. Use 6.1-sol for implementation and complex repairs. If a required model is not available, tell the user.
- Give each agent independent work and explicit file ownership. Examine their changes before you use them.
- When scope or behavior changes, update the design and roadmap.

## Project boundaries

- Before code changes, identify the owner, permitted callers, data owner, and affected contract.
- Obey the architecture contract for service calls, storage, shared helpers, and boundary changes. Keep pinned replay.
- Keep one Windows EXE entry point, Rust + Python, FSD frontend, and DDD microservices for each business capability.
- Keep rules separate by game, edition, build, mode, and season. Do not use static definitions as proof of owned items or complete mechanics.
- Keep observations, confirmed facts, and derived results separate. If prerequisites are unknown, do not give a definite conclusion.
- Do not access player saves. Do not change game files. Do not inject into games. Do not access process memory or DMA.
- Do not control gameplay. Do not discard items automatically.
- Do not publish personal paths, machine or account identifiers, credentials, real character data, or private screenshots.
- Keep original game resources, bulk extracted data, decompiled files, and downloaded tools local. Obey the research guide for reproduction and publication.
- Project code and documentation use [Apache-2.0](LICENSE). Examine third-party redistribution rights separately.

## Validate and deliver

Run these checks from the repository root:

```sh
python -m unittest discover -s tests -v
python scripts/check_architecture.py
python scripts/check_public_docs.py
python -m compileall -q scripts
```

- Run additional [repository checks](docs/development.md#validate-a-change) applicable to the change.
- Give the changes, actual check results, skipped checks, missing prerequisites, and unknowns. Keep current results separate from historical evidence and targets.
- Do not give source verification results without matching inputs. Game mechanics and release acceptance must have their own evidence.
- Do not commit, push, publish, create remote resources, or select a license without permission.
- Before an approved commit, examine staged paths, text, binary attachments, rights, and public author/committer identity. Automated checks do not replace this examination.
- Push only the approved branch. Never upload the entire `.git` directory or internal tool references.
