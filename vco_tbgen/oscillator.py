"""HB and HBNOISE oscillator analyses for Design Lab."""
import copy
import math
from .effective import numeric

def lc_hb_defaults(frequency, *, p='/OUTP', n='/OUTN'):
    """IC618 LC initialization: solve directly with linear IC and two tiers.

    Only new specs call this helper. Existing B-mode tests never receive it.
    Two-tier convergence is qualified by native inner/outer residual norms;
    the transient autosteady detector is not run by this native algorithm.
    """
    if numeric(frequency)<=0:raise ValueError('positive frequency required')
    return {'oscana':True,'p':p,'n':n,'HBFreq1':str(frequency),'HBHarm1':'15',
            'fundfreqs':[str(frequency)],'maxharms':['15'],
            'errpreset':'conservative','oscic':'lin','oscmethod':'twotier',
            'pinnode':p,'pinnodeminus':n,'pinnoderank':'1','autosteady':'yes'}


def relative_sweep(positive, negative, offsets, sidebands):
    return dict(sweeptype='relative', relharmvec=['1'], outType='voltage',
                p=positive, n=negative, maxsideband=str(sidebands),
                start='', stop='', incrType='Automatic', dec='',
                useDiscrete=True, values=[str(value) for value in offsets])


def install_oscillator(spec, *, frequency, positive, negative, offsets_hz=(10000.,), sidebands=15):
    """Install the Design Lab oscillator test and scalar measurement contract."""
    from .output_templates import oscillator_outputs

    spec = copy.deepcopy(spec)
    offsets = sorted({numeric(value) for value in offsets_hz})
    if not offsets or any(not math.isfinite(value) or value <= 0 for value in offsets):
        raise ValueError('At least one finite positive phase-noise offset is required')
    if not positive or not negative:
        raise ValueError('Select two distinct oscillator output nets')
    positive, negative = ('/' + node.lstrip('/') for node in (positive, negative))
    if positive == negative or '/' in (positive, negative):
        raise ValueError('Select two distinct oscillator output nets')
    hb = lc_hb_defaults(frequency, p=positive, n=negative)
    native_offsets = offsets if len(offsets) > 1 else [offsets[0], offsets[0]*2]
    noise = relative_sweep(positive, negative, native_offsets, sidebands)
    noise.update(noisetype='timeaverage', noiseout=['pm'])
    spec['completeness'] = 'L-c'
    spec['analyses'] = [dict(kind='hb', parameters=hb), dict(kind='hbnoise', parameters=noise)]
    outputs = oscillator_outputs(positive, negative, offsets, supplies=spec.get('supplies', []))
    spec['outputs'] = [row for row in spec.get('outputs', []) if not row['name'].startswith('VCO_')] + outputs
    spec['required'] = dict(schema='vco-tbgen.required.v1', analyses=['hb', 'hbnoise'],
                            outputs=[dict(name=row['name'], kind='scalar') for row in outputs],
                            saves=[row['name'] for row in spec.get('saves', [])])
    return spec
