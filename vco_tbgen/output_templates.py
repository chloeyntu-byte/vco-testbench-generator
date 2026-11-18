"""IC618 calculator expressions; units/definitions travel with every output.

IC618 HB fd is one-sided peak-normalized: peak = abs(Vp[1]-Vn[1]).
PM 'out' is V/sqrt(Hz), SSB PN = 10log10(2)+20log10(PM/peak).
"""
import json


def oscillator_outputs(positive, negative, offsets, *, supplies=(), prefix='VCO_', transfer=None):
    q = lambda v: json.dumps(str(v))
    voltage = lambda node: 'getData('+q(node)+' ?result "hb_fd")'
    diff = '('+voltage(positive)+'-'+voltage(negative)+')'
    f0 = 'drGetElem(drGetWaveformXVec('+voltage(positive)+') 1)'
    amplitude = 'mag(value('+diff+' '+f0+'))'
    rows = []
    def add(name, expression, unit, description):
        rows.append(dict(name=prefix+name, expression=expression, unit=unit, description=description, plot=True))
    add('HB_F0_Hz', f0, 'Hz', 'Fundamental frequency from the native HB frequency axis')
    add('HB_DIFF_PEAK_V', amplitude, 'V', 'Differential fundamental peak voltage = abs(Vp[1]-Vn[1]) in IC618 hb_fd; verified against hb_td, not RMS or peak-to-peak')
    for k in (2, 3) if transfer else ():
        add('HB_H'+str(k)+'_RATIO', 'mag(value('+diff+' '+str(k)+'*'+f0+'))/mag(value('+diff+' '+f0+'))', '1', 'Differential harmonic '+str(k)+' / fundamental amplitude ratio')
    powers = []
    for src in supplies:
        name = src['name']; current = 'real(value(getData('+q('/'+name.lstrip('/')+'/PLUS')+' ?result "hb_fd") 0))'
        v = '(0+'+voltage('/'+src['positive'].lstrip('/'))
        v += ('-'+voltage('/'+src['negative'].lstrip('/'))) if src['negative'] not in ('0','gnd!','/0','/gnd!') else ''
        v += ')'
        power = '(0-real(value('+v+' 0))*'+current+')'
        powers.append(power)
        add('HB_'+name+'_IDC_A', '0-'+current, 'A', 'DC current delivered by source, positive into DUT')
        add('HB_'+name+'_PDC_W', power, 'W', 'DC supply voltage times DC delivered current; excludes RF exchange')
        if transfer:
            transfer(add, q, src)
    if transfer:
        transfer(add, q, None)
    for offset in offsets:
        token = format(offset, '.15g').replace('.', 'p').replace('+', '')
        pm = 'value(getData("out" ?result "hbnoise_pm") '+str(offset)+')'
        pn = '(10*log10(2)+20*log10('+pm+'/'+amplitude+'))'
        add('HBNOISE_PN_'+token+'Hz_dBc_Hz', pn, 'dBc/Hz', 'Total PM out, SSB phase noise at '+str(offset)+' Hz')
        if powers:
            add('HBNOISE_FOM_'+token+'Hz_dB', pn+'-20*log10('+f0+'/'+str(offset)+')+10*log10(1000*(0+'+'+'.join(powers)+'))', 'dB', 'Signed oscillator FoM = PN -20log10(f0/offset) +10log10(Pdc/mW)')
    return rows


def bundle_outputs(bundle, *, supplies=(), injection=None):
    """Compatibility entry for callers of the original ISF templates."""
    from .isf import bundle_outputs as render
    return render(bundle, supplies=supplies, injection=injection)
