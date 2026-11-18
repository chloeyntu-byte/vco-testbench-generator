"""Native Maestro test creation and closed-setup augmentation."""
import datetime
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from . import native
from .native import sq, sl, pairs, guard
from .spec import digest
from .transaction import _save, _target, check_unlocked

def _canon(element):
    return [element.tag,sorted(element.attrib.items()),(element.text or '').strip(),[_canon(c) for c in element]]

def setup_snapshot(setup):
    out={};setup=Path(setup)
    for name in ['maestro.sdb','active.state']:
        file=setup/name
        if not file.is_file():raise ValueError('incomplete saved Maestro setup: '+str(file))
        root=ET.parse(file).getroot()
        rows=root.findall('./active/tests/test') if name=='maestro.sdb' else root.findall('./Test')
        out[name]={((r.text or '').strip() if name=='maestro.sdb' else r.attrib['Name']):_canon(r) for r in rows}
        if name=='maestro.sdb':
            # Every existing global/corner/model/sweep setting must remain identical.
            out['global']=[_canon(c) for c in root.find('active') if c.tag!='tests']
    out['test_states']={str(p.relative_to(setup)):digest(p.read_bytes().hex()) for p in (setup/'test_states').rglob('*') if p.is_file()}
    return out


def open_setup(spec,mode='a'):
    m=spec['maestro']
    b='envSetVal("asimenv.startup" "projectDir" \'string '+sq(Path(spec['workspace'])/'simulation')+')\n'
    b+='envSetVal("adexl.historyNamePrefix" "showNameHistoryForm" \'boolean nil)\n'
    b+='envSetVal("adexl.simulation" "saveLastNHistoryEntries" \'int 1000)\n'
    b+='s=maeOpenSetup('+sq(m['lib'])+' '+sq(m['cell'])+' '+sq(m['view'])+' ?mode '+sq(mode)+')\n'+guard('s','open setup failed')
    if mode=='a':b+='when(axlIsSessionReadOnly(s) error("SETUP_OPEN_OR_LOCKED: close GUI or use an in-GUI plugin"))\n'
    return b


