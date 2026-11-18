"""Single HB/HBNOISE/HBXF contract, shared by TB Generator and ISF adapters.

Reconciliation never mutates its input. For B the caller applies the returned
set only to the copied test. Source solver choices and unrelated analyses stay
intact; explicit ISF decisions take precedence over conflicting source fields.
"""
import copy
import math
from pathlib import Path
from .spec import digest
from .effective import numeric
from .oscillator import lc_hb_defaults, relative_sweep
from .output_templates import oscillator_outputs

KINDS = ('hb', 'hbnoise', 'hbxf')


def analysis_bundle(analyses, *, frequency, positive, negative, offsets_hz,
                    isf_harmonic=3, hb_harmonics=15, sidebands=10,
                    conditions=None, initial_conditions=None, solver_options=None):
    changes, pending = [], []
    inventory=[dict(kind=r['kind'],enabled=r.get('enabled',True)) for r in analyses if r['kind'] in KINDS]
    existing = {}
    for row in analyses:
        if row['kind'] not in KINDS or not row.get('enabled', True):
            continue
        if row['kind'] in existing:
            pending.append({'field': row['kind'], 'reason': 'Multiple enabled analyses require a selection'})
        existing[row['kind']] = copy.deepcopy(row['parameters'])
    def number(value, field, integer=False):
        try:
            v = numeric(value)
            if not math.isfinite(v) or v <= 0 or (integer and int(v) != v):
                raise ValueError()
            return int(v) if integer else v
        except (ValueError, TypeError, OverflowError):
            pending.append({'field': field, 'reason': 'Explicit positive numeric value required: '+str(value)})
            return None
    frequency = number(frequency, 'frequency_hz')
    N = number(isf_harmonic, 'isf_harmonic', True)
    h = number(hb_harmonics, 'hb_harmonics', True)
    sb = number(sidebands, 'sidebands', True)
    offsets = []
    for v in offsets_hz:
        f = number(v, 'offsets_hz')
        if f is not None: offsets.append(f)
    offsets = sorted(set(offsets))
    if not offsets: pending.append({'field': 'offsets_hz', 'reason': 'At least one positive offset is required'})
    p = '/'+str(positive or '').lstrip('/')
    n = '/'+str(negative or '').lstrip('/')
    if p == '/' or n == '/' or p == n:
        pending.append({'field': 'output', 'reason': 'Select two distinct output nets'})
    hb_fields = set('oscana p n HBFreq1 HBHarm1 fundfreqs maxharms autosteady autotstab autoharms saveinit oscic oscmethod pinnode pinnodeminus pinnoderank pinnodemag tstab errpreset oversample'.split())
    hb = {k:copy.deepcopy(v) for k,v in existing.get('hb', {}).items() if k in hb_fields and v is not None}
    solver_options=solver_options or {}
    solver_keys=set('tstab oscic oscmethod autosteady autotstab errpreset'.split())
    for key,value in solver_options.items():
        if key not in solver_keys:
            pending.append({'field':'solver/'+key,'reason':'Unsupported solver override; retain source or select a supported field'})
        else:hb[key]=copy.deepcopy(value)
    for key in ('fundfreqs', 'maxharms'):
        if len(hb.get(key, [])) > 1:
            pending.append({'field': 'hb/'+key, 'reason': 'Multi-tone HB cannot be converted to an autonomous single-tone ISF test'})
    hs = hb.get('maxharms', [hb.get('HBHarm1', h)])
    inherited_h = number(hs[0] if hs else h, 'hb/maxharms', True)
    sbs = [sb]
    for kind in ('hbnoise', 'hbxf'):
        if existing.get(kind, {}).get('maxsideband') not in (None, ''):
            sbs.append(number(existing[kind]['maxsideband'], kind+'/maxsideband', True))
    if pending:
        return dict(schema='vco-tbgen.hb-bundle.v1', shared={}, analyses=[], changes=changes,
                    pending=pending, inventory=inventory, present=list(existing), missing=[k for k in KINDS if k not in existing])
    h = max(h, inherited_h, N+1, 3)
    sb = max(sbs+[N+1])
    if 'hb' not in existing:
        hb = lc_hb_defaults(str(frequency), p=p, n=n)
    hb.update(copy.deepcopy(solver_options))
    hb.update(oscana=True, p=p, n=n, HBFreq1=str(frequency), fundfreqs=[str(frequency)],
              HBHarm1=str(h), maxharms=[str(h)])
    # Only replace pin aliases actually used by the solver. Do not switch B's solver.
    for key, val in [('pinnode', p), ('pinnodeminus', n)]:
        if key in hb: hb[key] = val
    native_offsets = list(offsets)
    if len(native_offsets) == 1:
        native_offsets.append(offsets[0]*2)
        changes.append(dict(field='native_offsets_hz', before=offsets, after=native_offsets,
                            reason='IC618 harmonic-family reader requires two samples; metrics use requested offsets only'))
    small = relative_sweep(p, n, native_offsets, sb)
    result = [dict(kind='hb', parameters=hb)]
    for kind in ('hbnoise', 'hbxf'):
        # Source display/diagnostic fields are harmless; sweep aliases must not leak.
        params = {k:copy.deepcopy(v) for k,v in existing.get(kind, {}).items()
                  if k in ('annotate', 'separatenoise')}
        params.update(small)
        if kind == 'hbnoise': params.update(noisetype='timeaverage', noiseout=['pm'])
        else: params.update(freqaxis='out')
        result.append(dict(kind=kind, parameters=params))
    for row in result:
        prior = existing.get(row['kind'])
        if prior is None:
            changes.append(dict(field=row['kind'], before=None, after=row['parameters'], reason='Complete the analysis bundle'))
        else:
            for key in sorted(row['parameters']):
                if prior.get(key) != row['parameters'].get(key):
                    changes.append(dict(field=row['kind']+'/'+key, before=prior.get(key), after=row['parameters'].get(key),
                                        reason='Align copied test with the shared ISF contract'))
    shared = dict(oscillator=True, frequency_hz=frequency, positive=p, negative=n,
                  hb_harmonics=h, isf_harmonic=N, sidebands=sb, offsets_hz=offsets,
                  native_offsets_hz=native_offsets, relharmvec=['1'], freqaxis='out',
                  solver={k:copy.deepcopy(hb[k]) for k in ('tstab','oscic','oscmethod','autosteady','errpreset') if k in hb},
                  initial_conditions=copy.deepcopy(initial_conditions or {}), conditions=copy.deepcopy(conditions or {}))
    return dict(schema='vco-tbgen.hb-bundle.v1', shared=shared, analyses=result, changes=changes,
                pending=[], inventory=inventory, present=list(existing), missing=[k for k in KINDS if k not in existing])


