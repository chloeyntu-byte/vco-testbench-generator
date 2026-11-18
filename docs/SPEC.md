# VCO TB Generator specification

VCO TB Generator prepares LC VCO fixtures and Maestro tests from an exported DUT, a selected OA cell, or a saved Maestro test. This document describes the fixture contract. See the [Python and CLI reference](API.md) and the [PDK binding guide](BINDINGS.md) for inputs and commands.

## Completeness levels

| Level | API and CLI | Return and materialization |
| --- | --- | --- |
| L-a | `dut_only(dut, cds_lib, workspace=..., runtime=...)` or `vco-tbgen dut-only REQUEST.json`. Design Lab exports the DUT before calling this API. | `dut_ready` and schematic/symbol interface readback. |
| L-b | `from_design_lab(..., completeness="L-b")` or an explicit v1 spec with `completeness: "L-b"`. | `fixture_ready`, schematic and config paths, and terminal connectivity evidence. The generated cell has no Maestro setup. |
| L-c | `from_design_lab(..., completeness="L-c")` or `install_oscillator(spec, frequency=..., positive=..., negative=...)`. | `prepared`, fixture plus HB/HBNOISE and qualified `VCO_` scalar outputs. Call `run` to solve. |
| L-d | ISF Explorer calls `vco_tbgen.isf`, then passes the frozen v1 spec to `materialize` or `materialize_session_add`. | `prepared` for a new/offline test, or an open-session transaction receipt. HB/HBNOISE/HBXF plus ISF measurements. |

The `dut-only` JSON keys are `dut`, `cds_lib`, `workspace`, and optional `runtime`. The `from-design-lab` JSON keys are `generated_dir`, `dut`, `workspace`, `cds_lib`, `library_path`, `maestro`, and optional `design_lab_root`. Pass `--level L-b` or `--level L-c` to that command. `plan` and `materialize` accept `--level` to check or set the explicit fixture level of a complete spec. To prepare L-d, use ISF Explorer to bind the device. For an existing closed or open setup use an L-d spec in `add_test_to_existing` mode. `run` accepts a prepared Maestro test.

An L-d request requires a selected device occurrence and proof of its terminals. The ISF module uses that selection when installing the test. Incomplete requests remain pending for user input.

## Module map

| Module | Responsibility | Callers |
| --- | --- | --- |
| `catalog` | Read library/cell/view inventory, OA ports, bus order, port role suggestions, and verify a DUT export | Both tools and CLI |
| `design_lab` | Transform a generated project, graph, binding and registers into a fixture spec | Design Lab and ISF entry A |
| `schematic` | Create supply, bias, control and register instances, wire the fixture, bind config, and verify connectivity | L-b worker and new Maestro materializer |
| `completion`, `spec` | Validate, freeze, and route a spec to the required materializer | Both tools and CLI |
| `maestro`, `session`, `preservation` | New Maestro, offline copied test, captured open-session transaction, and rollback/readback | Design Lab L-c and ISF Explorer |
| `oscillator`, `output_templates` | Oscillator HB defaults, offset sweep and scalar PN/f0/power expressions | Design Lab L-c. ISF shares these measurement expressions. |
| `isf` | Bind the proven D/S nodes, emit the injection stimulus, reconcile HB/HBNOISE/HBXF, and install ISF outputs and saves | ISF Explorer A, B and C |
| `runner`, `effective` | Run exact saved tests, extract RDB/PSF points and qualify required data and coverage | Both tools and CLI |
| `native`, `transaction`, `worker` | Private native process, per-operation artifacts, and optional command wrapper | Native operations |

The package loads its public operations on demand. The original `vco_tbgen.api`, `bundle`, `injection` and native emitter import paths remain available. Legacy unlevelled v1 specs keep their materialization behavior. The original `from_design_lab` call without a level still produces its historical full analysis bundle. New callers supply a level. Authoring PSS, PNOISE and transient analyses is no longer supported because neither consumer uses this feature. Copied Maestro tests preserve these and other inherited analyses. DC remains supported for fixture and grid checks.