def test_setup(spec, folder=None):
    m=spec['maestro'];t=sq(m['test']);b=open_setup(spec)
    b+='tbgenOriginalTests=maeGetSetup(?session s) tbgenEnabledTests=maeGetSetup(?enabled t ?session s)\n'
    b+='when(member('+t+' maeGetSetup(?session s)) error("Test name already exists"))\n'
    if spec['mode']=='add_test_to_existing':b+=guard('maeCreateTest('+t+' ?sourceTest '+sq(m['source_test'])+' ?session s)','copy test failed')
    else:
        b+=guard('maeCreateTest('+t+' ?lib '+sq(m['lib'])+' ?cell '+sq(m['cell'])+' ?view "config" ?simulator "spectre" ?session s)','create test failed')
        env={'controlMode':'batch','analysisOrder':[a['kind'] for a in spec['analyses']],'modelFiles':[[r['path'],r.get('section','')] for r in spec.get('models',[])]}
        if spec.get('initial_conditions'):
            # Explicit Spectre IC statements, native definitionFiles support verified separately.
            env['stimulusFile']=[str(Path(spec['workspace'])/'initial_conditions.scs')]
        b+=guard('maeSetEnvOption('+t+' ?options '+pairs(env)+' ?session s)','set environment failed')
        variables=dict(spec.get('variables',{}))
        for sw in spec.get('sweeps',[]):
            if sw.get('scope','test')=='test':variables[sw['variable']]=' '.join(map(str,sw['values']))
            else:
                variables.pop(sw['variable'],None)
                b+=guard('maeSetVar('+sq(sw['variable'])+' '+sq(' '.join(map(str,sw['values'])))+' ?session s)','global sweep failed')
        for key,value in variables.items():
            b+=guard('maeSetVar('+sq(key)+' '+sq(value)+' ?typeValue list('+t+') ?session s)','set variable failed')
            b+='unless(equal(maeGetVar('+sq(key)+' ?typeName "test" ?typeValue '+t+' ?session s) '+sq(value)+') error("variable readback mismatch"))\n'
        if variables:b+='printf("ENABLE_TEST_VARS %L\\n" maeSetEnableTestVar('+t+' '+sl(list(variables))+' ?enabled t ?session s))\n'
        for corner in spec.get('corners',[]):
            b+=guard('maeSetCorner('+sq(corner['name'])+' ?enabled '+sl(corner.get('enabled',True))+' ?enableTests list('+t+') ?session s)','set corner failed')
            for k,v in corner.get('variables',{}).items():b+=guard('maeSetVar('+sq(k)+' '+sq(v)+' ?typeName "corner" ?typeValue list('+sq(corner['name'])+') ?session s)','corner variable failed')
        if spec.get('corners'):
            b+='foreach(tbgenCorner maeGetSetup(?typeName "corners" ?session s) tbgenCorner=if(tbgenCorner=="nominal" then "_default" else tbgenCorner) unless(member(tbgenCorner '+sl([c['name'] for c in spec['corners']])+') maeSetSetup(?corners list(tbgenCorner) ?enabled nil ?session s)))\n'
        if spec.get('simulator_options'):b+=guard('maeSetSimOption('+t+' ?options '+pairs(spec['simulator_options'])+' ?session s)','simulator options failed')
    if spec.get('hbxf_injection'):
        from .isf import stimulus_setup
        b += stimulus_setup(spec, t)
    for a in spec['analyses']:
        b+=guard('maeSetAnalysis('+t+' '+sq(a['kind'])+' ?enable '+sl(a.get('enabled',True))+' ?options '+pairs(a['parameters'])+' ?session s)','set analysis failed '+a['kind'])
        # Fail on ignored options. Some fields normalize; exact requested types should match.
        for k,v in a['parameters'].items():
            b+='unless(equal(maeGetAnalysis('+t+' '+sq(a['kind'])+' ?option '+sq(k)+' ?session s) '+sl(v)+') error('+sq('analysis option readback mismatch: '+a['kind']+'/'+k)+'))\n'
    for o in spec.get('outputs',[]):b+=guard('maeAddOutput('+sq(o['name'])+' '+t+' ?expr '+sq(o['expression'])+' ?plot '+sl(o.get('plot',True))+' ?save t ?session s)','add output failed')
    for save in spec.get('saves',[]):b+=guard('maeAddOutput('+sq('SAVE_'+save['name'])+' '+t+' ?outputType '+sq(save['kind'])+' ?signalName '+sq(save['name'])+' ?plot nil ?save t ?session s)','add save failed')
    if spec['mode']=='add_test_to_existing':
        b+='foreach(tbgenOld tbgenOriginalTests maeSetSetup(?tests list(tbgenOld) ?enabled if(member(tbgenOld tbgenEnabledTests) then t else nil) ?session s))\n'
    b+=guard('maeSaveSetup(?session s)','save setup failed')+'maeCloseSession(?session s)\n'
    b+=open_setup(spec,'r')+'o=outfile('+sq(Path(folder or spec['workspace'])/'setup-readback.txt')+')\n'
    b+='fprintf(o "TESTS %L\\n" maeGetSetup(?session s))\n'
    for a in spec['analyses']:
        b+='fprintf(o '+sq(a['kind']+' %L\n')+' maeGetAnalysis('+t+' '+sq(a['kind'])+' ?session s))\n'
        for k,v in a['parameters'].items():b+='unless(equal(maeGetAnalysis('+t+' '+sq(a['kind'])+' ?option '+sq(k)+' ?session s) '+sl(v)+') error("reopen analysis mismatch"))\n'
    b+='fprintf(o "ENV %L\\nVARS %L\\n" maeGetEnvOption('+t+' ?session s) maeGetSetup(?typeName "variables" ?session s))\nclose(o) maeCloseSession(?session s)\n'
    return b


