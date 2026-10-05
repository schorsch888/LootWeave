# Agent Instructions

## Start here

- Read [README](README.md), [design](docs/design.md), and [roadmap](docs/roadmap.md) before changing the project.
- For research work, read the [research guide](docs/research.md) and the selected evidence relevant to the task.
- This is a research and design project with reproducibility tools and selected evidence, not a runnable application. Distinguish facts, constraints, proposals, unknowns, and unmeasured targets.
- Product implementation requires a task requesting it. Continue authorized work without repeated confirmation for routine, reversible local steps.

## Make focused changes

- Inspect the working-tree status and relevant diffs first; preserve existing user changes. Prefer `rg` for discovery and make the smallest justified change.
- Prefer the Python standard library over new dependencies.
- English is the primary documentation language. Keep `README.zh-CN.md` equivalent to `README.md`; keep this file, the design, and the roadmap in English only.
- Update the design and roadmap when scope or behavior changes.
- Delegate only independent work, with explicit file ownership; the primary agent integrates and reviews results. Use Luna for simple inventories and documentation scans, and 6.1-sol for implementation and complex repairs. Disclose unavailable models.

## Write with ASD-STE100

Use [ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf) for new or changed English text.
Obey all applicable rules in Part 1.
Use the dictionary in Part 2 for each word.
Do these checks:

- Use at most 20 words in each instruction sentence and 25 in each description sentence. Count words as Section 8 tells you.
- Keep one topic in each sentence. Keep each paragraph to one topic and at most six sentences.
- Give one command in each sentence. Steps at the same time can have their commands in one sentence. Put necessary conditions first.
- Use notes for information. Do not put instructions in notes.
- Use active voice and permitted verb forms and tenses. Use passive descriptions only when the actor is unknown.
- Use approved words only with their permitted meanings, forms, and parts of speech.
- Use technical nouns and verbs from the permitted categories. Keep the same term for the same thing.
- Use noun groups of at most three words. Obey Rule 2.2 for longer technical names.
- Keep necessary articles and connecting words. Do not use contractions or semicolons.
- Start necessary safety instructions with the command or condition. Then tell the reader about the risk.

For Chinese text, use short sentences.
Give the name of the person or system that does each step.
Use the same term for the same thing.
Give one step in each instruction.
English word limits are not applicable to Chinese text.

Do not change code, commands, identifiers, quotations, or legal text to obey these style rules.
Give the evidence and applicable conditions.
Tell the reader which facts are missing.

Before you send the text, do all applicable rule and dictionary checks.
Tell the user which checks you did not complete.
Write that the text obeys STE only when all applicable rule and dictionary checks are satisfactory.

## Preserve domain boundaries

- Required architecture: preserve the Windows single-EXE entry point; use Feature-Sliced Design (FSD) for the frontend and Domain-Driven Design (DDD) microservices organized by business capability for the backend.
- Required implementation stack: Rust + Python. React/TypeScript, Tauri, the Rust/Python responsibility split, deployment, and packaging remain proposals requiring validation.
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
python scripts/check_public_docs.py
python -m compileall -q scripts
```

- Report what changed, checks actually run and their results, skipped checks or missing prerequisites, and remaining unknowns. Acceptance needs conditions and observed results; a commit or a documentation check does not prove product behavior or game mechanics.
- Do not commit, push, publish, create remote resources, or choose a license without authorization.
- Before an authorized commit, review actual staged paths, text, binary attachments, licensing scope, and public author/committer identity. Automated privacy checks do not replace this review.
- Push only the authorized branch; never mirror internal tool references or upload the entire `.git` directory.
