#!/usr/bin/env python3
"""
collect_and_validate.py
=======================
Reproducible, static-only collection + validation of the malicious MCP server
fixtures released in the Connor repository (https://github.com/yiheng98/Connor),
for Problem Statement 3 (component observed-vs-declared-scope evaluation).

This script performs COLLECTION and STATIC DOCUMENTATION only. It:
  * copies original fixture files verbatim into source_snapshot/ (repo paths kept),
  * statically parses Python with the `ast` module (parse only -- never import/exec),
  * parses mcp.json / pyproject.toml as text/JSON/TOML,
  * emits raw_samples.jsonl, normalized_samples.jsonl, case_summary.csv,
    component_files.jsonl, manifest.json, validation_output.txt.

It NEVER imports a fixture module, installs dependencies, runs a setup/build
script, starts an MCP server, loads a skill, executes a test harness, or contacts
any endpoint named in fixture content. No credentials or network are used.

Usage:
    python3 collect_and_validate.py <repo_clone_dir> <output_dir>

<repo_clone_dir> must be a checkout of github.com/yiheng98/Connor pinned at the
commit recorded in manifest.json.
"""
import ast
import csv
import datetime
import hashlib
import json
import os
import re
import sys

SCHEMA_VERSION = "connor-malicious-mcp-normalized/1.0"
REPO_URL = "https://github.com/yiheng98/Connor"
PINNED_COMMIT = "326ab9116699442d2744b445b38c69524fbf43e6"
PAPER = "arXiv:2604.01905v2 (Huang et al., From Component Manipulation to System Compromise)"

# ---------------------------------------------------------------------------
# Reference tables. SOURCE: arXiv:2604.01905v2, Table 3 (19 influence paths) and
# Sec. 4.1 (6 attack goals). These are source-provided labels, recorded verbatim
# from the paper, and are applied to Connor-constructed PoCs by directory layout.
# ---------------------------------------------------------------------------
INFLUENCE_PATHS = {
    "p1":  {"path": "A_TD -> LLM1 --arg--> Builtin",                              "injection_point": "TD",            "stage": "LLM1"},
    "p2":  {"path": "A_AS -> LLM1 --arg--> Builtin",                              "injection_point": "AS",            "stage": "LLM1"},
    "p3":  {"path": "A_TD -> LLM1 --arg--> B_TSC",                                "injection_point": "TD, TSC",       "stage": "LLM1"},
    "p4":  {"path": "A_TD -> LLM1 --arg--> A_TSC",                                "injection_point": "TD, TSC",       "stage": "LLM1"},
    "p5":  {"path": "A_AS -> LLM1 --arg--> A_TSC",                                "injection_point": "AS, TSC",       "stage": "LLM1"},
    "p6":  {"path": "A_TD -> LLM1 --uri--> RSC",                                  "injection_point": "TD, RSC",       "stage": "LLM1"},
    "p7":  {"path": "A_TR -> LLM2 --arg--> B_TSC",                                "injection_point": "TR, TSC",       "stage": "LLM2"},
    "p8":  {"path": "A_TR -> LLM2 --arg--> Builtin",                              "injection_point": "TR",            "stage": "LLM2"},
    "p9":  {"path": "A_TR -> LLM2 --arg--> A_TSC",                                "injection_point": "TR, TSC",       "stage": "LLM2"},
    "p10": {"path": "A_TR -> LLM2 --uri--> RSC",                                  "injection_point": "TR, RSC",       "stage": "LLM2"},
    "p11": {"path": "A_TD -> LLM1 --uri--> RR -> LLM2 --arg--> B_TSC",            "injection_point": "TD, RR, TSC",   "stage": "LLM1+2"},
    "p12": {"path": "A_TD -> LLM1 --uri--> RR -> LLM2 --arg--> A_TSC",            "injection_point": "TD, RR, TSC",   "stage": "LLM1+2"},
    "p13": {"path": "A_TD -> LLM1 --uri--> RR -> LLM2 --arg--> Builtin",          "injection_point": "TD, RR",        "stage": "LLM1+2"},
    "p14": {"path": "A_TD -> LLM1 -> B_TR -> LLM2 --uri--> RSC",                  "injection_point": "TD, TR, RSC",   "stage": "LLM1+2"},
    "p15": {"path": "A_TD -> LLM1 -> B_TR -> LLM2 --arg--> A_TSC",                "injection_point": "TD, TR, TSC",   "stage": "LLM1+2"},
    "p16": {"path": "A_TD -> LLM1 -> B_TR -> LLM2 --arg--> Builtin",              "injection_point": "TD, TR",        "stage": "LLM1+2"},
    "p17": {"path": "TSC",                                                        "injection_point": "TSC",           "stage": "null"},
    "p18": {"path": "A_TSC + B_TSC",                                              "injection_point": "TSC",           "stage": "null"},
    "p19": {"path": "CONFIG",                                                     "injection_point": "CONFIG",        "stage": "null"},
}

