"""Run formatted AgentDojo, InjecAgent and Connor cases; save evidence under results."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
SUITES = {'agentdojo':'agent_dojo_tets', 'injecagent':'injec_agent_tets', 'connor':'connor_tests'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=['all', *SUITES], default='all')
    parser.add_argument('--case', default='all', help='Case number 1-100, or all')
    parser.add_argument('--condition', choices=['both','clean','attacked'], default='both')
    parser.add_argument('--port', type=int, default=19891)
    parser.add_argument('--dry-run', action='store_true')
    args=parser.parse_args()
    if args.case!='all':
        try:
            number=int(args.case)
            if not 1<=number<=100: raise ValueError()
        except ValueError: parser.error('--case must be all or a number from 1 to 100')
    selected=[]
    for dataset, subdir in SUITES.items():
        if args.dataset not in ('all', dataset): continue
        for folder in sorted((ROOT/'tests'/subdir).iterdir()):
            if folder.is_dir() and (folder/'clean.json').exists() and (args.case=='all' or int(folder.name.split('_')[0])==number):
                selected.append((dataset,folder))
    if not selected: parser.error('No matching tests')
    sys.path.insert(0,str(ROOT/'runner'))
    from mock_tools import configure_case
    batch=ROOT/'results'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    if not args.dry_run: batch.mkdir(parents=True)
    statuses=[]
    for dataset,folder in selected:
        status={'dataset':dataset,'case':folder.name}
        try:
            for condition in ('clean','attacked'): configure_case(folder,condition)
            print('Validated '+dataset+'/'+folder.name,flush=True)
            if not args.dry_run:
                result=subprocess.run([sys.executable,str(ROOT/'runner/run_test.py'),'--case-dir',str(folder),'--condition',args.condition,'--port',str(args.port),'--output-dir',str(batch/dataset/folder.name)])
                status['exit_code']=result.returncode
            else: status['exit_code']=0
        except Exception as exc:
            status.update(exit_code=1,error=str(exc))
            print('FAILED '+dataset+'/'+folder.name+': '+str(exc),flush=True)
        statuses.append(status)
        if not args.dry_run: (batch/'run_status.json').write_text(json.dumps(statuses,indent=2),encoding='utf-8')
    if args.dry_run: print(f'Validated {sum(s["exit_code"]==0 for s in statuses)}/{len(statuses)} cases. No model calls.')
    else:
        lines=['# Batch results','','| Dataset | Case | Runner status |','|---|---|---|']
        lines += [f'| {s["dataset"]} | {s["case"]} | {"completed" if s["exit_code"]==0 else "failed/incomplete"} |' for s in statuses]
        lines += ['','Runner completion is not a security outcome. Review each case SUMMARY.md and condition result.json.']
        (batch/'SUMMARY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('Results: '+str(batch))
    return int(any(s['exit_code'] for s in statuses))

if __name__=='__main__':
    raise SystemExit(main())
