# Offline example

Run from the repository root with Python 3.11 or later.

```sh
python -B -m vco_tbgen plan examples/generic-request.json --json
```

`generic-request.json` describes an L-c test with a DC supply, bias source, one-bit enable, four-bit Verilog-A register, and differential output. Its `models` array matches `model_includes` in `generic-binding.json`. The binding, library names and all numerical inputs are fictional. The plan returns `ready` with a spec hash and the proposed operations.

For a native request, use your actual DUT and terminal names, review the stimulus values and substitute your own workspace, library mapping and [PDK binding](../docs/BINDINGS.md).
