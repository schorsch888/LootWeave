"""The independent, bounded wire schema for local live observations."""
from __future__ import annotations

import re

from contracts import number, require


def string(maximum=200):
    return ("string", maximum)


def enum(*values):
    return ("enum", values)


def array(spec, maximum):
    return ("array", spec, maximum)


def mapping(spec, maximum=256):
    return ("mapping", spec, maximum)


def obj(**fields):
    return ("object", fields)


INTEGER, NUMBER, BOOLEAN, KEY = ("integer",), ("number",), ("boolean",), ("key",)
TEXT = string()
NUMBERS = mapping(NUMBER)


def decode(value, spec):
    kind = spec[0]
    if kind in ("object", "mapping"):
        require(value is None or isinstance(value, dict), "live_sample_invalid")
        value = value or {}
        if kind == "object":
            return {name: decode(value.get(name), field) for name, field in spec[1].items()}
        require(len(value) <= spec[2], "live_sample_too_large")
        return {name: decode(item, spec[1]) for name, item in value.items()
                if isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", name)}
    if kind == "array":
        require(value is None or isinstance(value, list), "live_sample_invalid")
        require(value is None or len(value) <= spec[2], "live_sample_too_large")
        return [decode(item, spec[1]) for item in value or []]
    if kind in ("string", "key", "enum"):
        if value is None:
            return ""
        require(isinstance(value, str), "live_sample_invalid")
        if kind == "key":
            require(not value or re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", value), "live_sample_invalid")
        elif kind == "enum":
            require(value in spec[1], "live_sample_invalid")
        else:
            require(len(value) <= spec[1], "live_sample_too_large")
        return value
    if value is None:
        return None
    if kind == "boolean":
        require(type(value) is bool, "live_sample_invalid")
    elif kind == "integer":
        require(type(value) is int and 0 <= value < 2**53, "live_sample_invalid")
    elif kind == "number":
        require(number(value) and abs(value) < 2**53, "live_sample_invalid")
    return value


ALLOCATIONS = array(obj(id=KEY, name=TEXT, role=KEY, rank=INTEGER, max=INTEGER,
                        tree=TEXT, group=TEXT, description=string(1200)), 512)
BUILD_SOURCE = obj(id=KEY, name=TEXT, rank=INTEGER, actor=enum("hero", "companion"),
                   level=INTEGER, set_id=KEY, companion_id=KEY)
PREVIEW = obj(name=TEXT, template_id=KEY, rarity=KEY, item_level=INTEGER, ancient=BOOLEAN,
              black_mist=BOOLEAN, status=KEY, modifiers=array(obj(stat=KEY, value=NUMBER), 128))
CHECKLIST = array(obj(name=TEXT, reason=string(800), container=KEY), 2000)
OVERVIEW = obj(
    character=obj(xp=INTEGER, hp=obj(current=NUMBER, max=NUMBER), mana=obj(current=NUMBER, max=NUMBER),
                  area=TEXT, game_state=KEY, map=obj(key=KEY, label=TEXT), town=obj(key=KEY, label=TEXT),
                  primary_stat=KEY, paragon=obj(unlocked=BOOLEAN, level=INTEGER, xp=INTEGER)),
    stats=obj(final=NUMBERS, base=NUMBERS, validation=mapping(BOOLEAN, 32)),
    panel=obj(dps=NUMBER, toughness=NUMBER, recovery=NUMBER, max_hp=NUMBER, aps=NUMBER, dps_exact=NUMBER,
              weapon_damage=NUMBER, flat_damage=NUMBER, formula=string(800), game_labels_match=BOOLEAN,
              game_labels=mapping(TEXT, 32), primary=NUMBERS, crit=NUMBERS, bonus=NUMBERS),
    materials=array(obj(id=KEY, name=TEXT, amount=INTEGER), 512),
    capacity=mapping(obj(used=INTEGER, capacity=INTEGER, fullness_used=INTEGER,
                         level=enum("ok", "warn", "full", "unknown"), ratio=NUMBER, kind=KEY), 4),
    storage_pages=array(obj(page=INTEGER, used=INTEGER, capacity=INTEGER, usable=BOOLEAN), 100),
    in_flight_count=INTEGER, alerts=array(obj(code=KEY, severity=KEY, detail=string(800)), 100),
    carriage=obj(active_companion=KEY, base_capacity=INTEGER, extra_capacity=NUMBER, game_label=TEXT,
                 game_label_match=BOOLEAN, autofill_inventory=BOOLEAN, in_combat=BOOLEAN,
                 pickup_rarities=array(KEY, 30)),
    town_checklist=obj(go_to_town=BOOLEAN, open=CHECKLIST, store=CHECKLIST, review=CHECKLIST,
                       keep=CHECKLIST, stash_all=CHECKLIST),
    abilities=ALLOCATIONS, talents=ALLOCATIONS, potion_slots=array(TEXT, 4),
    run=obj(waves_total=INTEGER, wave_index=INTEGER, enemies_remaining=INTEGER, planned_items=INTEGER,
            picked_unminted=INTEGER, collected=INTEGER, granted=INTEGER, map=TEXT, difficulty=KEY,
            in_run=BOOLEAN, committed=BOOLEAN),
    history=obj(totals=NUMBERS, recent=array(obj(planned=INTEGER, collected=INTEGER, granted=INTEGER,
                                               gold=INTEGER, committed=BOOLEAN), 100)),
    statistics=obj(total_game_time_s=NUMBER, total_earned_gold=INTEGER, total_earned_exp=INTEGER,
                   total_deaths=INTEGER, loot_counts_by_rarity=mapping(INTEGER, 16)),
    ground=array(obj(name=TEXT, rarity=KEY, registered=BOOLEAN), 2000),
    forecast=obj(map=TEXT, current_wave=INTEGER, totals=NUMBERS,
                 waves=array(obj(index=INTEGER, wave=INTEGER, type=KEY, gold=INTEGER,
                                 enemies=array(obj(name=TEXT, count=INTEGER), 256), items=array(PREVIEW, 2000)), 200)),
    chests=array(obj(name=TEXT, contents=array(PREVIEW, 2000)), 100),
    features=mapping(enum("enabled", "partial", "unavailable", "disabled"), 100),
)
ITEM = obj(instance_id=KEY, name=TEXT, template_id=KEY, slot=KEY,
           container=enum("equipment", "inventory", "storage", "carriage"), index=INTEGER, page=INTEGER,
           record_kind=enum("equipment", "other"), ownership=enum("held", "preview", "unknown"),
           settlement=enum("settled", "pending", "unknown", "not_required"),
           rarity=KEY, locked=BOOLEAN, ancient=BOOLEAN, black_mist=BOOLEAN, required_level=INTEGER,
           upgrade_level=INTEGER, sockets=INTEGER, sockets_used=INTEGER, item_level=INTEGER, armor=NUMBER,
           weapon=obj(damage=NUMBER, speed=NUMBER, dps=NUMBER), effect_description=string(1200),
           embedded_items=array(BUILD_SOURCE, 64),
           affixes=array(obj(id=KEY, name=TEXT, value=NUMBER, unit=string(40),
                            roll=obj(quality=NUMBER, low=NUMBER, high=NUMBER)), 128))
FINDING = obj(name=TEXT, template_id=KEY, rarity=KEY, kind=KEY, slot=KEY, map=TEXT, difficulty=KEY,
              boss=TEXT, status=KEY, ancient=BOOLEAN, black_mist=BOOLEAN, market=BOOLEAN, item_level=INTEGER,
              price=INTEGER, wave=INTEGER, time=NUMBER, source=KEY, how=enum("manual", "auto", "unknown"), piece=KEY)
DAMAGE_SOURCE = obj(id=KEY, name=TEXT, actor=KEY, dmg=NUMBER, hits=INTEGER, crits=INTEGER, kills=INTEGER)
RUN = obj(id=KEY, map=TEXT, difficulty=KEY, level=INTEGER, result=enum("clear", "died", "skip", "left", "live", "unknown"),
          partial=BOOLEAN, t0=NUMBER, t1=NUMBER, dur=NUMBER, wave=INTEGER, waves=INTEGER, boss=INTEGER,
          exp=INTEGER, gold=INTEGER, deaths=INTEGER, loot=mapping(INTEGER, 16),
          damage=obj(dmg=NUMBER, hits=INTEGER, crits=INTEGER, kills=INTEGER, active=INTEGER,
                     partial=BOOLEAN, sources=array(DAMAGE_SOURCE, 128)),
          special=mapping(INTEGER, 16), finds=array(FINDING, 100))
LOADOUT = obj(slot=INTEGER, name=TEXT, empty=BOOLEAN, worn=BOOLEAN,
              abilities=array(obj(role=KEY, key=KEY, name=TEXT), 32),
              gear=array(obj(slot=KEY, key=KEY, name=TEXT, rarity=KEY), 32),
              missing=array(obj(slot=KEY, name=TEXT, reason=KEY), 32))
REPORT_INPUT = obj(
    runs=obj(records=array(RUN, 1000), live=RUN),
    combat=obj(coverage_started_at=NUMBER, session_started_at=NUMBER,
               events=array(obj(at=NUMBER, source_id=KEY, source_name=TEXT, actor=KEY,
                                damage=NUMBER, hits=INTEGER, crits=INTEGER, kills=INTEGER), 8192)),
    lineage=obj(draws=array(FINDING, 5000), finds=array(FINDING, 2000)),
    loadouts=obj(slots=array(LOADOUT, 5)),
    status=obj(producer_version=KEY, events=array(obj(kind=KEY, action=KEY, ok=BOOLEAN, map=KEY), 100),
               catalogs=obj(maps=array(obj(key=KEY, name=TEXT, type=KEY, prerequisite=KEY,
                                          entry=array(obj(item=KEY, amount=INTEGER, difficulties=array(KEY, 16)), 32)), 512),
                            potions=array(obj(key=KEY, name=TEXT, description=string(1200),
                                              recipe=obj(quantity=INTEGER, ingredients=array(obj(key=KEY, name=TEXT, amount=INTEGER), 64))), 512),
                            affix_pools=mapping(array(KEY, 128), 128),
                            gem_kinds=array(KEY, 32), rune_rarities=array(KEY, 16)),
               collection_coverage=mapping(enum("complete", "partial", "unknown"), 32)),
)
