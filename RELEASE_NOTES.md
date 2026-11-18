# VCO TB Generator 1.1.0

Tests added to an existing Maestro setup can inherit saved global model-group
corners. Result coverage checks the reported model files and named sections for
each corner, along with the numeric sweep and corner values. A missing or
different model section leaves the point unmatched.

The supported format is a saved IC6.1.8 setupdb v6 group with absolute model-file
paths, named sections and the All/Global scope. Unsupported saved group
formats are rejected before launch. See the [calling rules](docs/CALLING_RULES.md)
and [specification](docs/SPEC.md).

The fixture schema remains `vco-tbgen.spec.v1`. Try the fictional L-c request
under [examples](examples) with `vco-tbgen plan examples/generic-request.json --json`.
Native operations require your own licensed Cadence installation and model
binding.
