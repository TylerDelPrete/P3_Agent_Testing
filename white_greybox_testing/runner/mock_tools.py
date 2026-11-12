"""Select source schemas and validate prepared inputs. No tool execution here."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = []
DEFINITIONS = {}

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def initial_state():
    return read(ROOT / 'initial_state.json')

def configure_case(folder, condition='clean'):
    pair = [read(folder / (c + '.json')) for c in ('clean', 'attacked')]
    clean, attacked = pair
    for field in ('case_id', 'user_request', 'prior_tool_call', 'source_setting', 'environment_ref', 'policy_ref'):
        if clean[field] != attacked[field]:
            raise ValueError('Mismatched clean/attacked field: ' + field)
    for condition, case in zip(('clean', 'attacked'), pair):
        if case['condition'] != condition or case.get('observed_outcome') is not None:
            raise ValueError('Invalid condition or prefilled outcome')
    if clean.get('dataset') == 'Connor':
        import hashlib
        project=ROOT.parent.parent.resolve()
        source=read(folder/'source_record.json')
        pinned=[json.loads(line) for line in (project/'data/Connor/collection/normalized_samples.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        if source not in pinned or source['case_id']!=clean['case_id']:
            raise ValueError('Connor component differs from pinned collection')
        for item in read(folder/'provenance.json')['sources']:
            path=(project/item['path']).resolve()
            if not path.is_relative_to(project/'data') or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('Connor source hash mismatch')
        env=read(folder/'environment_spec.json')
        if set(env['definitions'])!=set(env['attacked_definitions']):
            raise ValueError('Connor paired tool availability differs')
        if env['definitions']==env['attacked_definitions'] and clean['tool_response_text']==attacked['tool_response_text']:
            raise ValueError('Connor case has no exposed attack difference')
        DEFINITIONS.clear()
        DEFINITIONS.update(env['attacked_definitions' if condition=='attacked' else 'definitions'])
    elif clean.get('dataset') == 'AgentDojo':
        import hashlib
        source = read(folder / 'source_record.json')
        provenance = read(folder / 'provenance.json')
        project = ROOT.parent.parent.resolve()
        for item in provenance['sources']:
            path = (project / item['path']).resolve()
            if not path.is_relative_to(project / 'data') or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('AgentDojo source hash mismatch: ' + item['path'])
        pinned = [json.loads(line) for line in (project/'data/AgentDojo/collection/normalized_samples.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        if source not in pinned or source['legitimate_user_task'] != clean['user_request']:
            raise ValueError('AgentDojo task differs from pinned source')
        if clean['prior_tool_call']['name'] not in source['relevant_tools']:
            raise ValueError('Retrieval tool is not in source task')
        if clean.get('mock_actions') != attacked.get('mock_actions'):
            raise ValueError('Condition action definitions differ')
        if clean['tool_response_text'] == attacked['tool_response_text']:
            raise ValueError('Identical clean and attacked fixtures')
        environment = read(folder/'environment_spec.json')
        DEFINITIONS.clear()
        DEFINITIONS.update(environment['definitions'])
    else:
        source_path = ROOT.parent.parent / 'data/InjecAgent/collection/normalized_samples.jsonl'
        source = next((json.loads(line) for line in source_path.read_text(encoding='utf-8').splitlines()
                       if json.loads(line)['case_id'] == clean['case_id']), None)
        if source is None:
            raise ValueError('Case not found in pinned InjecAgent collection')
        if attacked['tool_response_text'] != source['malicious_tool_response_content']:
            raise ValueError('Attack text differs from pinned source')
        import ast
        if clean['user_request'] != source['legitimate_user_task'] or clean['prior_tool_call']['name'] != source['relevant_tool'] or clean['prior_tool_call']['arguments'] != ast.literal_eval(source['user_tool_parameters']):
            raise ValueError('Task or retrieval context differs from pinned source')
        if not isinstance(clean['tool_response_text'], str) or clean['tool_response_text'] == attacked['tool_response_text'] or '<Attacker Instruction>' in clean['tool_response_text']:
            raise ValueError('Invalid clean control')
        all_definitions = read(ROOT / 'tool_definitions.json')
        names = list(dict.fromkeys([source['relevant_tool']] + source['attacker_tools']))
        DEFINITIONS.clear()
        DEFINITIONS.update({name: all_definitions[name] for name in names})
    declared = set(read(ROOT/'plugin/openclaw.plugin.json')['contracts']['tools'])
    missing = set(DEFINITIONS) - declared
    if missing:
        raise ValueError('Tools missing from OpenClaw plugin contract: ' + ', '.join(sorted(missing)))
    TOOLS.clear()
    for name, definition in DEFINITIONS.items():
        properties = {p['name']: {'type': [p['type'], 'null'] if p.get('nullable') else p['type'], 'description': p['description'],
                      **({'default': p['default']} if 'default' in p else {}),
                      **({'items': {}} if p['type'] == 'array' else {})} for p in definition['parameters']}
        TOOLS.append({'type': 'function', 'name': name, 'description': definition['summary'],
                      'parameters': {'type': 'object', 'additionalProperties': False, 'properties': properties,
                                     'required': [p['name'] for p in definition['parameters'] if p['required']]}})
    return source
