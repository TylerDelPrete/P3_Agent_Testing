"""Explicit compatibility rules derived from the clean fixture, never attack text."""
import ast
import json

def prepared_input(folder,condition):
    def read(name): return json.loads((folder/name).read_text(encoding='utf-8-sig'))
    case=read(condition+'.json'); clean=read('clean.json')
    rules={'optional_limits':{},'optional_nulls':[]}
    name=case['prior_tool_call']['name']
    if case.get('dataset')!='Connor':
        text=clean['tool_response_text']
        try:
            value=json.loads(text)
            if isinstance(value,str): value=ast.literal_eval(value)
        except (ValueError,SyntaxError):
            try: value=ast.literal_eval(text)
            except (ValueError,SyntaxError): value=None
        if name=='get_most_recent_transactions' and isinstance(value,list) and value:
            rules['optional_limits']['n']=len(value)
        if name=='GitHubSearchRepositories' and isinstance(value,dict) and isinstance(value.get('repositories'),list) and value['repositories']:
            rules['optional_limits']['max_results']=len(value['repositories'])
        if name=='search_emails': rules['optional_nulls']=['sender']
    case['retrieval_compatibility']=rules
    case['harness_version']='2-retrieval-classification'
    return case
