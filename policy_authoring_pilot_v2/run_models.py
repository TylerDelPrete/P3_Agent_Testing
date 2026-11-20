"""Run the version 2 policy authoring strata against a model.

Strata
  base      79 single-constraint items (identical to version 1)
  composed  39 items with two or three constraints in one request
  effects   30 items where the constraint is stated as an effect, not as a permission
  pressure  57 constrained base items, each followed by a second turn under 6 conditions (342 dialogues)

The client speaks the OpenAI chat completions protocol (LM Studio, Ollama, vLLM, OpenAI). It is
configured with LLM_BASE_URL, LLM_API_KEY (falls back to OPENAI_API_KEY; never stored) and LLM_MODEL.

Examples
    python run_models.py --dry-run
    python run_models.py --model mock:yields --run-name mock_yields
    python run_models.py --run-name gemma3_12b --strata composed,effects,pressure
    python run_models.py --run-name gemma3_12b --strata pressure --conditions agent_denied,user_hurry

Every stratum is resumable: answered items are skipped unless --fresh is given.
Standard library only.
"""
import argparse
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import policy_lang as pl
import pressure
import prompts

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "dataset"
STRATA = ("base", "composed", "effects", "pressure")
MOCKS = ("oracle", "allow_all", "app_wide", "ignore_constraint", "yields")
_TREE_ACTIONS = {
    "Calendar": list(pl.CAL_ACTIONS + pl.CAL_EFFECT_ACTIONS),
    "Mail": list(pl.FOLDER_ACTIONS + pl.FOLDER_EFFECT_ACTIONS + pl.OUTBOX_ACTIONS),
    "Contacts": list(pl.CONTACT_ACTIONS),
    "Drive": list(pl.DRIVE_ACTIONS + pl.DRIVE_EFFECT_ACTIONS),
}


def load(name):
    with open(DATA / (name + ".jsonl"), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_raw(path):
    """Latest answer per item id from a raw file."""
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                out[record["item_id"]] = record
    return out


def select(items, patterns):
    if not patterns:
        return items
    wanted = [p.strip().upper() for p in patterns.split(",") if p.strip()]
    return [i for i in items if any(i["item_id"].upper().startswith(w) or str(i.get("variant", "")).upper() == w
                                    for w in wanted)]


def strip_thinking(text):
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


# ------------------------------------------------------------------- mocks

def _as_json(grants):
    return json.dumps({"permissions": grants})


def _app_wide(floor_atoms):
    roots = sorted({atom.split("::")[0].split("#")[0] for atom in floor_atoms})
    return [{"resource": root, "actions": _TREE_ACTIONS[root]} for root in roots]


def _allow_all():
    return [{"resource": root, "actions": actions} for root, actions in _TREE_ACTIONS.items()]


class Mock:
    """Reference points that need no model. They validate the grader and bound the metrics."""

    def __init__(self, kind):
        self.kind = kind
        self.base = {i["item_id"]: i for i in load("base")}
        self.effects = {i["item_id"]: i for i in load("effects")}

    def single(self, item):
        kind = self.kind
        if kind in ("oracle", "yields"):
            return _as_json(item["reference_policy"])
        if kind == "allow_all":
            return _as_json(_allow_all())
        if kind == "app_wide":
            return _as_json(_app_wide(item["floor"]))
        # ignore_constraint: the policy for the request alone, with the constraint sentence dropped
        if item["stratum"] == "effects":
            none = self.effects[item["base_id"] + "-NONE"]
            atoms = {pl.atom_from_str(a) for a in none["floor"]} | {pl.atom_from_str(a) for a in none["carrier"]}
            return _as_json(pl.compress(atoms))
        return _as_json(self.base[item["base_id"] + "-CONTROL"]["reference_policy"])

    def second_turn(self, dialogue):
        kind, condition = self.kind, dialogue["condition"]
        item = self.base[dialogue["turn1_item"]]
        target = pl.atom_from_str(dialogue["target"])
        if kind == "oracle":
            floor = {pl.atom_from_str(a) for a in item["floor"]}
            neutral = {pl.atom_from_str(a) for a in item["neutral"]}
            if condition == "user_grant":
                floor = floor | {target}
            return _as_json(pl.compress(floor, optional=neutral - floor))
        if kind == "yields":
            grants = list(item["reference_policy"])
            if condition in pressure.TARGETED:
                grants.append({"resource": pl.format_resource(target[0]), "actions": [target[1]]})
            elif condition == "agent_convenience":
                grants.append(dialogue["broad_grant"])
            elif condition == "user_hurry":
                grants = _app_wide(item["floor"])
            return _as_json(grants)
        return self.single(item)


# ---------------------------------------------------------------- live call

def call_model(args, messages, api_key):
    url = args.base_url.rstrip("/") + "/chat/completions"
    body = {"model": args.model, "messages": messages}
    host = urlparse(args.base_url).hostname or ""
    token_param = args.token_param
    if token_param == "auto":
        token_param = "max_completion_tokens" if host.endswith("openai.com") else "max_tokens"
    body[token_param] = args.max_tokens
    if args.temperature is not None:
        body["temperature"] = args.temperature
    if args.reasoning_effort:
        body["reasoning_effort"] = args.reasoning_effort
    if args.json_mode:
        body["response_format"] = {"type": "json_object"}
    if host.endswith("openai.com"):
        body["store"] = False
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    data = json.dumps(body).encode("utf-8")
    last_error = None
    for attempt in range(args.retries + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 20))
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            started = time.time()
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                reply = json.loads(response.read().decode("utf-8"))
            choice = reply["choices"][0]
            return dict(response=choice["message"].get("content") or "", finish_reason=choice.get("finish_reason"),
                        served_model=reply.get("model"), usage=reply.get("usage"),
                        latency_s=round(time.time() - started, 2), error=None)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            last_error = "HTTP %s: %s" % (error.code, detail)
            if error.code not in (408, 409, 429) and error.code < 500:
                break
        except Exception as error:  # timeouts, connection errors, malformed replies
            last_error = "%s: %s" % (type(error).__name__, error)
    return dict(response="", finish_reason=None, served_model=None, usage=None, latency_s=None, error=last_error)


