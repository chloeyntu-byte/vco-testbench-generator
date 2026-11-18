# Python and CLI reference

Use the packaged [fixture schema](../vco_tbgen/resources/tb-spec-v1.schema.json) for JSON fields. See the [specification](SPEC.md) for validation and native readback rules.

## Entry modes

### Design Lab project or export

Call `vco_tbgen.from_design_lab(generated_dir, dut=..., workspace=..., cds_lib=..., library_path=..., maestro=..., completeness="L-c")`. Supply the exported DUT library, cell and view. The generated directory contains these files:

- `manifest.json` records export metadata.
- `graph.json` contains `ports` and `parameters`. Parameters include `vdd`, `vdc`, `vdd_bank` for a separate `VDDB` rail, and `frequency_guess_ghz` for L-c.
- `binding.json` supplies the [model includes](BINDINGS.md).
- `registers.json` is an array of register records with `name`, `bits`, `default`, and `pins_msb_first`. The adapter translates these into LSB-first fixture wiring.

`generated_dir` can also be a project dictionary or a path to a project JSON file. In that case, set `design_lab_root` or `VCO_DESIGN_LAB_ROOT` to your Design Lab checkout. The adapter calls its generator to prepare the four files. Provide an OA DUT export corresponding to that project.

The equivalent command is `vco-tbgen from-design-lab REQUEST.json --level L-c`. The request supplies the same named arguments. Use `--level L-b` if you only need schematic and config.

### Existing Maestro test

Set `mode` to `add_test_to_existing` and specify `maestro.source_test` and an unused `maestro.test` name. Use an owned copy of the library for batch changes and close the setup in Virtuoso. The new test inherits models, variables, corners and sweeps. The generator verifies preservation of the original tests. Use `plan_session_add(spec, context)` and `materialize_session_add(plan, context)` for explicit confirmation and a transaction in an open session. The session context and serialization versions are defined in the [specification](SPEC.md#existing-setups).

### New fixture for an OA cell

1. Use `browse_libraries(cds_lib)` and `describe_cell(lcv, cds_lib)` to find the DUT and read its symbol terminals. Run `classify_ports(descriptor)` offline to suggest port roles and bus order. Confirm the assignments against the circuit.
2. Set `mode` to `create_new`. Write `workspace`, `cds_lib` and `library_path` as absolute paths. Place the target library inside the workspace and match its directory name to `maestro.lib`.
3. Specify drivers with `supplies` and `controls`. For multi-bit pins use `registers` with an integer `code_variable`, LSB-first members, width and rail nets. Reserve `probes` for explicitly routed series connections.
4. Set `completeness` to `L-b` with empty analyses for schematic/config. For L-c call `install_oscillator(spec, frequency="1G", positive="/OUTP", negative="/OUTN")` with your selected output and frequency guess. The [fictional example request](../examples/generic-request.json) illustrates this shape.

## Completeness and outputs

| Level | Request | Result |
| --- | --- | --- |
| L-a | `dut_only(dut, cds_lib, workspace=...)` | DUT schematic and symbol interface readback |
| L-b | Fixture spec with empty analyses | Schematic and config with terminal connectivity evidence |
| L-c | Oscillator fixture | HB/HBNOISE and qualified carrier frequency, phase noise, and supply power |
| L-d | `vco_tbgen.isf` builds the ISF request and installs its test | HB/HBNOISE/HBXF, a selected device injection probe, and saves for the output pair and device |

For L-d, `vco_tbgen.isf.analysis_bundle(...)` reconciles the analysis settings. Use `injection_for_device(device)` with proven D/S terminals, then `install_isf(spec, bundle, injection=..., device=..., supplies=...)` to freeze the test. Use the same planning and materialization APIs below. ISF computations are supplied by the calling application.

## Plan, materialize and run

```python
from vco_tbgen import materialize, plan, results, run

proposal = plan(spec)  # Offline. Resolve any ask operations first.
if proposal["status"] == "ready":
    receipt = materialize(spec, proposal)  # Native. Verifies proposal and spec match.
    if receipt["status"] == "prepared":
        handle = run(receipt, wait=False)
        report = results(handle)
```

L-b materialization stops with `fixture_ready`. L-c and L-d produce a prepared setup. The CLI commands `plan`, `materialize`, `run` and `results` read JSON files, print JSON and accept `--output PATH` to save it. `materialize --plan PATH` takes a previously saved plan. The CLI returns a nonzero exit code for `failed` and `needs_input` responses.

## Native runtime

| Setting | Default and purpose |
| --- | --- |
| `runtime.virtuoso` | `TBGEN_VIRTUOSO`, then `virtuoso` from `PATH` |
| `runtime.environment_script` | `TBGEN_ENVIRONMENT_SCRIPT`, then inherited shell environment. Use an absolute script path to source project-specific setup. |
| `runtime.timeout_seconds` | Native child timeout, default 1800 seconds |
| `runtime.min_free_bytes` | Native disk threshold, at least 2 GiB |
| `TBGEN_RUN_ROOT` | Artifacts for library and cell reads when no workspace is supplied. Defaults to a per-user cache. |

For calls through an ISF host that shares a Cadence setup script between tools, specify `runtime.environment_script` or `TBGEN_ENVIRONMENT_SCRIPT` at both stages.

`TBGEN_COMMAND_TEMPLATE` optionally wraps native requests in a site command. By default the worker executes directly. The value is a JSON array of arguments. A single `{command}` argument expands into the original executable and its arguments. Each `{library}` argument expands to the library name. Expansion preserves argument boundaries and uses no shell interpolation. For example, if your site provides a lock wrapper:

```sh
export TBGEN_COMMAND_TEMPLATE='["site-lock", "--library", "{library}", "--", "{command}"]'
```

Use a wrapper that waits for the child and returns its exit status. For a materialize/run transaction the wrapper belongs around the whole worker, so setup backups, readback and rollback remain inside its scope. For catalog reads the library argument is `TBGEN_READER`. When running directly, serialize changes to the same library.

## Tests

Run offline checks with `python -B -m unittest discover -s tests -v`. Native integration checks are opt-in via `TBGEN_NATIVE=1`. Supply a locally qualified L-d create spec in `TBGEN_NATIVE_SPEC` with a decimal register and a supply driven by a numeric design variable. For multi-PDK replay use the per-profile L-d specs described in the [specification](SPEC.md#run-and-evidence). The existing-setup tests additionally use `TBGEN_PHASE2_NATIVE=1`, an owned `TBGEN_PHASE2_ROOT`, a user-provided copyable Maestro fixture spec in `TBGEN_EXISTING_SPEC`, and `TBGEN_EXISTING_WAVE_NODE` for the source test's saved HB voltage. Map the copyable setup’s dependencies in `cds.lib`. The source setup should include a qualified HB/HBNOISE/HBXF test and an enabled inherited noise analysis. Use disposable fixtures for all native tests.
