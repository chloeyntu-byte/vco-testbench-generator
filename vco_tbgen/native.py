"""Fresh batch Virtuoso processes, private mappings, checked native SKILL emission."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = {
    'virtuoso': os.environ.get('TBGEN_VIRTUOSO', 'virtuoso'),
    'environment_script': os.environ.get('TBGEN_ENVIRONMENT_SCRIPT', ''),
    'timeout_seconds': 1800,
    'min_free_bytes': 2147483648,
}


def wrap_command(command, library):
    """Expand an optional argv template for a site scheduler or lock wrapper."""
    raw = os.environ.get('TBGEN_COMMAND_TEMPLATE')
    if not raw:
        return command
    try:
        template = json.loads(raw)
    except ValueError as exc:
        raise ValueError('TBGEN_COMMAND_TEMPLATE must be a JSON array of arguments') from exc
    if (not isinstance(template, list)
            or not all(isinstance(arg, str) and arg for arg in template)
            or template.count('{command}') != 1
            or template[0] in ('{command}', '{library}')):
        raise ValueError('TBGEN_COMMAND_TEMPLATE requires a wrapper executable and one {command} argument')
    index = template.index('{command}')
    return [
        *(library if arg == '{library}' else arg for arg in template[:index]),
        *command,
        *(library if arg == '{library}' else arg for arg in template[index+1:]),
    ]

def sq(value):return json.dumps(str(value),ensure_ascii=True)
def sl(value):
    if value is None:return 'nil'
    if isinstance(value,bool):return 't' if value else 'nil'
    if isinstance(value,(int,float)):return str(value)
    if isinstance(value,(list,tuple)):return 'list('+' '.join(sl(v) for v in value)+')'
    return sq(value)
def pairs(values):return sl([[k,v] for k,v in values.items()])
def guard(call,message):return 'unless('+call+' error('+sq(message)+'))\n'
def new_folder(base,prefix):
    path=Path(base).resolve()/(prefix+'_'+uuid.uuid4().hex[:12]);path.mkdir(parents=True);return path

def execute(body,folder,cds_lib,library,library_path=None,runtime=None,locked=False):
    """Lock wait is outside the owned child timeout; never kill another process."""
    validate_skill(body)
    runtime=dict(DEFAULT_RUNTIME,**(runtime or {}));folder=Path(folder).resolve()
    runtime['min_free_bytes'] = max(DEFAULT_RUNTIME['min_free_bytes'], runtime['min_free_bytes'])
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'job.il').exists():raise FileExistsError('worker directory already used')
    (folder/'home').mkdir()
    (folder/'tmp').mkdir()
    mapping='INCLUDE '+sq(Path(cds_lib).resolve())+'\n'
    if library_path:mapping+='DEFINE '+library+' '+sq(Path(library_path).resolve())+'\n'
    (folder/'cds.lib').write_text(mapping)
    done=folder/'job.ok'
    (folder/'job.il').write_text('tbgenResult=errset(progn(\n'+body+'\n) t)\nwhen(tbgenResult tbgenO=outfile('+sq(done)+') fprintf(tbgenO "OK") close(tbgenO))\nif(tbgenResult then exit(0) else exit(1))\n')
    (folder/'driver.il').write_text('unless(errset(load('+sq(folder/'job.il')+') t) exit(1))\n')
    child = ['set -e']
    if runtime['environment_script']:
        child.append('source '+shlex.quote(runtime['environment_script']))
    child += ['export HOME='+shlex.quote(str(folder/'home')), 'export LC_ALL=C CDS_LOAD_ENV=CWD','export TMPDIR='+shlex.quote(str(folder/'tmp'))+' CDS_TMP_DIR='+shlex.quote(str(folder/'tmp'))+' TMP='+shlex.quote(str(folder/'tmp'))+' TEMP='+shlex.quote(str(folder/'tmp')),'unset CDS_LIB_PATH CDS_LOAD_PATH','for tbgenVar in ${!CDS_MPS_@}; do unset "$tbgenVar"; done', 'df -h /','test "$(df -Pk / | awk \'NR==2 {print $4}\')" -ge '+str((runtime['min_free_bytes']+1023)//1024), 'exec timeout --signal=TERM --kill-after=30 '+str(runtime['timeout_seconds'])+' '+shlex.join([runtime['virtuoso'],'-nograph','-nocdsinit','-cdslib',str(folder/'cds.lib'),'-restore',str(folder/'driver.il'),'-log',str(folder/'cadence.log')])]
    (folder/'child.sh').write_text('\n'.join(child)+'\n')
    command = ['bash', str(folder/'child.sh')]
    if not locked:
        command = wrap_command(command, library)
    subprocess.run(['df','-h','/'],stdout=subprocess.PIPE,check=True)
    if shutil.disk_usage('/').free<runtime['min_free_bytes']:raise RuntimeError('DISK_LOW: below '+str(runtime['min_free_bytes'])+' bytes')
    record={'cwd':str(folder),'command':command,'start':time.time()}
    (folder/'command.json').write_text(json.dumps(record,indent=2)+'\n')
    with (folder/'stdout.log').open('w') as log:
        proc=subprocess.run(command,cwd=folder,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
    record.update(returncode=proc.returncode,elapsed_seconds=time.time()-record['start'],log=str(folder/'stdout.log'),script=str(folder/'job.il'))
    (folder/'command.json').write_text(json.dumps(record,indent=2)+'\n')
    if proc.returncode or not done.exists():raise RuntimeError('NATIVE_FAILED: '+str(folder)+'\n'+(folder/'stdout.log').read_text(errors='replace')[-2400:])
    return record


def validate_skill(text):
    """Catch incomplete emission before a tool/license is started."""
    depth=0;quoted=False;escaped=False;comment=False
    for c in text:
        if comment:
            if c=='\n':comment=False
        elif quoted:
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
        elif c==';':comment=True
        elif c=='"':quoted=True
        elif c=='(':depth+=1
        elif c==')':
            depth-=1
            if depth<0:raise ValueError('unbalanced generated SKILL')
    if depth or quoted:raise ValueError('incomplete generated SKILL')

# Compatibility for earlier consumers of the native emitter.
def __getattr__(name):
    if name in ('create_tb', 'register_cell', 'register_source', 'register_view', 'symbol'):
        from . import schematic
        return getattr(schematic, name)
    if name in ('open_setup', 'test_setup'):
        from . import maestro
        return getattr(maestro, name)
    raise AttributeError(name)
