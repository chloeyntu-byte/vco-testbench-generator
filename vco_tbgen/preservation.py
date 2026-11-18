"""IC618 v6/v5 serializer boundary: splice only a natively created new test.

Cadence's save operation can append duplicate fields to *unmodified* tests.
Keep the exact original file bytes and transplant only the newly created test
from its native save. Unknown formats are refused before any native write.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.parsers import expat


def fragments(data,path):
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('DTD/ENTITY not supported')
    parser=expat.ParserCreate();stack=[];starts=[];rows=[]
    def start(name,attrs):
        stack.append(name)
        if tuple(stack)==path:starts.append(parser.CurrentByteIndex)
    def end(name):
        if tuple(stack)==path:
            first=starts.pop();last=data.index(b'>',parser.CurrentByteIndex)+1
            raw=data[first:last];element=ET.fromstring(raw)
            key=element.attrib.get('Name') or (element.text or '').strip()
            rows.append((key,raw))
        stack.pop()
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(data,True)
    if len({k for k,_ in rows})!=len(rows):raise ValueError('duplicate test identities')
    return dict(rows)


def qualify(setup):
    setup=Path(setup)
    required={'maestro.sdb':('setupdb','6'),'active.state':('statedb','5')}
    for file,(tag,version) in required.items():
        if (setup/file).is_symlink():raise ValueError('setup files must not be symlinks')
        data=(setup/file).read_bytes()
        if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('unsafe/unsupported XML')
        root=ET.fromstring(data)
        if root.tag!=tag or root.attrib.get('version')!=version:raise ValueError('unsupported Maestro format: '+file)


def preserve_original(backup,setup,new_test):
    backup=Path(backup);setup=Path(setup);qualify(backup);qualify(setup)
    for name,path,closing in [('maestro.sdb',('setupdb','active','tests','test'),b'</tests>'),('active.state',('statedb','Test'),b'</statedb>')]:
        original=(backup/name).read_bytes();saved=(setup/name).read_bytes()
        old=fragments(original,path);new=fragments(saved,path)
        if new_test in old or set(new)!=set(old)|{new_test}:raise RuntimeError('native save added unexpected tests')
        fragment=new[new_test]
        # Exactly one insertion; original tests, globals, corners, sweeps and
        # history are preserved byte-for-byte. New test payload comes from SKILL.
        containers=list(fragments(original,path[:-1]).values())
        if len(containers)!=1:raise ValueError('ambiguous XML container')
        container=containers[0];position=container.rfind(closing)
        if position<0:raise ValueError('missing XML container closing tag')
        appended=container[:position]+fragment+b'\n'+container[position:]
        merged=original.replace(container,appended,1)
        ET.fromstring(merged)
        actual=fragments(merged,path)
        if any(actual.get(k)!=v for k,v in old.items()):raise RuntimeError('original test byte mismatch')
        target=setup/name
        temporary=target.with_name(target.name+'.tbgen-new')
        with temporary.open('xb') as stream:stream.write(merged)
        temporary.replace(target)


def native_snapshot_body(setup,output):
    """Effective getter values, in addition to the exact source XML invariant."""
    from .native import sq
    root=ET.parse(Path(setup)/'maestro.sdb').getroot()
    b='o=outfile('+sq(output)+')\n'
    for test in root.findall('./active/tests/test'):
        tn=(test.text or '').strip();t=sq(tn)
        b+='fprintf(o '+sq(tn+' ENABLED %L ENV %L SIM %L JOB %L\n')+' maeGetEnabledAnalysis('+t+' ?session s) maeGetEnvOption('+t+' ?session s) maeGetSimOption('+t+' ?session s) maeGetJobPolicy(?testName '+t+' ?session s))\n'
        b+='foreach(a maeGetEnabledAnalysis('+t+' ?session s) fprintf(o "%s %L\\n" a maeGetAnalysis('+t+' a ?includeEmpty t ?session s)))\n'
        for var in test.findall('./vars/var'):
            name=(var.text or '').strip()
            b+='fprintf(o '+sq(tn+' VAR '+name+' %L\n')+' maeGetVar('+sq(name)+' ?typeName "test" ?typeValue '+t+' ?session s))\n'
    return b+'close(o)\n'


def preserve_run_settings(backup,setup):
    """Keep original active setup bytes while retaining newly registered histories."""
    backup=Path(backup);setup=Path(setup);qualify(backup);qualify(setup)
    old=(backup/'maestro.sdb').read_bytes();saved=(setup/'maestro.sdb').read_bytes()
    path=('setupdb','active')
    old_active=list(fragments(old,path).values());new_active=list(fragments(saved,path).values())
    if len(old_active)!=1 or len(new_active)!=1:raise ValueError('ambiguous active setup')
    merged=saved.replace(new_active[0],old_active[0],1);ET.fromstring(merged)
    (setup/'maestro.sdb').write_bytes(merged)
    (setup/'active.state').write_bytes((backup/'active.state').read_bytes())

    # Native Run also rewrites existing per-test state payloads. Restore those
    # exact files, retaining newly registered history states. Never touch locks.
    for prior in (backup/'test_states').rglob('*.state'):
        target=setup/prior.relative_to(backup)
        if target.is_symlink():raise ValueError('test state symlink refused')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(prior.read_bytes())
