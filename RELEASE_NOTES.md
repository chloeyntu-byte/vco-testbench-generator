# VCO TB Generator 1.0.0

This release packages the CLI, Python API, fixture schema and native SKILL resources. It supports plans for new LC VCO testbenches and tests that inherit an existing Maestro setup. The generic L-c request in `examples/` runs without EDA software.

For native materialization and execution, supply a compatible Virtuoso/Spectre environment, a mapped DUT and your own PDK binding. The existing-test preservation path targets IC6.1.8 setupdb v6 and statedb v5.

The fixture schema stays at `vco-tbgen.spec.v1`. Existing ISF callers can continue to use `vco_tbgen.isf` and the session APIs. See [runtime configuration](docs/API.md#native-runtime) for portable defaults and optional site wrapping.
