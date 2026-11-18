"""Generate a bound, fail-closed transaction for a caller-owned Maestro session.

The API emits SKILL; it never attaches to or closes a session. The caller runs
that file in the exact session after reviewing the plan and save policy.
"""
import copy
import datetime
import json
from pathlib import Path
import shlex
import shutil
import sys
from . import native
from .spec import digest, plan
from .transaction import _target, _save
from .maestro import setup_snapshot, test_setup
from .preservation import qualify, native_snapshot_body


def disk_revision(setup):
    return digest({n:(Path(setup)/n).read_bytes().hex() for n in ['maestro.sdb','active.state']})


def plan_session_add(spec, context):
    if spec.get('mode')!='add_test_to_existing':raise ValueError('session API requires add mode')
    proposal=plan(spec)
    if proposal['status']!='ready':raise ValueError('unresolved spec: '+json.dumps(proposal))
    if context.get('schema')!='vco-tbgen.session-context.v1':raise ValueError('unsupported session context')
    required=['session','window_id','lcv','dirty','save_policy','revision','generation','setup_handle']
    if any(k not in context for k in required):raise ValueError('incomplete session context')
    if not isinstance(context['dirty'],bool):raise ValueError('dirty must be known')
    if context['save_policy'] not in ['save','reject']:raise ValueError('explicit save or reject required')
    if context['dirty'] and context['save_policy']=='reject':raise ValueError('UNSAVED_SETUP_REJECTED')
    if not isinstance(context['session'],str) or not context['session'] or not context['generation']:raise ValueError('missing session identity')
    if context['window_id'] is None:
        import os
        if not context.get('private_batch') or os.environ.get('TBGEN_NATIVE')!='1':raise ValueError('exact window required')
    elif not isinstance(context['window_id'],int) or isinstance(context['window_id'],bool):raise ValueError('invalid window')
    if not isinstance(context['setup_handle'],int) or isinstance(context['setup_handle'],bool):raise ValueError('exact setup handle required')
    m=spec['maestro']
    if context['lcv']!={k:m[k] for k in ['lib','cell','view']}:raise ValueError('LCV mismatch')
    setup=_target(spec);qualify(setup)
    if context['revision']!=disk_revision(setup):raise ValueError('stale saved setup revision')
    names=setup_snapshot(setup)['maestro.sdb']
    if m['test'] in names or m['source_test'] not in names:raise ValueError('source/new test identity conflict')
    payload={'schema':'vco-tbgen.session-plan.v1','spec':copy.deepcopy(spec),'context':copy.deepcopy(context),'proposal':proposal}
    return dict(payload,plan_hash=digest(payload))


def materialize_session_add(proposal, session):
    payload={k:v for k,v in proposal.items() if k!='plan_hash'}
    if proposal.get('schema')!='vco-tbgen.session-plan.v1' or digest(payload)!=proposal.get('plan_hash'):raise ValueError('modified session plan')
    if session!=proposal['context']:raise ValueError('stale or different session context')
    spec=proposal['spec']
    if plan_session_add(spec,session)!=proposal:raise ValueError('stale session plan')
    folder=native.new_folder(spec['workspace'],'session-add');setup=_target(spec)
    _save(folder/'plan.json',proposal)
    if spec.get('hbxf_injection'):
        from .isf import write_stimulus
        write_stimulus(spec)
    body=session_skill(proposal,folder)
    native.validate_skill(body);(folder/'transaction.il').write_text(body)
    return {'schema':'vco-tbgen.session-materialized.v1','status':'awaiting_session_execution','new_test':spec['maestro']['test'],
            'skill_path':str(folder/'transaction.il'),'receipt_path':str(folder/'receipt.json'),'plan_hash':proposal['plan_hash'],'context':session}


def session_skill(proposal,folder):
    spec=proposal['spec'];context=proposal['context'];folder=Path(folder);setup=_target(spec)
    def helper(stage):
        argv=[sys.executable,'-B','-m','vco_tbgen.session',stage,str(folder)]
        command='PYTHONPATH='+shlex.quote(str(native.ROOT))+' '+shlex.join(argv)
        return 'unless(system('+native.sq(command)+')==0 error('+native.sq('session '+stage+' failed')+'))\n'
    # Reuse the exact incremental analysis/output emitter, without its lifecycle.
    emitted=test_setup(spec)
    start=emitted.index('tbgenOriginalTests=');end=emitted.index('unless(maeSaveSetup')
    mutation=emitted[start:end]
    state='tbgen_'+proposal['plan_hash'][:16]
    b='let((s tbgenResult tbgenRollback tbgenBeforeDirty)\ns='+native.sq(context['session'])+'\n'
    b+='unless(maeIsValidMaestroSession(s) error("session no longer valid"))\n'
    if context['window_id'] is not None:b+='unless(equal(axlGetWindowSession('+str(context['window_id'])+') s) error("window/session mismatch"))\n'
    for k,func in [('lib','Lib'),('cell','Cell'),('view','View')]:
        b+='unless(equal(axlGetSession'+func+'Name(s) '+native.sq(context['lcv'][k])+') error("session LCV mismatch"))\n'
    b+='unless(equal(axlGetMainSetupDB(s) '+str(context['setup_handle'])+') error("setup handle changed"))\n'
    b+='unless(equal(ddGetObj('+native.sq(spec['maestro']['lib'])+')~>readPath '+native.sq(Path(spec['library_path']).resolve())+') error("session library path mismatch"))\n'
    b+='when(axlIsSessionReadOnly(s) error("session is read-only"))\n'
    b+='tbgenBeforeDirty=maeIsSetupModified(?session s)\nunless(equal(tbgenBeforeDirty '+native.sl(context['dirty'])+') error("dirty context changed"))\n'
    b+=helper('backup')  # pre-save bytes; never copy locks
    if context['dirty']:b+=native.guard('maeSaveSetup(?session s)','explicit save failed')
    # Native serialization baseline and full native rollback state, kept in session.
    b+=native.guard('maeSaveSetupState('+native.sq(state)+' ?session s)','native rollback state failed')
    b+=native.guard('maeSaveSetup(?session s)','baseline save failed')+helper('baseline')
    b+=native_snapshot_body(setup,folder/'native-before.txt')
    b+='tbgenResult=errset(progn(\n'+mutation
    b+=native.guard('maeSaveSetup(?session s)','session save failed')
    b+=native_snapshot_body(setup,folder/'native-after.txt')+helper('verify')
    b+=') t)\n'
    b+='unless(tbgenResult\ntbgenRollback=errset(progn(\n'
    b+=native.guard('maeLoadSetupState('+native.sq(state)+" ?operation 'overwrite ?session s)",'native rollback failed')
    b+=native.guard('maeSaveSetup(?session s)','rollback save failed')
    b+=native_snapshot_body(setup,folder/'native-after.txt')+helper('rollback')
    b+=') t)\nunless(tbgenRollback error("ROLLBACK_FAILED: inspect receipt and backup"))\n)\n'
    b+='unless(maeIsValidMaestroSession(s) error("caller session lost"))\n)\n'
    return b


