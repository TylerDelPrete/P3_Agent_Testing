#!/usr/bin/env python3
"""Slurm Ollama starter: run on the cluster LOGIN NODE (not workstation)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / 'config.json').read_text())

def expanded(value):
    return str(Path(value).expanduser().resolve())

def run(command, capture=False):
    return subprocess.run(command, check=True, text=True, capture_output=capture)

def state_path():
    return ROOT / '.jobid'

def jobid():
    if not state_path().exists():
        sys.exit('No recorded job. Run: python3 hpc_llm.py start')
    return state_path().read_text().strip()

def submit(kind):
    logdir = Path(expanded(CFG['logs_dir']))
    logdir.mkdir(parents=True, exist_ok=True)
    modeldir = expanded(CFG['models_dir'])
    Path(modeldir).mkdir(parents=True, exist_ok=True)
    binary = CFG['ollama_binary']
    if '/' in binary:
        binary = expanded(binary)
    if kind == 'serve':
        script = ROOT / 'serve.sh'
        arguments = [modeldir, str(CFG['port']), CFG['keep_alive'], str(CFG['context_length']), binary]
        opts = ['--job-name=ollama-api', f"--gres={CFG['gpu_gres']}", f"--mem={CFG['gpu_memory']}",
                f"--time={CFG['time']}"]
        if CFG['gpu_partition']:
            opts.append(f"--partition={CFG['gpu_partition']}")
    else:
        script = ROOT / 'pull.sh'
        manifest = (ROOT / CFG['manifest']).resolve()
        if not manifest.is_file():
            sys.exit(f'Missing manifest: {manifest}')
        arguments = [modeldir, str(CFG['port']), str(manifest), binary]
        opts = ['--job-name=ollama-pull', f"--mem={CFG['cpu_memory']}", '--time=04:00:00']
        if CFG['cpu_partition']:
            opts.append(f"--partition={CFG['cpu_partition']}")
    cmd = ['sbatch', '--parsable', '--nodes=1', '--ntasks=1', f"--cpus-per-task={CFG['cpus']}",
           f"--output={logdir}/{kind}-%j.log", *opts, str(script), *arguments]
    result = run(cmd, True).stdout.strip()
    if kind == 'serve':
        state_path().write_text(result.split(';')[0] + '\n')
    print(f'Submitted {kind} job: {result}')
    print(f'Logs: {logdir}/{kind}-<jobid>.log')

def status():
    jid = jobid()
    r = subprocess.run(['squeue', '-h', '-j', jid, '-o', '%i|%T|%N|%L'],
                       capture_output=True, text=True, check=True)
    if not r.stdout.strip():
        print(f'Job {jid} is not in squeue (completed, failed, or cancelled). Check logs.')
        return
    _, state, node, left = r.stdout.strip().split('|', 3)
    print(f'Job {jid}: {state}; node={node}; time remaining={left}')
    if state == 'RUNNING':
        print(f'SSH tunnel from workstation (if compute-node SSH is allowed):')
        print(f'  ssh -N -J USER@LOGIN_HOST -L 6767:127.0.0.1:{CFG["port"]} USER@{node}')
        print('Local API: http://127.0.0.1:6767/v1')
    else:
        print('The tunnel is available only after the job starts.')

def stop():
    jid = jobid()
    run(['scancel', jid])
    print(f'Cancellation requested for {jid}')
    state_path().unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('start')
    sub.add_parser('status')
    sub.add_parser('stop')
    models = sub.add_parser('models')
    models.add_argument('action', choices=['pull', 'show'])
    args = parser.parse_args()
    if args.cmd == 'start':
        if state_path().exists():
            old = state_path().read_text().strip()
            r = run(['squeue', '-h', '-j', old, '-o', '%T'], True).stdout.strip()
            if r:
                sys.exit(f'Job {old} still active ({r}). Stop it before starting another.')
        submit('serve')
    elif args.cmd == 'status':
        status()
    elif args.cmd == 'stop':
        stop()
    elif args.action == 'pull':
        submit('pull')
    else:
        print((ROOT / CFG['manifest']).read_text())

if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(f'Command failed ({exc.returncode}): {exc.cmd}')
