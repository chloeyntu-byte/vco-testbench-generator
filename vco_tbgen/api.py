"""Compatibility imports for the original TB Generator API."""
from . import catalog
from .catalog import classify_ports
from .spec import plan
from .transaction import _target, check_unlocked

RUN_ROOT = catalog.RUN_ROOT


def browse_libraries(cds_lib):
    return catalog.browse_libraries(cds_lib, workspace=RUN_ROOT)


def describe_cell(lcv, cds_lib):
    return catalog.describe_cell(lcv, cds_lib, workspace=RUN_ROOT)


def __getattr__(name):
    if name == 'setup_snapshot':
        from .maestro import setup_snapshot
        return setup_snapshot
    if name in ('materialize', 'run', 'results'):
        from . import __getattr__ as public_api
        return public_api(name)
    raise AttributeError(name)
