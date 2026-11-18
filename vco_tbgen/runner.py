"""Native RDB enumeration plus Spectre terminal evidence. No guessed PSF paths."""
import json
import datetime
import shutil
import math
from pathlib import Path
import re
from . import native
from .transaction import _locked, _save, _target, check_unlocked
from .spec import digest
from .maestro import open_setup
from .effective import literal


def run_script(spec,folder):
    t=native.sq(spec['maestro']['test']);out=Path(folder)/'points.tsv'
    b=(Path(__file__).resolve().parent/'resources/reader.il').read_text()+'\n'+open_setup(spec)
    b+='unless(equal(sort(maeGetEnabledAnalysis('+t+' ?session s) \'alphalessp) sort('+native.sl([a['kind'] for a in spec['analyses'] if a.get('enabled',True)])+' \'alphalessp)) error("effective analyses changed"))\n'
    for a in spec['analyses']:
        for key,value in a['parameters'].items():
            b+='unless(equal(maeGetAnalysis('+t+' '+native.sq(a['kind'])+' ?option '+native.sq(key)+' ?session s) '+native.sl(value)+') error("effective measurement option changed"))\n'
    b+='modeBefore=maeGetEnvOption('+t+' ?option "controlMode" ?session s)\n'
    b+=native.guard('maeSetEnvOption('+t+' ?options list(list("controlMode" "batch")) ?session s)','set batch mode failed')
    b+='unless(equal(maeGetEnvOption('+t+' ?option "controlMode" ?session s) "batch") error("batch mode readback mismatch"))\n'
    b+='enabledBefore=maeGetSetup(?enabled t ?session s)\n'
    b+='maeSetSetup(?tests maeGetSetup(?session s) ?enabled nil ?session s)\nmaeSetSetup(?tests list('+t+') ?enabled t ?session s)\n'
    b+='runResult=errset(progn(\nrunId=maeRunSimulation(?waitUntilDone t ?returnRunId t ?session s)\nunless(runId error("submission failed"))\nmaeWaitUntilDone(\'All ?session s)\nmaeExportOutputView(?fileName '+native.sq(Path(folder)/'evaluated.csv')+' ?session s)\nmaeWaitUntilDone(\'All ?session s)\nrd=axlGetRunData(s runId) hist=axlGetHistoryName(rd)\nr=maeReadResDB(?historyName hist ?session s)\nunless(r error("missing RDB"))\n'
    b+='o=outfile('+native.sq(out)+')\nfprintf(o "HISTORY\\t%s\\n" hist)\nhe=axlGetHistoryEntry(axlGetMainSetupDB(s) hist)\nfprintf(o "RDB\\t%s\\n" axlGetHistoryResults(he))\n'
    wanted=sorted(set([p['net'] for p in spec['ports']]+[p['internal_net'] for p in spec.get('probes',[])]+[v['name'] for v in spec.get('saves',[])]))
    wanted += [a['parameters'][key] for a in spec['analyses'] for key in ['p','n'] if a['parameters'].get(key)]
    wanted=sorted(set('/'+v.lstrip('/') for v in wanted if v not in ['0','gnd!','/0','/gnd!']))
    required_signals = spec.get('required', {}).get('saves', [v['name'] for v in spec.get('saves', [])])
    b+='tbgenReadSignals='+native.sl(sorted(set(wanted) | set(required_signals)))+'\n'
    b+='tbgenRequiredSignals='+native.sl(required_signals)+'\n'
    drain = None
    if spec.get('hbxf_injection', {}).get('drain_terminal'):
        from .isf import native_drain
        signal, spectre = native_drain(spec)
        occurrence, _, terminal = signal.rpartition('/')
        drain = (signal, (spectre, occurrence+':'+terminal, signal))
    b += 'tbgenNumberedDrain='+native.sl(drain)+'\n'
    b+='tbgenAnalysisNames='+native.sl(sorted({name for a in spec['analyses'] for name in RESULT_NAMES.get(a['kind'],())}))+'\n'
    b+='tbgenExpressions='+native.sl([[o['name'],o['expression']] for o in spec.get('outputs',[]) if o.get('plot',True)])+'\n'
    b+='''foreach(point r->points() foreach(corner point->corners() foreach(test corner->tests()
 fprintf(o "POINT\\t%L\\t%s\\t%s\\t%L\\t%s\\n" point->id corner->name test->name test->status test->resultsDir)
 foreach(param corner->params() fprintf(o "PARAM\\t%s\\t%L\\n" param->name param->value))
 tbgenWaveNames=nil
 foreach(value test->outputs() when(member(value->value list("wave" 'wave)) tbgenWaveNames=cons(value->name tbgenWaveNames)) fprintf(o "OUTPUT\\t%s\\t%L\\t%L\\n" value->name value->type value->value))
 when(test->status=='done
  openResults(strcat(test->resultsDir "/psf"))
  foreach(ana results()
   fprintf(o "ANALYSIS\\t%L\\n" ana)
   when(member(if(symbolp(ana) then symbolToString(ana) else ana) tbgenAnalysisNames)
   tbgenActualSignals=outputs(?result ana)
   when(tbgenNumberedDrain && member(ana '(hb_fd hb_td))
    tbgenNumberedWave=nil
    foreach(alias cadr(tbgenNumberedDrain)
     unless(tbgenNumberedWave
      waveResult=errset(getData(alias ?result ana) nil)
      when(waveResult tbgenNumberedWave=car(waveResult))))
    when(tbgenNumberedWave
     tbgenSignal=car(tbgenNumberedDrain)
     tbgenEmitWave(o ana tbgenSignal tbgenNumberedWave nil)
     tbgenEmitOutput(o strcat("__save__" tbgenSignal) tbgenNumberedWave nil)))
   foreach(signal append(tbgenActualSignals if(member(ana '(hbnoise_pm pnoise)) then list("out") else nil))
    when(member(signal tbgenReadSignals) || ana=='hbxf || signal=="out" || signal==car(tbgenActualSignals)
    waveResult=errset(getData(signal ?result ana) nil)
    when(waveResult
     tbgenEmitWave(o ana signal car(waveResult) nil)
     when(member(signal tbgenRequiredSignals) tbgenEmitOutput(o strcat("__save__" signal) car(waveResult) nil)))))))
  foreach(expression tbgenExpressions
   when(member(car(expression) tbgenWaveNames)
   waveResult=errset(evalstring(cadr(expression)) nil)
   when(waveResult tbgenEmitOutput(o car(expression) car(waveResult) nil))))
))))
close(o)
) t)
'''
    b+='maeSetEnvOption('+t+' ?options list(list("controlMode" modeBefore)) ?session s)\nmaeSetSetup(?tests maeGetSetup(?session s) ?enabled nil ?session s)\nmaeSetSetup(?tests enabledBefore ?enabled t ?session s)\nmaeSaveSetup(?session s) maeCloseSession(?session s)\nunless(runResult error("simulation/result export failed"))\n'
    return b


