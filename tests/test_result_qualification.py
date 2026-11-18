"""Adversarial completion tests independent of Cadence/retained machine results."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vco_tbgen.effective import effective_spec,expected_conditions,literal,verify_coverage
from vco_tbgen.runner import verify_point,execute_run,run_script,carrier_reading,read_points
from vco_tbgen.native import validate_skill


def fixture(root):
    root=Path(root);(root/'spectre.out').write_text('Spectre completes with 0 errors, 1 warning.\n')
    (root/'run.rdb').write_text('test RDB path')
    def row(analysis,signal,real=1,**extra):return dict(analysis=analysis,signal=signal,x=1e9,real=real,imag=.2,**extra)
    return {'point_id':1,'test':'COPY','corner':'TT','native_status':'done','psf_dir':str(root),
            'resultsDir':str(root.parent),'rdb':str(root/'run.rdb'),'variables':{'CODE':10.,'VDD':1.8},
            'analyses':['hb_fd','hbnoise_pm','hbxf'],
            'raw_samples':[row('hb_fd','/P'),row('hb_fd','/N',-1),row('hbnoise_pm','out'),
                           row('hbxf','/SOURCE',coordinates_native='(("harmonic" 0))')],
            'outputs':{'VDD':{'type':'expr','value':1.8}}}

CONTRACT={'analyses':[{'kind':'hb','parameters':{'oscana':True,'p':'/P','n':'/N'}},
                      {'kind':'hbnoise','parameters':{'noiseout':['pm']}},
                      {'kind':'hbxf','parameters':{}}],
          'outputs':[{'name':'VDD','expression':'VAR("VDD")'}], 'saves':[{'name':'/P'}]}


def saved_setup(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'maestro.sdb').write_text('''<setupdb version="6"><active>
    <currentmode>Single Run, Sweeps and Corners</currentmode>
    <vars><var>VDD<value>1.8</value></var></vars>
    <tests><test>COPY<vars><var>CODE<value>10 11</value></var></vars></test></tests>
    <corners><corner enabled="0">_default</corner><corner enabled="1">TT</corner>
    <corner enabled="1">LOW<vars><var>VDD<value>1.7</value></var></vars></corner></corners>
    </active></setupdb>''')
    analyses=''
    for kind,params in [('hb',{'oscana':'t','p':'"/P"','n':'"/N"'}),('hbnoise',{'noiseout':'("pm")'}),('hbxf',{})]:
        fields='<field Name="enable">(t)</field>'+''.join('<field Name="'+k+'">'+v+'</field>' for k,v in params.items())
        analyses+='<analysis Name="'+kind+'"><partition Name="fields">'+fields+'</partition></analysis>'
    (root/'active.state').write_text('''<statedb version="5"><Test Name="COPY">
    <component Name="analyses"><analyses>'''+analyses+'''</analyses></component>
    <component Name="outputs"><partition><field Name="outputList">
    <field><field Name="name">"VDD"</field><field Name="expression">VAR("VDD")</field><field Name="plot">t</field></field>
    <field><field Name="name">"SAVE_P"</field><field Name="signal">"/P"</field><field Name="save">t</field></field>
    </field></partition></component></Test></statedb>''')


class ResultQualification(unittest.TestCase):
    def test_valid_rf_result(self):
        with tempfile.TemporaryDirectory() as d:self.assertEqual(verify_point(fixture(d),['hb','hbnoise','hbxf'],CONTRACT),[])

    def test_hbxf_cannot_satisfy_hb(self):
        with tempfile.TemporaryDirectory() as d:
            p=fixture(d);p['analyses']=['hbxf'];p['raw_samples']=[r for r in p['raw_samples'] if r['analysis']=='hbxf']
            self.assertIn('required analysis missing: hb',verify_point(p,['hb']))

    def test_missing_data_despite_analysis_names(self):
        for analysis in ['hb_fd','hbnoise_pm','hbxf']:
            with self.subTest(analysis=analysis),tempfile.TemporaryDirectory() as d:
                p=fixture(d);p['raw_samples']=[r for r in p['raw_samples'] if r['analysis']!=analysis]
                self.assertTrue(verify_point(p,['hb','hbnoise','hbxf'],CONTRACT));self.assertEqual(p['completion']['state'],'failed')

    def test_missing_or_failed_expression(self):
        for value in [None,'nil','wave','error',float('nan'),float('inf')]:
            with self.subTest(value=value),tempfile.TemporaryDirectory() as d:
                p=fixture(d);p['outputs']['VDD']['value']=value
                self.assertTrue(any('expression' in i for i in verify_point(p,[],CONTRACT)))
        with tempfile.TemporaryDirectory() as d:
            p=fixture(d);p['outputs']={};self.assertTrue(verify_point(p,[],CONTRACT))

    def test_zero_expression_and_plot_false(self):
        with tempfile.TemporaryDirectory() as d:
            p=fixture(d);p['outputs']['VDD']['value']=0
            self.assertEqual(verify_point(p,[],CONTRACT),[])
            c=copy.deepcopy(CONTRACT);c['outputs'][0]['plot']=False;p['outputs']={}
            self.assertEqual(verify_point(p,[],c),[])

    def test_missing_save_nonfinite_and_harmonic(self):
        for mutation in ['save','nan','harmonic']:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as d:
                p=fixture(d)
                if mutation=='save':p['raw_samples']=[r for r in p['raw_samples'] if r['signal']!='/P']
                if mutation=='nan':p['raw_samples'][-1]['imag']=float('nan')
                if mutation=='harmonic':p['raw_samples'][-1]['coordinates_native']='nil'
                self.assertTrue(verify_point(p,['hbxf'],CONTRACT))

    def test_coverage_multiset(self):
        expected=expected_conditions({'variables':{'CODE':10,'VDD':1.8},'sweeps':[{'variable':'CODE','values':[10,11]}],
                                     'corners':[{'name':'TT'},{'name':'LOW','variables':{'VDD':1.7}}]})
        points=[dict(e,point_id=i,test='COPY') for i,e in enumerate(expected)]
        coverage,issues=verify_coverage(points,expected,'COPY');self.assertEqual(issues,[]);self.assertEqual(coverage['matched'],4)
        dup=[copy.deepcopy(points[0]) for _ in range(4)]
        coverage,issues=verify_coverage(dup,expected,'COPY');self.assertTrue(issues);self.assertEqual(coverage['matched'],1);self.assertEqual(len(coverage['missing']),3)
        points[0]['test']='ORIGINAL';self.assertTrue(verify_coverage(points,expected,'COPY')[1])

    def test_missing_and_wrong_variable_rejected(self):
        expected=[{'corner':'TT','variables':{'CODE':10}}]
        for variables in [{},{'CODE':11},{'CODE':'NaN'}]:
            self.assertTrue(verify_coverage([{'corner':'TT','variables':variables,'test':'COPY','point_id':1}],expected,'COPY')[1])

    def test_effective_inheritance_and_reader(self):
        with tempfile.TemporaryDirectory() as d:
            saved_setup(d)
            # Exactly the incremental B input that caused the review failure.
            spec={'mode':'add_test_to_existing','ports':[],'maestro':{'test':'COPY'},'analyses':[{'kind':'hbxf','parameters':{}}]}
            e=effective_spec(spec,d)
            self.assertEqual({a['kind'] for a in e['analyses']},{'hb','hbnoise','hbxf'})
            self.assertTrue(e['analyses'][0]['parameters']['oscana']);self.assertEqual(len(expected_conditions(e)),4)
            self.assertEqual(e['outputs'][0]['name'],'VDD');self.assertEqual(e['saves'][0]['name'],'/P')
            # Runtime script must include inherited analysis families and nodes.
            e.update(workspace=d,maestro=dict(lib='L',cell='C',view='maestro',test='COPY'))
            script=run_script(e,Path(d));validate_skill(script)
            self.assertIn("foreach(ana results()",script);self.assertIn("hbnoise_pm",script);self.assertIn('"/N"',script)
            self.assertNotIn('rexMatchp(strcat("^"',script)

    def test_whole_run_missing_rf_or_duplicate_grid_fails(self):
        with tempfile.TemporaryDirectory() as d:
            work=Path(d);setup=work/'oa/L/C/maestro';saved_setup(setup)
            spec={'mode':'create_new','workspace':d,'library_path':str(work/'oa/L'),'cds_lib':'/unused',
                  'maestro':{'lib':'L','cell':'C','view':'maestro','test':'COPY'},'ports':[],
                  'analyses':[{'kind':'hbxf','parameters':{}}]}
            p=fixture(work);p['outputs']={};p['raw_samples']=[r for r in p['raw_samples'] if r['analysis']=='hb_fd']
            with patch('vco_tbgen.runner.native.execute',return_value={}),patch('vco_tbgen.runner.read_points',return_value=('H',p['rdb'],[copy.deepcopy(p) for _ in range(4)])):
                r=execute_run(spec,{},work)
            self.assertEqual(r['status'],'failed');self.assertEqual(r['coverage']['matched'],1)
            self.assertIn('carrier',r['points'][0])
            self.assertTrue(any('hbxf' in i for i in r['issues']));self.assertTrue(any('expression' in i for i in r['issues']))

    def test_optional_hb_unavailable_carrier_does_not_fail_run(self):
        # Exercise the complete result/JSON path with parsed native non-finite
        # samples, for both optional preserved HB and explicitly required HB.
        for required_hb in [False,True]:
            for signal in ['/P','/N']:
                for field in ['x','real','imag']:
                    for invalid in ['nan','inf','-inf']:
                        with self.subTest(required_hb=required_hb,signal=signal,field=field,invalid=invalid),tempfile.TemporaryDirectory() as d:
                            work=Path(d);setup=work/'oa/L/C/maestro';saved_setup(setup)
                            db=setup/'maestro.sdb'
                            db.write_text(db.read_text().replace('10 11','10').replace('<corner enabled="1">LOW<vars><var>VDD<value>1.7</value></var></vars></corner>',''))
                            required=['hbxf']+(['hb'] if required_hb else [])
                            spec={'mode':'add_test_to_existing','workspace':d,'library_path':str(work/'oa/L'),'cds_lib':'/unused',
                                  'maestro':{'lib':'L','cell':'C','view':'maestro','test':'COPY'},'ports':[],
                                  'analyses':[{'kind':'hbxf','parameters':{}}],
                                  'required':{'schema':'vco-tbgen.required.v1','analyses':required,'outputs':[],'saves':[]}}
                            p=fixture(work)
                            values=dict(x='1e9',real='1',imag='.2');values[field]=invalid
                            tsv=work/'sample.tsv';tsv.write_text('POINT\t1\tTT\tCOPY\tdone\t'+d+'\nRAW\thb_fd\t'+signal+'\t'+'\t'.join(values[k] for k in ['x','real','imag'])+'\n')
                            parsed=read_points(tsv)[2][0]['raw_samples'][0]
                            self.assertIsNone(parsed[field])
                            p['raw_samples'][0 if signal=='/P' else 1]=parsed
                            with patch('vco_tbgen.runner.native.execute',return_value={}),patch('vco_tbgen.runner.read_points',return_value=('H',p['rdb'],[p])):
                                r=execute_run(spec,{},work)
                            self.assertEqual(r['status'],'failed' if required_hb else 'completed')
                            self.assertEqual(r['points'][0]['completion']['state'],r['status'])
                            self.assertIsNone(r['points'][0]['carrier'])
                            self.assertIn('non-finite',r['points'][0]['carrier_diagnostic'])
                            self.assertEqual(r['coverage']['matched'],1)
                            self.assertEqual(bool(r['issues']),required_hb)
                            self.assertEqual(json.loads((work/'run.json').read_text())['status'],r['status'])

    def test_carrier_missing_malformed_and_overflow_are_unavailable(self):
        params={'p':'/P','n':'/N'}
        with tempfile.TemporaryDirectory() as d:
            baseline=fixture(d)
            self.assertEqual(carrier_reading(baseline,params)['magnitude_v'],2.)
            for signal in ['/P','/N']:
                for field in ['x','real','imag']:
                    p=copy.deepcopy(baseline)
                    row=next(r for r in p['raw_samples'] if r['signal']==signal)
                    del row[field]
                    self.assertIsNone(carrier_reading(p,params))
            for missing in ['/P','/N','both']:
                p=copy.deepcopy(baseline)
                p['raw_samples']=[r for r in p['raw_samples'] if r['signal']!=missing and (missing!='both' or r['analysis']!='hb_fd')]
                self.assertIsNone(carrier_reading(p,params))
            p=copy.deepcopy(baseline)
            p['raw_samples'][0]['real']=1e308;p['raw_samples'][1]['real']=-1e308
            self.assertIsNone(carrier_reading(p,params))
            p['raw_samples'][0].update(real=1.7e308,imag=1.7e308)
            p['raw_samples'][1].update(real=0.,imag=0.)
            self.assertIsNone(carrier_reading(p,params))
            # Finite higher harmonics cannot mask unavailable fundamental data.
            p=copy.deepcopy(baseline)
            p['raw_samples']+=[dict(r,x=2e9) for r in p['raw_samples'] if r['analysis']=='hb_fd']
            p['raw_samples'][0]['real']=None
            self.assertIsNone(carrier_reading(p,params))
            # A single-ended carrier needs no negative-node sample.
            self.assertEqual(carrier_reading(baseline,{'p':'/P'})['frequency_hz'],1e9)

    def test_si_suffix_and_unsupported_grid(self):
        self.assertEqual(expected_conditions({'variables':{'C':'10p 20p'}})[1]['variables']['C'],2e-11)
        with self.assertRaises(ValueError):expected_conditions({'variables':{'C':'1:2:9'}})
        self.assertEqual(literal('("pm" t nil)'),['pm',True,None])
