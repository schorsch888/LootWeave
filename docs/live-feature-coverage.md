# Live data feature coverage

This document describes LootWeave's own live observation model for Deskrawl online mode.
It describes source behavior, not complete game functionality or real-game acceptance.

Rust owns native capture, desktop functions, and process lifetime.
Python owns APIs, OCR processing, statistics, and storage. React presents observations and review.
One Windows EXE remains the desktop entry point. Python services ship with the application.

## Data views

| View | Current model and behavior | Limits |
| --- | --- | --- |
| Character | Samples can include character identity, level, XP, HP, mana, area, map, and Paragon. | Sources supply these values. Missing values remain unknown. Deskrawl context is declared, not independently verified. |
| Equipment and containers | Samples can include equipped items, inventory, storage, carriage, affixes, units, roll ranges, upgrades, sockets, and embedded items. | Only received observations appear. Missing item flags remain unknown. Socket contents and effects require source evidence. |
| Build | Samples can include abilities, talents, Paragon, runes, companions, and temporary effects. | Supplied ranks and identifiers do not prove game mechanics or hidden allocations. |
| Observed panel | Samples can include base stats, final stats, validation, and observed panel values. | Observed values remain separate from estimates. They do not prove combat damage or gear gains. |
| Resources | Views can show materials, potions, capacities, storage pages, pickup settings, and alerts when supplied. | Missing quantities and settings remain unknown. No value is inferred from absence. |
| Run reports | The API accepts up to 1,000 run records. Rates use at most 20 recent records with `partial: false` and complete duration, XP, and gold. | Map summaries describe the received data. They are not optimal route recommendations. Missing reports show “not collected.” |
| Combat | The API accepts up to 8,192 damage events. It computes 10-second and 60-second DPS only for complete windows. | Missing or partial windows remain unknown. No event input means “not collected.” |
| Lineage | The API accepts up to 5,000 draws and 2,000 finds. It reports observed frequencies. | Frequencies do not predict future draws or establish game probabilities. Missing input shows “not collected.” |
| Loadout references | The UI can show five read-only loadout positions, with supplied skills, gear, and missing items. | Missing positions and flags remain unknown. LootWeave does not change game equipment. |
| Status and definitions | Views can show source-provided catalogs, events, and static definitions. LootWeave retains its own knowledge-pack cache. | The view shows only received data. Missing catalogs and mechanics remain unknown. |

The model also separates town checklists, ground items, transit, forecasts, and chest contents.
These records remain distinct from held equipment.
A preview does not establish ownership, probability, or a future item.

## Owned API and storage

The protocol is `lootweave-live/1`.
The Gateway accepts samples at `POST /api/profile/live/samples` under the current session.
Raw JSON input is limited to 4 MiB.
Samples include source identity, context, class, capture time, character, items, equipped slots, and coverage.
Optional fields include overview, build data, reports, and report coverage.

`GET /api/profile/live/sources` lists received sources.
`POST /api/profile/imports/live/read` binds a source to the current session and freezes a preview.
`POST /api/profile/imports/live/draft` creates a draft from that preview.

Sample and preview caches each hold up to 16 entries and 8 MiB for 600 seconds.
A new sample replaces the previous sample from its source.
The API rejects older samples and conflicting samples with the same millisecond capture time.

Polling and sample publication do not write SQLite.
Draft creation stores the frozen source. Explicit confirmation creates a snapshot revision.
Missing coverage does not mean an empty inventory. Missing item flags and loadout positions remain unknown.

## OCR and capture

The UI can load a local JSON observation file.
The capture-observation feature can also load a local BMP file up to 6 MiB and 1600 by 1200 pixels.
It accepts uncompressed 24-bit or 32-bit BMP input.
Python uses the existing OCR path and Profile stores the original observation as unconfirmed.
If the actual screenshot time is unknown, the observation keeps that time unknown.
Windows OCR models require Windows.

Native screenshot capture remains a Rust operation.
OCR reads visible fields supported by the current demonstration parser.
OCR cannot read hidden memory or hidden game state.
There is no automatic game-memory collector or official game API.

## Statistics and interpretation

Python calculates statistics from received records and events.
It describes only the supplied sample window. It does not infer missing gameplay data.
Complete run rates use summed XP and gold over summed duration.

Combat DPS uses the full 10-second or 60-second window.
Lineage reports observed frequencies only.
These calculations do not establish complete mechanics, optimal routes, or item probabilities.

Ten views and a broad data model do not mean that LootWeave automatically collects or verifies every game feature.
Real Deskrawl online capture, layout coverage, and game mechanics remain unverified.

## Current owned API response sizes

This measurement used fictional inventory-only samples with the current owned API implementation.
Python called Profile handlers with temporary storage. The measurement used compact UTF-8 response bodies.
It did not measure CPU, total memory, frame rate, or end-to-end latency.

| Held records | Full read | Unchanged read | Body reduction |
| ---: | ---: | ---: | ---: |
| 80 | 49502 bytes | 549 bytes | 98.89% |
| 800 | 451985 bytes | 552 bytes | 99.88% |
| 1500 | 843288 bytes | 555 bytes | 99.93% |

The response optimization does not reduce producer input.
Reports can change response size and content hashes.

## Acceptance limits

The current data model and views do not establish full game functionality.
No automatic Deskrawl collector or official game API has passed acceptance.
OCR support is limited to visible demonstration fields. Windows OCR requires Windows.
Real-game capture, complete field coverage, and game mechanics remain unverified.