def sample_number(value):
    number=float(value)
    return number if math.isfinite(number) else None


def atom(value):
    try:
        result=json.loads(value)
        return None if isinstance(result,float) and not math.isfinite(result) else result
    except ValueError:return value


def read_points(file):
    points=[];current=None;history=None;rdb=None
    for line in Path(file).read_text().splitlines():
        row=line.split('\t');kind=row[0]
        if kind=='HISTORY':history=row[1]
        elif kind=='RDB':rdb=row[1]
        elif kind=='POINT':
            current={'schema':'vco-tbgen.point-result.v1','point_id':atom(row[1]),'corner':row[2],'test':row[3],'native_status':row[4],'resultsDir':row[5],'psf_dir':str(Path(row[5])/'psf'),'variables':{},'outputs':{},'analyses':[],'raw_samples':[],'output_waveforms':{},'output_scalars':{}};points.append(current)
        elif current is not None:
            if kind=='PARAM':current['variables'][row[1]]=atom(row[2])
            elif kind=='OUTPUT':current['outputs'][row[1]]={'type':row[2],'value':atom(row[3])}
            elif kind=='SCALAR_SAMPLE':
                current['output_scalars'].setdefault(row[1],[]).append([sample_number(v) for v in row[2:4]])
            elif kind=='WAVE_META':
                w=current['output_waveforms'].setdefault(row[1],{'curves':[]})
                w['curves'].append({'coordinates_native':row[2],'family':literal(row[2]),'x_unit':atom(row[3]),'y_unit':atom(row[4]),'sample_columns':['x','real','imag'],'samples':[]})
            elif kind=='WAVE_SAMPLE':
                current['output_waveforms'][row[1]]['curves'][-1]['samples'].append([sample_number(v) for v in row[2:5]])
            elif kind=='ANALYSIS':current['analyses'].append(row[1])
            elif kind=='FAMILY_RAW':current['raw_samples'].append({'analysis':row[1],'signal':row[2],'coordinates_native':row[3],'x':sample_number(row[4]),'real':sample_number(row[5]),'imag':sample_number(row[6])})
            elif kind=='RAW':current['raw_samples'].append({'analysis':row[1],'signal':row[2],'x':sample_number(row[3]),'real':sample_number(row[4]),'imag':sample_number(row[5])})
    for p in points:p.update(rdb=rdb,history=history)
    return history,rdb,points


