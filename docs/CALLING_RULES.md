# Calling rules for host applications

This page is the contract for any program that calls VCO TB Generator: a design environment, a script, or an analysis tool such as [VCO ISF Explorer](https://github.com/chloeyntu-byte/vco-isf-explorer). The [API reference](API.md) lists every argument; the [specification](SPEC.md) defines validation and readback.

## 1. Find and load the generator

| Method | Use |
| --- | --- |
| `python -m pip install .` in a checkout, or install the released wheel (distribution `vco-tbgen`) | The host imports `vco_tbgen` from its own environment |
| A checkout path passed by the host (for ISF Explorer: `--tbgen-root PATH` or `VCO_TBGEN_ROOT`) | The host adds the path to `sys.path` only while importing and must verify that `vco_tbgen.__file__` lies inside that path |

Hosts should read `vco_tbgen.__version__` and refuse major versions they were not written for. Within a major version, the public names below keep their signatures and response schemas.

Public names (from `vco_tbgen`): `plan`, `validate`, `materialize`, `run`, `results`, `browse_libraries`, `describe_cell`, `classify_ports`, `dut_only`, `from_design_lab`, `lc_hb_defaults`, `install_oscillator`, `plan_session_add`, `materialize_session_add`, `analysis_bundle`, `install_bundle`, and the `isf` module. Other modules are internal.

## 2. Pick the completeness level

| Level | Ask for it when | You get |
| --- | --- | --- |
| L-a | You only need the DUT interface | Symbol terminal readback |
| L-b | You need a schematic fixture and config | Schematic + config, connectivity evidence |
| L-c | You need oscillator performance | HB + HBNOISE, f0, phase noise and supply power outputs |
| L-d | You run ISF analysis | L-c plus HBXF, a probe across the selected device's D/S terminals, and saves for the output pair and device |

A host asks for the lowest level it needs. ISF-specific parts (HBXF, injection probe, device saves) are created only through `vco_tbgen.isf`; L-a to L-c never add them. HB, HBNOISE and HBXF always share one fundamental, harmonic count, output pair and offset list (`analysis_bundle`).

## 3. Follow the lifecycle

```
request ──> plan (offline) ──> materialize (native) ──> run ──> results
              │  status: ready | needs_input
              └─ resolve every "ask" operation with the user before materializing
```

1. **Plan offline.** `plan(spec)` never touches OA data. It returns `ready` with a spec hash, or `needs_input` with the fields to confirm.
2. **Confirm with the user.** Port roles from `classify_ports` are suggestions. The host shows them and records the user's confirmation; it never auto-accepts an ambiguous role, a register width or a supply value.
3. **Materialize with the same plan.** `materialize(spec, plan)` rejects a spec whose hash differs from the plan.
4. **Run and read results** through `run(receipt)` and `results(handle)`. A result is usable only when the required outputs, saves and point coverage pass qualification. For an inherited model-group corner, coverage checks the reported file/section pairs against the saved group. Supported IC6.1.8 setupdb v6 groups use absolute paths, named sections and the All/Global scope. Unsupported formats fail before launch.

## 4. Writing rules

- **New fixtures (create mode)** go into a library inside a workspace the caller owns. Never point `workspace` at a shared or PDK library.
- **Existing Maestro setups (add-test mode)** must be closed in Virtuoso, or the host must use the live-session pair `plan_session_add` / `materialize_session_add` after an explicit user confirmation in that window. The generator backs up the setup, adds only the new test, reads it back, verifies that the original tests, variables, corners and sweeps are unchanged, and restores the backup on failure.
- The generator refuses to write when it finds an OA lock or a read-only session. Hosts must not delete lock files to get past this.
- Serialize writes to the same library. Sites with shared simulators or libraries set `TBGEN_COMMAND_TEMPLATE` (see the [API reference](API.md#native-runtime)) so the whole transaction, from backup through verification, runs inside the site lock.
- Native steps need at least 2 GiB free disk (`runtime.min_free_bytes`).

## 5. Responses and exit codes

Every call returns a JSON object with `status`. The CLI prints that object and exits nonzero for `failed` and `needs_input`. Hosts should key on `status` and the structured issue codes, not on message text.

## 6. Example: how VCO ISF Explorer calls the generator

| ISF entry | Generator calls |
| --- | --- |
| A · Design Lab project | `from_design_lab(..., completeness="L-b")` for the fixture, then the L-d steps below |
| B · Existing Maestro | Reads the source test, then add-test mode (batch) or `plan_session_add` → `materialize_session_add` (open window, after confirmation) |
| C · New cell | `browse_libraries` → `describe_cell` → `classify_ports` (user confirms roles) → fixture spec, then the L-d steps below |

L-d steps for every entry: `isf.analysis_bundle` (one HB/HBNOISE/HBXF bundle) → `isf.injection_for_device` (probe across the selected device's proven D/S terminals) → `isf.install_isf` → `plan` → `materialize` → `run` → `results`.

ISF Explorer performs no OA or Maestro writes itself; every write goes through these calls.
