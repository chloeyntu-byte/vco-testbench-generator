"""Private worker dispatch and artifact paths shared by setup and run."""
import json
import os
from pathlib import Path
import subprocess
import sys
from . import native

def _save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def _target(spec):
    work=Path(spec['workspace']).resolve();lib=Path(spec['library_path']).resolve();m=spec['maestro']
    if not lib.is_relative_to(work):raise ValueError('library_path must be inside the owned workspace')
    if lib.name!=m['lib']:raise ValueError('private library directory must match library name')
    target=lib/m['cell']/m['view']
    if not target.resolve().is_relative_to(lib):raise ValueError('setup symlink escapes owned library')
    return target


def check_unlocked(setup):
    """Never remove locks. Native axlIsSessionReadOnly is the second, race-safe gate."""
    setup=Path(setup)
    locks=[str(p) for p in setup.rglob('*') if p.name.endswith(('.cdslck','.oa-lock')) or '.cdslck.' in p.name or p.name.startswith('.oa-lock')]
    if locks:raise RuntimeError('SETUP_OPEN_OR_LOCKED: close the GUI setup or use an in-GUI plugin: '+', '.join(locks))
    return {'filesystem_locks':locks,'native_gate':'axlIsSessionReadOnly'}


def _locked(action,spec,extra=None,wait=True):
    work=Path(spec['workspace']).resolve();work.mkdir(parents=True,exist_ok=True)
    folder=native.new_folder(work,action)
    _save(folder/'request.json',{'action':action,'spec':spec,'extra':extra or {},'folder':str(folder)})
    command = native.wrap_command(
        [sys.executable, '-B', '-m', 'vco_tbgen.worker', str(folder/'request.json')],
        spec['maestro']['lib'],
    )
    env=os.environ.copy();env['PYTHONPATH']=str(native.ROOT)+os.pathsep+env.get('PYTHONPATH','');env['PYTHONDONTWRITEBYTECODE']='1'
    _save(folder/'transaction-command.json',{'command':command,'cwd':str(folder)})
    if not wait:
        with (folder/'transaction.log').open('w') as log:
            p=subprocess.Popen(command,cwd=folder,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        return {'schema':'vco-tbgen.run.v1','status':'running','pid':p.pid,'manifest_path':str(folder/'response.json'),'points':[],'issues':[]}
    with (folder/'transaction.log').open('w') as log:
        p=subprocess.run(command,cwd=folder,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
    if not (folder/'response.json').exists():raise RuntimeError('transaction failed: '+str(folder)+' rc='+str(p.returncode))
    return json.loads((folder/'response.json').read_text())
