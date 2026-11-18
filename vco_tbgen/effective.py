"""Read the qualified saved test, and compare actual condition multisets.

No arbitrary SKILL evaluation. Only the IC618 v6/v5 serialization qualified by
preservation.py is supported. Unsupported sweep syntax fails before submission.
"""
import copy
import itertools
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from .preservation import qualify


def literal(text):
    """Small non-executing SKILL literal reader (strings, lists, numbers, t/nil)."""
    tokens=re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+',text.strip())
    def read(index):
        if index>=len(tokens):raise ValueError('incomplete SKILL literal')
        token=tokens[index]
        if token=='(':
            values=[];index+=1
            while index<len(tokens) and tokens[index]!=')':
                value,index=read(index);values.append(value)
            if index==len(tokens):raise ValueError('unclosed SKILL literal')
            return values,index+1
        if token==')':raise ValueError('unexpected closing literal')
        if token.startswith('"'):return json.loads(token),index+1
        if token=='t':return True,index+1
        if token=='nil':return None,index+1
        try:return float(token),index+1
        except ValueError:return token,index+1
    value,end=read(0)
    if end!=len(tokens):raise ValueError('unsupported SKILL expression')
    return value


def native_flag(text):
    value=literal(text or 'nil')
    if value is True or isinstance(value,list) and len(value)==1 and value[0] is True:return True
    if value is None or value == []:return False
    raise ValueError('unsupported native enable flag')


def required_contract(spec):
    """B defaults to the caller's increment, never the entire inherited setup."""
    return copy.deepcopy(spec.get('required', {
        'schema':'vco-tbgen.required.v1',
        'analyses':[a['kind'] for a in spec['analyses'] if a.get('enabled',True)],
        'outputs':[{'name':o['name'],'kind':'scalar'} for o in spec.get('outputs',[]) if o.get('plot',True)],
        'saves':[o['name'] for o in spec.get('saves',[])]}))


def named(parent,path,name):
    found=[e for e in parent.findall(path) if e.get('Name')==name]
    if len(found)!=1:raise ValueError('missing or ambiguous saved setting: '+name)
    return found[0]


def fields(parent):
    return {e.get('Name'):(e.text or '').strip() for e in parent.findall('./field')}


def variables(parent):
    return {(v.text or '').strip():v.findtext('value','').strip() for v in parent.findall('./vars/var')}


def effective_spec(spec,setup):
    """Called under the library transaction lock, before modifying/running setup."""
    setup=Path(setup);qualify(setup)
    active=ET.parse(setup/'maestro.sdb').getroot().find('active')
    tests=[e for e in active.findall('./tests/test') if (e.text or '').strip()==spec['maestro']['test']]
    if len(tests)!=1:raise ValueError('effective test identity missing or ambiguous')
    test=tests[0]
    state=named(ET.parse(setup/'active.state').getroot(),'./Test',spec['maestro']['test'])
    result=copy.deepcopy(spec)
    result['analyses']=[]
    preserved_analyses=[]
    component=named(state,'./component','analyses')
    for a in component.findall('./analyses/analysis'):
        af=fields(named(a,'./partition','fields'))
        enabled=native_flag(af.get('enable'))
        preserved_analyses.append({'kind':a.get('Name'),'enabled':enabled,'native_fields':af})
        if not enabled:continue
        # Read the options governing result qualification from the saved test;
        # all other setup fields remain native and are never reconstructed.
        params={key:literal(af[key]) for key in ['oscana','p','n','noiseout'] if af.get(key)}
        result['analyses'].append({'kind':a.get('Name'),'enabled':True,'parameters':params})
    if not result['analyses']:raise ValueError('no enabled effective analyses')
    result['outputs']=[];result['saves']=[]
    outputs=named(state,'./component','outputs')
    for row in outputs.findall('./partition/field[@Name="outputList"]/field'):
        f=fields(row)
        if not f.get('name'):raise ValueError('unnamed saved output')
        name=literal(f['name'])
        if (f.get('expression') or 'nil')!='nil':
            result['outputs'].append({'name':name,'expression':f['expression'],'plot':native_flag(f.get('plot'))})
        if (f.get('signal') or 'nil')!='nil' and native_flag(f.get('save')):
            result['saves'].append({'name':literal(f['signal']),'kind':'terminal' if literal(f.get('type') or 'nil')=='terminal' else 'net'})
    result['variables']=variables(test)
    # Enabled global variables override the stale local fallback in IC618.
    # sourceTest defaults a new test to global enabled when no entry exists.
    for var in active.findall('./vars/var'):
        deps=[d for d in var.findall('./dependentTests/dependentTest') if (d.text or '').strip()==spec['maestro']['test']]
        if len(deps)>1:raise ValueError('ambiguous global variable scope')
        if var.get('enabled','1')!='0' and (not deps or deps[0].get('enabled','1')!='0'):
            result['variables'][(var.text or '').strip()]=var.findtext('value','').strip()
    result['corners']=[]
    for c in active.findall('./corners/corner'):
        if c.get('enabled','1')=='0':continue
        # The MVP only qualifies the native independent variable/corner grid.
        if any(e.tag!='vars' for e in c):raise ValueError('unsupported corner setting; coverage unknown')
        name=(c.text or '').strip()
        result['corners'].append({'name':'nominal' if name=='_default' else name,'variables':variables(c)})
    if not result['corners']:raise ValueError('no enabled saved corners; coverage unknown')
    mode=active.findtext('currentmode','').strip()
    if mode!='Single Run, Sweeps and Corners':raise ValueError('unsupported run mode; coverage unknown: '+mode)
    if active.find('parametricsets') is not None:raise ValueError('parametric sets are not qualified')
    result.pop('sweeps',None)  # native variable values already contain the sweep
    result['required']=required_contract(spec if spec['mode']=='add_test_to_existing' or 'required' in spec else result)
    result['preserved']={k:copy.deepcopy(result[k]) for k in ['outputs','saves']}
    result['preserved']['analyses']=preserved_analyses
    result['_effective_source']={'setup':str(setup),'test':spec['maestro']['test'],'format':'IC618 setupdb v6 / statedb v5'}
    return result