def install_bundle(spec, bundle, *, supplies=None):
    """Return a TB spec with the entire set and required named measurements."""
    if bundle['pending']: raise ValueError('Unresolved analysis bundle: '+str(bundle['pending']))
    spec = copy.deepcopy(spec)
    spec['analysis_bundle'] = copy.deepcopy(bundle)
    spec['analysis_bundle']['metric_sources']=copy.deepcopy(spec.get('supplies', []) if supplies is None else supplies)
    spec['analyses'] = [a for a in spec['analyses'] if a['kind'] not in KINDS]+copy.deepcopy(bundle['analyses'])
    spec['analysis_bundle']['execution_conditions']=execution_conditions(spec)
    spec['analysis_bundle']['injection']=copy.deepcopy(spec.get('hbxf_injection'))
    outputs = bundle_outputs(bundle, supplies=spec.get('supplies', []) if supplies is None else supplies, injection=spec.get('hbxf_injection'))
    # Generated names are owned by this contract; unrelated user outputs survive.
    spec['outputs'] = [o for o in spec.get('outputs', []) if not o['name'].startswith('ISF_')]+outputs
    required = spec.setdefault('required', dict(schema='vco-tbgen.required.v1', analyses=[], outputs=[], saves=[]))
    required['analyses'] = list(dict.fromkeys(required['analyses']+list(KINDS)))
    required['outputs'] = [o for o in required['outputs'] if not o['name'].startswith('ISF_')]+[dict(name=o['name'], kind='waveform' if '_RAW_' in o['name'] else 'scalar') for o in outputs]
    return spec