def _materialize(spec,extra,folder):
    level = spec.get('completeness')
    setup=_target(spec);existing=spec['mode']=='add_test_to_existing';before=None;backup=None
    if existing:
        check_unlocked(setup)
        from .preservation import qualify
        qualify(setup);before=setup_snapshot(setup)
        names=before['maestro.sdb'];m=spec['maestro']
        if m['test'] in names:raise ValueError('test name already exists')
        if m['source_test'] not in names:raise ValueError('source test not found')
        stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        backup=Path(str(setup)+'.bak-'+stamp)
        if backup.exists():raise FileExistsError(str(backup))
        shutil.copytree(setup,backup,ignore=shutil.ignore_patterns('*.cdslck*','*.oa-lock*','results','*.sdb~'))
        check_unlocked(setup)
        _save(folder/'rollback.json',{'setup':str(setup),'backup':str(backup)})
        body='';expected=[]
    else:
        from .schematic import prepare_fixture
        body,expected=prepare_fixture(spec,folder)
        if spec.get('initial_conditions'):
            ic=Path(spec['workspace'])/'initial_conditions.scs'
            content='simulator lang=spectre\nic '+' '.join(k+'='+str(v) for k,v in spec['initial_conditions'].items())+'\n'
            if ic.exists() and ic.read_text()!=content:raise FileExistsError(str(ic))
            if not ic.exists():ic.write_text(content)
    if spec.get('hbxf_injection'):
        from .isf import write_stimulus
        write_stimulus(spec)
    setup_body = test_setup(spec, folder)
    if existing:
        from .preservation import native_snapshot_body
        capture = native_snapshot_body(backup, folder / 'original-native-before.txt')
        setup_body = setup_body.replace('tbgenOriginalTests=', capture + 'tbgenOriginalTests=', 1)
    body += setup_body
    receipt = native.execute(body, folder / 'native', spec['cds_lib'], spec['maestro']['lib'],
                             spec['library_path'], spec.get('runtime'), locked=True)
    if not existing:
        from .schematic import verify_connectivity
        verify_connectivity(folder, expected)
    preservation=None
    if before is not None:
        from .preservation import preserve_original,native_snapshot_body
        check_unlocked(setup)
        preserve_original(backup,setup,spec['maestro']['test'])
        verify_body=open_setup(spec,'r')+native_snapshot_body(backup,folder/'original-native-after.txt')
        for a in spec['analyses']:
            for k,v in a['parameters'].items():
                verify_body+='unless(equal(maeGetAnalysis('+native.sq(spec['maestro']['test'])+' '+native.sq(a['kind'])+' ?option '+native.sq(k)+' ?session s) '+native.sl(v)+') error("new test readback mismatch"))\n'
        verify_body+='maeCloseSession(?session s)\n'
        native.execute(verify_body,folder/'verify-native',spec['cds_lib'],spec['maestro']['lib'],spec['library_path'],spec.get('runtime'),locked=True)
        if (folder/'original-native-before.txt').read_bytes()!=(folder/'original-native-after.txt').read_bytes():raise RuntimeError('original effective native getter values changed')
        after=setup_snapshot(setup)
        for filename in ['maestro.sdb','active.state']:
            for key,value in before[filename].items():
                if after[filename].get(key)!=value:raise RuntimeError('ORIGINAL_TEST_CHANGED '+filename+'/'+key+'; backup '+str(backup))
        if after['global']!=before['global'] or after['test_states']!=before['test_states']:raise RuntimeError('ORIGINAL_GLOBAL_OR_STATES_CHANGED; backup '+str(backup))
        preservation={'original_tests_unchanged':True,'snapshot_before':before,'snapshot_after':after}
        _save(folder/'preservation.json',preservation)
    result={'schema':'vco-tbgen.materialized.v1','status':'prepared','spec':spec,'spec_hash':digest(spec),'plan':extra['plan'],'setup_dir':str(setup),'workspace':spec['workspace'],'receipt':receipt,'backup':str(backup) if backup else None,'preservation':str(folder/'preservation.json') if preservation else None,'manifest_path':str(folder/'materialized.json')}
    if level:
        result['completeness'] = level
    if not existing:
        result.update(schematic_dir=str(setup.parent / 'schematic'), config_dir=str(setup.parent / 'config'))
    _save(folder/'materialized.json',result);return result
