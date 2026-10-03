# Deskrawl XP penalty and leveling comparisons

This research concerns the static configuration and reviewed native branches of Deskrawl build `25690430`. It did not execute the game, read player saves, measure XP per hour or verify server formulas. The [evidence record](../research/experience-penalty.json) contains source identities, addresses, constants, branch review and remaining unknowns.

## Reviewed local multiplier

The formal scene binds `level0:40412` to GameConfig `sharedassets0.assets:59808`, with `IsDemo=0`, `MaxPlayerLevel=70` and `XpZeroUnderLevel=6`. The reviewed `GameManager.dlu(int)` and inline kill-processing code in `GameManager.dlt(Enemy)` use:

```text
penalty = clamp((6 - (character level - enemy level)) / 6, 0, 1)
```

The branch reads `Character._level`; it does not add paragon level. These are ideal mathematical multipliers. Native float32 arithmetic and subsequent integer rounding affect final XP.

| Enemy levels below the character | Penalty multiplier |
| --- | --- |
| Equal or higher | 100% |
| 1 | 5/6 ≈ 83.33% |
| 2 | 4/6 ≈ 66.67% |
| 3 | 3/6 = 50% |
| 4 | 2/6 ≈ 33.33% |
| 5 | 1/6 ≈ 16.67% |
| 6 or more | 0% |

Here, 100% means no level-gap penalty. Higher-level enemies may have different base XP; the multiplier does not make their actual rewards equal.

## Zero multiplier is not always zero awarded XP

The reviewed kill path has three distinct branches:

- Rewards unhandled and `Enemy.PlannedXP > 0`: use planned XP directly; this branch does not reapply the local penalty, XP bonuses or minimum.
- Rewards unhandled without positive planned XP: calculate local base XP, multiply by the level penalty, `1 + XPGain` and the map multiplier, then round and enforce a minimum of **1 XP**. A zero penalty therefore still yields 1 on this path.
- Rewards already handled: award 0 on this invocation to avoid duplication. The minimum-one rule does not apply to this branch.

The local offline helper `hc.dvq` also contains the penalty and minimum-one handling. This does not prove that server offline rewards match it. Who supplies positive planned XP, online overrides and server calculations remain unverified.

## What would make one route faster?

Compare **actual cumulative XP earned / complete elapsed time**, including killing, movement, waiting, recovery and death losses. Enemy density and the number cleared also matter. For comparable single-enemy cycles:

```text
A is faster than B when actual_XP_A / complete_time_A > actual_XP_B / complete_time_B.
```

Test candidates under comparable version, mode, level range, build and buffs; account for XP spanning level-ups. Confirm access before suggesting a route. Without comparable records, give trial candidates; “best” refers only to measured candidates. Static map levels and the penalty alone cannot establish an optimal map.

The formal config has normal, nightmare and hell-1 XP multipliers of 1, 1.5 and 2. If enemy mix, levels, bonuses and density match, the local calculation branch applies, no special-map multiplier applies, and rounding/minimum effects are negligible:

| Comparison | Complete-cycle condition for the higher difficulty to win |
| --- | --- |
| Nightmare versus normal | Less than 1.5× normal time |
| Hell 1 versus normal | Less than 2× normal time |
| Hell 1 versus nightmare | Less than 4/3× nightmare time |

These are conditional deductions, not measured best difficulties. `MapData.cfv` has additional branches for special map types; the three difficulty values are not universal final multipliers. Actual XP observations are needed to cover planned rewards and server differences. The future leveling capability and its acceptance cases are in [M5](roadmap.md#m5-acquisition-leveling-and-other-games).

## Reproduce evidence-identity checks

Follow the [research guide](research.md) to prepare the pinned dependencies and generate matching local outputs first. Then, from the repository root in PowerShell:

```powershell
python scripts/validate_deskrawl_xp.py --game "$env:DESKRAWL_GAME_DIR"
```

The [standard-library validator](../scripts/validate_deskrawl_xp.py) checks five source hashes, the formal configuration/scene link, six reviewed native method hashes and PE address mappings, and three constants. A previous local run passed these checks; without matching inputs, no new verification can be claimed. Re-generated intermediate DLLs or exports must match the reviewed identities or receive a new provenance/semantic review; changing expected hashes to make a command pass is not validation.

This check does not execute native methods or repeat the semantic review, behavioral experiments or server validation. It is specific to the recorded build and branches, not other games or untracked skill/rune XP behavior. Publication and product boundaries are recorded in the [design](design.md).
