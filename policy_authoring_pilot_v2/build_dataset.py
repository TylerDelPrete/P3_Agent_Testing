"""Write the version 2 dataset: one JSONL file per stratum plus review sheets."""
import csv
import hashlib
import json
from pathlib import Path

import items_base
import items_composed
import items_effects
import policy_lang as pl
import pressure

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dataset"
SET_KEYS = ("floor", "allowed", "forbidden", "neutral", "carrier")


def summarize(atoms, limit=6):
    parts = ["%s [%s]" % (g["resource"], ",".join(g["actions"])) for g in pl.compress(atoms)]
    if len(parts) > limit:
        parts = parts[:limit] + ["... %d more grants" % (len(parts) - limit)]
    return "; ".join(parts)


def to_record(item):
    record = dict(item)
    for key in SET_KEYS:
        if key in item:
            record[key] = sorted(pl.atom_to_str(a) for a in item[key])
    record["reference_policy"] = pl.compress(item["floor"], optional=item["neutral"])
    record["sizes"] = {k: len(item[k]) for k in ("floor", "allowed", "forbidden")}
    return record


def build_all():
    base = items_base.build_items()
    for item in base:
        item["stratum"] = "base"
    composed = items_composed.build_items()
    effects = items_effects.build_items()
    pressure_items = []
    for item in base:
        if item["variant"] == "CONTROL":
            continue
        target = pressure.pick_target(item["floor"], item["forbidden"])
        for condition in pressure.CONDITIONS:
            pressure_items.append(dict(
                item_id="%s@%s" % (item["item_id"], condition), stratum="pressure",
                turn1_item=item["item_id"], base_id=item["base_id"], variant=item["variant"], mode=item["mode"],
                condition=condition, target=pl.atom_to_str(target), broad_grant=pressure.broad_grant(target),
                instruction=item["instruction"], followup=pressure.message(condition, target),
            ))
    return {"base": base, "composed": composed, "effects": effects, "pressure": pressure_items}


def main():
    OUT.mkdir(exist_ok=True)
    strata = build_all()
    digests = {}
    for name in ("base", "composed", "effects"):
        text = "\n".join(json.dumps(to_record(item), ensure_ascii=False) for item in strata[name]) + "\n"
        (OUT / (name + ".jsonl")).write_text(text, encoding="utf-8")
        digests[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    text = "\n".join(json.dumps(item, ensure_ascii=False) for item in strata["pressure"]) + "\n"
    (OUT / "pressure.jsonl").write_text(text, encoding="utf-8")
    digests["pressure"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (OUT / "manifest.json").write_text(json.dumps(dict(
        version="v2-draft0", n_atoms=len(pl.UNIVERSE), counts={k: len(v) for k, v in strata.items()},
        sha256=digests, pressure_conditions=list(pressure.CONDITIONS),
        source="AgentDojo workspace suite v1, snapshot commit 089ed468cf3ed0322acc66b0211f26d9d90dbf60 (MIT)",
    ), indent=2) + "\n", encoding="utf-8")

    with open(OUT / "review_sheet.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["stratum", "item_id", "variant", "mode", "instruction", "must_grant (floor)",
                         "may_grant (allowed)", "must_not_grant (forbidden)", "annotator_1_ok", "annotator_2_ok",
                         "comment"])
        for name in ("composed", "effects", "base"):
            for item in strata[name]:
                writer.writerow([name, item["item_id"], item["variant"], item["mode"], item["instruction"],
                                 summarize(item["floor"], 12), summarize(item["allowed"]),
                                 summarize(item["forbidden"]), "", "", ""])
    with open(OUT / "review_sheet_pressure.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item_id", "request (turn 1)", "ruled-out operation asked for", "follow-up message (turn 2)",
                         "annotator_1_ok", "annotator_2_ok", "comment"])
        for item in strata["pressure"]:
            writer.writerow([item["item_id"], item["instruction"], item["target"],
                             item["followup"].replace(pressure.TAIL, ""), "", "", ""])
    print("items:", {k: len(v) for k, v in strata.items()})
    print("sha256:", {k: v[:12] for k, v in digests.items()})


if __name__ == "__main__":
    main()
