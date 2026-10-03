# LootWeave

English · [简体中文](README.zh-CN.md)

Connect item affixes, character builds, and game mechanics to explain how to use an item, whether to equip it, and why to keep it.

LootWeave is an open-source project working toward a local Windows equipment decision assistant, without requiring players to assign stat weights. Deskrawl is the first research target; Diablo II, III, and IV are future candidates with separate version and mode rules.

**The project is in research and design. There is no runnable application, EXE, OCR pipeline, or equipment evaluation service.** Current work includes selected mechanics research, static-data extraction and independent verification tools, and a staged implementation plan.

## Explore the project

| Entry | Purpose |
| --- | --- |
| [Design](docs/design.md) | Product scope, core data, architecture, evidence, and privacy boundaries |
| [Roadmap](docs/roadmap.md) | Dependencies, deliverables, and acceptance gates |
| [Research guide](docs/research.md) | Published evidence, tool prerequisites, reproduction commands, and limitations |
| [AGENTS.md](AGENTS.md) | Repository collaboration and publication rules |

Local research validated 1,593 selected static objects from Deskrawl build `25690430`; this does not establish complete game mechanics, real player item rolls, or final combat/drop formulas. Reproducing those checks requires lawfully obtained matching game files and regenerated local intermediates. Raw game resources, full extracted databases, and downloaded tools are not distributed here.

## Get started

For repository checks, prepare Git and Python. Python 3.12 is the research reference environment; the documentation check uses only Python's standard library and Git, with no game installation required.

```sh
git clone https://github.com/schorsch888/LootWeave.git
cd LootWeave
python scripts/check_public_docs.py
```

Start with the [design](docs/design.md) and [roadmap](docs/roadmap.md). For static-data reproduction, follow the [research guide](docs/research.md); its external tools and game prerequisites are separate from this quick check. A document precheck cannot prove the absence of secrets or validate game mechanics.

English documents are authoritative; the Chinese README is an equivalent translation.

## Repository checks

Run the same checks configured in the [GitHub Actions workflow](.github/workflows/checks.yml):

```sh
python -m unittest discover -s tests -v
python scripts/check_public_docs.py
python -m compileall -q scripts
```

They require no game files or research dependencies. The workflow is configured for pushes and pull requests; a successful remote run must be verified separately. These checks cover publication boundaries and script syntax, not product behavior or game formulas.

## Contribute

Use [Issues](https://github.com/schorsch888/LootWeave/issues) to discuss requirements, provide versioned public sources, or propose focused changes. Read [AGENTS.md](AGENTS.md), explain the evidence for your change, and include the checks actually run and remaining unknowns. Update affected design or acceptance criteria when behavior changes.

Do not submit personal data, real character snapshots, private screenshots, credentials, player saves, or raw game resources. Publish reproducibility scripts and selected sanitized evidence when they have a clear purpose; keep redundant drafts and private generated material local. See the [publication boundaries](docs/design.md#privacy-and-publication).

## License

LootWeave code and documentation are licensed under [Apache-2.0](LICENSE). This license does not grant rights to redistribute third-party game resources, downloaded tools, or other content owned by their respective licensors.
