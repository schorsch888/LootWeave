# Owned live observation API

This API exchanges structured observations inside LootWeave's existing local runtime.
It does not automatically collect game data. LootWeave has no official game API integration or automatic collector.
OCR remains available for visible fields. Its current parser supports only the documented demonstration labels.

Rust owns desktop entry, native capture, and process lifetime. Python owns this API, validation, statistics, and storage.
React presents observations and manages review. The Windows distribution retains one EXE entry.

## Routes and authentication

The gateway uses the existing launch session credential and literal loopback address.
It forwards `/api/profile/...` to the owning Profile service under `/v1/...`.
No additional listener or credentials field appears in the live input panel.

| Gateway route | Purpose | Durable write |
| --- | --- | --- |
| `POST /api/profile/live/samples` | Validate and publish a source sample | None |
| `GET /api/profile/live/sources` | List available source IDs and capture times | None |
| `POST /api/profile/imports/live/read` | Bind the sample to a declared context and freeze a preview | None |
| `POST /api/profile/imports/live/draft` | Convert selected held equipment from that preview | Save its source observation |
| `POST /api/profile/confirmations` | Save explicitly reviewed facts through the existing flow | Append a Profile revision |

Sample publication cannot confirm observations. The protocol accepts only the documented fields and routes.
Historical stored revisions remain readable. They retain their original evidence and bytes.

## Required sample fields

The protocol name is `lootweave-live/1`.
The sample requires `schema`, `producer_id`, `captured_at`, `context`, `class_id`, `character.level`, and an `items` array.
Source identifiers use letters, digits, dots, underscores, and hyphens. They have at most 100 characters.
Capture time uses ISO 8601 with a time zone. It must be at most 120 seconds old or 30 seconds ahead.

The context includes `game_id`, `edition`, `game_build`, `mode`, `season`, `ruleset_id`, and `content_entitlements`.
The source declares this context. LootWeave does not verify it from process metadata.
The current input panel targets Deskrawl build `25690430`. Edition, mode, and class must match the selected values.

This example contains fictional data. Replace the capture time with the current UTC time before publication.

```json
{
  "schema": "lootweave-live/1",
  "producer_id": "desktop",
  "captured_at": "<current UTC time>",
  "context": {
    "game_id": "deskrawl",
    "edition": "1.0.0i",
    "game_build": "25690430",
    "mode": "online",
    "season": "not_applicable",
    "ruleset_id": "deskrawl-25690430",
    "content_entitlements": []
  },
  "class_id": "sorcerer",
  "character": {"name": "Fictional hero", "level": 12, "gold": 42},
  "items": [{
    "instance_id": "fixture-wand",
    "template_id": "FixtureWand",
    "name": "Fictional wand",
    "record_kind": "equipment",
    "slot": "weapon",
    "container": "inventory",
    "ownership": "held",
    "settlement": "settled",
    "affixes": [{"id": "Intelligence", "name": "Intelligence", "value": 12, "unit": "unverified"}]
  }],
  "equipped_slots": [],
  "coverage": {"inventory": "partial"}
}
```

The complete whitelist is in [live_schema.py](../services/profile/live_schema.py).
Unknown object fields are discarded. Missing numeric and Boolean fields retain unknown values.
Missing lists do not prove complete collection. Coverage uses `complete`, `partial`, or `unknown`.

Counts are nonnegative integers below `2**53`. Numeric fields must be finite and below `2**53` in absolute value.

## Item and build observations

Containers are `equipment`, `inventory`, `storage`, and `carriage`. Only items with `ownership: held` enter the held preview.
Online candidates require `settlement: settled`. Pending items, duplicate instances, unread affixes, and unavailable instance IDs cannot become candidates.
Ring candidates require an explicit `ring1` or `ring2` comparison slot.

An absent item record does not prove an empty slot.
`equipped_slots` lists explicitly observed slots, including observed empty slots. Unlisted slots remain unknown.
Producers must omit a slot when incomplete collection could explain its absent item.

Items can supply actual affixes, units, roll ranges, upgrades, sockets, embedded items, weapon fields, and descriptions.
Descriptions do not establish effects. Missing units remain `unverified`, and missing socket contents remain unknown.
Ground drops, forecasts, and unopened chest contents belong in `overview`. They cannot become held candidates through those fields.

