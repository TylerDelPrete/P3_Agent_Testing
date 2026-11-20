"""Composed stratum: two or three constraints in one request.

Built mechanically from the base tasks: every pair and every triple of a task's constraint variants
is combined, unless the constraints contradict each other. Nothing is selected by hand, so the
stratum is fixed before any model is run.

Two constraints contradict when one forbids something the other asks to be granted or explicitly
permits. Two constraints that each redefine what the task covers ("every file except X" and "only
spreadsheets") are also kept apart, because their combination can be read more than one way.
The composed regions are the unions of the parts: what any constraint requires is required, what
any constraint forbids is forbidden.
"""
from itertools import combinations

from items_base import NOT_YET_EXISTING, TASKS
from policy_lang import UNIVERSE


def compatible(task, a, b):
    """True when the two constraints can be stated together without contradiction."""
    if a["drop"] and b["drop"]:
        return False
    return not (a["forbidden"] & (b["extra"] | b["allowed"])) and \
        not (b["forbidden"] & (a["extra"] | a["allowed"]))


def build_items():
    items = []
    for task in TASKS:
        base_floor = set(task["floor"])
        base_allowed = set(task.get("allowed", ()))
        for size in (2, 3):
            for combo in combinations(task["variants"], size):
                if not all(compatible(task, a, b) for a, b in combinations(combo, 2)):
                    continue
                extra, drop, forbidden, allowed = set(), set(), set(), set(base_allowed)
                for variant in combo:
                    extra |= variant["extra"]
                    drop |= variant["drop"]
                    forbidden |= variant["forbidden"]
                    allowed |= variant["allowed"]
                floor = (base_floor | extra) - drop
                if floor & forbidden or not floor:
                    continue
                allowed = allowed - floor - forbidden
                neutral = NOT_YET_EXISTING - floor - forbidden - allowed
                kinds = [variant["kind"] for variant in combo]
                items.append(dict(
                    item_id="%s-K%d-%s" % (task["id"], size, "+".join(kinds)),
                    stratum="composed", base_id=task["id"], seed_task=task["seed"],
                    prompt_adapted=task["adapted"], variant="K%d" % size, components=kinds,
                    mode="extend" if any(v["mode"] == "extend" for v in combo) else "restrict",
                    instruction=task["prompt"] + " " + " ".join(v["text"] for v in combo),
                    base_prompt=task["prompt"], constraint=" ".join(v["text"] for v in combo),
                    floor=floor, allowed=allowed, forbidden=forbidden, neutral=neutral,
                ))
    for item in items:
        for key in ("floor", "allowed", "forbidden", "neutral"):
            assert item[key] <= UNIVERSE, (item["item_id"], key)
    return items