# Connor PoC category directory -> source-provided attack goal label.
# SOURCE: PoCs/README.md directory names + arXiv:2604.01905v2 Sec 4.1 six goals.
POC_CATEGORY = {
    "backdoor_PoC":     "backdoor (e.g. planting SSH keys / unauthorized execution pathways)",
    "payload_exec_PoC": "download & execute payload",
    "ransomeware_PoC":  "ransomware",   # repo spelling 'ransomeware' kept verbatim
    "reverse_shell_PoC":"reverse shell",
    "stealing_PoC":     "data leakage (token / sensitive data exfiltration)",
    "sabotaging_PoC":   "sabotaging (file tampering/deletion, DoS)",
}

# Dataset/Malicious upstream attribution.
# SOURCE: THIRD_PARTY_NOTICES.md lists four upstream projects; in-file evidence
# (FastMCP display names, /tmp/dvmcp_* paths, Chinese maintenance-notice payloads)
# is used to attribute where determinable. Where not determinable from the repo
# alone, candidate set is recorded and exact upstream marked unresolved.
THIRD_PARTY_SOURCES = [
    "AIS2Lab/MCPSecBench",
    "MCP-Security/MCP-Artifact",
    "harishsg993010/damn-vulnerable-MCP-server",
    "security-pride/MCP_Landscape",
]
DATASET_ATTRIB = {
    # name: (attributed_upstream_or_None, confidence, evidence)
    "MCPSecBench":           ("AIS2Lab/MCPSecBench", "high",
                              "directory name 'MCPSecBench'; matches THIRD_PARTY_NOTICES entry AIS2Lab/MCPSecBench (Yang et al., 2025)"),
    "challenge1":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge2":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge3":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge4":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge5":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge6":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge7":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge8":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge9":  ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "challenge10": ("harishsg993010/damn-vulnerable-MCP-server", "high", "FastMCP name 'Challenge N'; /tmp/dvmcp_* paths match DVMCP"),
    "namespace":   ("security-pride/MCP_Landscape", "medium",
                    "fixture references 'mcp-landscape' repo name and models github namespace-spoofing/shadowing; best matches MCP_Landscape"),
    "tool_poisoning":        (None, "low", "tool-description poisoning PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
    "ETHPriceCurrentServer": (None, "low", "logic-corruption style tool-poisoning PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
    "Poisonattack1":         (None, "low", "tool-description poisoning PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
    "Poisonattack2":         (None, "low", "tool-description poisoning PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
    "Poisonattack3":         (None, "low", "tool-description poisoning PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
    "weather_attack1":       (None, "low", "indirect-prompt-injection-via-external-resource PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
    "weather_attack2":       (None, "low", "indirect-prompt-injection-via-external-resource PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
    "weather_attack3":       (None, "low", "indirect-prompt-injection-via-external-resource PoC; upstream not identifiable from repo alone; candidate: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape"),
}

# PoC fixtures that reference the shipped external resources under PoCs/response/.
# SOURCE: static grep of fixture source (recorded verbatim in the mapping).
RESPONSE_REFS = {
    ("payload_exec_PoC", "p8"): ["PoCs/response/payload_exec_p8_news.html"],
    ("stealing_PoC", "p7"):     ["PoCs/response/stealing_poc_p7_news.html"],
}
# All payload_exec PoCs fetch example.sh from the attacker endpoint; example.sh is
# shipped under PoCs/response/example.sh as the referenced external payload.
for _p in ["p1","p2","p3","p4","p5","p6","p7","p8","p9","p10","p11","p12","p13","p14","p15","p16","p17"]:
    RESPONSE_REFS.setdefault(("payload_exec_PoC", _p), []).append("PoCs/response/example.sh")

SUPPORTING_FILES = [
    "README.md", "LICENSE.md", "THIRD_PARTY_NOTICES.md", ".gitattributes",
    "licenses/APACHE-2.0.txt",
    "PoCs/README.md", "PoCs/LICENSE", "PoCs/NOTICE",
    "PoCs/response/example.sh", "PoCs/response/payload_exec_p8_news.html",
    "PoCs/response/stealing_poc_p7_news.html",
    "Dataset/LICENSE.md",
]

# ---------------------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def copy_verbatim(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(fi.read())

def seg(src, node):
    try:
        s = ast.get_source_segment(src, node)
        return s if s is not None else ""
    except Exception:
        return ""

def parse_python_interfaces(src):
    """Statically parse a FastMCP server file. Returns (servers, tools, parse_error).
    Never imports or executes the module."""
    servers = {}   # varname -> display name
    tools = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {}, [], f"SyntaxError: {e}"
    # server instances
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            fname = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if fname == "FastMCP":
                disp = None
                if node.value.args:
                    a0 = node.value.args[0]
                    if isinstance(a0, ast.Constant):
                        disp = a0.value
                for kw in node.value.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        disp = kw.value.value
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        servers[t.id] = disp
    # tools / resources / prompts
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                dcall = dec if isinstance(dec, ast.Call) else None
                dattr = dcall.func if dcall else dec
                if not isinstance(dattr, ast.Attribute):
                    continue
                kind = dattr.attr  # 'tool' | 'resource' | 'prompt'
                if kind not in ("tool", "resource", "prompt"):
                    continue
                server_var = getattr(dattr.value, "id", None)
                # name / uri
                name = node.name
                uri = None
                if dcall:
                    if dcall.args and isinstance(dcall.args[0], ast.Constant):
                        uri = dcall.args[0].value
                    for kw in dcall.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            name = kw.value.value
                # params
                params = []
                a = node.args
                defaults = list(a.defaults)
                pos = list(a.args)
                default_map = {}
                if defaults:
                    for p, d in zip(pos[-len(defaults):], defaults):
                        default_map[p.arg] = seg(src, d)
                for p in pos:
                    params.append({
                        "name": p.arg,
                        "annotation": seg(src, p.annotation) if p.annotation else None,
                        "default": default_map.get(p.arg),
                    })
                tools.append({
                    "server_var": server_var,
                    "server_display_name": servers.get(server_var),
                    "kind": kind,
                    "name": name,
                    "resource_uri": uri,
                    "parameters": params,
                    "returns": seg(src, node.returns) if node.returns else None,
                    "docstring": ast.get_docstring(node, clean=False),
                })
    return servers, tools, None

def parse_pyproject_deps(path):
    if not os.path.exists(path):
        return [], None
    txt = read_text(path)
    reqpy = None
    m = re.search(r'requires-python\s*=\s*"([^"]+)"', txt)
    if m:
        reqpy = m.group(1)
    deps = []
    # Bracket-aware parse: mcp[cli] contains ], so non-greedy \[.*?\] is wrong.
    m = re.search(r'dependencies\s*=\s*\[', txt)
    if m:
        i = m.end()
        depth = 1
        while i < len(txt) and depth:
            if txt[i] == '[': depth += 1
            elif txt[i] == ']': depth -= 1
            i += 1
        block = txt[m.end():i-1]
        deps = re.findall(r'"([^"]+)"', block)
    return deps, reqpy

def network_endpoints(src):
    """Extract external endpoints referenced in source (recorded, never contacted)."""
    eps = set()
    for pat in [r'https?://[^\s"\'\)\]]+', r'/dev/tcp/[^\s"\'\)]+', r'nc\s+[\w\.\-]+\s+\d+']:
        for m in re.findall(pat, src):
            eps.add(m.rstrip('.,'))
    return sorted(eps)

# ---------------------------------------------------------------------------
def collect(repo, out):
    os.makedirs(out, exist_ok=True)
    # author-reported ASR from Appendix B (optional companion file next to this script)
    asr_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "author_asr.json")
    if os.path.exists(asr_path):
        with open(asr_path, encoding="utf-8") as _f:
            AUTHOR_ASR = json.load(_f)
    else:
        AUTHOR_ASR = {}
    snap = os.path.join(out, "source_snapshot")
    retrieval_time = datetime.datetime.now().astimezone().isoformat()

    raw_records = []
    norm_records = []
    comp_file_records = []
    source_hashes = {}   # repo_path -> sha256

    def snapshot(repo_rel):
        srcp = os.path.join(repo, repo_rel)
        dstp = os.path.join(snap, repo_rel)
        copy_verbatim(srcp, dstp)
        h = sha256_file(srcp)
        source_hashes[repo_rel] = h
        return h

    # supporting files
    for rel in SUPPORTING_FILES:
        if os.path.exists(os.path.join(repo, rel)):
            snapshot(rel)
    # benign zip: LFS pointer only (out of scope, not downloaded). Snapshot the pointer text.
    benign = "Dataset/Benign/benign_servers.zip"
    if os.path.exists(os.path.join(repo, benign)):
        snapshot(benign)

    fixtures = []  # (case_id, kind, category_or_source, name, repo_dir, pyfile)
    # 114 Connor PoCs
    pocs_root = os.path.join(repo, "PoCs")
    for cat in sorted(POC_CATEGORY):
        catdir = os.path.join(pocs_root, cat)
        if not os.path.isdir(catdir):
            continue
        for pdir in sorted(os.listdir(catdir),
                           key=lambda x: (0, int(x[1:])) if re.fullmatch(r'p\d+', x) else (1, x)):
            full = os.path.join(catdir, pdir)
            if not os.path.isdir(full):
                continue
            case_id = f"connor-poc-{cat}-{pdir}"
            fixtures.append(("poc", cat, case_id, pdir, f"PoCs/{cat}/{pdir}", "main.py"))
    # 20 prior/third-party Dataset/Malicious servers
    mal_root = os.path.join(repo, "Dataset", "Malicious")
    for name in sorted(os.listdir(mal_root),
                       key=lambda x: (re.sub(r'\d+$','',x), int(re.search(r'\d+$',x).group()) if re.search(r'\d+$',x) else -1)):
        full = os.path.join(mal_root, name)
        if not os.path.isdir(full):
            continue
        pys = sorted([f for f in os.listdir(full) if f.endswith(".py")])
        pyfile = pys[0] if pys else None
        case_id = f"connor-dataset-malicious-{name}"
        fixtures.append(("dataset", None, case_id, name, f"Dataset/Malicious/{name}", pyfile))

    for kind, cat, case_id, name, repo_dir, pyfile in fixtures:
        full_dir = os.path.join(repo, repo_dir)
        files = sorted(os.listdir(full_dir))
        file_entries = []
        for fn in files:
            rel = f"{repo_dir}/{fn}"
            if os.path.isfile(os.path.join(full_dir, fn)):
                h = snapshot(rel)
                file_entries.append({
                    "repo_path": rel,
                    "snapshot_path": f"source_snapshot/{rel}",
                    "sha256": h,
                    "size_bytes": os.path.getsize(os.path.join(full_dir, fn)),
                })
        # static parse
        servers, tools, perr = ({}, [], None)
        src_text = ""
        if pyfile:
            src_text = read_text(os.path.join(full_dir, pyfile))
            servers, tools, perr = parse_python_interfaces(src_text)
        mcp_json_text = None
        mcp_json_obj = None
        if os.path.exists(os.path.join(full_dir, "mcp.json")):
            mcp_json_text = read_text(os.path.join(full_dir, "mcp.json"))
            try:
                mcp_json_obj = json.loads(mcp_json_text)
            except Exception:
                mcp_json_obj = None
        deps, reqpy = parse_pyproject_deps(os.path.join(full_dir, "pyproject.toml"))
        endpoints = network_endpoints(src_text) if src_text else []

        server_names = sorted({v for v in servers.values() if v})
        tool_list = [{
            "name": t["name"], "kind": t["kind"], "server": t["server_display_name"],
            "resource_uri": t["resource_uri"],
            "parameters": t["parameters"], "returns": t["returns"],
            "docstring": t["docstring"],
        } for t in tools]

        # mcp.json command/args
        setup = None
        config_command_malicious = False
        if mcp_json_obj:
            srvs = mcp_json_obj.get("mcpServers", {})
            parts = []
            for k, v in srvs.items():
                cmd = v.get("command")
                args = v.get("args", [])
                parts.append({"server_key": k, "command": cmd, "args": args})
                joined = (cmd or "") + " " + " ".join(args or [])
                if re.search(r'authorized_keys|/dev/tcp|\bnc\b|curl|wget|base64|bash -c', joined):
                    config_command_malicious = True
            setup = parts

        # external resource refs
        resp_refs = []
        if kind == "poc":
            resp_refs = RESPONSE_REFS.get((cat, name), [])

        # origin
        if kind == "poc":
            origin = "Connor-constructed"
            goal = POC_CATEGORY[cat]
            ip = INFLUENCE_PATHS.get(name, {})
            influence_path = {
                "path_id": name.upper(),
                "influence_path": ip.get("path"),
                "injection_point": ip.get("injection_point"),
                "stage": ip.get("stage"),
                "source": f"{PAPER}, Table 3",
            }
            attack_labels = {
                "category_directory": cat,          # verbatim repo dir name
                "path_directory": name,             # verbatim repo subdir name
                "attack_goal": goal,                # paper Sec 4.1 goal label
            }
            lic_refs = ["PoCs/LICENSE", "PoCs/NOTICE", "licenses/APACHE-2.0.txt (Apache-2.0)"]
            upstream = {"attributed_source": "Connor (this repository)", "confidence": "high",
                        "evidence": f"file located under PoCs/{cat}/{name}; PoCs/README.md declares these as the 114 constructed PoCs"}
        else:
            origin = "prior PoC"
            attrib, conf, ev = DATASET_ATTRIB.get(name, (None, "low", "unresolved"))
            goal = None
            influence_path = None   # not labeled with Connor influence paths in source
            attack_labels = {
                "directory": name,
                "fastmcp_display_names": server_names,  # often encodes the attack label verbatim
            }
            lic_refs = ["Dataset/LICENSE.md", "THIRD_PARTY_NOTICES.md",
                        "upstream third-party license applies (not Apache-2.0)"]
            upstream = {"attributed_source": attrib, "candidate_sources": THIRD_PARTY_SOURCES,
                        "confidence": conf, "evidence": ev}

        # dependencies & environment
        env = {
            "python_dependencies": deps,
            "requires_python": reqpy,
            "runtime_from_mcp_json": setup,
            "host_requirements": "Connor detector requires Docker to run servers (repo README); fixtures are stdio FastMCP servers",
            "external_resource_dependencies": resp_refs,
            "referenced_external_endpoints_DO_NOT_CONTACT": endpoints,
        }

        # declared description
        declared_description = {
            "fastmcp_display_names": server_names,
            "primary_source_file": f"{repo_dir}/{pyfile}" if pyfile else None,
            "note": "FastMCP display name(s) and tool docstrings (recorded verbatim under declared_tools_and_capabilities).",
        }

        # expected behavior (collector-summarized from DECLARED cover functionality only)
        cover = None
        if server_names:
            cover = server_names[0]
        expected_behavior = {
            "declared_cover_functionality": cover,
            "basis": "collector summary of the server's self-declared functionality (FastMCP name / tool summary line); extracted from source, not an authorized task spec or clean control",
        }

        # documented setup/trigger
        documented_setup_or_trigger = {
            "mcp_json": setup,
            "mcp_json_raw": mcp_json_text,
            "config_command_contains_shell_payload": config_command_malicious,
        }

        # unresolved
        unresolved = []
        if perr:
            unresolved.append(f"python_parse_error: {perr}")
        if not server_names:
            unresolved.append("no_fastmcp_display_name_found")
        if kind == "dataset" and upstream["attributed_source"] is None:
            unresolved.append("exact_upstream_source_unresolved")
        if kind == "dataset":
            unresolved.append("documented_attacker_objective_not_explicitly_labeled_in_source")

        extraction_status = "complete" if not unresolved else "partial"

        # interpretation (collector notes, separated from source facts)
        interp = []
        if kind == "poc":
            interp.append(f"Collector reads this as a Connor-constructed fixture instantiating influence path {name.upper()} with attack goal '{goal}'. The injected instructions live in the tool docstring(s)/argument schema and/or mcp.json command; they are declared-scope artifacts, NOT observed runtime behavior.")
            if config_command_malicious:
                interp.append("mcp.json command embeds a shell payload (config-channel / P19-style trigger).")
            if resp_refs:
                interp.append(f"Fixture references shipped external resource(s) {resp_refs}; served locally via 'python -m http.server 8080' per PoCs/README (not started here).")
        else:
            interp.append("Collector reads this as a prior/third-party PoC bundled into Connor's evaluation Dataset/Malicious; it is NOT a Connor-constructed fixture. Upstream attribution per THIRD_PARTY_NOTICES.md + in-file evidence.")
        interp.append("observed_outcome is null: no component was executed. Any attack objective / malicious code pattern is a declared/author-reported property, not a measured experimental result.")

        provenance = {
            "repository_url": REPO_URL,
            "commit_hash": PINNED_COMMIT,
            "source_paths": [fe["repo_path"] for fe in file_entries],
            "original_component_dir": repo_dir,
            "original_identifiers": {"name": name, "category_or_source": cat if cat else "Dataset/Malicious"},
            "retrieval_time": retrieval_time,
            "retrieval_time_zone": "America/Denver",
        }

        norm = {
            "case_id": case_id,
            "dataset": "Connor",
            "schema_version": SCHEMA_VERSION,
            "original_component_id_or_name": name,
            "component_origin": origin,
            "component_upstream_attribution": upstream,
            "component_file_refs": [fe["repo_path"] for fe in file_entries],
            "declared_description": declared_description,
            "declared_tools_and_capabilities": tool_list,
            "documented_setup_or_trigger": documented_setup_or_trigger,
            "documented_attacker_objective": (
                {"attack_goal": goal, "source": f"PoCs directory '{cat}' + {PAPER} Sec 4.1"} if kind == "poc"
                else {"attack_goal": None, "source": "not explicitly labelled in released fixture; see fastmcp_display_names / interpretation"}
            ),
            "original_behavior_or_attack_labels": attack_labels,
            "influence_path": influence_path,
            "expected_behavior": expected_behavior,
            "author_reported_result": (
                {**AUTHOR_ASR[f"{cat}/{name}"], "evidence_ref": AUTHOR_ASR[f"{cat}/{name}"]["source"]}
                if kind == "poc" and f"{cat}/{name}" in AUTHOR_ASR else None
            ),
            "observed_outcome": None,        # no execution performed
            "runtime_evidence_refs": [],     # no released per-fixture runtime evidence files in repo
            "dependencies_and_environment_requirements": env,
            "license_refs": lic_refs,
            "provenance": provenance,
            "extraction_status": extraction_status,
            "unresolved_fields": unresolved,
            "interpretation": interp,
        }
        norm_records.append(norm)

        raw = {
            "record_type": "source_extraction_record",
            "note": "Extraction record derived from Connor repo source files; NOT an original dataset JSON (the repo ships no per-fixture JSON records).",
            "case_id": case_id,
            "component_origin": origin,
            "source_files": file_entries,
            "fastmcp_servers": servers,
            "extracted_tools_verbatim_docstrings": tools,
            "mcp_json_verbatim": mcp_json_text,
            "pyproject_dependencies": deps,
            "requires_python": reqpy,
            "referenced_external_endpoints": endpoints,
            "external_resource_refs": resp_refs,
            "python_parse_error": perr,
            "provenance": {"repository_url": REPO_URL, "commit_hash": PINNED_COMMIT,
                           "retrieval_time": retrieval_time},
        }
        raw_records.append(raw)

        comp_file_records.append({
            "case_id": case_id,
            "component_origin": origin,
            "files": file_entries,
        })

    # supporting external resources recorded as a non-fixture artifact record
    resp_dir = os.path.join(repo, "PoCs", "response")
    if os.path.isdir(resp_dir):
        resp_files = []
        for fn in sorted(os.listdir(resp_dir)):
            rel = f"PoCs/response/{fn}"
            if os.path.isfile(os.path.join(resp_dir, fn)):
                if rel not in source_hashes:
                    snapshot(rel)
                resp_files.append({"repo_path": rel, "sha256": source_hashes[rel],
                                   "size_bytes": os.path.getsize(os.path.join(repo, rel))})
        raw_records.append({
            "record_type": "supporting_artifact_record",
            "note": "Shipped external resources (malicious HTML for indirect prompt injection + example.sh payload) referenced by payload_exec/stealing PoCs. Supporting artifacts, NOT counted as distinct server fixtures. README.md calls this folder 'external_resources' but it is released as 'PoCs/response/'.",
            "case_id": "connor-supporting-response-resources",
            "files": resp_files,
        })

    # ---- write outputs ----
    def write_jsonl(fn, records):
        with open(os.path.join(out, fn), "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_jsonl("raw_samples.jsonl", raw_records)
    write_jsonl("normalized_samples.jsonl", norm_records)
    write_jsonl("component_files.jsonl", comp_file_records)

    # case_summary.csv (collector-written)
    with open(os.path.join(out, "case_summary.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "component_origin", "category_or_upstream", "fixture_name",
                    "influence_path_id", "injection_point", "declared_cover_functionality",
                    "attacker_objective_label", "num_files", "collector_summary"])
        for n in norm_records:
            ip = n["influence_path"]
            if n["component_origin"] == "Connor-constructed":
                cat_or_up = n["original_behavior_or_attack_labels"]["category_directory"]
                obj = n["documented_attacker_objective"]["attack_goal"]
                summ = f"Connor PoC: {ip['path_id']} ({ip['injection_point']}) goal={obj}; masquerades as '{n['expected_behavior']['declared_cover_functionality']}'."
            else:
                up = n["component_upstream_attribution"]["attributed_source"] or "upstream-unresolved"
                cat_or_up = up
                obj = "; ".join(n["original_behavior_or_attack_labels"].get("fastmcp_display_names", [])) or "n/a"
                summ = f"Prior/third-party PoC ({up}); declared names: {obj}."
            w.writerow([
                n["case_id"], n["component_origin"], cat_or_up,
                n["original_component_id_or_name"],
                ip["path_id"] if ip else "", ip["injection_point"] if ip else "",
                n["expected_behavior"]["declared_cover_functionality"] or "",
                obj if n["component_origin"] == "Connor-constructed" else "",
                len(n["component_file_refs"]), summ,
            ])

    # manifest.json
    counts_origin = {}
    counts_poc_goal = {}
    counts_dataset_upstream = {}
    for n in norm_records:
        counts_origin[n["component_origin"]] = counts_origin.get(n["component_origin"], 0) + 1
        if n["component_origin"] == "Connor-constructed":
            g = n["documented_attacker_objective"]["attack_goal"]
            counts_poc_goal[g] = counts_poc_goal.get(g, 0) + 1
        else:
            up = n["component_upstream_attribution"]["attributed_source"] or "unresolved-upstream"
            counts_dataset_upstream[up] = counts_dataset_upstream.get(up, 0) + 1

    out_files = ["raw_samples.jsonl", "normalized_samples.jsonl", "component_files.jsonl",
                 "case_summary.csv"]
    output_hashes = {fn: sha256_file(os.path.join(out, fn)) for fn in out_files}

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository_url": REPO_URL,
        "commit_hash": PINNED_COMMIT,
        "paper": PAPER,
        "retrieval_time": retrieval_time,
        "retrieval_time_zone": "America/Denver",
        "collection_mode": "static_documentation_only_no_execution",
        "counts": {
            "distinct_component_fixtures": len(norm_records),
            "by_component_origin": counts_origin,
            "connor_constructed_by_attack_goal": counts_poc_goal,
            "prior_poc_by_upstream": counts_dataset_upstream,
            "raw_extraction_records": len(raw_records),
            "snapshot_source_files": len(source_hashes),
        },
        "source_file_sha256": source_hashes,
        "output_file_sha256": output_hashes,
        "notes": [
            "distinct_component_fixtures counts one MCP server directory per fixture (a fixture = one server dir with its mcp.json + source + pyproject), NOT one per file.",
            "Connor-constructed fixtures = 19 influence paths x 6 attack goals = 114.",
            "prior PoC fixtures = 20 servers under Dataset/Malicious (from existing research).",
            "Dataset/Benign/benign_servers.zip is a Git-LFS pointer (527 MB), benign and out of scope; not downloaded. Only the LFS pointer text is snapshotted.",
            "observed_outcome is null for every record (no execution).",
        ],
    }
    # ship author_asr companion for reproducibility (if present)
    if AUTHOR_ASR:
        with open(os.path.join(out, "author_asr.json"), "w", encoding="utf-8") as f:
            json.dump(AUTHOR_ASR, f, ensure_ascii=False, indent=2)
        manifest["output_file_sha256"]["author_asr.json"] = sha256_file(os.path.join(out, "author_asr.json"))
        manifest["notes"].append("author_reported_result for Connor PoCs is filled from paper Appendix B Tables 11-16 (parsed into author_asr.json). This is author-reported ASR, NOT observed_outcome.")
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return norm_records, raw_records, comp_file_records, manifest

# ---------------------------------------------------------------------------
def validate(repo, out, norm_records, comp_file_records, manifest):
    lines = []
    def log(s): lines.append(s)
    ok = True

    log("CONNOR MALICIOUS MCP FIXTURE COLLECTION -- VALIDATION OUTPUT")
    log("=" * 64)
    log(f"commit: {manifest['commit_hash']}")
    log(f"retrieval_time: {manifest['retrieval_time']} ({manifest['retrieval_time_zone']})")
    log("")

    # 1. JSONL syntax + counts
    def check_jsonl(fn):
        p = os.path.join(out, fn)
        n = 0
        with open(p, encoding="utf-8") as f:
            for i, ln in enumerate(f, 1):
                if ln.strip():
                    json.loads(ln)
                    n += 1
        return n
    nraw = check_jsonl("raw_samples.jsonl")
    nnorm = check_jsonl("normalized_samples.jsonl")
    ncf = check_jsonl("component_files.jsonl")
    log(f"[1] JSONL syntax OK. raw_samples={nraw}, normalized_samples={nnorm}, component_files={ncf}")

    # 2. unique case_ids
    ids = [n["case_id"] for n in norm_records]
    dup = [x for x in set(ids) if ids.count(x) > 1]
    if dup:
        ok = False; log(f"[2] FAIL duplicate case_ids: {dup}")
    else:
        log(f"[2] OK unique case_ids ({len(ids)})")

    # 3. counts agree across normalized / component_files / csv / manifest
    import csv as _csv
    with open(os.path.join(out, "case_summary.csv"), encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    ncsv = len(rows)
    nman = manifest["counts"]["distinct_component_fixtures"]
    if len({nnorm, ncf, ncsv, nman}) == 1:
        log(f"[3] OK counts agree: normalized={nnorm}, component_files={ncf}, csv={ncsv}, manifest={nman}")
    else:
        ok = False; log(f"[3] FAIL count mismatch: normalized={nnorm}, component_files={ncf}, csv={ncsv}, manifest={nman}")

    # 4. constructed vs prior counted separately
    co = manifest["counts"]["by_component_origin"]
    cc = co.get("Connor-constructed", 0)
    pp = co.get("prior PoC", 0)
    log(f"[4] origin split: Connor-constructed={cc}, prior PoC={pp}, total={cc+pp}")
    if cc == 114 and pp == 20:
        log("    OK matches expected 114 constructed + 20 prior (paper: 134 malicious instances).")
    else:
        ok = False; log("    FAIL expected 114 constructed + 20 prior.")

    # 5. Connor goal distribution 19 each
    gd = manifest["counts"]["connor_constructed_by_attack_goal"]
    log(f"[5] Connor attack-goal distribution: {json.dumps(gd, ensure_ascii=False)}")
    if all(v == 19 for v in gd.values()) and len(gd) == 6:
        log("    OK 6 goals x 19 influence paths.")
    else:
        ok = False; log("    FAIL expected 6 goals x 19 each.")

    # 6. every referenced file exists in snapshot AND matches recorded hash
    mism = 0; missing = 0; checked = 0
    for cfr in comp_file_records:
        for fe in cfr["files"]:
            checked += 1
            snp = os.path.join(out, fe["snapshot_path"])
            if not os.path.exists(snp):
                missing += 1; continue
            if sha256_file(snp) != fe["sha256"]:
                mism += 1
    if missing == 0 and mism == 0:
        log(f"[6] OK all {checked} component files present in snapshot and hashes match.")
    else:
        ok = False; log(f"[6] FAIL snapshot files checked={checked} missing={missing} hash_mismatch={mism}")

    # 7. snapshot hashes == recorded source_file_sha256 (re-read from live repo)
    rem = 0
    for rel, h in manifest["source_file_sha256"].items():
        live = os.path.join(repo, rel)
        if os.path.exists(live) and sha256_file(live) != h:
            rem += 1
    log(f"[7] source hash re-verification against live repo: mismatches={rem}" + (" OK" if rem == 0 else " FAIL"))
    if rem: ok = False

    # 8. observed_outcome null everywhere; author_reported_result null; runtime_evidence empty
    bad = [n["case_id"] for n in norm_records if n["observed_outcome"] is not None]
    bad2 = [n["case_id"] for n in norm_records if n["runtime_evidence_refs"]]
    if not bad and not bad2:
        log(f"[8] OK observed_outcome null for all {len(norm_records)}; runtime_evidence_refs empty for all.")
    else:
        ok = False; log(f"[8] FAIL observed_outcome set: {bad[:5]}; runtime refs: {bad2[:5]}")

    # 9. influence_path only on Connor PoCs; unique (category,path) for PoCs
    poc = [n for n in norm_records if n["component_origin"] == "Connor-constructed"]
    keys = [(n["original_behavior_or_attack_labels"]["category_directory"],
             n["influence_path"]["path_id"]) for n in poc]
    dk = [k for k in set(keys) if keys.count(k) > 1]
    if not dk and all(n["influence_path"] for n in poc):
        log(f"[9] OK {len(poc)} Connor PoCs each carry a unique (category, influence-path) and an influence_path.")
    else:
        ok = False; log(f"[9] FAIL duplicate (cat,path) keys: {dk}")

    # 10. shared / supporting files documented
    # response resources referenced by multiple PoCs
    refcount = {}
    for n in norm_records:
        for r in n["dependencies_and_environment_requirements"]["external_resource_dependencies"]:
            refcount[r] = refcount.get(r, 0) + 1
    log(f"[10] shared external-resource references (documented): {json.dumps(refcount, ensure_ascii=False)}")

    # 11. licensing / missing artifacts reported
    log("[11] licensing: Connor PoCs = Apache-2.0 (PoCs/LICENSE, PoCs/NOTICE); Dataset/Malicious = upstream third-party (Dataset/LICENSE.md, THIRD_PARTY_NOTICES.md). Benign zip (LFS, 527MB) excluded as benign+out-of-scope.")
    unresolved_up = [n["case_id"] for n in norm_records
                     if n["component_origin"] == "prior PoC" and n["component_upstream_attribution"]["attributed_source"] is None]
    log(f"[11] prior-PoC fixtures with unresolved exact upstream: {len(unresolved_up)} -> {unresolved_up}")

    # 12. parse errors
    perr = [r["case_id"] for r in [] ]  # placeholder; parse errors surfaced via unresolved_fields
    pe = [n["case_id"] for n in norm_records if any("python_parse_error" in u for u in n["unresolved_fields"])]
    log(f"[12] python parse errors: {len(pe)} -> {pe}")

    log("")
    log("RESULT: " + ("ALL CHECKS PASSED" if ok else "ONE OR MORE CHECKS FAILED"))
    with open(os.path.join(out, "validation_output.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return ok

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 collect_and_validate.py <repo_clone_dir> <output_dir>")
        sys.exit(2)
    repo, out = sys.argv[1], sys.argv[2]
    norm, raw, cf, manifest = collect(repo, out)
    validate(repo, out, norm, cf, manifest)

if __name__ == "__main__":
    main()