Optional build fields include `abilities`, `talents`, `paragon`, `runes`, `companions`, and `temporary_effects`.
Ranks and source identifiers do not establish complete mechanics. Explicit `observed_panel` fields remain separate from `overview.panel` source estimates.
Known gold and material counts can enter the reviewed draft. Missing quantities remain unknown, while a supplied zero remains zero.

## Reports and statistics

Optional `reports` and `report_coverage` describe `runs`, `combat`, `lineage`, `loadouts`, and `status`.
Each report needs an explicit coverage declaration. Without its report or known coverage, the interface shows “not collected.”
Python owns all descriptive calculations. No game formula, equipment verdict, or route ranking is added by this protocol.

| Report | Input and interpretation |
| --- | --- |
| Runs | At most 1,000 records. Complete records need `partial: false`, positive duration, and known XP and gold for rates. |
| Combat | At most 8,192 events with UTC Unix seconds, source, actor, damage, and optional hit, critical, and kill counts. |
| Lineage | At most 5,000 draws and 2,000 finds. Manual and automatic source labels describe observations without starting game actions. |
| Loadouts | At most five numbered reference slots with supplied skills, gear, and missing items. Missing slots remain unknown. |
| Status | Supplied producer version, coverage, catalogs, and allowlisted events. No game process state is read. |

Run rates divide summed XP and gold by summed duration. They use the latest 20 complete records in source order.
Sources must send run history from oldest to newest. Partial records do not enter those rates.
Map summaries describe the received window. They do not prove comparable trials or an optimal route.

Combat DPS divides observed damage by the full 10-second or 60-second window.
The producer must declare complete event coverage from `coverage_started_at` through capture time.
Partial coverage or an insufficient window produces unknown DPS. Session totals retain their coverage status.
An empty complete window can produce zero. Missing hit, critical, or kill counts do not become known zeros.

Lineage frequencies describe received samples. They do not predict the next draw or establish game probabilities.
Unknown ancient and black-mist markers do not enter their corresponding denominators.
Market markers are supplied labels, not verified eligibility. Loadout references do not change game equipment.

## Supply data and review

1. Start LootWeave.
2. Select **实时 API**.
3. Wait for Profile readiness.
4. Load an owned observation JSON file through **载入观测文件**.
5. Confirm the declared scope.
6. Select **读取／刷新当前数据**.
7. Select a held candidate.
8. Select **载入候选与当前构筑**.
9. Review the draft and its unknown fields.
10. Confirm and save the snapshot.

For development, [send_live_sample.py](../scripts/send_live_sample.py) can send an owned JSON file through the gateway.
Supply the current local gateway address and launch credential. Keep the credential out of files, screenshots, and normal logs.

```powershell
$env:LOOTWEAVE_LIVE_SESSION = "<current launch credential>"
python scripts/send_live_sample.py --gateway http://127.0.0.1:<port> --file own-sample.json
Remove-Item Env:LOOTWEAVE_LIVE_SESSION
```

Without `--file`, the sender accepts one JSON sample per stdin line. It does not collect game data.
The sender disables proxies and redirects. It prints only confirmation state and sample hash.
No sample becomes confirmed through this command.

## Ordering, caches, and frozen review

Raw JSON is limited to 4 MiB. Both temporary caches hold at most 16 entries and 8 MiB of encoded content each.
Entries expire after 600 seconds. These limits do not bound total process memory.

A new source sample replaces the prior sample from the same producer.
Older capture times and conflicting samples at the same millisecond are rejected. Identical retries are idempotent.

Optional monitoring starts two seconds after each completed read. Reads do not overlap, and hidden pages pause them.
Candidate selection stops monitoring. A failed background read stops monitoring and preserves the earlier preview.
An unchanged content hash returns metadata without repeating items and reports.

Draft conversion uses the frozen preview ID and hash. Later publication cannot change the selected draft.
Explicit refresh preserves edited fields but invalidates their source association. Confirmation requires another load and review.
Historical revisions remain immutable. Game collection, game mechanics, and Windows release acceptance require separate evidence.
