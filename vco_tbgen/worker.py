"""Transaction worker launched through the configured command wrapper, when set."""
import json
from pathlib import Path
import sys
import traceback
from .transaction import _save

def main():
    request=json.loads(Path(sys.argv[1]).read_text());folder=Path(request['folder'])
    try:
        if request['action']=='materialize':
            from .maestro import _materialize
            value=_materialize(request['spec'],request['extra'],folder)
        elif request['action']=='fixture':
            from .schematic import materialize_fixture
            value=materialize_fixture(request['spec'],request['extra'],folder)
        elif request['action']=='run':
            from .runner import execute_run
            value=execute_run(request['spec'],request['extra'],folder)
        else:raise ValueError('invalid worker action')
        code=0
    except Exception as e:
        traceback.print_exc()
        journal=folder/'rollback.json'
        rollback=None
        if journal.is_file():
            try:
                import shutil
                from .transaction import check_unlocked
                j=json.loads(journal.read_text());check_unlocked(j['setup'])
                for name in ['maestro.sdb','active.state']:
                    shutil.copy2(Path(j['backup'])/name,Path(j['setup'])/name)
                backup_states=Path(j['backup'])/'test_states';current_states=Path(j['setup'])/'test_states'
                for state in current_states.rglob('*.state'):
                    relative=state.relative_to(current_states);prior=backup_states/relative
                    if prior.is_file():shutil.copy2(prior,state)
                    else:
                        destination=folder/'failed-test-states'/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(state),str(destination))
                rollback='restored original setup files from '+j['backup']
            except Exception as restore_error:rollback='FAILED: '+str(restore_error)
        value={'schema':'vco-tbgen.failure.v1','status':'failed','error':str(e),'evidence':str(folder),'rollback':rollback};code=1
    _save(folder/'response.json',value);return code
if __name__=='__main__':sys.exit(main())