## Fixture spec v1

The JSON schema is shipped at `vco_tbgen/resources/tb-spec-v1.schema.json`. Python validates the used Draft-07 subset and adds semantic checks. The schema version and spec hash travel in artifacts.

| Field | Contract |
| --- | --- |
| `mode` | `create_new` or `add_test_to_existing` |
| `workspace`, `cds_lib`, `library_path` | Absolute paths. Target library resides inside the owned workspace and its directory name matches `maestro.lib`. Workers create a private cds.lib overlay. |
| `dut`, `maestro` | Explicit OA lib/cell/view. The TB uses the DUT symbol and binds the declared DUT view in config. A copied test names both the source and new test. |
| `ports` | Name, net, direction and an explicit role. Unresolved roles and missing drivers for required inputs block creation. A designation as external is explicit. |
| `supplies`, `controls` | AnalogLib DC sources. Voltage/current controls and values may refer to declared design variables. |
| `registers` | Width 1–30, LSB-first members, integer variable and range, rails, and optional inversion. Default, corner and sweep codes are range checked. |
| `probes` | Explicit, optional DUT-port series fixtures with `zero_volt` or `iprobe`. Outer net to internal net is the positive direction. |
| `models`, `runtime` | Ordered model paths and sections, and the native execution profile. PDK masters, parameters and sections come from binding/graph data. Supply domains come from the exported circuit interface and parameters. Native execution checks disk capacity before starting. |
| `variables`, `corners`, `sweeps` | New fixture settings. Independent numeric discrete sweeps can use test or global scope. Existing setup copies inherit these settings. |
| `analyses`, `outputs`, `saves` | Native option types and result expressions. Enabled output expressions use `plot=true` for IC618 evaluation. Signal saves use OA hierarchy syntax. |
| `simulator_options`, `initial_conditions` | Native options and an explicit private Spectre IC stimulus. |
| `required` | `vco-tbgen.required.v1` with analysis names, named outputs of kind scalar/waveform, and required save signal names. |
| `source` | Generated artifact paths, provenance and hashes. |

`plan` yields keep/add/ask operations and the hash of the complete input. Materialization recomputes the plan. An existing cell, stale plan or unresolved ask blocks the write. Port grading uses real symbol terminals, and expands ascending and descending buses without changing the source descriptor. The decimal-to-binary cell is `isf_decimal_register` for four bits and `isf_decimal_register_wN` for other widths. Each view has a fixed interface. Its output is `(((DEC_CODE >> i) & 1) ^ INVERT) * V(vdd,vss)` relative to vss.

## Maestro and ISF

IC618 needs explicit `fundfreqs` and `maxharms` in HB. `HBFreq1` and `HBHarm1` also populate the UI. New LC tests use linear initial conditions, two-tier HB, the selected output pins, and conservative precision. HBNOISE uses relative offsets, `relharmvec=["1"]`, voltage output and PM noise. HBXF uses the same grid and `freqaxis="out"`. A single requested offset receives a second native sample at twice the offset to keep the harmonic family readable. Metrics continue to use the requested offset. The two-tier solver uses frequency-domain residuals as convergence evidence.

The ISF Explorer selector supplies the selected output pair, target occurrence and proven terminal nets. The ISF module adds a D-to-S injection branch consisting of a zero-DC current source in series with an iprobe. `injection_for_device(..., probe='zero_volt')` selects a zero-volt series element. The branch has zero DC excitation and its source is the HBXF input. The test also saves the actual device drain branch current. For a model with a numbered drain formal, the module uses the proven Spectre terminal identifier from device selection. Use a separate request for each selected occurrence when independent tests are required.

