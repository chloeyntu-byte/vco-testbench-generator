# User-provided PDK bindings

A binding records the local OA masters and Spectre model includes used by your DUT. Keep your binding, model files and OA libraries in your own environment. The [generic binding](../examples/generic-binding.json) demonstrates the format with fictional `example_pdk`, `nch`, `pch` and a placeholder model path.

## Fields

| JSON field | Meaning |
| --- | --- |
| `schema` | `vco.binding.v1` identifies the binding format. |
| `name` | User-chosen binding identifier. |
| `model_includes` | Ordered array of objects with `path` and optional `section`. Use absolute paths to model files readable by Spectre. Include the section only when it is defined by that file and needed for the test. |
| `roles` | Device metadata for the design producer. Key by role, such as `nmos` or `pmos`. Each example row names its OA `library`, `cell`, `view`, Spectre `model` and `terminals`. The MOS row maps logical `d/g/s/b` to the actual OA terminal names. |
| `description` | Optional note for the binding's reader. |

VCO TB Generator consumes `model_includes` from the Design Lab export's `binding.json`. The design producer owns the `roles` mapping, any required property or netlist parameter maps, and the generated DUT. The TB Generator uses the exported DUT symbol and the requested schematic/config view as a whole.

## Write and use a binding

1. Start with the example and choose names from your local PDK. Check OA master and terminal names against your installed library. For Design Lab project generation, supply any additional roles and property mappings required by the project producer.
2. List model files and sections in the order required by your circuit. Confirm that the PDK libraries are mapped by your `cds.lib`.
3. For a Design Lab export, use this information in the exported `binding.json`. For a hand-written `create_new` request, copy the `model_includes` array into the request's `models` field and provide the DUT's library/cell/view. In `add_test_to_existing` mode the new test inherits the source test's models.
4. Run `vco-tbgen plan REQUEST.json --json` to check spec structure, then confirm native model resolution in your Cadence environment. Offline planning does no OA or model file access.

Choose supplies, port roles, control values and starting conditions for your circuit. The example values illustrate the request format.
