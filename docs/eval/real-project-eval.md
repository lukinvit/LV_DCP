# Advisory Real-Project Eval

Synthetic eval is the only **mandatory CI-gated** retrieval contract in LV_DCP.
Polyglot and multi-project eval are **manual/advisory** because they depend on
real repositories outside this repo.

## What this solves

- makes local project resolution explicit
- explains why advisory projects were skipped
- gives one report workflow for `polyglot` and `multiproject`

## Local project map

Copy the example file and edit the values to match the directory names of your
already registered projects:

```bash
cp tests/eval/project_map.example.yaml ~/.lvdcp/eval-project-map.yaml
```

Example:

```yaml
projects:
  GoTS_Project: my-real-go-ts-repo
  PythonTS_Project: my-real-python-ts-repo
  Project_Large: my-large-project
```

Notes:

- keys are the generic fixture names from `tests/eval/*.yaml`
- values are the final path components of registered project roots
- override the default path with `LVDCP_EVAL_PROJECT_MAP=/abs/path/to/map.yaml`

## Prerequisites

- the target projects are registered in `~/.lvdcp/config.yaml`
- each target project has already been scanned and indexed

## Commands

```bash
bash scripts/polyglot-eval-report.sh local
bash scripts/multiproject-eval-report.sh local
```

Reports are written under `docs/eval/` with the current date in the filename.

## Interpreting skips

Skipped projects are expected on machines that do not have the full advisory
portfolio available. Common reasons:

- project not registered under the expected directory name
- project registered but not indexed yet
- no local project map provided, so identity mapping was used
