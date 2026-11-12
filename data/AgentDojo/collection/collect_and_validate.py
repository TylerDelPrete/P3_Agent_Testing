#!/usr/bin/env python3
"""AgentDojo static collection + validation (collector-written; no credentials needed).

Stdlib only. PyYAML is NOT required (an optional cross-check is run only if `yaml` is importable).

Safety properties:
  * AgentDojo code is never imported or executed. Python sources are parsed with `ast` only.
  * Registration / benchmark-version membership is derived by a *static simulation* of the module
    import order declared in src/agentdojo/task_suite/load_suites.py (import statements are read
    from the AST; no module body is executed).
  * No models are called, no benchmark is run, no URL found inside repository content is visited.

Usage:
  python collect_and_validate.py collect  --out OUT_DIR [--tarball T.tar.gz] [--tree tree.json]
                                          [--commit-json commit.json] [--retrieved-at ISO_UTC]
  python collect_and_validate.py finalize --out OUT_DIR     # writes manifest.json (after README.md exists)
  python collect_and_validate.py validate --out OUT_DIR     # independent re-read; writes validation_output.txt

`collect` downloads (if not supplied) the codeload tarball for the pinned commit, the GitHub git-tree
listing and commit metadata (unauthenticated public API), verifies every file's git blob SHA-1 against
the tree, writes source_snapshot/ and all derived outputs.
"""
from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import tarfile
import time
import urllib.request
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path, PurePosixPath

