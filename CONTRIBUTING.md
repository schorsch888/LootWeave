# Contributing to LootWeave

Contributions should make the project easier to understand, reproduce, validate, or maintain. Documentation corrections, reproducibility improvements, synthetic regression cases, and scoped research evidence are useful starting points. Read the [README](README.md), [design](docs/design.md), and [roadmap](docs/roadmap.md) before proposing a change.

## Choose a contribution

- **Documentation:** correct an explanation, repair a link, improve onboarding, or keep the two READMEs equivalent. Small corrections can go directly to a pull request.
- **Research:** follow the [research guide](docs/research.md). Identify the game, edition, build, mode, and season, and explain what the evidence establishes and what remains unknown.
- **Tools or experimental source:** describe the concrete problem and verify the affected behavior. Discuss substantial scope or architecture changes in an issue before implementing them.

Use [Issues](https://github.com/schorsch888/LootWeave/issues) for questions, reproducible problems, and proposals. Search existing issues first. The documentation and research templates help capture the needed context; a blank issue is appropriate for other topics. Keep discussion respectful and focused on the work.

## Set up and verify

The [development guide](docs/development.md) covers prerequisites, local source setup, desktop builds, and checks by component. Documentation and portable repository checks need Git and Python 3.12 or newer; they do not need a game installation.

Run the required baseline from the repository root:

```powershell
python -m unittest discover -s tests -v
python scripts/check_public_docs.py
python -m compileall -q scripts
```

Run the additional checks relevant to your change. Report the exact commands, observed results, skips, and missing prerequisites. A skipped source check is not a successful reproduction. Repository checks do not establish real-game mechanics, real screenshot accuracy, or release acceptance.

## Put information in the right place

| Content | Location |
| --- | --- |
| Project purpose, maturity, entry points, and help | [README.md](README.md) and [README.zh-CN.md](README.zh-CN.md) |
| Setup, commands, and troubleshooting | [Development guide](docs/development.md) |
| Current source behavior, contracts, and ownership | [Implementation](docs/implementation.md) |
| Product constraints and architecture | [Design](docs/design.md) |
| Planned work and acceptance conditions | [Roadmap](docs/roadmap.md) |
| Research prerequisites, methods, and selected evidence | [Research guide](docs/research.md) and the records it links |
| Dated observations, artifact identities, and unresolved checks | [Validation record](docs/validation.md) |

English is the primary documentation language. Update both READMEs in the same change when their shared content changes; keep the design, roadmap, and agent instructions in English. Keep detailed measurements and installer hashes in validation records instead of duplicating them across the home pages.

Use relative links to included repository files. Commands must name scripts available in a clean clone and state any external dependencies. Label facts, requirements, proposals, unknowns, and unmeasured targets explicitly. Update the design and roadmap when scope or behavior changes. Preserve historical evidence and append new observations with their own source and scope.

## Evidence and publication boundaries

Include only material needed to understand, reproduce, validate, or maintain the contribution. A research result should state source/build identity, method, scope, actual outcomes, failed checks, and unknowns. Source hashes identify inputs; they do not prove mechanics or redistribution rights.

Use synthetic examples and logical references such as `repo://`, `game://`, and `steam://`. Do not attach personal paths, account or machine identifiers, credentials, real character snapshots, private screenshots, or player saves. Keep original game resources, bulk extractions, decompiled intermediates, and downloaded tools local. An ignored file can still be tracked; review the actual diff and attachments before submission.

The project does not read or modify player saves, modify game files, inject into games, access process memory or DMA, control gameplay, or dispose of items automatically. Static definitions are not owned item instances, and field decoding does not establish complete mechanics, DPS, or final drop probabilities. Unknown prerequisites must continue to block unsupported conclusions.

## Submit a focused pull request

1. Explain the problem and resulting change, with a related issue when available.
2. Include only files needed for that change and preserve unrelated work.
3. Record validation results and remaining limits. Use a small synthetic reproduction for a behavior change.
4. Review text, links, binary attachments, third-party notices, and the public author/committer identity before committing.

Project code and documentation use [Apache-2.0](LICENSE). Preserve required notices and review third-party rights separately. The project license does not authorize redistribution of game content or downloaded tools. Agent-specific working rules are in [AGENTS.md](AGENTS.md).