# Explicit IC618 reader names; no prefix/substring matching (hbxf is not hb).
RESULT_NAMES={'hb':('hb_fd','hb_td','hb_fi'), 'hbnoise':('hbnoise_pm','hbnoise'),
              'hbxf':('hbxf',), 'pss':('pss_fd','pss_td'), 'pnoise':('pnoise',),
              'dc':('dc','dcOp'), 'tran':('tran',), 'noise':('noise',)}


def result_names(kind):
    if kind not in RESULT_NAMES:raise ValueError('unsupported enabled analysis: '+kind)
    return RESULT_NAMES[kind]


def finite(value):
    return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value)


def steady_state_reading(log):
    """Qualify explicit transient detection or normalized two-tier HB residuals.

    Two-tier + linear IC solves in frequency domain without tstab. It must not
    be labelled a successful transient detection merely because no warning was
    printed. Require the last complete outer iteration, its inner residual,
    native HB completion and zero-error terminal evidence instead.
    """
    path=Path(log);text=path.read_text(errors='replace') if path.is_file() else ''
    warning=bool(re.search(r'steady-state has not been detected',text,re.I))
    transient=bool(re.search(r'(?:steady.state (?:has been|is) (?:detected|reached)|steady.state detected)',text,re.I))
    result={'status':'not_detected' if warning else 'detected' if transient else 'unverified',
            'detected':transient and not warning,'transient_detected':transient and not warning,
            'basis':'tstab' if transient and not warning else None,
            'warning':'HB_STEADY_STATE_NOT_DETECTED' if warning else None,'evidence':str(path)}
    if warning or transient:return result
    sections=re.findall(r'Harmonic Balance Steady State Analysis.*?Total time required for hb analysis `hb[^\n]*',text,re.S)
    if not sections:return result
    hb=sections[-1];iterations={}
    for match in re.finditer(r'-> Outer iter=\s*(\d+): (Probe Current|Frequency|ProbeVol)=[^\n]*?norm\s*=\s*([^\s,]+)',hb):
        try:value=float(match[3])
        except ValueError:value=float('nan')
        iterations.setdefault(int(match[1]),{})[match[2]]=value
    inner=re.findall(r'Resd Norm=([^\s]+)',hb)
    if not iterations or not inner:return result
    residuals=iterations[max(iterations)]
    try:residuals=dict(residuals,inner=float(inner[-1]))
    except ValueError:return result
    terminal=re.search(r'Spectre completes with\s+(\d+) errors?[, .]',text,re.I)
    frequency=re.search(r'Fundamental frequency is ([0-9.eE+-]+) ([kMGT]?Hz)',hb)
    ok=(set(residuals)=={'Probe Current','Frequency','ProbeVol','inner'}
        and all(finite(v) and 0<=v<1 for v in residuals.values())
        and terminal is not None and terminal[1]=='0' and frequency is not None
        and float(frequency[1])>0)
    result.update(normalized_residuals=residuals,outer_iteration=max(iterations))
    if ok:result.update(status='converged',detected=True,basis='two_tier_hb_residuals')
    return result