def bundle_errors(spec):
    """Reject stale derived fields and weakened measurement qualification."""
    b=spec.get('analysis_bundle')
    if not b:return []
    errors=[]
    try:
        s=b['shared']
        rebuilt=analysis_bundle(b['analyses'],frequency=s['frequency_hz'],positive=s['positive'],negative=s['negative'],
            offsets_hz=s['offsets_hz'],isf_harmonic=s['isf_harmonic'],hb_harmonics=s['hb_harmonics'],sidebands=s['sidebands'],
            conditions=s['conditions'],initial_conditions=s['initial_conditions'])
        if b.get('pending') or rebuilt['pending'] or rebuilt['shared']!=s or rebuilt['analyses']!=b['analyses']:
            errors.append('/analysis_bundle: inconsistent shared/derived fields')
        if [a for a in spec['analyses'] if a['kind'] in KINDS]!=b['analyses']:
            errors.append('/analysis_bundle: derived analyses changed; rebuild the bundle')
        if b.get('execution_conditions')!=execution_conditions(spec):
            errors.append('/analysis_bundle: actual TB operating conditions changed; rebuild the bundle')
        if b.get('injection')!=spec.get('hbxf_injection'):
            errors.append('/analysis_bundle: actual HBXF injection changed; rebuild the bundle')
        if spec.get('mode')=='create_new':
            conditions=s['conditions']
            temp=conditions.get('temperature_c')
            actual=spec.get('simulator_options',{}).get('temp')
            if (temp is None)!=(actual is None) or temp is not None and numeric(temp)!=numeric(actual):
                errors.append('/analysis_bundle/conditions/temperature_c: differs from actual TB')
            if s['initial_conditions']!=spec.get('initial_conditions',{}):
                errors.append('/analysis_bundle/initial_conditions: differs from actual TB')
            vs=conditions.get('variables',{})
            if isinstance(vs,list):vs={r['name']:r['value'] for r in vs if r['enabled'] and not r['omitted'] and r['scope']=='test'}
            if vs!=spec.get('variables',{}):errors.append('/analysis_bundle/conditions/variables: differs from actual TB')
        elif spec.get('mode')=='add_test_to_existing':
            conditions=s['conditions']; inherited=conditions.get('inherited',{})
            if 'temperature_c' in inherited:
                temp=conditions.get('temperature_c'); source_temp=inherited['temperature_c']
                if (temp is None)!=(source_temp is None) or temp is not None and numeric(temp)!=numeric(source_temp):
                    errors.append('/analysis_bundle/conditions/temperature_c: differs from inherited source temperature')
        if 'metric_sources' in b:
            generated=bundle_outputs(b,supplies=b['metric_sources'],injection=b.get('injection'))
            actual={o['name']:o for o in spec.get('outputs',[])}
            required=spec.get('required',{})
            for o in generated:
                if actual.get(o['name'])!=o:errors.append('/outputs/'+o['name']+': stale bundle metric')
                kind='waveform' if '_RAW_' in o['name'] else 'scalar'
                if dict(name=o['name'],kind=kind) not in required.get('outputs',[]):
                    errors.append('/required/outputs/'+o['name']+': bundle metric must be qualified')
            if not set(KINDS).issubset(required.get('analyses',[])):
                errors.append('/required/analyses: complete HB set required')
    except (KeyError,TypeError,ValueError):
        errors.append('/analysis_bundle: invalid bundle contract')
    return errors


def execution_conditions(spec):
    """Actual TB fields, sealed on installation, never refreshed on validation."""
    return {key:copy.deepcopy(spec.get(key, {} if key in ('variables','simulator_options','initial_conditions') else []))
            for key in ('variables','simulator_options','initial_conditions','corners','sweeps')}


def stimulus_path(spec):
    return Path(spec['workspace']) / ('hbxf-injection-'+digest(spec['hbxf_injection'])[:16]+'.scs')


def write_stimulus(spec):
    if not spec.get('hbxf_injection'):return
    probe=spec['hbxf_injection']
    name = probe['name']
    reference = probe['negative']
    probe_kind = probe.get('probe')
    injection_return = name+'_RETURN' if probe_kind else reference
    content = 'simulator lang=spectre\n'+name+' ('+probe['positive']+' '+injection_return+') isource dc=0 type=dc\n'
    if probe_kind:
        component = 'iprobe' if probe_kind == 'iprobe' else 'vsource dc=0 type=dc'
        content += name+'_PROBE ('+injection_return+' '+reference+') '+component+'\n'
    drain = native_drain(spec)
    if drain:
        content += 'save '+drain[1]+'\n'
    path=stimulus_path(spec)
    if path.exists() and path.read_text()!=content:raise FileExistsError(str(path))
    if not path.exists():path.write_text(content)