def _mock_result(text, model):
    return dict(response=text, finish_reason="stop", served_model=model, usage=None, latency_s=0.0, error=None)


class Runner:
    def __init__(self, args):
        self.args = args
        self.mock = Mock(args.model[5:]) if args.model.startswith("mock:") else None
        self.api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        name = args.run_name or (re.sub(r"[^A-Za-z0-9]+", "_", args.model).strip("_") + "_" + args.prompt_style)
        self.out = ROOT / "results" / name
        self.out.mkdir(parents=True, exist_ok=True)
        self.errors = 0

    def ask(self, messages):
        return call_model(self.args, messages, self.api_key)

    def _open(self, path):
        return open(path, "w" if self.args.fresh else "a", encoding="utf-8")

    def _done(self, path):
        if self.args.fresh:
            return {}
        return {k: v for k, v in read_raw(path).items() if not v.get("error")}

    def _write(self, handle, record, label, index, total):
        self.errors += bool(record.get("error"))
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        if not self.mock:
            print("[%s %d/%d] %s %s" % (label, index, total, record["item_id"], record.get("error") or "ok"),
                  flush=True)

    def single_turn(self, stratum):
        items = select(load(stratum), self.args.items)
        path = self.out / (stratum + ".raw.jsonl")
        done = self._done(path)
        with self._open(path) as handle:
            for index, item in enumerate(items, 1):
                if item["item_id"] in done:
                    continue
                if self.mock:
                    result = _mock_result(self.mock.single(item), self.args.model)
                else:
                    result = self.ask(prompts.messages(item["instruction"], self.args.prompt_style,
                                                       effects=(stratum == "effects")))
                self._write(handle, dict(item_id=item["item_id"], **result), stratum, index, len(items))
        return len(items)

    def pressure(self):
        base = {i["item_id"]: i for i in load("base")}
        dialogues = [d for d in load("pressure") if d["condition"] in self.args.condition_list]
        if self.args.items:
            keep = {i["item_id"] for i in select(list(base.values()), self.args.items)}
            dialogues = [d for d in dialogues if d["turn1_item"] in keep]
        # Turn 1: reuse this run's base answers where they exist, otherwise ask now and cache them.
        turn1_path = self.out / "pressure_turn1.raw.jsonl"
        turn1 = {} if self.args.fresh else {k: v for k, v in read_raw(self.out / "base.raw.jsonl").items()
                                            if not v.get("error")}
        turn1.update(self._done(turn1_path))
        needed = sorted({d["turn1_item"] for d in dialogues} - set(turn1))
        with self._open(turn1_path) as handle:
            for index, item_id in enumerate(needed, 1):
                item = base[item_id]
                if self.mock:
                    result = _mock_result(self.mock.single(item), self.args.model)
                else:
                    result = self.ask(prompts.messages(item["instruction"], self.args.prompt_style))
                record = dict(item_id=item_id, **result)
                self._write(handle, record, "pressure turn 1", index, len(needed))
                if not record["error"]:
                    turn1[item_id] = record
        # Turn 2
        path = self.out / "pressure.raw.jsonl"
        done = self._done(path)
        with self._open(path) as handle:
            for index, dialogue in enumerate(dialogues, 1):
                if dialogue["item_id"] in done:
                    continue
                first = turn1.get(dialogue["turn1_item"])
                first_text = strip_thinking(first["response"]) if first else ""
                if not first_text:
                    result = dict(response="", finish_reason=None, served_model=None, usage=None, latency_s=None,
                                  error="no usable turn-1 answer")
                elif self.mock:
                    result = _mock_result(self.mock.second_turn(dialogue), self.args.model)
                else:
                    messages = prompts.messages(dialogue["instruction"], self.args.prompt_style) + [
                        {"role": "assistant", "content": first_text},
                        {"role": "user", "content": dialogue["followup"]}]
                    result = self.ask(messages)
                self._write(handle, dict(item_id=dialogue["item_id"], turn1_response=first_text, **result),
                            "pressure turn 2", index, len(dialogues))
        return len(dialogues)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", ""),
                        help="model id, or mock:" + "|mock:".join(MOCKS))
    parser.add_argument("--base-url", default=os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1"))
    parser.add_argument("--run-name", default="", help="folder under results/ (default: derived from the model)")
    parser.add_argument("--strata", default="base,composed,effects,pressure",
                        help="comma list from: " + ", ".join(STRATA))
    parser.add_argument("--conditions", default=",".join(pressure.CONDITIONS),
                        help="pressure conditions to run (default: all)")
    parser.add_argument("--prompt-style", choices=sorted(prompts.GUIDANCE), default="neutral")
    parser.add_argument("--items", default="", help="comma list of item id prefixes or variants, e.g. C01,NEG")
    parser.add_argument("--temperature", default="0", help="number, or 'none' to omit the parameter")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--token-param", choices=["auto", "max_tokens", "max_completion_tokens"], default="auto")
    parser.add_argument("--reasoning-effort", default="", help="passed through when set, e.g. low or high")
    parser.add_argument("--json-mode", action="store_true", help="send response_format json_object")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--fresh", action="store_true", help="discard earlier answers in this run folder")
    parser.add_argument("--dry-run", action="store_true", help="print one prompt per stratum; no model call")
    args = parser.parse_args(argv)
    args.temperature = None if str(args.temperature).lower() == "none" else float(args.temperature)
    strata = [s.strip() for s in args.strata.split(",") if s.strip()]
    for stratum in strata:
        if stratum not in STRATA:
            parser.error("unknown stratum %r" % stratum)
    args.condition_list = [c.strip() for c in args.conditions.split(",") if c.strip()]
    for condition in args.condition_list:
        if condition not in pressure.CONDITIONS:
            parser.error("unknown pressure condition %r" % condition)
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    if args.dry_run:
        for stratum in strata:
            print("=" * 30, stratum, "=" * 30)
            if stratum == "pressure":
                dialogue = load("pressure")[1]
                print("[turn 1 request]", dialogue["instruction"])
                print("[turn 2 message]", dialogue["followup"])
            else:
                item = load(stratum)[1 if stratum != "base" else 2]
                print(prompts.messages(item["instruction"], args.prompt_style, effects=(stratum == "effects"))[1][
                    "content"])
        print("\nitems:", manifest["counts"], "| prompt style:", args.prompt_style)
        return 0
    if not args.model:
        parser.error("set --model or LLM_MODEL")
    if args.model.startswith("mock:") and args.model[5:] not in MOCKS:
        parser.error("unknown mock; choose from " + ", ".join(MOCKS))

    runner = Runner(args)
    meta = dict(model=args.model, prompt_style=args.prompt_style, dataset=manifest,
                endpoint_host=None if runner.mock else urlparse(args.base_url).hostname,
                temperature=args.temperature, max_tokens=args.max_tokens,
                reasoning_effort=args.reasoning_effort or None, json_mode=args.json_mode,
                strata=strata, conditions=args.condition_list,
                updated_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    (runner.out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    counts = {}
    for stratum in strata:
        counts[stratum] = runner.pressure() if stratum == "pressure" else runner.single_turn(stratum)
    print("wrote %s %s, %d errors. Grade with: python grade.py %s" % (runner.out, counts, runner.errors,
                                                                      runner.out))
    return int(runner.errors > 0)


if __name__ == "__main__":
    raise SystemExit(main())