The required HBXF output is a complex V/A family. It retains the native harmonic coordinates and all frequencies. Signed ISF order is native harmonic plus one, and the output-frequency axis is f0 plus offset. The phase-noise expression is `10log10(2)+20log10(PM_ASD/Vdiff_peak)`. IC618 `hb_fd` stores a peak-normalized differential fundamental. DC power uses the saved supply-terminal current, sign-adjusted as positive into the fixture, and the DC voltage across that source. L-d also includes harmonic ratios and signed FoM. New native Maestro options are read back after saving and reopening.

### Existing setups

The optional command wrapper can hold a library lock and simulator slot for the full transaction, from backup through verification. Without a wrapper, schedule transactions against the same library serially. The worker checks for existing OA locks and native session read-only state. An entire setup backup omits locks and result payloads. The new test is made with native `maeCreateTest(?sourceTest ...)`. IC618 normalizes parts of the old tests when saving, so the qualified setupdb v6/statedb v5 serializer inserts only the native new test fragments into the preserved baseline. The worker reopens the result and checks old test getters, global/corner/sweep/history data and test state fingerprints. Failed writes restore the captured baseline while it is safe to do so.

The live path uses `plan_session_add(spec, context)` and `materialize_session_add(plan, context)`. The versioned context identifies the exact `session`, `window_id`, `setup_handle`, `lcv`, `dirty`, `save_policy`, disk `revision`, and context `generation`. The plugin captures these with the native window/session/setup getters and `maeIsSetupModified`. The emitted SKILL runs inside that window after confirmation and checks the same identity, library path and revision. Dirty `reject` stops before mutation. Dirty `save` persists the user's pending changes first, then takes the rollback baseline. Failure restores via `maeLoadSetupState` and verifies the original setup again. The transaction keeps the session open. A batch test may use `private_batch=true` and a null window ID with `TBGEN_NATIVE=1`. Logical comparison covers the full old settings and allows only IC618 cache normalization and expected registration of the new test.

## Run and evidence

A run uses an owned private HOME, cds.lib, and scratch directory. `run(materialized, wait=False)` returns a handle for `results` polling. The worker reads the exact saved test and verifies effective native settings before starting. RDB results locate each PSF by the native results directory. The reader exports scalar and complete finite waveform data, including complex components, units and family coordinates. Legacy optional outputs are reported as unverified. Inherited analyses remain enabled as saved and have independent qualification only when required.

Success requires native completion, a zero-error Spectre terminal state, required result families and saves, finite named measurements, and matching test/corner/variable coverage. A required HB carrier must exceed 10 µV differential fundamental. Two-tier stationary qualification requires finite final normalized inner/outer residuals below one, a positive f0, and a completed solve. Transient steady-state detection is reported separately when it was used. A failed or unavailable optional inherited carrier is reported as unavailable. Coverage compares each actual point with the expected **multiset** so duplicates cannot fill missing combinations. For a saved global model group, coverage also compares the reported model files and named sections against the group assigned to that corner. The saved IC6.1.8 setupdb v6 format uses absolute file paths and the All/Global scope. Unknown sweep or model-group formats, parametric sets and unsupported setup versions are rejected before launch.

The native path was verified on one Virtuoso IC6.1.8 and Spectre 18.1 installation across three CMOS processes. Process names and qualification data are withheld. Each user supplies their own Cadence environment, licensed simulator and PDK. Native tests are opt-in. For opt-in multi-PDK replay set `TBGEN_NATIVE=1` and `TBGEN_PDK_SPECS=/absolute/profiles.json` and run `python -B -m unittest discover -s tests -p test_completeness.py -v`. The profile JSON maps each PDK label to a complete L-d create spec with a private owned workspace, its read-only PDK mapping, and the exported DUT. Each replay creates a fresh fixture, runs native HB/HBNOISE/HBXF, and retains the qualification JSON and Spectre log. In supported IC618 batches, the private session tests also exercise clean add, explicit dirty save/reject and injected rollback. This is simulator and fixture qualification. Oscillator design performance and other Cadence versions need separate evidence.
