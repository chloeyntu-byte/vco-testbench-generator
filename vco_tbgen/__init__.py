"""Independent VCO testbench generator. Public imports load on demand."""
from importlib import import_module

__version__ = '1.0.0'

_EXPORTS = {
    'isf': ('isf', None),
    'browse_libraries': ('api', 'browse_libraries'),
    'describe_cell': ('api', 'describe_cell'),
    'classify_ports': ('catalog', 'classify_ports'),
    'dut_only': ('catalog', 'dut_only'),
    'materialize': ('completion', 'materialize'),
    'run': ('runner', 'run'),
    'results': ('runner', 'results'),
    'plan': ('spec', 'plan'),
    'validate': ('spec', 'validate'),
    'from_design_lab': ('design_lab', 'from_design_lab'),
    'lc_hb_defaults': ('oscillator', 'lc_hb_defaults'),
    'install_oscillator': ('oscillator', 'install_oscillator'),
    'plan_session_add': ('session', 'plan_session_add'),
    'materialize_session_add': ('session', 'materialize_session_add'),
    'analysis_bundle': ('isf', 'analysis_bundle'),
    'install_bundle': ('isf', 'install_bundle'),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    module = import_module('.'+module_name, __name__)
    return getattr(module, attribute) if attribute else module