def verify_point(point,required,contract=None):
    log=Path(point['psf_dir'])/'spectre.out';issues=[]
    text=log.read_text(errors='replace') if log.is_file() else ''
    match=re.search(r'Spectre completes with\s+(\d+) errors?[, .]',text,re.IGNORECASE)
    if point['native_status']!='done' or match is None or match.group(1)!='0':
        issues.append('missing zero-error Spectre terminal summary or native status is not done')
    rows=point.get('raw_samples',[])
    valid=[r for r in rows if all(finite(r.get(k)) for k in ['x','real','imag'])]
    if not contract or 'required' not in contract:
        if len(valid)!=len(rows):issues.append('non-finite or malformed waveform samples')
    for kind in required:
        names=result_names(kind)
        # HB requires frequency-domain data; td alone cannot prove a carrier.
        needed=('hb_fd',) if kind=='hb' else names
        if not set(needed).intersection(point['analyses']):issues.append('required analysis missing: '+kind)
        if not any(r['analysis'] in needed for r in valid):issues.append('required readable data missing: '+kind)
        if any(r['analysis'] in needed and r not in valid for r in rows):issues.append('required analysis has non-finite data: '+kind)
    if contract:
        qualification=contract.get('required',{})
        required_outputs=qualification.get('outputs',[dict(o,kind='scalar') for o in contract.get('outputs',[]) if o.get('plot',True)])
        required_saves=qualification.get('saves',[s['name'] for s in contract.get('saves',[])])
        for a in contract['analyses']:
            if 'required' in contract and a['kind'] not in required:continue
            if not a.get('enabled',True):continue
            if a['kind']=='hbnoise' and 'pm' in (a['parameters'].get('noiseout') or []):
                if not any(r['analysis']=='hbnoise_pm' and r['signal']=='out' for r in valid):
                    issues.append('required HBNOISE PM total waveform missing')
            if a['kind']=='hbxf':
                xf=[r for r in valid if r['analysis']=='hbxf']
                if not xf or not all('harmonic' in r.get('coordinates_native','') for r in xf):
                    issues.append('required HBXF complex family/harmonic coordinates missing')
        point['output_qualification']={}
        for output in contract.get('outputs',[]):
            record=point.get('outputs',{}).get(output['name'],{})
            point['output_qualification'][output['name']]={'status':'unverified','reason':'preserved output; not required' if finite(record.get('value')) or output['name'] in point.get('output_waveforms',{}) else 'preserved output; not evaluable or not validated'}
        for output in required_outputs:
            name=output['name'];record=point.get('outputs',{}).get(name,{})
            if output.get('kind','scalar')=='scalar':
                ok=record.get('type')=='expr' and finite(record.get('value'))
            else:
                curves=point.get('output_waveforms',{}).get(name,{}).get('curves',[])
                ok=bool(curves) and all(c['samples'] and c.get('x_unit') is not None and c.get('y_unit') is not None
                    and all(len(r)==3 and all(finite(v) for v in r) for r in c['samples']) for c in curves)
            if name=='ISF_HBXF_RAW_INJECTION' and contract.get('hbxf_injection'):
                curves=point.get('output_waveforms',{}).get(name,{}).get('curves',[])
                harmonics={v for c in curves for label,v in c.get('family',[]) if label=='harmonic'}
                N=contract.get('analysis_bundle',{}).get('shared',{}).get('isf_harmonic',1)
                wanted=set(range(-N-1,N))|{-1,0,1}
                unit_ok=all(c.get('y_unit')=='V/A' and c.get('x_unit')=='Hz' for c in curves)
                ok=ok and unit_ok and wanted.issubset(harmonics)
                point['hbxf_injection_qualification']=dict(source=contract['hbxf_injection'],
                    current_transfer_units=unit_ok,harmonics=sorted(harmonics),required_harmonics=sorted(wanted),verified=ok)
            point['output_qualification'][name]={'status':'verified' if ok else 'failed','kind':output.get('kind','scalar')}
            if not ok:issues.append('required evaluated expression missing or unreadable: '+name)
        for name in required_saves:
            readable=any(r['signal']==name for r in valid)
            if 'required' in contract:
                curves=point.get('output_waveforms',{}).get('__save__'+name,{}).get('curves',[])
                scalars=point.get('output_scalars',{}).get('__save__'+name,[])
                readable=(readable and bool(curves or scalars)
                    and all(c['samples'] and all(all(finite(v) for v in row) for row in c['samples']) for c in curves)
                    and all(len(row)==2 and all(finite(v) for v in row) for row in scalars))
            if not readable:issues.append('required saved signal unreadable: '+name)
        point['preserved_results']=[{'name':name,'finite_data':any(r['analysis']==name for r in valid)} for name in point['analyses']]
    if not point.get('rdb') or not Path(point['rdb']).is_file():issues.append('RDB path not readable')
    point['completion']={'state':'completed' if not issues else 'failed','evidence':[str(log),point.get('rdb')]}
    point['issues']=issues
    return issues