def logical_snapshot(setup):
    snapshot=setup_snapshot(setup)
    # IC618 accumulates adeInfo cache fields on each save/load. Compare their
    # last effective value; analyses, variables, models and outputs stay exact.
    for test in snapshot['active.state'].values():
        for component in test[3]:
            if component[0]=='component' and dict(component[1]).get('Name')=='adeInfo':
                fields={}
                for field in component[3]:
                    name=dict(field[1]).get('Name')
                    if field[0]!='field' or name not in ['designInfo','projectDir','descriptiontext']:
                        raise ValueError('unknown adeInfo serialization field')
                    fields[name]=field
                component[3]=[fields[k] for k in sorted(fields)]
    return json.loads(json.dumps(snapshot))


def _main(stage,folder):
    folder=Path(folder);proposal=json.loads((folder/'plan.json').read_text());spec=proposal['spec'];setup=_target(spec)
    receipt=folder/'receipt.json';new=spec['maestro']['test']
    try:
        if stage=='backup':
            if disk_revision(setup)!=proposal['context']['revision']:raise ValueError('saved context changed')
            backup=Path(str(setup)+'.bak-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            shutil.copytree(setup,backup,ignore=shutil.ignore_patterns('*.cdslck*','*.oa-lock*','results'))
            _save(folder/'backup.json',{'setup':str(setup),'backup':str(backup)})
        elif stage=='baseline':
            _save(folder/'baseline.json',logical_snapshot(setup))
        elif stage in ['verify','rollback']:
            before=json.loads((folder/'baseline.json').read_text());after=logical_snapshot(setup)
            _save(folder/(stage+'-snapshot.json'),after)
            for filename in ['maestro.sdb','active.state']:
                if stage=='verify' and set(after[filename])!=set(before[filename])|{new}:raise ValueError('unexpected test set')
                if stage=='rollback' and filename=='maestro.sdb' and set(after[filename])!=set(before[filename]):raise ValueError('rollback test set differs')
                if stage=='rollback' and filename=='active.state' and not set(before[filename]).issubset(after[filename]):raise ValueError('rollback original state missing')
                for k,v in before[filename].items():
                    if after[filename].get(k)!=v:raise ValueError('original test changed: '+filename+'/'+k)
            # sourceTest registers only the new test in global variable masks.
            # Existing per-test masks and all variable/corner/sweep values stay exact.
            projected=copy.deepcopy(after['global'])
            def project(node):
                if not isinstance(node,list) or len(node)!=4:return
                node[3]=[child for child in node[3] if not((child[0]=='dependentTest' or node[0]=='disabledtests' and child[0]=='test') and child[2]==new)]
                for child in node[3]:project(child)
                node[3]=[child for child in node[3] if not(child[0]=='dependentTests' and not child[3])]
            for node in projected:project(node)
            projected=[node for node in projected if not(node[0]=='disabledtests' and not node[3])]
            baseline_globals=copy.deepcopy(before['global'])
            for node in baseline_globals:project(node)
            baseline_globals=[node for node in baseline_globals if not(node[0]=='disabledtests' and not node[3])]
            if baseline_globals!=projected:raise ValueError('global/corner/sweep changed')
            if (folder/'native-before.txt').read_bytes()!=(folder/'native-after.txt').read_bytes():raise ValueError('native getter mismatch')
            _save(receipt,{'schema':'vco-tbgen.session-receipt.v1','status':'added' if stage=='verify' else 'rolled_back',
                'new_test':new,'context':proposal['context'],'backup':json.loads((folder/'backup.json').read_text()),
                'original_tests_verified':True,'session_closed':False,'rollback':'not_needed' if stage=='verify' else 'verified',
                'inactive_state_payloads':sorted(set(after['active.state'])-set(after['maestro.sdb'])),
                'failure':(json.loads(receipt.read_text()) if receipt.is_file() else {'reason':'native mutation/readback failed; see SKILL log'}) if stage=='rollback' else None})
        else:raise ValueError('unknown session stage')
    except Exception as e:
        _save(receipt,{'schema':'vco-tbgen.session-receipt.v1','status':'failed','stage':stage,'error':str(e),'new_test':new,'session_closed':False})
        raise

if __name__=='__main__':_main(sys.argv[1],sys.argv[2])
