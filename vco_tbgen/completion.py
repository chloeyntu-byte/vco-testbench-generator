"""Route a validated, frozen TB plan to the requested materializer."""
from .spec import plan
from .transaction import _locked, _target


def materialize(spec,completion_plan=None):
    frozen=plan(spec)
    if completion_plan is not None and completion_plan!=frozen:raise ValueError('stale or modified completion plan')
    if frozen['status']!='ready':return {'schema':'vco-tbgen.materialized.v1','status':'needs_input','plan':frozen}
    _target(spec)
    action = 'fixture' if spec.get('completeness') == 'L-b' else 'materialize'
    return _locked(action, spec, {'plan': frozen})