def execute_run(spec,extra,folder):
    setup=_target(spec);check_unlocked(setup)
    from .effective import effective_spec, expected_conditions, verify_coverage
    if spec.get('hbxf_injection'):
        from .isf import write_stimulus
        write_stimulus(spec)
    effective=effective_spec(spec,setup)
    expected=expected_conditions(effective)
    _save(folder/'effective-contract.json',effective)
    backup=None
    if spec['mode']=='add_test_to_existing':
        from .preservation import qualify
        qualify(setup)
        backup=Path(str(setup)+'.bak-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        shutil.copytree(setup,backup,ignore=shutil.ignore_patterns('*.cdslck*','*.oa-lock*','results'))
        _save(folder/'rollback.json',{'setup':str(setup),'backup':str(backup)})
    receipt=native.execute(run_script(effective,folder),folder/'native',spec['cds_lib'],spec['maestro']['lib'],spec['library_path'],spec.get('runtime'),locked=True)
    if backup is not None:
        from .preservation import preserve_run_settings
        from .maestro import setup_snapshot
        check_unlocked(setup);before=setup_snapshot(backup)
        preserve_run_settings(backup,setup)
        after=setup_snapshot(setup)
        if any(before[k]!=after[k] for k in ['maestro.sdb','active.state','global']) or any(after['test_states'].get(k)!=v for k,v in before['test_states'].items()):raise RuntimeError('original settings changed after run')
        _save(folder/'run-preservation.json',{'status':'passed','backup':str(backup),'original_settings_unchanged':True})
    history,rdb,points=read_points(folder/'points.tsv')
    issues=[]
    wanted_variables=set(effective.get('variables',{})) | {k for c in expected for k in c['variables']}
    required=effective['required']['analyses']
    for p in points:
        issues+=verify_point(p,required,effective)
        hb=next((a for a in effective['analyses'] if a['kind']=='hb' and a.get('enabled',True) and a['parameters'].get('oscana')),None)
        if hb:
            p['steady_state']=steady_state_reading(Path(p['psf_dir'])/'spectre.out')
            if spec['mode']=='create_new' and 'hb' in required and not p['steady_state']['detected']:
                issue=p['steady_state']['warning'] or 'HB_STEADY_STATE_UNVERIFIED';issues.append(issue);p['issues'].append(issue);p['completion']['state']='failed'
            carrier=carrier_reading(p,hb['parameters'])
            p['carrier']=carrier
            if carrier is None or carrier['magnitude_v']<1e-5:
                issue='HB oscillator has no usable carrier (missing, non-finite, DC or numerical solution)'
                p['carrier_diagnostic']=issue
                if 'hb' in required:
                    issues.append(issue);p['issues'].append(issue);p['completion']['state']='failed'
        values,parameter_evidence=read_design_parameters(p['psf_dir'],wanted_variables)
        p['variables'].update(values);p['variable_evidence']=parameter_evidence
    if not points:issues.append('no result points')
    coverage,coverage_issues=verify_coverage(points,expected,effective['maestro']['test'])
    issues+=coverage_issues
    result={'schema':'vco-tbgen.run.v1','status':'completed' if not issues else 'failed','history':history,'rdb':rdb,'points':points,'issues':issues,'receipt':receipt,'manifest_path':str(folder/'run.json'),'coverage':coverage,'effective_contract':str(folder/'effective-contract.json')}
    _save(folder/'run.json',result);return result


def read_design_parameters(psf_dir,wanted):
    """Read the actual per-point ASCII info struct, never current setup defaults."""
    path=Path(psf_dir)/'designParamVals.info'
    if not path.is_file():return {},{'status':'unknown','reason':'missing designParamVals.info'}
    text=path.read_text(errors='replace')
    fields=re.search(r'"top-level" STRUCT\((.*?)\)\s*(?:PROP\(.*?\)\s*)?VALUE',text,re.S)
    values=re.search(r'VALUE\s*"top-level"\s*"top-level"\s*\((.*?)\)\s*END',text,re.S)
    if not fields or not values:return {},{'status':'unknown','reason':'unsupported info format','path':str(path)}
    names=re.findall(r'"([^"\n]+)"\s+FLOAT DOUBLE',fields.group(1));numbers=values.group(1).split()
    if len(names)!=len(numbers):return {},{'status':'unknown','reason':'field/value count mismatch','path':str(path)}
    table=dict(zip(names,map(float,numbers)))
    return {key:table[key] for key in wanted if key in table},{'status':'read','provider':'PSF designParamVals','path':str(path)}


def carrier_reading(point,parameters):
    """Unavailable HB data are diagnostic unless the caller requires HB."""
    p=parameters.get('p');n=parameters.get('n','/0')
    rows=[r for r in point.get('raw_samples',[]) if r.get('analysis')=='hb_fd' and r.get('signal') in (p,n)]
    # Reject incomplete carrier-node samples before comparing frequencies or
    # constructing complex values; never substitute a later harmonic for bad data.
    if any(not all(finite(r.get(k)) for k in ('x','real','imag')) for r in rows):return None
    positive=[r for r in rows if r['signal']==p and r['x']>0]
    if not positive:return None
    a=min(positive,key=lambda r:r['x']);b=next((r for r in rows if r['analysis']=='hb_fd' and r['signal']==n and r['x']==a['x']),None)
    if n not in ['/0','0','/gnd!'] and b is None:return None
    voltage=complex(a['real'],a['imag'])-(complex(b['real'],b['imag']) if b else 0)
    magnitude=math.hypot(voltage.real,voltage.imag)
    if not all(finite(v) for v in (voltage.real,voltage.imag,magnitude)):return None
    return {'frequency_hz':a['x'],'real_v':voltage.real,'imag_v':voltage.imag,'magnitude_v':magnitude,'definition':'complex P minus N at fundamental; native Fourier coefficient'}


def run(materialized,wait=True):
    if materialized.get('status')!='prepared':raise ValueError('prepared materialization required')
    if digest(materialized['spec'])!=materialized['spec_hash']:raise ValueError('materialized spec changed')
    return _locked('run',materialized['spec'],{'materialized':materialized},wait=wait)


def results(run_handle):
    if run_handle.get('schema')=='vco-tbgen.failure.v1':return {'schema':'vco-tbgen.results.v1','status':'failed','points':[],'issues':[run_handle.get('error','native failure')]}
    if run_handle.get('schema')!='vco-tbgen.run.v1':raise ValueError('expected run handle')
    if run_handle.get('status')=='running' and Path(run_handle['manifest_path']).is_file():
        run_handle=json.loads(Path(run_handle['manifest_path']).read_text())
    points=run_handle.get('points',[])
    return {'schema':'vco-tbgen.results.v1','status':run_handle['status'],'history':run_handle.get('history'),'points':points,'issues':run_handle.get('issues',[]) or ([run_handle['error']] if run_handle.get('error') else [])}