REPO_URL = "https://github.com/ethz-spylab/agentdojo"
COMMIT = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"
TARBALL_URL = f"https://codeload.github.com/ethz-spylab/agentdojo/tar.gz/{COMMIT}"
TREE_URL = f"https://api.github.com/repos/ethz-spylab/agentdojo/git/trees/{COMMIT}?recursive=1"
COMMIT_URL = f"https://api.github.com/repos/ethz-spylab/agentdojo/commits/{COMMIT}"
SCHEMA_VERSION = "agentdojo-static-normalized/1.0"
DATASET = "AgentDojo"
PKG_ROOT = "src/agentdojo"
SNAPSHOT_EXCLUDE_PREFIXES = ("runs/",)
ENTRY_MODULE = "agentdojo.task_suite.load_suites"
ALLOWED_REL_TYPES = {
    "task_registered_in_suite", "task_effective_in_benchmark_version", "task_definition_supersedes",
    "task_slot_overwritten_by", "combined_task_component", "task_ground_truth_calls_tool",
    "task_has_evaluator", "task_uses_suite_fixture", "suite_exposes_tool", "suite_uses_fixture_file",
    "fixture_includes_file", "suite_declares_injection_vector", "injection_vector_placeholder_in_fixture",
    "attack_generator_registered",
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_blob_sha1(b: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def fetch(url: str, dest: Path, tries: int = 6) -> None:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "agentdojo-static-collector"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            dest.write_bytes(data)
            return
        except Exception as e:  # network can be flaky; retry
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"download failed for {url}: {last}")


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(jdump(r) + "\n")


def gh_blob_url(path, start=None, end=None) -> str:
    u = f"{REPO_URL}/blob/{COMMIT}/{path}"
    if start:
        u += f"#L{start}" + (f"-L{end}" if end and end != start else "")
    return u


def vstr(v) -> str:
    return ".".join(str(x) for x in v)


class Unresolved(Exception):
    pass


def static_value(node, scopes):
    """Resolve a pure-literal expression statically (constants, tuples/lists, names bound to constants,
    string concatenation, simple f-strings). Anything else raises Unresolved. Nothing is executed."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(static_value(e, scopes) for e in node.elts)
    if isinstance(node, ast.List):
        return [static_value(e, scopes) for e in node.elts]
    if isinstance(node, ast.Name):
        for s in scopes:
            if node.id in s:
                v = s[node.id]
                if isinstance(v, Unresolved):
                    raise v
                return v
        raise Unresolved(f"name {node.id!r} not statically resolvable")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = static_value(node.left, scopes), static_value(node.right, scopes)
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        raise Unresolved("non-string concatenation")
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                if part.conversion != -1 or part.format_spec is not None:
                    raise Unresolved("f-string conversion/format_spec not rendered statically")
                v = static_value(part.value, scopes)
                if not isinstance(v, (str, int)) or isinstance(v, bool):
                    raise Unresolved(f"f-string field of type {type(v).__name__} not rendered statically")
                out.append(str(v))
            else:
                raise Unresolved("unknown f-string part")
        return "".join(out)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join" \
            and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str) \
            and len(node.args) == 1 and not node.keywords:
        seq = static_value(node.args[0], scopes)
        if isinstance(seq, (list, tuple)) and all(isinstance(x, str) for x in seq):
            return node.func.value.value.join(seq)
        raise Unresolved("str.join over non-literal sequence")
    raise Unresolved(f"expression type {type(node).__name__} not statically resolvable")


class Module:
    def __init__(self, name, path, text):
        self.name, self.path, self.text = name, path, text
        self.lines = text.splitlines(keepends=True)
        self.tree = ast.parse(text, filename=path)
        self.consts = {}
        self.import_map = {}
        for st in self.tree.body:
            if isinstance(st, ast.ImportFrom) and st.module and st.level == 0:
                for a in st.names:
                    self.import_map[a.asname or a.name] = (st.module, a.name)

    def segment(self, start, end):
        return "".join(self.lines[start - 1:end])


class Project:
    def __init__(self, files):
        self.files = files
        self.modules = {}

    def mod_path(self, modname):
        rel = modname.replace(".", "/")
        if not rel.startswith("agentdojo"):
            return None
        for p in (f"src/{rel}.py", f"src/{rel}/__init__.py"):
            if p in self.files:
                return p
        return None

    def get(self, modname):
        if modname in self.modules:
            return self.modules[modname]
        p = self.mod_path(modname)
        if p is None:
            return None
        m = Module(modname, p, self.files[p].decode("utf-8"))
        self.modules[modname] = m
        return m

    def resolve_name(self, mod, name, depth=0):
        if depth > 6:
            raise Unresolved("import chain too deep")
        if name in mod.consts:
            v = mod.consts[name]
            if isinstance(v, Unresolved):
                raise v
            return v
        for st in mod.tree.body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) \
                    and st.targets[0].id == name:
                try:
                    v = static_value(st.value, [mod.consts])
                except Unresolved as e:
                    v = e
                mod.consts[name] = v
                if isinstance(v, Unresolved):
                    raise v
                return v
        if name in mod.import_map:
            srcmod, attr = mod.import_map[name]
            m2 = self.get(srcmod)
            if m2 is None:
                raise Unresolved(f"{name} imported from non-repo module {srcmod}")
            return self.resolve_name(m2, attr, depth + 1)
        raise Unresolved(f"module constant {name!r} not found")


class LazyScope(dict):
    def __init__(self, project, mod):
        super().__init__()
        self.project, self.mod = project, mod

    def __contains__(self, k):
        try:
            self[k]
            return True
        except Unresolved:
            return False

    def __getitem__(self, k):
        return self.project.resolve_name(self.mod, k)


# ----------------------------------------------------------------- static import simulation

class Registry:
    def __init__(self):
        self.slots = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))  # suite->kind->id->slot->def
        self.events = []

    def put(self, suite, kind, task_id, slot, def_id, how, order):
        prev = self.slots[suite][kind][task_id].get(slot)
        self.slots[suite][kind][task_id][slot] = def_id
        self.events.append(dict(order=order, suite=suite, kind=kind, task_id=task_id, slot=slot,
                                def_id=def_id, how=how, overwrote=prev))
        return prev


class Simulator:
    """Walks module top-level statements in import order (as Python would) without executing them."""

    def __init__(self, project):
        self.p = project
        self.loaded, self.loading = [], set()
        self.reg = Registry()
        self.defs = OrderedDict()
        self.order = 0
        self.skipped_classes = []
        self.combinators = {}
        self.dormant = False  # True while loading modules NOT reachable from the load_suites import graph

    def suite_of_object(self, mod, obj_name):
        if obj_name in mod.import_map:
            srcmod, attr = mod.import_map[obj_name]
            m = re.match(r"agentdojo\.default_suites\.v1\.(\w+)\.task_suite$", srcmod)
            if m and attr == "task_suite":
                return m.group(1)
        m = re.match(r"agentdojo\.default_suites\.v1\.(\w+)\.task_suite$", mod.name)
        if m and obj_name == "task_suite":
            return m.group(1)
        return None

    def load(self, modname):
        parts = modname.split(".")
        for i in range(1, len(parts) + 1):
            self._load_one(".".join(parts[:i]))

    def _load_one(self, modname):
        if modname in self.loaded or modname in self.loading:
            return
        mod = self.p.get(modname)
        if mod is None:
            return
        self.loading.add(modname)
        self.loaded.append(modname)
        for st in mod.tree.body:
            self.statement(mod, st)
        self.loading.discard(modname)

    def statement(self, mod, st):
        if isinstance(st, ast.Import):
            for a in st.names:
                if a.name.startswith("agentdojo"):
                    self.load(a.name)
        elif isinstance(st, ast.ImportFrom):
            if st.module and st.level == 0 and st.module.startswith("agentdojo"):
                self.load(st.module)
                for a in st.names:
                    sub = f"{st.module}.{a.name}"
                    if self.p.mod_path(sub):
                        self.load(sub)
        elif isinstance(st, ast.ClassDef):
            self.classdef(mod, st)
        elif isinstance(st, ast.Assign):
            v = st.value
            if isinstance(v, ast.Call) and isinstance(v.func, ast.Subscript) and \
                    isinstance(v.func.value, ast.Name) and v.func.value.id == "TaskCombinator" and v.args \
                    and isinstance(v.args[0], ast.Name):
                suite = self.suite_of_object(mod, v.args[0].id)
                for t in st.targets:
                    if isinstance(t, ast.Name):
                        self.combinators[(mod.name, t.id)] = suite
        elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            self.combinator_call(mod, st)

    def combinator_suite(self, mod, name):
        if (mod.name, name) in self.combinators:
            return self.combinators[(mod.name, name)]
        if name in mod.import_map:
            return self.combinators.get(mod.import_map[name])
        return None

    def decorator_info(self, mod, d):
        src = ast.get_source_segment(mod.text, d)
        node, call_args, call_kw = d, [], {}
        if isinstance(d, ast.Call):
            node, call_args, call_kw = d.func, d.args, {k.arg: k.value for k in d.keywords}
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            return None
        meth = node.attr
        if meth not in ("register_user_task", "update_user_task", "register_injection_task", "update_injection_task"):
            return None
        suite = self.suite_of_object(mod, node.value.id)
        if suite is None:
            raise RuntimeError(f"cannot resolve suite object {node.value.id} in {mod.path}")
        kind = "user_task" if "user" in meth else "injection_task"
        scope = LazyScope(self.p, mod)
        if meth.startswith("register"):
            return suite, kind, (1, 0, 0), "register", None, src
        vnode = call_args[0] if call_args else call_kw.get("benchmark_version")
        slot = tuple(static_value(vnode, [scope]))
        new_flag = False
        if len(call_args) > 1:
            new_flag = bool(static_value(call_args[1], [scope]))
        elif "new" in call_kw:
            new_flag = bool(static_value(call_kw["new"], [scope]))
        return suite, kind, slot, "update", new_flag, src

    def classdef(self, mod, cls):
        regs = [r for r in (self.decorator_info(mod, d) for d in cls.decorator_list) if r]
        if not regs:
            if re.match(r"(UserTask|InjectionTask)\d+$", cls.name):
                self.skipped_classes.append([mod.path, cls.name, cls.lineno, "no registration decorator"])
            return
        if len(regs) > 1:
            raise RuntimeError(f"multiple registration decorators on {cls.name}")
        suite, kind, slot, how, new_flag, dec_src = regs[0]
        prefix = "UserTask" if kind == "user_task" else "InjectionTask"
        m = re.match(rf"{prefix}(\d+)$", cls.name)
        task_id = f"{kind}_{int(m.group(1))}"
        folder = mod.path.split("/")[3]
        def_id = f"agentdojo/{suite}/{task_id}@{folder}"
        if def_id in self.defs:
            raise RuntimeError(f"duplicate def id {def_id}")
        self.order += 1
        start = min([x.lineno for x in cls.decorator_list] + [cls.lineno])
        d = dict(def_id=def_id, suite=suite, kind=kind, task_id=task_id, slot=slot, how=how, new_flag=new_flag,
                 decorator_source=dec_src, module=mod.name, path=mod.path, symbol=cls.name, start=start,
                 end=cls.end_lineno, node=cls, mod=mod, order=self.order, definition_kind="class", folder=folder,
                 reachable=not self.dormant)
        if how == "update" and task_id not in self.reg.slots[suite][kind] and not (kind == "injection_task" and new_flag):
            d["registration_error"] = "update of unknown task id (source would raise ValueError at import)"
        self.defs[def_id] = d
        d["overwrote_slot_def"] = self.reg.put(suite, kind, task_id, slot, def_id, how, self.order)

    def combinator_call(self, mod, st):
        call, f = st.value, st.value.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.attr in ("create_combined_task", "update_combined_task")):
            return
        suite = self.combinator_suite(mod, f.value.id)
        if suite is None:
            raise RuntimeError(f"unknown combinator {f.value.id} in {mod.path}")
        scope = LazyScope(self.p, mod)
        name = static_value(call.args[0], [scope])
        kw = {k.arg: k.value for k in call.keywords}
        comps = [self.component_ref(mod, a, suite, scope) for a in call.args[1:3]]
        if f.attr == "create_combined_task":
            slot, how = (1, 0, 0), "register (TaskCombinator.create_combined_task)"
        else:
            slot, how = tuple(static_value(kw["benchmark_version"], [scope])), "update (TaskCombinator.update_combined_task)"
        prompt_node = kw.get("prompt")
        task_id = f"user_task_{int(re.match(r'UserTask(\d+)$', name).group(1))}"
        folder = mod.path.split("/")[3]
        def_id = f"agentdojo/{suite}/{task_id}@{folder}"
        if def_id in self.defs:
            raise RuntimeError(f"duplicate def id {def_id}")
        self.order += 1
        d = dict(def_id=def_id, suite=suite, kind="user_task", task_id=task_id, slot=slot, how=how, new_flag=None,
                 decorator_source=None, module=mod.name, path=mod.path, symbol=name, start=st.lineno,
                 end=st.end_lineno, node=call, mod=mod, order=self.order, definition_kind="combinator_call",
                 folder=folder, components=comps, prompt_node=prompt_node, reachable=not self.dormant)
        self.defs[def_id] = d
        d["overwrote_slot_def"] = self.reg.put(suite, "user_task", task_id, slot, def_id, how, self.order)

    def component_ref(self, mod, a, suite, scope):
        src = ast.get_source_segment(mod.text, a)
        slots = self.reg.slots[suite]["user_task"]
        if isinstance(a, ast.Subscript) and isinstance(a.value, ast.Attribute) and a.value.attr == "user_tasks":
            tid = static_value(a.slice, [scope])
            s = max(x for x in slots[tid] if x <= (1, 0, 0))
            return dict(expr=src, task_id=tid, rule="TaskSuite.user_tasks property on base suite object (benchmark_version 1.0.0): highest slot <= 1.0.0 at this point of import",
                        resolved_slot=vstr(s), def_id=slots[tid][s])
        if isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr == "get_latest_user_task_by_id":
            tid = static_value(a.args[0], [scope])
            v = tuple(static_value(a.args[1], [scope]))
            s = max(x for x in slots[tid] if x < v)
            return dict(expr=src, task_id=tid, rule=f"get_latest_user_task_by_id: highest slot < {vstr(v)} at this point of import",
                        resolved_slot=vstr(s), def_id=slots[tid][s])
        if isinstance(a, ast.Subscript) and isinstance(a.value, ast.Subscript) and \
                isinstance(a.value.value, ast.Attribute) and a.value.value.attr == "_user_tasks":
            tid = static_value(a.value.slice, [scope])
            v = tuple(static_value(a.slice, [scope]))
            return dict(expr=src, task_id=tid, rule=f"_user_tasks[id][{vstr(v)}]: exact slot", resolved_slot=vstr(v), def_id=slots[tid][v])
        raise RuntimeError(f"unsupported combinator component expression {src} in {mod.path}")


# --------------------------------------------------------------------------- task extraction

BASE_DEFAULTS = {}


def load_base_defaults(p):
    mod = p.get("agentdojo.base_tasks")
    for cls in mod.tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name in ("BaseUserTask", "BaseInjectionTask"):
            for st in cls.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
                    try:
                        val = static_value(st.value, [])
                    except Unresolved:
                        val = ast.get_source_segment(mod.text, st.value)
                    BASE_DEFAULTS[(cls.name, st.target.id)] = dict(declared_in=f"{mod.path}:{st.lineno}", class_=cls.name, value=val)


def class_assigns(mod, cls, outer):
    scope, res = {}, OrderedDict()
    for st in cls.body:
        tgt, val = None, None
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            tgt, val = st.targets[0].id, st.value
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
            tgt, val = st.target.id, st.value
        if tgt is None:
            continue
        entry = dict(line_start=st.lineno, line_end=st.end_lineno)
        if tgt == "DIFFICULTY":
            entry.update(value=ast.get_source_segment(mod.text, val), resolution="enum_reference_source_text")
            scope[tgt] = Unresolved("enum")
        else:
            try:
                v = static_value(val, [scope] + outer)
                scope[tgt] = v
                entry.update(value=list(v) if isinstance(v, tuple) else v,
                             resolution="literal" if isinstance(val, ast.Constant) else "static_expression")
            except Unresolved as e:
                scope[tgt] = e
                entry.update(value=None, resolution="unresolved", reason=str(e), source_text=mod.segment(st.lineno, st.end_lineno))
        res[tgt] = entry
    return res


def ground_truth_calls(fn):
    calls, issues = [], []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "FunctionCall":
            fnode = {k.arg: k.value for k in n.keywords}.get("function")
            if isinstance(fnode, ast.Constant) and isinstance(fnode.value, str):
                calls.append(dict(function=fnode.value, line=n.lineno))
            else:
                issues.append(dict(line=n.lineno, reason="FunctionCall.function is not a string literal"))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "ground_truth":
            issues.append(dict(line=n.lineno, reason="ground_truth delegates to another task's ground_truth"))
    calls.sort(key=lambda c: c["line"])
    return calls, issues


# ------------------------------------------------------------------------------- tools

def parse_docstring(doc):
    desc, params, ret, cur = [], OrderedDict(), None, None
    for ln in doc.splitlines():
        m = re.match(r"\s*:param\s+(\w+):\s?(.*)$", ln)
        r = re.match(r"\s*:returns?:\s?(.*)$", ln)
        if m:
            cur = ("param", m.group(1)); params[m.group(1)] = m.group(2).strip()
        elif r:
            cur = ("return", None); ret = r.group(1).strip()
        elif cur and ln.strip():
            if cur[0] == "param":
                params[cur[1]] = (params[cur[1]] + " " + ln.strip()).strip()
            else:
                ret = ((ret or "") + " " + ln.strip()).strip()
        elif cur is None:
            desc.append(ln)
    return "\n".join(desc).strip(), params, ret


def extract_tools(p, suites):
    tools, suite_tools, rels = OrderedDict(), OrderedDict(), []
    for suite in suites:
        mod = p.get(f"agentdojo.default_suites.v1.{suite}.task_suite")
        tl = [st for st in mod.tree.body if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TOOLS" for t in st.targets)][-1]
        suite_tools[suite] = dict(path=mod.path, start=tl.lineno, end=tl.end_lineno, tools=[])
        for e in tl.value.elts:
            if not isinstance(e, ast.Name):
                raise RuntimeError("non-name TOOLS element")
            srcmod, attr = mod.import_map[e.id]
            tmod = p.get(srcmod)
            fn = next(st for st in tmod.tree.body if isinstance(st, ast.FunctionDef) and st.name == attr)
            tool_id = f"{tmod.path}::{attr}"
            if tool_id not in tools:
                doc = ast.get_docstring(fn, clean=True)
                desc, pdocs, ret_doc = parse_docstring(doc or "")
                a = fn.args
                pos = a.posonlyargs + a.args
                defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
                args, deps = [], []
                for arg, dflt in list(zip(pos, defaults)) + list(zip(a.kwonlyargs, a.kw_defaults)):
                    ann = ast.get_source_segment(tmod.text, arg.annotation) if arg.annotation is not None else None
                    depm = re.search(r"Depends\(\s*[\"']([^\"']+)[\"']\s*\)", ann or "")
                    if depm:
                        deps.append(OrderedDict(name=arg.arg, annotation=ann, env_dependency=depm.group(1)))
                        continue
                    args.append(OrderedDict(name=arg.arg, annotation=ann,
                                            default=ast.get_source_segment(tmod.text, dflt) if dflt is not None else None,
                                            required=dflt is None, docstring_description=pdocs.get(arg.arg),
                                            in_runtime_schema=arg.arg in pdocs))
                start = min([x.lineno for x in fn.decorator_list] + [fn.lineno])
                notes = [
                    "description_static = docstring text before the first ':param'/':return' field (collector parse). At runtime "
                    "functions_runtime.make_function builds the description with docstring_parser (short + long description) and "
                    "replaces 'None' with 'null'; that runtime string was not computed.",
                    "Arguments annotated Annotated[..., Depends(...)] are environment injections, not model-visible arguments.",
                    "Runtime JSON schema is a Pydantic model built by make_function/_parse_args from documented params only "
                    "(in_runtime_schema); types are kept as annotation source text, no JSON schema was computed.",
                ]
                if any(not x["in_runtime_schema"] for x in args):
                    notes.append("At least one non-Depends argument has no ':param' docstring entry and would be absent from the runtime schema.")
                tools[tool_id] = OrderedDict(
                    tool_id=tool_id, dataset=DATASET, name=attr, description_static=desc or None, docstring_raw=doc,
                    arguments=args, environment_dependencies=deps,
                    return_annotation=ast.get_source_segment(tmod.text, fn.returns) if fn.returns is not None else None,
                    return_docstring=ret_doc,
                    signature_source=tmod.segment(start, fn.body[0].lineno - 1).rstrip("\n"),
                    suites=[], benchmark_versions="all (TOOLS lists are defined once in default_suites/v1/<suite>/task_suite.py; get_new_version deep-copies the suite and does not change tools)",
                    provenance=OrderedDict(repository_url=REPO_URL, commit_hash=COMMIT, source_path=tmod.path, symbol=attr,
                                           start_line=start, end_line=fn.end_lineno, source_url=gh_blob_url(tmod.path, start, fn.end_lineno)),
                    extraction_notes=notes, unresolved_fields=["runtime_json_schema", "runtime_description_string"])
            if suite not in tools[tool_id]["suites"]:
                tools[tool_id]["suites"].append(suite)
            suite_tools[suite]["tools"].append(dict(name=attr, tool_id=tool_id, list_line=e.lineno))
            rels.append(dict(type="suite_exposes_tool", source=f"suite:{suite}", target=f"tool:{tool_id}",
                             evidence=dict(source_path=mod.path, line=e.lineno, symbol="TOOLS"),
                             basis="TOOLS list passed to TaskSuite(...) via make_function"))
    return tools, suite_tools, rels


# --------------------------------------------------------------------- fixtures / vectors

YAML_ESC = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
            "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029"}


def yaml_dq_unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            n = s[i + 1]
            if n in YAML_ESC:
                out.append(YAML_ESC[n]); i += 2
            elif n in "xuU":
                w = {"x": 2, "u": 4, "U": 8}[n]
                out.append(chr(int(s[i + 2:i + 2 + w], 16))); i += 2 + w
            else:
                raise ValueError(f"unsupported escape \\{n}")
        else:
            out.append(c); i += 1
    return "".join(out)


def parse_injection_vectors(text, path):
    """Minimal parser for the flat 2-level mapping in injection_vectors.yaml; refuses anything else."""
    vecs, cur = OrderedDict(), None
    for ln_no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_]+):\s*$", line)
        if m:
            cur = m.group(1)
            if cur in vecs:
                raise ValueError(f"duplicate vector {cur} in {path}")
            vecs[cur] = dict(vector_id=cur, line=ln_no)
            continue
        m = re.match(r"^\s{2}(description|default):\s*(.*)$", line)
        if m and cur:
            val = m.group(2)
            if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
                v = yaml_dq_unescape(val[1:-1])
            elif len(val) >= 2 and val[0] == "'" and val[-1] == "'":
                v = val[1:-1].replace("''", "'")
            elif val and not re.search(r"[:#{}\[\]&*!|>%@`\"']", val):
                v = val
            else:
                raise ValueError(f"unsupported scalar at {path}:{ln_no}")
            vecs[cur][m.group(1)] = v
            vecs[cur][m.group(1) + "_line"] = ln_no
            continue
        raise ValueError(f"unsupported line {path}:{ln_no}: {line!r}")
    return vecs


def fixture_files_for_suite(files, suite):
    base = f"{PKG_ROOT}/data/suites/{suite}"
    env = f"{base}/environment.yaml"
    incl = []
    for ln_no, line in enumerate(files[env].decode("utf-8").splitlines(), 1):
        m = re.search(r"!include\s+(\S+)", line)
        if m:
            incl.append(dict(path=str(PurePosixPath(base) / m.group(1)), line=ln_no))
    return env, f"{base}/injection_vectors.yaml", incl


# ------------------------------------------------------------------------------- attacks

def extract_attacks(p):
    classes = OrderedDict()
    for modname in ("agentdojo.attacks.base_attacks", "agentdojo.attacks.baseline_attacks",
                    "agentdojo.attacks.dos_attacks", "agentdojo.attacks.important_instructions_attacks"):
        mod = p.get(modname)
        for st in mod.tree.body:
            if isinstance(st, ast.ClassDef):
                classes[st.name] = (mod, st)

    def cls_attr(name, attr):
        mod, st = classes[name]
        for s in st.body:
            if isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == attr for t in s.targets):
                return mod, s
        return None

    def bases(name):
        return [b.id for b in classes[name][1].bases if isinstance(b, ast.Name)]

    def mro(name):
        seq = [name]
        for b in bases(name):
            if b in classes:
                seq += [x for x in mro(b) if x not in seq]
        return seq

    out = []
    for name, (mod, st) in classes.items():
        if not any(isinstance(d, ast.Name) and d.id == "register_attack" for d in st.decorator_list):
            continue
        nm = cls_attr(name, "name")
        attack_name = static_value(nm[1].value, []) if nm else None
        template, tsrc = None, None
        for c in mro(name):
            cmod, cst = classes[c]
            for attr in ("_JB_STRING", "_DOS_STRING"):
                r = cls_attr(c, attr)
                if r:
                    template = static_value(r[1].value, [])
                    tsrc = dict(source_path=r[0].path, start_line=r[1].lineno, end_line=r[1].end_lineno, symbol=f"{c}.{attr}")
                    break
            if template is None:
                init = next((s for s in cst.body if isinstance(s, ast.FunctionDef) and s.name == "__init__"), None)
                if init:
                    for n in ast.walk(init):
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "__init__" \
                                and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                            template = n.args[0].value
                            tsrc = dict(source_path=cmod.path, start_line=n.args[0].lineno, end_line=n.args[0].end_lineno,
                                        symbol=f"{c}.__init__ (literal passed to super().__init__)")
                            break
            if template is not None:
                break
        start = min([d.lineno for d in st.decorator_list] + [st.lineno])
        notes = ["generator_template is attack-generator SOURCE TEXT with runtime placeholders; it is NOT a concrete payload. "
                 "Concrete injections are produced at runtime per (user task, injection task, injection candidate vector, model name) "
                 "by the attack's attack() method and BaseAttack.get_injection_candidates (which executes the user task ground truth).",
                 "Template found by following the in-repo class hierarchy statically (nearest _JB_STRING/_DOS_STRING or literal passed to super().__init__)."]
        if template is None:
            notes.append("No static template: attack is interactive or computed (see source).")
        out.append(OrderedDict(
            attack_id=f"attack:{attack_name}", attack_name=attack_name, class_name=name, bases=bases(name),
            in_repo_mro=mro(name), generator_template=template, generator_template_source=tsrc,
            generator_template_placeholders=sorted(set(re.findall(r"\{(\w+)\}", template))) if template else None,
            is_published_payload=False, notes=notes,
            provenance=OrderedDict(repository_url=REPO_URL, commit_hash=COMMIT, source_path=mod.path, symbol=name,
                                   start_line=start, end_line=st.end_lineno, source_url=gh_blob_url(mod.path, start, st.end_lineno))))
    return out


def parse_benchmark_versions(p):
    mod = p.get(ENTRY_MODULE)
    suite_vars, versions = {}, OrderedDict()
    for st in mod.tree.body:
        tgt = None
        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            tgt = st.target.id
        elif isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
            tgt = st.targets[0].id
        if tgt and re.match(r"_V[\d_]+_SUITES$", tgt):
            mapping = OrderedDict()
            for k, v in zip(st.value.keys, st.value.values):
                sname = static_value(k, [])
                if isinstance(v, ast.Name):
                    ver, expr = (1, 0, 0), v.id + "  (base suite object; TaskSuite default benchmark_version=(1, 0, 0))"
                elif isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "get_new_version":
                    ver, expr = tuple(static_value(v.args[0], [])), ast.get_source_segment(mod.text, v)
                else:
                    raise RuntimeError("unsupported suite mapping")
                mapping[sname] = dict(suite_version=vstr(ver), expr=expr, line=v.lineno)
            suite_vars[tgt] = mapping
        if tgt == "_SUITES":
            d = st.value.args[1]
            for k, v in zip(d.keys, d.values):
                versions[static_value(k, [])] = v.id
    return OrderedDict((vn, dict(variable=var, suites=suite_vars[var])) for vn, var in versions.items()), mod.path


# ------------------------------------------------------------------------------- collect

def read_sources(args, out):
    work = out / "_download_cache"
    tb = Path(args.tarball) if args.tarball else None
    tree_p = Path(args.tree) if args.tree else None
    commit_p = Path(args.commit_json) if args.commit_json else None
    if None in (tb, tree_p, commit_p):
        work.mkdir(exist_ok=True)
        if tb is None:
            tb = work / "src.tar.gz"; fetch(TARBALL_URL, tb)
        if tree_p is None:
            tree_p = work / "tree.json"; fetch(TREE_URL, tree_p)
        if commit_p is None:
            commit_p = work / "commit.json"; fetch(COMMIT_URL, commit_p)
    return tb, json.loads(tree_p.read_text(encoding="utf-8")), json.loads(commit_p.read_text(encoding="utf-8"))


def collect(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    retrieved_at = args.retrieved_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tb, tree, commit_meta = read_sources(args, out)
    if commit_meta["sha"] != COMMIT or tree.get("truncated") or tree.get("sha") not in (COMMIT, commit_meta["commit"]["tree"]["sha"]):
        raise SystemExit("commit/tree metadata does not match pinned commit")
    tree_blobs = {t["path"]: t for t in tree["tree"] if t["type"] == "blob"}
    tar_sha256 = sha256_bytes(tb.read_bytes())
    files, runs_files, blob_mismatch, symlinks = {}, {}, [], []
    with tarfile.open(tb, "r:gz") as t:
        if t.pax_headers.get("comment") != COMMIT:
            raise SystemExit("tarball pax comment does not match pinned commit")
        for m in t.getmembers():
            parts = PurePosixPath(m.name).parts
            if len(parts) < 2:
                continue
            rel = "/".join(parts[1:])
            if rel.startswith("/") or ".." in PurePosixPath(rel).parts:
                raise SystemExit(f"unsafe path in tarball: {m.name}")
            if m.issym():
                data = m.linkname.encode(); symlinks.append(rel)
            elif m.isfile():
                data = t.extractfile(m).read()
            else:
                continue
            e = tree_blobs.get(rel)
            if e is None or e["sha"] != git_blob_sha1(data):
                blob_mismatch.append(rel)
            (runs_files if rel.startswith(SNAPSHOT_EXCLUDE_PREFIXES) else files)[rel] = data
    missing_from_tar = sorted(set(tree_blobs) - set(files) - set(runs_files))
    snap = out / "source_snapshot"
    for rel, data in files.items():
        dest = snap / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    (out / "git_tree_listing.json").write_text(json.dumps(tree, indent=1), encoding="utf-8")
    (out / "git_commit_metadata.json").write_text(json.dumps(commit_meta, indent=1), encoding="utf-8")

    # runs/ inventory: path-derived fields + 4 metadata keys only. messages/injections text/utility/security NOT read out.
    runs_rows = []
    for rel in sorted(runs_files):
        data = runs_files[rel]
        parts = rel.split("/")
        row = OrderedDict(path=rel, bytes=len(data), sha256=sha256_bytes(data), git_blob_sha1_verified=rel not in blob_mismatch,
                          pipeline_dir=parts[1] if len(parts) > 2 else None, suite_dir=parts[2] if len(parts) > 3 else None,
                          task_dir=parts[3] if len(parts) > 4 else None, attack_dir=parts[4] if len(parts) > 5 else None,
                          file_stem=PurePosixPath(rel).stem, json_parse_ok=None, json_benchmark_version=None,
                          json_agentdojo_package_version=None, json_evaluation_timestamp=None, json_injection_keys_count=None)
        if rel.endswith(".json"):
            try:
                j = json.loads(data.decode("utf-8"))
                row["json_parse_ok"] = True
                row["json_benchmark_version"] = j.get("benchmark_version")
                row["json_agentdojo_package_version"] = j.get("agentdojo_package_version")
                row["json_evaluation_timestamp"] = j.get("evaluation_timestamp")
                inj = j.get("injections")
                row["json_injection_keys_count"] = len(inj) if isinstance(inj, dict) else None
            except Exception:
                row["json_parse_ok"] = False
        runs_rows.append(row)
    with (out / "runs_inventory.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(runs_rows[0].keys())); w.writeheader(); w.writerows(runs_rows)

    # ---- static analysis
    p = Project(files)
    load_base_defaults(p)
    sim = Simulator(p)
    sim.load(ENTRY_MODULE)
    # registry state reachable from the official entry point (frozen copy)
    reach_slots = {s: {k: {t: dict(v) for t, v in kd.items()} for k, kd in sd.items()} for s, sd in sim.reg.slots.items()}
    reachable_modules = list(sim.loaded)
    # task modules present in the repo but not reachable from load_suites.py: parsed for completeness, flagged dormant
    sim.dormant = True
    dormant_modules = []
    for path in sorted(files):
        if path.startswith(f"{PKG_ROOT}/default_suites/") and path.endswith(".py"):
            modname = path[len("src/"):-3].replace("/", ".")
            if modname.endswith(".__init__"):
                modname = modname[: -len(".__init__")]
            if modname not in sim.loaded:
                dormant_modules.append(modname)
                sim.load(modname)
    versions, versions_path = parse_benchmark_versions(p)
    suites = sorted({d["suite"] for d in sim.defs.values()})
    eff = OrderedDict()
    for bv, info in versions.items():
        for suite, sinfo in info["suites"].items():
            sv = tuple(int(x) for x in sinfo["suite_version"].split("."))
            res = dict(suite_version=sinfo["suite_version"])
            for kind in ("user_task", "injection_task"):
                res[kind] = OrderedDict()
                for tid, slots in reach_slots.get(suite, {}).get(kind, {}).items():
                    c = [s for s in slots if s <= sv]
                    if c:
                        res[kind][tid] = slots[max(c)]
            eff[(bv, suite)] = res
    def_versions = defaultdict(list)
    for (bv, suite), r in eff.items():
        for kind in ("user_task", "injection_task"):
            for tid, did in r[kind].items():
                if bv not in def_versions[did]:
                    def_versions[did].append(bv)
    tools, suite_tools, tool_rels = extract_tools(p, suites)
    tool_names_by_suite = {s: {t["name"] for t in st["tools"]} for s, st in suite_tools.items()}
    attacks = extract_attacks(p)

    fixtures, vector_rows, fixture_rels = OrderedDict(), [], []
    for suite in suites:
        env, vec, incl = fixture_files_for_suite(files, suite)
        fx = dict(environment=env, injection_vectors=vec, includes=[i["path"] for i in incl])
        fixtures[suite] = fx
        for fpath in [env, vec] + fx["includes"]:
            fixture_rels.append(dict(type="suite_uses_fixture_file", source=f"suite:{suite}", target=f"file:{fpath}",
                                     evidence=dict(source_path=f"{PKG_ROOT}/task_suite/task_suite.py",
                                                   symbol="read_suite_file / load_and_inject_default_environment / get_injection_vector_defaults"),
                                     basis="TaskSuite reads data/suites/<suite>/environment.yaml (resolving !include) and injection_vectors.yaml"))
        for i in incl:
            fixture_rels.append(dict(type="fixture_includes_file", source=f"file:{env}", target=f"file:{i['path']}",
                                     evidence=dict(source_path=env, line=i["line"]), basis="!include tag (yaml_loader.ImportLoader)"))
        vecs = parse_injection_vectors(files[vec].decode("utf-8"), vec)
        ftexts = {fp: files[fp].decode("utf-8").splitlines() for fp in [env] + fx["includes"]}
        all_ph = set()
        for lines in ftexts.values():
            for ln in lines:
                all_ph |= set(re.findall(r"\{([A-Za-z0-9_]+)\}", ln))
        no_ph = []
        for vid, v in vecs.items():
            locs = [dict(path=fp, line=i) for fp, lines in ftexts.items() for i, ln in enumerate(lines, 1) if "{" + vid + "}" in ln]
            if not locs:
                no_ph.append(vid)
            vector_rows.append(OrderedDict(
                vector_id=f"{suite}:{vid}", suite=suite, injection_vector=vid, description=v.get("description"),
                default=v.get("default"), placeholder_locations=locs,
                provenance=OrderedDict(repository_url=REPO_URL, commit_hash=COMMIT, source_path=vec, start_line=v["line"],
                                       end_line=max(v.get("description_line", v["line"]), v.get("default_line", v["line"]))),
                notes=["Source fact: named str.format placeholder in the suite environment fixture plus its default (non-attack) fill value. "
                       "Defaults are fixture text, not attack payloads; treat as untrusted data. All benchmark versions share these fixture files at this commit."]))
            fixture_rels.append(dict(type="suite_declares_injection_vector", source=f"suite:{suite}", target=f"vector:{suite}:{vid}",
                                     evidence=dict(source_path=vec, line=v["line"]), basis="injection_vectors.yaml key"))
            for l in locs:
                fixture_rels.append(dict(type="injection_vector_placeholder_in_fixture", source=f"vector:{suite}:{vid}", target=f"file:{l['path']}",
                                         evidence=dict(source_path=l["path"], line=l["line"]), basis="literal '{" + vid + "}' format field in fixture text"))
        fx.update(vector_count=len(vecs), placeholders_without_vector=sorted(all_ph - set(vecs)), vectors_without_placeholder=no_ph)

    # ---- task records
    raw_rows, norm_rows, rels = [], [], list(tool_rels) + fixture_rels
    for a in attacks:
        rels.append(dict(type="attack_generator_registered", source=a["attack_id"], target="registry:agentdojo.attacks.attack_registry.ATTACKS",
                         evidence=dict(source_path=a["provenance"]["source_path"], line=a["provenance"]["start_line"]), basis="@register_attack decorator"))
    defs = sim.defs
    extracted = {}
    for did, d in defs.items():
        if d["definition_kind"] == "class":
            cls = d["node"]
            meths = {s.name: dict(start=min([x.lineno for x in s.decorator_list] + [s.lineno]), end=s.end_lineno)
                     for s in cls.body if isinstance(s, ast.FunctionDef)}
            gt = next((s for s in cls.body if isinstance(s, ast.FunctionDef) and s.name == "ground_truth"), None)
            calls, issues = ground_truth_calls(gt) if gt else ([], [])
            extracted[did] = dict(consts=class_assigns(d["mod"], cls, [LazyScope(p, d["mod"])]), methods=meths, gt_calls=calls, gt_issues=issues)

    def task_text(did):
        d = defs[did]
        if d["definition_kind"] == "class":
            c = extracted[did]["consts"].get("PROMPT" if d["kind"] == "user_task" else "GOAL")
            return c["value"] if c else None
        return combined_prompt(did)[0]

    def combined_prompt(did):
        d = defs[did]
        if d["prompt_node"] is not None:
            try:
                return static_value(d["prompt_node"], [LazyScope(p, d["mod"])]), "literal prompt= argument of the combinator call"
            except Unresolved as e:
                return None, f"unresolved: {e}"
        p1, p2 = task_text(d["components"][0]["def_id"]), task_text(d["components"][1]["def_id"])
        if p1 is None or p2 is None:
            return None, "unresolved: component prompt unresolved"
        return (f"Perform the following tasks in the order they are given: 1. {p1} 2. {p2}",
                "derived by collector: TaskCombinator._create_combined_task default f-string template filled with the statically resolved component PROMPTs")

    def gt_tools(did):
        d = defs[did]
        if d["definition_kind"] == "class":
            return [c["function"] for c in extracted[did]["gt_calls"]]
        return gt_tools(d["components"][0]["def_id"]) + gt_tools(d["components"][1]["def_id"])

    comb_mod = p.get("agentdojo.task_suite.task_combinators")
    comb_fn = next(s for s in ast.walk(comb_mod.tree) if isinstance(s, ast.FunctionDef) and s.name == "_create_combined_task")
    gic = f"{PKG_ROOT}/attacks/base_attacks.py::BaseAttack.get_injection_candidates"

    for did, d in defs.items():
        mod = d["mod"]
        src = mod.segment(d["start"], d["end"])
        raw_id = f"raw:{d['path']}#L{d['start']}-L{d['end']}"
        src_sha = sha256_bytes(src.encode("utf-8"))
        raw_rows.append(OrderedDict(
            raw_id=raw_id, envelope="agentdojo-static-extraction-envelope/1.0",
            envelope_note="Collector-written extraction envelope around verbatim Python source. AgentDojo publishes tasks as Python classes / combinator calls, not JSON; this is NOT an original JSON record.",
            dataset=DATASET, suite=d["suite"], record_type="user_task" if d["kind"] == "user_task" else "attacker_task",
            original_task_id=d["task_id"], definition_kind=d["definition_kind"], symbol=d["symbol"],
            source_locator=OrderedDict(repository_url=REPO_URL, commit_hash=COMMIT, source_path=d["path"], start_line=d["start"],
                                       end_line=d["end"], source_url=gh_blob_url(d["path"], d["start"], d["end"]),
                                       snapshot_path=f"source_snapshot/{d['path']}"),
            source_text_sha256=src_sha, source_text=src))
        is_user = d["kind"] == "user_task"
        unresolved, interp, fields_basis, evaluators = [], [], OrderedDict(), []
        fx = fixtures[d["suite"]]
        env_refs = [fx["environment"]] + fx["includes"] + [fx["injection_vectors"]]
        meta = OrderedDict(definition_kind=d["definition_kind"], definition_folder=d["folder"], class_or_task_name=d["symbol"],
                           registration=OrderedDict(mechanism=d["how"], decorator_source=d["decorator_source"],
                                                    version_slot=vstr(d["slot"]), new_flag=d["new_flag"]),
                           reachable_from_load_suites_import_graph=d["reachable"],
                           effective_in_benchmark_versions=def_versions.get(did, []),
                           slot_overwrote_definition=d.get("overwrote_slot_def") if d["reachable"] else None,
                           hypothetical_slot_collision_if_imported=None if d["reachable"] else d.get("overwrote_slot_def"),
                           registration_error=d.get("registration_error"))
        legit = objective = None
        if d["definition_kind"] == "class":
            ex = extracted[did]
            key = "PROMPT" if is_user else "GOAL"
            fld = "legitimate_user_task" if is_user else "attacker_objective"
            c = ex["consts"].get(key)
            if c is None:
                unresolved.append(dict(field=fld, reason=f"{key} not assigned in class body"))
            elif c["value"] is None:
                unresolved.append(dict(field=fld, reason=c.get("reason"), source_lines=[c["line_start"], c["line_end"]]))
            else:
                legit, objective = (c["value"], None) if is_user else (None, c["value"])
                fields_basis[fld] = dict(source_attribute=key, resolution=c["resolution"], source_lines=[c["line_start"], c["line_end"]])
            consts = OrderedDict(ex["consts"])
            for f in ("GROUND_TRUTH_OUTPUT", "DIFFICULTY"):
                if f not in consts:
                    bd = BASE_DEFAULTS.get(("BaseUserTask" if is_user else "BaseInjectionTask", f))
                    consts[f] = dict(value=bd["value"] if bd else None, resolution=f"inherited default from {bd['class_'] if bd else '?'}",
                                     declared_in=bd["declared_in"] if bd else None)
            meta["class_attributes"] = consts
            meta["methods_defined_in_class"] = ex["methods"]
            meta["has_init_environment_override"] = "init_environment" in ex["methods"]
            for mname in (("ground_truth", "utility", "utility_from_traces") if is_user else ("ground_truth", "security", "security_from_traces")):
                if mname in ex["methods"]:
                    m = ex["methods"][mname]
                    evaluators.append(OrderedDict(method=mname, role="ground_truth" if mname == "ground_truth" else "evaluator",
                                                  source_path=d["path"], start_line=m["start"], end_line=m["end"], defined_in=d["symbol"]))
                elif mname.endswith("_from_traces"):
                    evaluators.append(OrderedDict(method=mname, role="evaluator", source_path=f"{PKG_ROOT}/base_tasks.py", start_line=None, end_line=None,
                                                  defined_in=("BaseUserTask" if is_user else "BaseInjectionTask") + " (inherited default; returns None so the state-based check is used)"))
            gt_list = ex["gt_calls"]
            if ex["gt_issues"]:
                unresolved.append(dict(field="relevant_tools", reason="; ".join(sorted({i["reason"] for i in ex["gt_issues"]})),
                                       source_lines=[i["line"] for i in ex["gt_issues"]]))
            if "init_environment" in ex["methods"]:
                interp.append("Task overrides init_environment: its starting state differs from the raw fixture and is computed at runtime.")
        else:
            prompt, basis = combined_prompt(did)
            legit = prompt
            fields_basis["legitimate_user_task"] = dict(resolution=basis)
            meta["combined_from"] = d["components"]
            meta["class_attributes"] = OrderedDict(
                DIFFICULTY=dict(value="TaskDifficulty.MEDIUM", resolution="set in TaskCombinator._create_combined_task"),
                GROUND_TRUTH_OUTPUT=dict(value=None, resolution="unresolved: f-string over component instances at runtime"))
            evaluators.append(OrderedDict(method="ground_truth/utility/utility_from_traces (combined)", role="evaluator", source_path=comb_mod.path,
                                          start_line=comb_fn.lineno, end_line=comb_fn.end_lineno,
                                          defined_in="TaskCombinator._create_combined_task -> NewCombinedTask",
                                          composes=[c["def_id"] for c in d["components"]]))
            unresolved.append(dict(field="original_metadata.class_attributes.GROUND_TRUTH_OUTPUT", reason="built at runtime from component instances"))
            if basis.startswith("derived"):
                interp.append("legitimate_user_task was reconstructed by the collector from the combinator's default template and the component PROMPTs; it is not a literal in the source.")
            gt_list = [dict(function=f, line=None, via="component ground_truth") for f in gt_tools(did)]
            interp.append("Combined task: ground_truth = component1 + component2; utility = component1.utility(strict=False) and component2.utility(strict=True).")
            for c in d["components"]:
                rels.append(dict(type="combined_task_component", source=f"task:{did}", target=f"task:{c['def_id']}",
                                 evidence=dict(source_path=d["path"], line=d["start"], expr=c["expr"]), basis=c["rule"]))
        relevant = list(OrderedDict.fromkeys(g["function"] for g in gt_list))
        meta["ground_truth_function_calls"] = gt_list
        bad = [t for t in relevant if t not in tool_names_by_suite[d["suite"]]]
        if bad:
            unresolved.append(dict(field="relevant_tools", reason=f"ground-truth tool(s) not in suite TOOLS: {bad}"))
        if is_user:
            unresolved.append(dict(field="injection_target_or_surface", source_ref=gic,
                                   reason="Injection candidates for a user task are computed at runtime: get_injection_candidates executes the task ground truth on a canary-injected environment and keeps the placeholders that appear in tool outputs. Not resolvable without execution."))
        else:
            unresolved.append(dict(field="injection_target_or_surface", source_ref=gic,
                                   reason="Injection tasks are not bound to an injection vector in source; vectors are chosen per paired user task at runtime. Suite-level vectors are listed in injection_vectors.jsonl."))
            unresolved.append(dict(field="published_attack_payload", source_ref=f"{PKG_ROOT}/attacks/",
                                   reason="Payloads are generated at runtime by attack classes from templates (attacks.jsonl). No concrete payload literal is published in task definitions. Rendered per-run injections exist in runs/*.json ('injections') but were only inventoried, not extracted."))
        if not d["reachable"]:
            interp.append("DORMANT: this module is not imported by src/agentdojo/task_suite/load_suites.py or by any module it imports (static import graph), so this definition is never registered through get_suite()/get_suites(). "
                          "Its declared slot is recorded but it is effective in no benchmark version. If a user imported the module manually the outcome would depend on import timing relative to load_suites (get_new_version deep-copies suites at import).")
        elif not def_versions.get(did):
            interp.append("Not effective in any registered benchmark version: its registry slot is overwritten later in the static import order. Kept for provenance.")
        if d.get("overwrote_slot_def") and d["reachable"]:
            interp.append(f"Writes the same (suite, task_id, version slot) as {d['overwrote_slot_def']} and replaces it in the registry (later import wins). Derived by static import-order simulation, not by execution.")
        interp.append("Ground-truth calls and evaluator code describe expected behaviour only; they are not evidence that any attack ran or succeeded.")
        norm_rows.append(OrderedDict(
            case_id=did, dataset=DATASET, suite=d["suite"], record_type="user_task" if is_user else "attacker_task",
            original_task_id=d["task_id"], legitimate_user_task=legit, attacker_objective=objective,
            published_attack_payload=None, injection_target_or_surface=None, relevant_tools=relevant,
            environment_fixture_refs=env_refs, evaluator_refs=evaluators, original_metadata=meta,
            supplied_continuation=None, observed_outcome=None,
            provenance=OrderedDict(repository_url=REPO_URL, commit_hash=COMMIT, source_path=d["path"], symbol=d["symbol"], module=d["module"],
                                   start_line=d["start"], end_line=d["end"], source_url=gh_blob_url(d["path"], d["start"], d["end"]),
                                   raw_id=raw_id, source_text_sha256=src_sha, retrieved_at_utc=retrieved_at),
            extraction_status="partial" if any(u["field"] in ("legitimate_user_task", "attacker_objective", "relevant_tools") for u in unresolved)
            else "resolved_except_runtime_fields",
            unresolved_fields=unresolved,
            interpretation=OrderedDict(collector_notes=interp, field_resolution=fields_basis,
                                       relevant_tools_basis="Tool names in the task's ground_truth FunctionCall literals (static read). Not the full tool set available to the agent (see suite_exposes_tool relationships)."),
        ))
        rels.append(dict(type="task_registered_in_suite", source=f"task:{did}", target=f"suite:{d['suite']}",
                         evidence=dict(source_path=d["path"], line=d["start"], decorator=d["decorator_source"] or d["how"]),
                         basis=f"{d['how']} at version slot {vstr(d['slot'])}" + ("" if d["reachable"] else " -- DORMANT declaration: module not reachable from load_suites.py, so never executed via get_suite()"),
                         reachable_from_load_suites=d["reachable"]))
        for bv in def_versions.get(did, []):
            rels.append(dict(type="task_effective_in_benchmark_version", source=f"task:{did}", target=f"benchmark_version:{bv}/{d['suite']}",
                             evidence=dict(source_path=versions_path, symbol="_SUITES / get_new_version + task_suite.get_version_compatible_items"),
                             basis="highest registered slot <= suite benchmark_version; registry from static import-order simulation"))
        if d.get("overwrote_slot_def") and d["reachable"]:
            rels.append(dict(type="task_slot_overwritten_by", source=f"task:{d['overwrote_slot_def']}", target=f"task:{did}",
                             evidence=dict(source_path=d["path"], line=d["start"]), basis="same (suite, task_id, slot) registered later in static import order"))
        for g in gt_list:
            if g.get("line") is not None:
                rels.append(dict(type="task_ground_truth_calls_tool", source=f"task:{did}", target=f"tool_name:{d['suite']}:{g['function']}",
                                 evidence=dict(source_path=d["path"], line=g["line"]), basis="FunctionCall(function=<literal>) in ground_truth"))
        for e in evaluators:
            if e["start_line"] is not None:
                rels.append(dict(type="task_has_evaluator", source=f"task:{did}", target=f"code:{e['source_path']}#L{e['start_line']}-L{e['end_line']}",
                                 evidence=dict(source_path=e["source_path"], line=e["start_line"], method=e["method"]), basis="method definition"))
        rels.append(dict(type="task_uses_suite_fixture", source=f"task:{did}", target=f"file:{fx['environment']}",
                         evidence=dict(source_path=f"{PKG_ROOT}/task_suite/task_suite.py", symbol="TaskSuite.load_and_inject_default_environment"),
                         basis="every task of a suite runs on that suite's environment fixture"))
    for suite in reach_slots:
        for kind in reach_slots[suite]:
            for tid, slots in reach_slots[suite][kind].items():
                o = sorted(slots.items())
                for (s1, d1), (s2, d2) in zip(o, o[1:]):
                    rels.append(dict(type="task_definition_supersedes", source=f"task:{d2}", target=f"task:{d1}",
                                     evidence=dict(newer_slot=vstr(s2), older_slot=vstr(s1)),
                                     basis="higher version slot for the same task_id is used for benchmark versions >= that slot"))
    rel_rows = []
    for i, r in enumerate(rels, 1):
        rr = OrderedDict(relationship_id=f"rel-{i:05d}"); rr.update(r); rel_rows.append(rr)
    return dict(out=out, retrieved_at=retrieved_at, tree_blobs=tree_blobs, tar_sha256=tar_sha256, files=files, runs_files=runs_files,
                runs_rows=runs_rows, blob_mismatch=blob_mismatch, symlinks=symlinks, missing_from_tar=missing_from_tar, commit_meta=commit_meta,
                sim=sim, versions=versions, reachable_modules=reachable_modules, dormant_modules=dormant_modules, eff=eff, suites=suites, tools=tools, suite_tools=suite_tools, attacks=attacks,
                fixtures=fixtures, vector_rows=vector_rows, raw_rows=raw_rows, norm_rows=norm_rows, rel_rows=rel_rows, def_versions=def_versions)


def write_outputs(S):
    out = S["out"]
    files, runs_files, runs_rows = S["files"], S["runs_files"], S["runs_rows"]
    results_html = files["docs/results-table.html"].decode("utf-8")
    explorer_links = sorted(set(re.findall(r'href="(https://explorer\.invariantlabs\.ai[^"]+)"', results_html)))
    traj = [
        OrderedDict(link_id="traj-repo-runs", location=f"{REPO_URL}/tree/{COMMIT}/runs",
                    kind="in-repo run logs: one JSON per (pipeline, suite, user task, attack, injection task|none)",
                    source_of_link="repository tree at pinned commit; arXiv:2406.13352 Appendix E.3",
                    access_conditions="public, no authentication; included in the pinned codeload tarball (MIT repository license)",
                    collected="inventoried only (runs_inventory.csv: path, size, sha256, git-blob check, path-derived ids, 4 metadata keys); contents not normalized, outcomes not read out",
                    file_count=len(runs_files), total_bytes=sum(len(b) for b in runs_files.values())),
        OrderedDict(link_id="traj-results-page", location="https://agentdojo.spylab.ai/results/",
                    kind="results table page (built from docs/results.md + docs/results-table.html)",
                    source_of_link="README.md ('Inspect Results'); docs/index.md; arXiv abstract page",
                    access_conditions="public web page; HTTP 200 when checked by the collector on 2026-10-18",
                    collected="not downloaded; its source docs/results-table.html is preserved in source_snapshot/"),
        OrderedDict(link_id="traj-invariant-explorer", location="https://explorer.invariantlabs.ai/benchmarks/",
                    kind="external trace viewer (Invariant Explorer), per-run 'Explore' links in docs/results-table.html",
                    source_of_link="README.md; docs/results.md; docs/results-table.html",
                    access_conditions="on 2026-10-18 both the benchmark URL and a sampled per-run URL redirected (HTTP 200 after redirect) to https://github.com/invariantlabs-ai/explorer; hosted traces not reachable at the published URLs; nothing downloaded",
                    per_run_links=explorer_links, per_run_link_count=len(explorer_links), collected="not downloaded"),
        OrderedDict(link_id="traj-paper-gdrive", location="https://drive.google.com/file/d/16nhDqSTRVac_GbcC3-9WMjVaJZfmcwLO/view?usp=share_link",
                    kind="zipped model outputs referenced by the paper (to be unzipped into runs/)",
                    source_of_link="arXiv:2406.13352 Appendix E.3",
                    access_conditions="Google Drive share link; view page returned HTTP 200 without login on 2026-10-18; no separate terms found; file NOT downloaded",
                    collected="not downloaded (separate externally hosted trace collection; deferred to a later task)"),
    ]
    write_jsonl(out / "trajectory_links.jsonl", traj)
    vm_rows = []
    for (bv, suite), r in S["eff"].items():
        for kind in ("user_task", "injection_task"):
            for tid, did in sorted(r[kind].items(), key=lambda kv: int(kv[0].rsplit("_", 1)[1])):
                vm_rows.append(OrderedDict(benchmark_version=bv, suite=suite, suite_version=r["suite_version"],
                                           record_type="user_task" if kind == "user_task" else "attacker_task",
                                           original_task_id=tid, effective_case_id=did))
    with (out / "version_matrix.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(vm_rows[0].keys())); w.writeheader(); w.writerows(vm_rows)
    norm = S["norm_rows"]
    write_jsonl(out / "raw_samples.jsonl", S["raw_rows"])
    write_jsonl(out / "normalized_samples.jsonl", norm)
    write_jsonl(out / "tools.jsonl", S["tools"].values())
    write_jsonl(out / "relationships.jsonl", S["rel_rows"])
    write_jsonl(out / "injection_vectors.jsonl", S["vector_rows"])
    write_jsonl(out / "attacks.jsonl", S["attacks"])
    with (out / "case_summary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "suite", "record_type", "original_task_id", "definition_folder", "version_slot",
                    "effective_in_benchmark_versions", "relevant_tools", "extraction_status", "collector_summary", "summary_is_collector_written"])
        for r in norm:
            txt = r["legitimate_user_task"] if r["record_type"] == "user_task" else r["attacker_objective"]
            t1 = " ".join(txt.split()) if txt else None
            s = "[collector summary] " + ((t1[:140] + "...") if t1 and len(t1) > 140 else (t1 or "(text unresolved)"))
            w.writerow([r["case_id"], r["suite"], r["record_type"], r["original_task_id"], r["original_metadata"]["definition_folder"],
                        r["original_metadata"]["registration"]["version_slot"], ";".join(r["original_metadata"]["effective_in_benchmark_versions"]),
                        ";".join(r["relevant_tools"]), r["extraction_status"], s, "true"])
    fixtures, suite_tools, defs = S["fixtures"], S["suite_tools"], S["sim"].defs
    counts = OrderedDict()
    counts["definitions"] = OrderedDict(
        user_task_definitions=sum(1 for r in norm if r["record_type"] == "user_task"),
        attacker_task_definitions=sum(1 for r in norm if r["record_type"] == "attacker_task"),
        user_task_definitions_class=sum(1 for d in defs.values() if d["kind"] == "user_task" and d["definition_kind"] == "class"),
        user_task_definitions_combinator=sum(1 for d in defs.values() if d["definition_kind"] == "combinator_call"),
        definitions_not_effective_in_any_version=sum(1 for did in defs if not S["def_versions"].get(did)),
        definitions_dormant_not_reachable_from_load_suites=sum(1 for d in defs.values() if not d["reachable"]),
        definitions_overwritten_in_same_slot=sum(1 for did, d in defs.items() if d["reachable"] and not S["def_versions"].get(did)))
    pv = OrderedDict()
    for (bv, suite), r in S["eff"].items():
        pv.setdefault(bv, OrderedDict())[suite] = OrderedDict(
            suite_version=r["suite_version"], user_tasks=len(r["user_task"]), attacker_tasks=len(r["injection_task"]),
            tools=len(suite_tools[suite]["tools"]), injection_vectors=fixtures[suite]["vector_count"],
            fixture_files=2 + len(fixtures[suite]["includes"]))
    counts["per_benchmark_version"] = pv
    counts["suites"] = len(S["suites"])
    counts["benchmark_versions"] = len(S["versions"])
    counts["tools_unique_functions"] = len(S["tools"])
    counts["tools_per_suite"] = OrderedDict((s, len(v["tools"])) for s, v in suite_tools.items())
    counts["injection_vectors"] = len(S["vector_rows"])
    counts["attack_generators_registered"] = len(S["attacks"])
    counts["relationships_total"] = len(S["rel_rows"])
    counts["relationships_by_type"] = OrderedDict(sorted(Counter(r["type"] for r in S["rel_rows"]).items()))
    counts["raw_samples"] = len(S["raw_rows"])
    counts["normalized_samples"] = len(norm)
    counts["version_matrix_rows"] = len(vm_rows)
    counts["source_snapshot_files"] = len(files)
    counts["runs_files_inventoried"] = len(runs_files)
    counts["runs_pipelines"] = len({r["pipeline_dir"] for r in runs_rows})
    counts["trajectory_links"] = len(traj)
    runs_summary = OrderedDict()
    for r in runs_rows:
        e = runs_summary.setdefault(r["pipeline_dir"], dict(files=0, bytes=0, suites=Counter(), attack_dirs=Counter(), json_benchmark_versions=Counter()))
        e["files"] += 1; e["bytes"] += r["bytes"]; e["suites"][r["suite_dir"]] += 1
        e["attack_dirs"][str(r["attack_dir"])] += 1; e["json_benchmark_versions"][str(r["json_benchmark_version"])] += 1
    for e in runs_summary.values():
        for k in ("suites", "attack_dirs", "json_benchmark_versions"):
            e[k] = OrderedDict(sorted(e[k].items()))
    sim = S["sim"]
    analysis = OrderedDict(
        note="Collector-generated static analysis artefact. Nothing here was produced by executing AgentDojo code.",
        static_import_order_from_load_suites=S["reachable_modules"],
        dormant_modules_not_reachable=S["dormant_modules"],
        registration_events=[dict(e, slot=vstr(e["slot"])) for e in sim.reg.events],
        skipped_task_like_classes=sim.skipped_classes, benchmark_versions=S["versions"], fixtures=fixtures,
        suite_tools=suite_tools, runs_summary=runs_summary, tar_symlinks=S["symlinks"], blob_mismatch=S["blob_mismatch"],
        tree_blobs_missing_from_tarball=S["missing_from_tar"])
    (out / "static_analysis.json").write_text(json.dumps(analysis, indent=1, ensure_ascii=False), encoding="utf-8")
    ra = S["retrieved_at"]
    u = dt.datetime.strptime(ra, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    cm = S["commit_meta"]
    core = OrderedDict(
        schema_version=SCHEMA_VERSION, dataset=DATASET, repository_url=REPO_URL, commit_hash=COMMIT,
        commit_committer_date_utc=cm["commit"]["committer"]["date"], commit_tree_sha=cm["commit"]["tree"]["sha"],
        commit_message_first_line=cm["commit"]["message"].splitlines()[0],
        retrieved_at=OrderedDict(utc=ra, america_denver=(u - dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S-06:00") + " (MDT)"),
        retrieval_sources=OrderedDict(tarball=TARBALL_URL, tree=TREE_URL, commit=COMMIT_URL),
        tarball_sha256=S["tar_sha256"], tarball_pax_comment_commit=COMMIT,
        git_blob_verification=OrderedDict(blobs_in_tree=len(S["tree_blobs"]), files_in_tarball=len(files) + len(runs_files),
                                          mismatched_or_missing=len(S["blob_mismatch"]), tree_blobs_missing_from_tarball=len(S["missing_from_tar"])),
        snapshot_policy="Every file of the pinned commit except runs/** is preserved under source_snapshot/ at its repository path. runs/** is inventoried in runs_inventory.csv (sha256 + git blob check) but not copied.",
        counts=counts, runs_summary=runs_summary)
    (out / "_manifest_core.json").write_text(json.dumps(core, indent=1, ensure_ascii=False), encoding="utf-8")
    return core


def finalize(out):
    core = json.loads((out / "_manifest_core.json").read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    hashes = OrderedDict()
    for fp in sorted(out.rglob("*")):
        if fp.is_file():
            rel = fp.relative_to(out).as_posix()
            if rel in ("manifest.json", "validation_output.txt", "_manifest_core.json") or rel.startswith("_download_cache/"):
                continue
            hashes[rel] = sha256_bytes(fp.read_bytes())
    core["file_sha256"] = hashes
    core["file_count_hashed"] = len(hashes)
    core["hash_exclusions"] = ["manifest.json (cannot hash itself)", "validation_output.txt (written after the manifest by validate)"]
    (out / "manifest.json").write_text(json.dumps(core, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "_manifest_core.json").unlink()


# ------------------------------------------------------------------------------ validate

def validate(out):
    out = Path(out)
    log, ok_all = [], True

    def check(name, cond, detail=""):
        nonlocal ok_all
        ok_all &= bool(cond)
        log.append(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    def read_jsonl(name):
        rows, bad = [], 0
        with (out / name).open(encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    bad += 1
        return rows, bad

    log.append(f"AgentDojo static collection -- validation run_at_utc={dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    log.append("Independent re-read of saved outputs; re-parses preserved snapshot files with ast (no AgentDojo code imported or executed).")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    log.append(f"commit={manifest['commit_hash']}  retrieved_at_utc={manifest['retrieved_at']['utc']}")
    data = {}
    for n in ("raw_samples.jsonl", "normalized_samples.jsonl", "tools.jsonl", "relationships.jsonl",
              "injection_vectors.jsonl", "attacks.jsonl", "trajectory_links.jsonl"):
        rows, bad = read_jsonl(n)
        data[n] = rows
        check(f"JSONL parses: {n}", bad == 0 and rows, f"{len(rows)} records, {bad} unparsable")
    raw, norm, tools, rels = data["raw_samples.jsonl"], data["normalized_samples.jsonl"], data["tools.jsonl"], data["relationships.jsonl"]
    vecs, attacks = data["injection_vectors.jsonl"], data["attacks.jsonl"]
    snap = out / "source_snapshot"
    cache = {}

    def lines_of(path):
        if path not in cache:
            cache[path] = (snap / path).read_text(encoding="utf-8").splitlines(keepends=True)
        return cache[path]

    # -- ids / locators
    for name, rows, key in (("raw_id", raw, "raw_id"), ("case_id", norm, "case_id"), ("tool_id", tools, "tool_id"),
                            ("relationship_id", rels, "relationship_id"), ("vector_id", vecs, "vector_id"), ("attack_id", attacks, "attack_id")):
        ids = [r[key] for r in rows]
        check(f"unique {name}", len(ids) == len(set(ids)), f"{len(ids)} ids")
    locs = [(r["source_locator"]["source_path"], r["source_locator"]["start_line"], r["source_locator"]["end_line"]) for r in raw]
    check("unique raw source locators (path, start, end)", len(locs) == len(set(locs)))
    raw_by = {r["raw_id"]: r for r in raw}
    by_case = {n["case_id"]: n for n in norm}
    check("normalized <-> raw one-to-one", sorted(n["provenance"]["raw_id"] for n in norm) == sorted(raw_by), f"{len(norm)} vs {len(raw)}")
    bad = [n["case_id"] for n in norm
           if raw_by[n["provenance"]["raw_id"]]["original_task_id"] != n["original_task_id"]
           or raw_by[n["provenance"]["raw_id"]]["source_locator"]["source_path"] != n["provenance"]["source_path"]
           or raw_by[n["provenance"]["raw_id"]]["source_locator"]["start_line"] != n["provenance"]["start_line"]
           or raw_by[n["provenance"]["raw_id"]]["source_text_sha256"] != n["provenance"]["source_text_sha256"]
           or n["provenance"]["commit_hash"] != manifest["commit_hash"]]
    check("normalized provenance consistent with raw locator, text hash and manifest commit", not bad, ",".join(bad[:5]))
    bad = [n["case_id"] for n in norm if n["case_id"] != f"agentdojo/{n['suite']}/{n['original_task_id']}@{n['original_metadata']['definition_folder']}"
           or not n["provenance"]["source_path"].startswith(f"src/agentdojo/default_suites/{n['original_metadata']['definition_folder']}/")]
    check("case_id = agentdojo/<suite>/<task_id>@<definition_folder> and matches source path", not bad, ",".join(bad[:5]))
    bad = [n["case_id"] for n in norm if n["record_type"] == "user_task" and not n["original_task_id"].startswith("user_task_")
           or n["record_type"] == "attacker_task" and not n["original_task_id"].startswith("injection_task_")]
    check("record_type consistent with original_task_id prefix", not bad)

    # -- source text
    bad = []
    for r in raw:
        L = r["source_locator"]
        txt = "".join(lines_of(L["source_path"])[L["start_line"] - 1:L["end_line"]])
        if txt != r["source_text"] or sha256_bytes(txt.encode("utf-8")) != r["source_text_sha256"]:
            bad.append(r["raw_id"])
    check("raw source_text == preserved snapshot lines and sha256", not bad, f"{len(raw)} checked, {len(bad)} mismatches")

    # -- directly extracted values
    bad, n_lit, n_expr = [], 0, 0
    for n in norm:
        md = n["original_metadata"]
        if md["definition_kind"] != "class":
            continue
        key = "PROMPT" if n["record_type"] == "user_task" else "GOAL"
        val = n["legitimate_user_task"] if key == "PROMPT" else n["attacker_objective"]
        tree = ast.parse("".join(lines_of(n["provenance"]["source_path"])))
        cls = next((c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == md["class_or_task_name"]
                    and min([x.lineno for x in c.decorator_list] + [c.lineno]) == n["provenance"]["start_line"]), None)
        if cls is None:
            bad.append((n["case_id"], "class not found at locator")); continue
        node = None
        for st in cls.body:
            t = st.targets[0] if isinstance(st, ast.Assign) else (st.target if isinstance(st, ast.AnnAssign) else None)
            if isinstance(t, ast.Name) and t.id == key:
                node = st.value
        if node is None:
            if val is not None:
                bad.append((n["case_id"], "value present but no assignment"))
            continue
        try:
            lit = ast.literal_eval(node)
            n_lit += 1
            if lit != val:
                bad.append((n["case_id"], "literal mismatch"))
        except Exception:
            if val is None:
                continue
            n_expr += 1
            frags = [c.value for c in (node.values if isinstance(node, ast.JoinedStr) else ast.walk(node))
                     if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            if isinstance(node, ast.JoinedStr):
                pat = "".join(re.escape(part.value) if isinstance(part, ast.Constant) else "(.*?)" for part in node.values)
                if not re.fullmatch(pat, val, re.S):
                    bad.append((n["case_id"], "f-string template does not fully match value"))
            elif not all(fr in val for fr in frags):
                bad.append((n["case_id"], "expression fragments"))
        cattr = md["class_attributes"]
        for k, e in cattr.items():
            if e.get("resolution") == "literal":
                seg = "".join(lines_of(n["provenance"]["source_path"])[e["line_start"] - 1:e["line_end"]])
                if k not in seg:
                    bad.append((n["case_id"], f"attr {k} line"))
    check("PROMPT/GOAL match source (literal_eval equality; anchored f-string template match) and attribute line refs", not bad,
          f"{n_lit} literal equality checks, {n_expr} f-string/expression checks; failures {bad[:3]}")
    bad = []
    for n in norm:
        md = n["original_metadata"]
        if md["definition_kind"] != "combinator_call":
            continue
        txt = raw_by[n["provenance"]["raw_id"]]["source_text"]
        call = ast.parse(txt.strip()).body[0].value
        kw = {k.arg: k.value for k in call.keywords}
        if "prompt" in kw:
            if ast.literal_eval(kw["prompt"]) != n["legitimate_user_task"]:
                bad.append(n["case_id"] + ":prompt")
        else:
            c = md["combined_from"]
            exp = f"Perform the following tasks in the order they are given: 1. {by_case[c[0]['def_id']]['legitimate_user_task']} 2. {by_case[c[1]['def_id']]['legitimate_user_task']}"
            if n["legitimate_user_task"] != exp:
                bad.append(n["case_id"] + ":derived")
        if ast.literal_eval(call.args[0]) != md["class_or_task_name"]:
            bad.append(n["case_id"] + ":name")
        for c in md["combined_from"]:
            if f'"{c["task_id"]}"' not in txt or c["def_id"] not in by_case:
                bad.append(n["case_id"] + ":component")
    check("combined tasks: name/prompt/components consistent with call source and component records", not bad, ",".join(bad[:5]))

    # -- references
    stn = defaultdict(set)
    for t in tools:
        for s in t["suites"]:
            stn[s].add(t["name"])
    bad = [(n["case_id"], t) for n in norm for t in n["relevant_tools"] if t not in stn[n["suite"]]]
    check("relevant_tools resolve to tools exposed by the task's suite", not bad, f"{sum(len(n['relevant_tools']) for n in norm)} refs; unresolved {bad[:5]}")
    bad = [(n["case_id"], f) for n in norm for f in n["environment_fixture_refs"] if not (snap / f).is_file()]
    check("environment_fixture_refs resolve to preserved files", not bad, f"{sum(len(n['environment_fixture_refs']) for n in norm)} refs")
    bad, n_inh = [], 0
    for n in norm:
        for e in n["evaluator_refs"]:
            if e["start_line"] is None:
                n_inh += 1
                if "def " + e["method"] not in "".join(lines_of(e["source_path"])):
                    bad.append((n["case_id"], e["method"]))
                continue
            seg = "".join(lines_of(e["source_path"])[e["start_line"] - 1:e["end_line"]])
            m = e["method"].split(" ")[0].split("/")[0]
            if f"def {m}" not in seg and "def _create_combined_task" not in seg:
                bad.append((n["case_id"], e["method"]))
    check("evaluator_refs resolve to 'def <method>' in preserved source", not bad,
          f"{sum(len(n['evaluator_refs']) for n in norm)} refs ({n_inh} inherited base-class defaults checked by file); failures {bad[:3]}")
    bad = []
    for t in tools:
        pv = t["provenance"]
        seg = "".join(lines_of(pv["source_path"])[pv["start_line"] - 1:pv["end_line"]])
        fn = ast.parse(seg).body[0]
        if not isinstance(fn, ast.FunctionDef) or fn.name != t["name"] or ast.get_docstring(fn, clean=True) != t["docstring_raw"]:
            bad.append(t["tool_id"]); continue
        names = [a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs]
        if sorted(names) != sorted([a["name"] for a in t["arguments"]] + [d["name"] for d in t["environment_dependencies"]]):
            bad.append(t["tool_id"] + ":args")
    check("tools: name, docstring and argument names match preserved source", not bad, f"{len(tools)} tools; {bad[:5]}")
    bad = []
    for v in vecs:
        if not lines_of(v["provenance"]["source_path"])[v["provenance"]["start_line"] - 1].startswith(v["injection_vector"] + ":"):
            bad.append(v["vector_id"])
        for l in v["placeholder_locations"]:
            if "{" + v["injection_vector"] + "}" not in lines_of(l["path"])[l["line"] - 1]:
                bad.append(v["vector_id"] + ":placeholder")
        vv = parse_injection_vectors((snap / v["provenance"]["source_path"]).read_text(encoding="utf-8"), v["provenance"]["source_path"])[v["injection_vector"]]
        if vv.get("default") != v["default"] or vv.get("description") != v["description"]:
            bad.append(v["vector_id"] + ":value")
    nph = [v["vector_id"] for v in vecs if not v["placeholder_locations"]]
    check("injection vectors: key lines, values and placeholder locations resolve in preserved fixtures", not bad,
          f"{len(vecs)} vectors; vectors with no placeholder in fixtures: {nph or 'none'}")
    try:
        import yaml  # optional
        bad = []
        for v in vecs:
            y = yaml.safe_load((snap / v["provenance"]["source_path"]).read_text(encoding="utf-8"))[v["injection_vector"]]
            if y.get("default") != v["default"] or y.get("description") != v["description"]:
                bad.append(v["vector_id"])
        check("optional PyYAML cross-check of injection vector values", not bad, ",".join(bad))
    except ImportError:
        log.append("[SKIP] optional PyYAML cross-check of injection vector values -- PyYAML not installed; stdlib parser used (values re-parsed above)")
    bad = []
    for a in attacks:
        ts = a["generator_template_source"]
        if ts:
            tree = ast.parse("".join(lines_of(ts["source_path"])))
            vals = [ast.literal_eval(nd.value) for nd in ast.walk(tree) if isinstance(nd, ast.Assign) and nd.lineno == ts["start_line"]
                    and nd.end_lineno == ts["end_line"]]
            vals += [nd.value for nd in ast.walk(tree) if isinstance(nd, ast.Constant) and isinstance(nd.value, str)
                     and nd.lineno == ts["start_line"] and nd.end_lineno == ts["end_line"]]
            if a["generator_template"] not in vals:
                bad.append(a["attack_id"])
    check("attack generator templates equal the literals at their source lines", not bad, f"{len(attacks)} attacks; {bad}")
    eps = {"registry:agentdojo.attacks.attack_registry.ATTACKS"} | {f"task:{n['case_id']}" for n in norm}
    eps |= {f"tool:{t['tool_id']}" for t in tools} | {f"vector:{v['vector_id']}" for v in vecs} | {a["attack_id"] for a in attacks}
    eps |= {f"suite:{s}" for s in stn} | {f"tool_name:{s}:{x}" for s, xs in stn.items() for x in xs}
    pvc = manifest["counts"]["per_benchmark_version"]
    eps |= {f"benchmark_version:{bv}/{s}" for bv, ss in pvc.items() for s in ss}

    def ep_ok(e):
        if e in eps:
            return True
        if e.startswith("file:"):
            return (snap / e[5:]).is_file()
        if e.startswith("code:"):
            pth, rng = e[5:].split("#")
            a, b = rng.replace("L", "").split("-")
            return (snap / pth).is_file() and int(b) <= len(lines_of(pth)) and int(a) >= 1
        return False
    bad = [r["relationship_id"] for r in rels if not (ep_ok(r["source"]) and ep_ok(r["target"]))]
    check("relationship endpoints resolve (tasks, tools, vectors, files, code ranges, versions)", not bad, f"{len(rels)} relationships; unresolved {bad[:5]}")
    check("relationship types restricted to the source-supported set", all(r["type"] in ALLOWED_REL_TYPES for r in rels))
    pair = [r["relationship_id"] for r in rels if r["source"].startswith("task:") and r["target"].startswith("task:")
            and by_case[r["source"][5:]]["record_type"] != by_case[r["target"][5:]]["record_type"]]
    check("no user_task <-> attacker_task pair relationships (no invented task-attack combinations)", not pair, f"{len(pair)} found")
    dorm = [n for n in norm if not n["original_metadata"]["reachable_from_load_suites_import_graph"]]
    check("dormant (unreachable) definitions are effective in no benchmark version", all(not n["original_metadata"]["effective_in_benchmark_versions"] for n in dorm), f"{len(dorm)} dormant")

    # -- counts
    c = manifest["counts"]
    check("manifest counts == JSONL record counts",
          c["normalized_samples"] == len(norm) and c["raw_samples"] == len(raw) and c["tools_unique_functions"] == len(tools)
          and c["relationships_total"] == len(rels) and c["injection_vectors"] == len(vecs) and c["attack_generators_registered"] == len(attacks)
          and c["definitions"]["user_task_definitions"] == sum(n["record_type"] == "user_task" for n in norm)
          and c["definitions"]["attacker_task_definitions"] == sum(n["record_type"] == "attacker_task" for n in norm)
          and c["trajectory_links"] == len(data["trajectory_links.jsonl"]))
    check("manifest relationships_by_type == relationships.jsonl", dict(Counter(r["type"] for r in rels)) == dict(c["relationships_by_type"]))
    tps = Counter(s for t in tools for s in t["suites"])
    check("manifest tools_per_suite == tools.jsonl suite membership", dict(tps) == dict(c["tools_per_suite"]))
    with (out / "case_summary.csv").open(encoding="utf-8", newline="") as f:
        cs = list(csv.DictReader(f))
    check("case_summary.csv: one row per normalized record, same order, all marked collector-written",
          [r["case_id"] for r in cs] == [n["case_id"] for n in norm]
          and all(r["summary_is_collector_written"] == "true" and r["collector_summary"].startswith("[collector summary]") for r in cs))
    with (out / "version_matrix.csv").open(encoding="utf-8", newline="") as f:
        vm = list(csv.DictReader(f))
    vmc = Counter((r["benchmark_version"], r["suite"], r["record_type"]) for r in vm)
    bad = [f"{bv}/{s}" for bv, ss in pvc.items() for s, e in ss.items()
           if vmc[(bv, s, "user_task")] != e["user_tasks"] or vmc[(bv, s, "attacker_task")] != e["attacker_tasks"]]
    bad += [r["effective_case_id"] for r in vm if r["benchmark_version"] not in by_case[r["effective_case_id"]]["original_metadata"]["effective_in_benchmark_versions"]]
    eff_n = sum(len(n["original_metadata"]["effective_in_benchmark_versions"]) for n in norm)
    check("version_matrix.csv == manifest per-version counts == normalized effective_in_benchmark_versions",
          not bad and eff_n == len(vm) == c["relationships_by_type"].get("task_effective_in_benchmark_version"), f"{len(vm)} rows; {bad[:5]}")
    readme = (out / "README.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- COUNTS-JSON (.*?) -->", readme, re.S)
    check("README embedded counts block == manifest counts", bool(m) and json.loads(m.group(1)) == readme_counts(c))
    bad = [f"{bv}/{s}" for bv, ss in pvc.items() for s, e in ss.items()
           if f"| {bv} | {s} | {e['suite_version']} | {e['user_tasks']} | {e['attacker_tasks']} | {e['tools']} | {e['injection_vectors']} | {e['fixture_files']} |" not in readme]
    check("README per-version inventory table rows == manifest", not bad, ",".join(bad))
    with (out / "runs_inventory.csv").open(encoding="utf-8", newline="") as f:
        ri = list(csv.DictReader(f))
    check("runs_inventory.csv rows == manifest runs_files_inventoried", len(ri) == c["runs_files_inventoried"], f"{len(ri)} rows")

    # -- hashes / snapshot integrity
    bad = [rel for rel, h in manifest["file_sha256"].items() if not (out / rel).is_file() or sha256_bytes((out / rel).read_bytes()) != h]
    present = {fp.relative_to(out).as_posix() for fp in out.rglob("*") if fp.is_file()}
    unlisted = sorted(present - set(manifest["file_sha256"]) - {"manifest.json", "validation_output.txt"})
    check("manifest sha256 hashes match files", not bad, f"{len(manifest['file_sha256'])} files hashed, {len(bad)} mismatches")
    check("no output files missing from manifest (except manifest.json, validation_output.txt)", not unlisted, ",".join(unlisted[:5]))
    tree = json.loads((out / "git_tree_listing.json").read_text(encoding="utf-8"))
    tb = {t["path"]: t["sha"] for t in tree["tree"] if t["type"] == "blob"}
    snap_files = {fp.relative_to(snap).as_posix(): fp for fp in snap.rglob("*") if fp.is_file()}
    bad = [p for p, fp in snap_files.items() if tb.get(p) != git_blob_sha1(fp.read_bytes())]
    check("source_snapshot files == git blob SHA-1 in pinned commit tree", not bad, f"{len(snap_files)} files; mismatches {bad[:5]}")
    exp = {p for p in tb if not p.startswith(SNAPSHOT_EXCLUDE_PREFIXES)}
    check("source_snapshot covers every non-runs/ blob of the pinned tree", exp == set(snap_files), f"{len(exp)} expected")
    check("runs_inventory covers every runs/ blob of the pinned tree, all git-blob verified",
          {p for p in tb if p.startswith("runs/")} == {r["path"] for r in ri} and all(r["git_blob_sha1_verified"] == "True" for r in ri))
    check("tree listing sha matches manifest commit tree", tree.get("sha") in (manifest["commit_hash"], manifest["commit_tree_sha"]))

    # -- no invented outcomes / payloads / continuations
    check("observed_outcome is null in every normalized record", all(n["observed_outcome"] is None for n in norm))
    check("supplied_continuation is null in every normalized record", all(n["supplied_continuation"] is None for n in norm))
    check("published_attack_payload is null in every record (none published in definitions)", all(n["published_attack_payload"] is None for n in norm))
    check("injection_target_or_surface is null and listed as unresolved for every record",
          all(n["injection_target_or_surface"] is None and any(u["field"] == "injection_target_or_surface" for u in n["unresolved_fields"]) for n in norm))
    check("attack templates flagged as generator source, not payloads", all(a["is_published_payload"] is False for a in attacks))
    check("user tasks carry no attacker_objective; attacker tasks carry no legitimate_user_task",
          all((n["attacker_objective"] is None) if n["record_type"] == "user_task" else (n["legitimate_user_task"] is None) for n in norm))
    leak = [n["case_id"] for n in norm if re.search(r'"(utility|security)": (true|false)', json.dumps(n))]
    check("no run outcome fields (utility/security booleans) copied into normalized records", not leak)
    rcols = set(ri[0].keys()) if ri else set()
    check("runs_inventory has no outcome/content columns (utility, security, messages, injections text)",
          not rcols & {"utility", "security", "messages", "injections", "error"}, ",".join(sorted(rcols)))

    # -- summary
    log.append("")
    log.append("COUNTS (separate categories; never summed into 'test cases'):")
    d = c["definitions"]
    log.append(f"  suites={c['suites']}  benchmark_versions={c['benchmark_versions']}  unique tool functions={c['tools_unique_functions']}  tools per suite={dict(c['tools_per_suite'])}")
    log.append(f"  user_task definitions={d['user_task_definitions']} (class={d['user_task_definitions_class']}, combinator={d['user_task_definitions_combinator']})  attacker_task definitions={d['attacker_task_definitions']}")
    log.append(f"  definitions effective in no version={d['definitions_not_effective_in_any_version']} (dormant/unreachable={d['definitions_dormant_not_reachable_from_load_suites']}, overwritten in same slot={d['definitions_overwritten_in_same_slot']})")
    log.append(f"  injection vectors={c['injection_vectors']}  attack generators={c['attack_generators_registered']}  relationships={c['relationships_total']}")
    for t, k in c["relationships_by_type"].items():
        log.append(f"     {t}: {k}")
    log.append("  per benchmark version / suite: suite_version | user_tasks | attacker_tasks | tools | injection_vectors | fixture_files")
    for bv, ss in pvc.items():
        for s, e in ss.items():
            log.append(f"     {bv:7s} {s:10s} {e['suite_version']:6s} | {e['user_tasks']:3d} | {e['attacker_tasks']:3d} | {e['tools']:3d} | {e['injection_vectors']:3d} | {e['fixture_files']}")
    log.append(f"  runs/ files inventoried (not normalized)={c['runs_files_inventoried']} across {c['runs_pipelines']} pipeline directories")
    log.append("  unresolved field occurrences: " + json.dumps(dict(sorted(Counter(u["field"] for n in norm for u in n["unresolved_fields"]).items()))))
    log.append("  extraction_status: " + json.dumps(dict(Counter(n["extraction_status"] for n in norm))))
    log.append("")
    log.append("OVERALL: " + ("PASS" if ok_all else "FAIL"))
    (out / "validation_output.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    return ok_all


def readme_counts(c):
    return dict(per_benchmark_version=c["per_benchmark_version"], definitions=c["definitions"], suites=c["suites"],
                tools_unique_functions=c["tools_unique_functions"], tools_per_suite=c["tools_per_suite"],
                injection_vectors=c["injection_vectors"], attack_generators_registered=c["attack_generators_registered"],
                relationships_total=c["relationships_total"], relationships_by_type=c["relationships_by_type"],
                runs_files_inventoried=c["runs_files_inventoried"])


# -------------------------------------------------------------------------------- README

def write_readme(S, core):
    out = S["out"]
    c = core["counts"]
    norm = S["norm_rows"]
    by_case = {n["case_id"]: n for n in norm}
    pv = c["per_benchmark_version"]
    L = []
    A = L.append
    A("# AgentDojo static collection (collection and formatting only)")
    A("")
    A("## Purpose and handling")
    A("Static collection of the published AgentDojo task, attack, tool, fixture and evaluator definitions for single-agent prompt-injection research. "
      "No AgentDojo module was imported or executed, no dependency was installed, no model was called, the benchmark was not run, no attack was executed, "
      "no URL found inside repository content (attacker destinations, phishing links, etc.) was visited, and no embedded instruction was followed. "
      "All repository content, fixture text, injection defaults and attack templates are untrusted research data.")
    A("")
    A("## Source and pinning")
    A("- Paper: Debenedetti et al., \"AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents\", NeurIPS 2024 Datasets & Benchmarks, arXiv:2406.13352. "
      "The arXiv page states \"We release code for AgentDojo at https://github.com/ethz-spylab/agentdojo\"; the project page https://agentdojo.spylab.ai links the same repository.")
    A(f"- Repository: {REPO_URL}")
    A(f"- Pinned commit: `{COMMIT}` (HEAD of `main` at retrieval; committer date {core['commit_committer_date_utc']}; tree `{core['commit_tree_sha']}`; message: \"{core['commit_message_first_line']}\"). Package version in pyproject.toml: 0.1.35.")
    A(f"- Retrieved: {core['retrieved_at']['utc']} UTC = {core['retrieved_at']['america_denver']}.")
    A(f"- Retrieval: codeload tarball `{TARBALL_URL}` (sha256 `{core['tarball_sha256']}`; its pax header comment equals the commit SHA), "
      "plus the GitHub git-tree listing and commit metadata (saved as git_tree_listing.json and git_commit_metadata.json). "
      f"Every one of the {core['git_blob_verification']['blobs_in_tree']} blobs in the tree was checked by recomputing its git blob SHA-1 from the tarball bytes: "
      f"{core['git_blob_verification']['mismatched_or_missing']} mismatches, {core['git_blob_verification']['tree_blobs_missing_from_tarball']} missing. "
      "(A `git clone` was attempted first but failed on a TLS error, so the tarball + tree route was used.)")
    A(f"- Preservation: all {c['source_snapshot_files']} non-`runs/` files (code, docs, LICENSE, CITATION.bib, pyproject.toml, uv.lock, .python-version, CI/devcontainer config, notebooks, tests, fixtures) are in `source_snapshot/` at their repository paths. "
      f"`runs/` ({c['runs_files_inventoried']} published run-log JSON files, ~{round(S['trajectory_bytes'] / 1e6)} MB) is inventoried, not copied (see below).")
    A("")
    A("## License (verified at the pinned commit)")
    A("- `LICENSE`: MIT License, Copyright (c) 2024 Edoardo Debenedetti, Jie Zhang, Mislav Balunovic, Luca Beurer-Kellner, Marc Fischer, and Florian Tramèr. pyproject.toml classifier: `License :: OSI Approved :: MIT License`.")
    A("- The paper (Appendix E.4/E.5) says the code **and data** are released under MIT \"unless otherwise stated in some portions of the code\". No separate fixture/data license file exists.")
    A("- Marked third-party portions: `src/agentdojo/yaml_loader.py` (`!include` loader, MIT, Copyright (c) 2018 Josh Bode; plus a Stack Overflow snippet marked \"Released under CC BY-SA 3.0\"); `src/agentdojo/types.py` refers to the openai-python license for re-defined types.")
    A("- Externally hosted traces (Google Drive zip, Invariant Explorer) have no separate terms found; check them before downloading or redistributing.")
    A("")
    A("## How AgentDojo is structured (source facts used for extraction)")
    A("- Four suites (`workspace`, `travel`, `banking`, `slack`). Each has `src/agentdojo/default_suites/v1/<suite>/task_suite.py` (environment class + `TOOLS` list), `user_tasks.py` and `injection_tasks.py` (task classes), and fixtures `src/agentdojo/data/suites/<suite>/environment.yaml` (workspace uses `!include include/{inbox,calendar,cloud_drive}.yaml`) and `injection_vectors.yaml`.")
    A("- A user task is a class `UserTaskN` with `PROMPT`, optional `GROUND_TRUTH_OUTPUT`/`DIFFICULTY`/`COMMENT`, `ground_truth()` (list of `FunctionCall`s) and `utility()` (+ optional `utility_from_traces()`). An injection task (normalized as `attacker_task`) is `InjectionTaskN` with `GOAL`, `ground_truth()` and `security()`. IDs (`user_task_N`, `injection_task_N`) are assigned from the class name by the registration decorator.")
    A("- Some user tasks are not classes: `TaskCombinator.create_combined_task(...)` / `update_combined_task(...)` builds them from two component tasks at import time. These are recorded with `definition_kind = combinator_call`.")
    A("- Versioning: later folders (`v1_1`, `v1_1_1`, `v1_1_2`, `v1_2`, `v1_2_1`, `v1_2_2`) add or replace tasks with `@task_suite.update_user_task(V)` / `update_injection_task(V[, new=True])`, which writes into a per-task `{version slot -> instance}` map. "
      "`src/agentdojo/task_suite/load_suites.py` maps each benchmark version (`v1`, `v1.1`, `v1.1.1`, `v1.1.2`, `v1.2`, `v1.2.1`, `v1.2.2`) to suites with a suite version (via `get_new_version`). "
      "For a suite version V, each task ID resolves to the highest registered slot <= V (`get_version_compatible_items`). The benchmark script default is `v1.2.2`.")
    A("- Attacks (`src/agentdojo/attacks/`) are classes registered with `@register_attack`. Most fill a template with `{goal}` (the injection task GOAL), `{user}`, `{model}`, `{task}` or `{tools}` at runtime, "
      "and place the text in the injection vectors that `get_injection_candidates` finds by *executing the user task's ground truth* on a canary-filled environment. "
      "The security test cases are the per-suite cross product of user tasks and injection tasks (paper Sec. 3; `benchmark.py`). That rule is documented here, but **pairs were not enumerated**.")
    A("")
    A("## How the static extraction worked")
    A("- Every task-definition module was parsed with `ast`. Registration was reconstructed by a **static import-order simulation**: starting at `agentdojo.task_suite.load_suites`, the collector follows the top-level `import` statements in source order, as Python would, and replays only the registration decorators and combinator calls into a registry model. Module bodies are never executed.")
    A("- PROMPT/GOAL values are taken only if they are literals, or pure expressions over literals in the same class or module (f-strings over string or int constants, `+` concatenation, `', '.join(<literal list>)`). Anything else is left null and listed in `unresolved_fields`.")
    A("- The workspace fixture's `!include` links are resolved by path. Injection vectors are read with a strict stdlib parser of the flat two-level YAML mapping. The optional PyYAML cross-check is skipped when PyYAML is missing.")
    A("")
    A("## Inventory per benchmark version and suite")
    A("Counts are kept separate. User tasks, attacker (injection) tasks, tools and fixtures are different kinds of object and are never added together as \"test cases\". "
      "`fixture_files` = environment.yaml + includes + injection_vectors.yaml. The fixture files are not versioned: every benchmark version uses the same files at this commit. Tools are identical across versions.")
    A("")
    A("| benchmark_version | suite | suite_version | user_tasks | attacker_tasks | tools | injection_vectors | fixture_files |")
    A("|---|---|---|---|---|---|---|---|")
    for bv, ss in pv.items():
        for s, e in ss.items():
            A(f"| {bv} | {s} | {e['suite_version']} | {e['user_tasks']} | {e['attacker_tasks']} | {e['tools']} | {e['injection_vectors']} | {e['fixture_files']} |")
    A("")
    # changes vs v1
    A("Definitions that differ from the `v1` folder, per benchmark version (effective definition folder != v1):")
    A("")
    vm = defaultdict(lambda: Counter())
    for (bv, suite), r in S["eff"].items():
        for kind in ("user_task", "injection_task"):
            for tid, did in r[kind].items():
                f = did.split("@")[1]
                if f != "v1":
                    vm[bv][f"{suite}/{'user' if kind == 'user_task' else 'attacker'}@{f}"] += 1
    for bv in pv:
        A(f"- {bv}: " + (", ".join(f"{k}={v}" for k, v in sorted(vm[bv].items())) or "none (all v1 definitions)"))
    A("")
    d = c["definitions"]
    A(f"Definition records: {d['user_task_definitions']} user-task definitions ({d['user_task_definitions_class']} classes + {d['user_task_definitions_combinator']} combinator calls) and "
      f"{d['attacker_task_definitions']} attacker-task definitions across all version folders. One task ID can have several definitions, one per version folder, so these are not per-version counts. "
      f"{d['definitions_not_effective_in_any_version']} definitions are effective in no benchmark version (see findings).")
    A(f"Tools: {c['tools_unique_functions']} unique tool functions. Per-suite exposure is {dict(c['tools_per_suite'])}, i.e. {sum(c['tools_per_suite'].values())} suite-tool memberships, because these functions are exposed by more than one suite: "
      + ", ".join(f"`{t['name']}` ({'+'.join(t['suites'])})" for t in S["tools"].values() if len(t["suites"]) > 1) + ". "
      f"Injection vectors: {c['injection_vectors']}. Registered attack generators: {c['attack_generators_registered']}.")
    A("")
    A("Cross-check with the paper (v1): Table 1 reports workspace 40/6, slack 21/5, travel 20/7, banking 16/9 user/injection tasks (97 user tasks, 27 injection tasks). The text says 74 tools and Table 1 says 70; the per-suite tool counts sum to 24+11+28+11 = 74. "
      "The v1 row above reproduces the paper's user and injection counts. The paper's 629 security cases are the per-suite products of these counts. They are a derived product and were **not** materialized here.")
    A("")
    A("## Notable source findings (from static analysis; confirm by controlled execution before relying on them)")
    dorm = [n["case_id"] for n in norm if not n["original_metadata"]["reachable_from_load_suites_import_graph"]]
    ovw = [n for n in norm if n["original_metadata"]["slot_overwrote_definition"]]
    A(f"1. **`default_suites/v1_1_2` is not imported by `load_suites.py` or by any module it imports.** Its {len(dorm)} definitions ({', '.join(dorm)}) are never registered through `get_suite()`/`get_suites()`. "
      "As a result, the `v1.1.2` suites (workspace 1.1.2, travel 1.1.2) resolve to the same definitions as `v1.1.1`. These records are kept and flagged `reachable_from_load_suites_import_graph=false`, with no effective versions.")
    A("2. **Slot overwrite at 1.0.0.** " + "; ".join(f"`{n['case_id']}` is registered with `@task_suite.register_user_task` (slot 1.0.0) and so replaces `{n['original_metadata']['slot_overwrote_definition']}`" for n in ovw) +
      ". In the static import order the later definition wins in every benchmark version, including `v1`. The v1 originals are kept, with no effective versions.")
    A("3. Combined tasks capture their component *instances* at import time. For example, `workspace/user_task_19@v1` composes the v1 `user_task_13` instance. Component resolution follows the source accessors (`user_tasks[...]`, `get_latest_user_task_by_id`, `_user_tasks[id][V]`) against the simulated registry state at that point.")
    A("4. The `runs/` JSON files carry a `benchmark_version` field only in the newer runs (`v1.2.1` for the Llama-3.3 and Meta-SecAlign runs). Older runs have none (`None` in runs_inventory.csv), so their benchmark version cannot be read from the files.")
    A("")
    A("## Files")
    A(f"Schema version `{SCHEMA_VERSION}`.")
    A("- `raw_samples.jsonl`: one **extraction envelope** per task definition (class, including its decorator lines, or combinator call). It holds the verbatim source text, sha256 and locator (path, start/end line, GitHub permalink, snapshot path). This is not an original JSON record, because AgentDojo has none.")
    A("- `normalized_samples.jsonl`: one record per definition, `record_type` = `user_task` | `attacker_task` (AgentDojo calls these injection tasks).")
    A("- `case_summary.csv`: one row per normalized record. `collector_summary` is collector-written (whitespace-collapsed, truncated to 140 chars, prefixed `[collector summary]`) and is not source text.")
    A("- `tools.jsonl`: one record per tool function: name, static docstring description, raw docstring, arguments (annotation source, default, required, `:param` description, whether it enters the runtime schema), environment dependencies (`Depends`), return annotation, suites, provenance.")
    A("- `relationships.jsonl`: only relationships supported by the source, each with evidence (path/line) and basis. Types and counts are listed below. It has **no user-task x attacker-task pairs**.")
    A("- `injection_vectors.jsonl`: suite injection vectors (description, default fill text, placeholder locations in the fixtures). These are the injection surfaces published as source facts.")
    A("- `attacks.jsonl`: registered attack generators with their **template source text** (not payloads), placeholders and provenance.")
    A("- `version_matrix.csv`: benchmark_version x suite x task ID -> effective definition (`case_id`).")
    A("- `trajectory_links.jsonl`, `runs_inventory.csv`: inventory of published execution trajectories (see below).")
    A("- `static_analysis.json`: the import order used, every registration event, dormant modules, suite tool lists, fixture details and the runs summary.")
    A("- `git_tree_listing.json`, `git_commit_metadata.json`: provenance for the pinned commit. `source_snapshot/`: preserved files.")
    A("- `manifest.json`: commit, retrieval time, tarball hash, blob verification, counts, and the sha256 of every file except itself and validation_output.txt. `validation_output.txt`: actual validator output. `collect_and_validate.py`: the full pipeline.")
    A("")
    A("### Field mapping (normalized_samples.jsonl)")
    A("| Field | Source / rule |")
    A("|---|---|")
    for k, v in [
        ("case_id", "collector-generated `agentdojo/<suite>/<task_id>@<definition_folder>` (unique per definition)"),
        ("dataset", "\"AgentDojo\""), ("suite", "suite of the `task_suite` object targeted by the decorator / combinator"),
        ("record_type", "`user_task` (UserTaskN) or `attacker_task` (InjectionTaskN)"),
        ("original_task_id", "`user_task_N` / `injection_task_N`, as assigned by TaskSuite from the class name"),
        ("legitimate_user_task", "`PROMPT` (user tasks). For combined tasks: the `prompt=` literal, or the combinator's default template filled with the component PROMPTs (marked as derived in interpretation.field_resolution). Null for attacker tasks"),
        ("attacker_objective", "`GOAL` (attacker tasks); null for user tasks"),
        ("published_attack_payload", "always null: no concrete payload is published in the definitions (see attacks.jsonl for generators)"),
        ("injection_target_or_surface", "always null + unresolved: computed at runtime by get_injection_candidates (suite-level surfaces are in injection_vectors.jsonl)"),
        ("relevant_tools", "tool names in `FunctionCall(function=\"...\")` literals in `ground_truth` (combined tasks: union of the components)"),
        ("environment_fixture_refs", "the suite's environment.yaml, its includes, and injection_vectors.yaml"),
        ("evaluator_refs", "ground_truth / utility / utility_from_traces or ground_truth / security / security_from_traces method ranges (inherited defaults are noted without lines)"),
        ("original_metadata", "registration mechanism, decorator source, version slot, effective benchmark versions, reachability, slot overwrite, class attributes (DIFFICULTY, GROUND_TRUTH_OUTPUT, COMMENT, private constants such as attacker IBANs or e-mails, as literal values or unresolved), methods, ground-truth call list with lines, combinator components"),
        ("supplied_continuation", "always null (none in the source)"),
        ("observed_outcome", "always null. Evaluator code, ground truths and goals are not outcomes, and run logs were not read for outcomes"),
        ("provenance", "repository URL, commit, source path, symbol, module, exact start/end lines, GitHub permalink, raw_id, sha256 of the source text, retrieval time"),
        ("extraction_status / unresolved_fields", "`resolved_except_runtime_fields` when only runtime-computed fields are missing, `partial` otherwise; each unresolved field has a reason and a source reference"),
        ("interpretation", "collector notes, kept apart from the source facts"),
    ]:
        A(f"| {k} | {v} |")
    A("")
    A("### Relationship types and counts")
    for t, k in c["relationships_by_type"].items():
        A(f"- `{t}`: {k}")
    A(f"- Total: {c['relationships_total']}. `task_effective_in_benchmark_version` follows the static version-resolution rule. `task_ground_truth_calls_tool` targets a suite-scoped tool name, which resolves to a tools.jsonl entry through `suite_exposes_tool`.")
    A("")
    A("## Published execution trajectories (inventoried, not collected)")
    for t in S["traj"]:
        A(f"- {t['location']}: {t['kind']}. Access: {t['access_conditions']}. Status: {t['collected']}.")
    A(f"- `runs_inventory.csv` lists all {c['runs_files_inventoried']} files under `runs/` across {c['runs_pipelines']} pipeline directories, with path-derived pipeline/suite/task/attack/injection-task, size, sha256, git-blob verification, and four metadata keys (`benchmark_version`, `agentdojo_package_version`, `evaluation_timestamp`, number of injection keys). "
      "Messages, injection text, errors and utility/security results were **not** read out. These files contain concrete rendered injections, so they are the only place where concrete payloads and actually-run task-attack combinations are published. Extracting them is deferred to a separate task.")
    A("")
    A("## Extraction limits and unresolved fields")
    uc = Counter(u["field"] for n in norm for u in n["unresolved_fields"])
    for k, v in sorted(uc.items()):
        A(f"- `{k}`: {v} records.")
    partial = [n["case_id"] for n in norm if n["extraction_status"] == "partial"]
    A(f"- Records with status `partial` (PROMPT/GOAL or tool list not statically resolvable): {len(partial)}" + (f": {', '.join(partial)}" if partial else "") + ".")
    A("- `injection_target_or_surface` needs execution: the injectable vectors per user task are found by running its ground truth. `published_attack_payload` is generated per (user task, injection task, vector, model). The runtime tool description and JSON schema come from docstring_parser + Pydantic, and the combined-task GROUND_TRUTH_OUTPUT is built at runtime. Utility/security results need execution against an LLM.")
    A("- Ground-truth tool lists cover only `FunctionCall` literals. Calls built some other way would be missed, and are flagged when detected. Task-specific `init_environment` overrides (recorded) change the starting state at runtime.")
    A("- Benchmark membership was derived by static import-order simulation, not by executing `load_suites`. The two findings above should be confirmed in an isolated environment.")
    A("")
    A("## Reproduction")
    A("```")
    A(f"python3 collect_and_validate.py collect --out <OUT_DIR> --retrieved-at {core['retrieved_at']['utc']}")
    A("#   downloads the pinned tarball, git tree and commit metadata (public, no credentials), or use --tarball/--tree/--commit-json offline,")
    A("#   then writes all outputs, README.md and manifest.json, and runs validation")
    A("python3 collect_and_validate.py validate --out <OUT_DIR>    # re-validate an existing output folder")
    A("```")
    A("Requires Python >= 3.10 and the stdlib only. PyYAML is optional, for one extra cross-check. The output is deterministic for a fixed commit and `--retrieved-at`.")
    A("")
    A("## References consulted")
    A("- `TestSample/README.md` (InjecAgent Pilot-100) was used as the template: pinned commit with verified bytes, verbatim preservation, raw vs normalized split, collector-written summaries, null-not-invented outcomes, manifest hashes, and a separate validation output.")
    A("- `NMT Open Dataset Research.docx` (5 Oct 2026) was read for background only. Its AgentDojo entry (\"97 user tasks, 27 injection targets and 629 task-goal combinations across four suites\"; \"Code MIT; no separate fixture/data license identified\"; \"Published trajectories are also available\") agrees with the v1 counts and the license findings here. "
      "\"Injection targets\" there means injection *tasks* (attacker goals). The fixtures also declare 39 injection *vectors* (placeholders), which are a different count. The doc's AgentDojo links point to the repository, the results page and arXiv:2406.13352. It was not treated as permission to collect other datasets.")
    A("")
    A("## Before replay (not done here)")
    A("- Install the pinned package and dependencies (`uv.lock`) in an isolated, egress-restricted environment. Confirm the static findings by loading `get_suites(<version>)` there, and choose the benchmark version explicitly (the script default is v1.2.2).")
    A("- Run each suite's ground truths to compute injection candidates per user task (needed for injection surfaces and payloads), and render attack payloads per attack, model name and user name.")
    A("- Configure model/provider credentials, the pipeline/defense configuration and spend caps, and enumerate the user x injection task pairs from the per-suite cross product.")
    A("- Add instrumentation that keeps attempted, denied, executed and successful actions apart, plus authorization labels and clean controls, as the NMT doc recommends. For comparison, either extract the published runs/ logs (concrete payloads and outcomes) or re-run under pinned conditions.")
    A("")
    A("<!-- COUNTS-JSON " + json.dumps(readme_counts(c)) + " -->")
    (out / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def run_collect(args):
    S = collect(args)
    core = write_outputs(S)
    S["traj"] = [json.loads(l) for l in (S["out"] / "trajectory_links.jsonl").read_text(encoding="utf-8").splitlines()]
    S["trajectory_bytes"] = sum(len(b) for b in S["runs_files"].values())
    write_readme(S, core)
    shutil.copyfile(Path(__file__).resolve(), S["out"] / "collect_and_validate.py") if Path(__file__).resolve() != (S["out"] / "collect_and_validate.py").resolve() else None
    finalize(S["out"])
    return validate(S["out"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--out", required=True)
    c.add_argument("--tarball"); c.add_argument("--tree"); c.add_argument("--commit-json")
    c.add_argument("--retrieved-at", help="ISO UTC timestamp (YYYY-MM-DDTHH:MM:SSZ) of the original retrieval; default now")
    v = sub.add_parser("validate"); v.add_argument("--out", required=True)
    a = ap.parse_args()
    ok = run_collect(a) if a.cmd == "collect" else validate(Path(a.out))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