_SUFFIX={'':1.,'T':1e12,'G':1e9,'M':1e6,'meg':1e6,'k':1e3,'K':1e3,'m':1e-3,'u':1e-6,'n':1e-9,'p':1e-12,'f':1e-15,'a':1e-18}

def numeric(value):
    if isinstance(value,bool):raise ValueError('boolean is not a coordinate')
    text=str(value).strip()
    match=re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(meg|[TGMkKmunpfa]?)',text)
    if not match:raise ValueError('non-numeric condition: '+text)
    result=float(match[1])*_SUFFIX[match[2]]
    if not math.isfinite(result):raise ValueError('non-finite coordinate')
    return result


def choices(value):
    if not isinstance(value,str):return [numeric(value)]
    # Discrete whitespace-separated numeric choices are the native MVP format.
    return [numeric(v) for v in value.split()]


def expected_conditions(spec):
    rows=[]
    for c in spec.get('corners') or [{'name':'nominal','variables':{}}]:
        values=dict(spec.get('variables',{}))
        # Used by spec-only tests; effective_spec reads these from saved vars.
        for sweep in spec.get('sweeps',[]):values[sweep['variable']]=' '.join(map(str,sweep['values']))
        values.update(c.get('variables',{}))
        dimensions={}
        for key,value in values.items():
            try:dimensions[key]=choices(value)
            except ValueError:
                # A single expression is a default, not a known sweep axis.
                # Multi-token/range/list syntax could hide a sweep: fail closed.
                if isinstance(value,str) and not re.search(r'\s|:|\[|\]',value):continue
                raise ValueError('unsupported variable/sweep condition: '+key+'='+str(value))
        if any(not vals for vals in dimensions.values()):raise ValueError('empty sweep axis')
        for coordinates in itertools.product(*dimensions.values()):
            rows.append({'corner':c['name'],'variables':dict(zip(dimensions,coordinates))})
    return rows


def verify_coverage(points,expected,test):
    """Multiset matching with tight numeric tolerance, never just point counts."""
    unmatched=list(range(len(expected)));issues=[];unexpected=[]
    for p in points:
        found=None
        for index in unmatched:
            condition=expected[index]
            if p['test']!=test or p['corner']!=condition['corner']:continue
            try:
                ok=all(math.isclose(numeric(p['variables'][k]),v,rel_tol=1e-9,abs_tol=1e-18) for k,v in condition['variables'].items())
            except (KeyError,ValueError,TypeError):ok=False
            if ok:found=index;break
        if found is None:unexpected.append({'point_id':p['point_id'],'corner':p['corner'],'test':p['test'],'variables':p['variables']})
        else:unmatched.remove(found)
    if unmatched or unexpected:issues.append('point coverage mismatch: missing '+str(len(unmatched))+' unexpected/duplicate '+str(len(unexpected)))
    coverage={'expected':len(expected),'actual':len(points),'matched':len(expected)-len(unmatched),
              'missing':[expected[i] for i in unmatched],'unexpected':unexpected}
    return coverage,issues
