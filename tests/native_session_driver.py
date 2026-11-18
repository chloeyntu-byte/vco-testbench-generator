"""Called only by the private batch integration harness, after capturing native identity."""
import json
import sys
from pathlib import Path
from vco_tbgen import plan_session_add,materialize_session_add
from vco_tbgen.session import disk_revision


def prepare(folder, case):
    w=Path(folder);s=json.loads((w/'spec.json').read_text());actual=json.loads((w/'context-native.json').read_text())
    setup=Path(s['library_path'])/s['maestro']['cell']/s['maestro']['view']
    c=dict(actual,schema='vco-tbgen.session-context.v1',window_id=None,private_batch=True,
           lcv={k:s['maestro'][k] for k in ['lib','cell','view']},save_policy='reject' if case=='dirty-reject' else 'save',
           revision=disk_revision(setup),generation=case+'-1')
    (w/'context.json').write_text(json.dumps(c,indent=2))
    try:p=materialize_session_add(plan_session_add(s,c),c)
    except ValueError as e:
        if case!='dirty-reject':raise
        (w/'receipt.json').write_text(json.dumps({'status':'rejected','reason':str(e)}))
        (w/'invoke.il').write_text('printf("DIRTY_REJECTED\\n")\n');return
    (w/'prepared.json').write_text(json.dumps(p,indent=2));script=Path(p['skill_path'])
    if case=='rollback':
        script.write_text(script.read_text().replace('unless(maeSaveSetup(?session s) error("session save failed"))',
            'unless(maeSaveSetup(?session s) error("session save failed"))\nerror("INJECTED_FAILURE_AFTER_SAVE")'))
    (w/'invoke.il').write_text('load('+json.dumps(str(script))+')\n')

if __name__=='__main__':prepare(sys.argv[1],sys.argv[2])