def bundle_outputs(bundle, *, supplies=(), injection=None):
    """Emit ISF scalar metrics and the selected D-S complex transfer."""
    def transfer(add, quote, source):
        if source is not None:
            if not injection:
                name = source['name']
                add('HBXF_RAW_'+name, 'getData('+quote('/'+name.lstrip('/'))+' ?result "hbxf")',
                    'native', 'Raw supply transfer only; no selected gm current input. ISF adapters replace this with the selected drain/source current probe.')
            return
        if injection:
            add('HBXF_RAW_INJECTION', 'getData('+quote('/'+injection['name'])+' ?result "hbxf")',
                'V/A', 'Complex differential voltage / drain-to-source current transfer for '+injection['target_instance']+
                '; source '+injection['name']+' ('+injection['positive']+' -> '+injection['negative']+
                '). All native harmonic coordinates retained, including -1/0/+1; signed ISF k = harmonic+1, x=f0+offset. Raw family preserves phase and all offsets; no arbitrary scalar collapse.')
        elif not supplies:
            add('HBXF_RAW_FIRST_INPUT', 'getData(car(outputs(?result "hbxf")) ?result "hbxf")',
                'native', 'Raw first input, no gm selected. Source-dependent units; ISF adapters must select an explicit current probe.')

    shared = bundle['shared']
    return oscillator_outputs(shared['positive'], shared['negative'], shared['offsets_hz'],
                              supplies=supplies, prefix='ISF_', transfer=transfer)


def injection_for_device(device, *, occupied=(), probe='iprobe'):
    """Bind one proven device occurrence to a non-loading zero-DC D-S source."""
    terminals = device.get('terminals', {})
    if not all(terminals.get(key, {}).get('resolved_net') for key in ('D', 'S')):
        raise ValueError('HBXF current transfer requires proven drain/source nets')
    name = 'ISF_TB_INJECT'
    if probe not in ('iprobe', 'zero_volt'):
        raise ValueError('Select iprobe or zero_volt for the D-S injection branch')
    occupied = set(occupied)
    if {name, name+'_PROBE', name+'_RETURN'} & occupied:
        raise ValueError(name+' injection branch name collides with an existing instance or net')
    def node(key):
        value = terminals[key]['resolved_net'].replace('/', '.').lstrip('.')
        return '0' if value == 'gnd!' else value
    binding = dict(name=name, positive=node('D'), negative=node('S'),
                   target_instance=device['target_instance'].replace('/', '.').lstrip('.'), probe=probe)
    # A wrapped Spectre device can expose a numbered formal even when OA calls
    # the terminal D. The selector already resolves that formal from the model.
    formal = terminals['D'].get('formal', '')
    if isinstance(formal, str) and formal.isascii() and formal.isdecimal():
        binding['drain_terminal'] = formal
    return binding


def install_isf(spec, bundle, *, injection, device, supplies):
    """Install L-d, its D-S transfer and the device/output/supply saves."""
    spec = copy.deepcopy(spec)
    spec['completeness'] = 'L-d'
    spec['hbxf_injection'] = injection
    saves = {row['name']: row for row in spec.get('saves', []) if row['name'] not in ('/0', '/gnd!')}
    required_saves = []
    def save(node, kind):
        name = '/' + node.replace('.', '/').lstrip('/')
        if name in ('/0', '/gnd!'):
            return
        saves.setdefault(name, dict(name=name, kind=kind))
        if name not in required_saves:
            required_saves.append(name)

    shared = bundle['shared']
    for node in (shared['positive'], shared['negative']):
        save(node, 'net')
    for term in device['terminals'].values():
        save(term['resolved_net'], 'net')
    drain = native_drain(spec)
    if drain:
        required_saves.append(drain[0])
    else:
        save(injection['target_instance']+'/D', 'terminal')
    for supply in supplies:
        save(supply['positive'], 'net')
        save(supply['negative'], 'net')
        save(supply['name']+'/PLUS', 'terminal')
    spec['saves'] = list(saves.values())
    spec['required'] = dict(schema='vco-tbgen.required.v1', analyses=[], saves=required_saves, outputs=[])
    return install_bundle(spec, bundle, supplies=supplies)


def native_drain(spec):
    """OA-style result identity and the exact Spectre terminal save, if numbered."""
    injection = spec.get('hbxf_injection', {})
    formal = injection.get('drain_terminal')
    if formal is None:
        return None
    target = injection['target_instance']
    return '/' + target.replace('.', '/') + '/' + formal, target + ':' + formal


def stimulus_setup(spec, test):
    from .native import sq, guard

    body = 'tbgenStimuli=maeGetEnvOption('+test+' ?option "stimulusFile" ?session s)\n'
    body += 'unless(listp(tbgenStimuli) error("Unsupported stimulusFile format"))\n'
    body += 'tbgenStimuli=append(tbgenStimuli list('+sq(stimulus_path(spec))+'))\n'
    body += guard('maeSetEnvOption('+test+' ?options list(list("stimulusFile" tbgenStimuli)) ?session s)',
                  'set HBXF injection stimulus failed')
    body += 'unless(equal(maeGetEnvOption('+test+' ?option "stimulusFile" ?session s) tbgenStimuli) error("injection stimulus readback mismatch"))\n'
    return body
