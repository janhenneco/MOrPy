# MESA Runner (`mesa-runner`)

A `Python` package to serve as an interface for the stellar structure and evolution code Modules for Experiments in Stellar Astrophysics (`MESA`, https://mesastar.org). Its main capabilities are building ready-to-run work directories, run MESA models from within Python, and run multiple models in parallel using `MPI` or `subprocessing`.

The `mesa-runner` package's main modules are:

- `config.py`: Configuration and environment utilities. [DONE]

- `parser.py`: Parsing utilities for MESA defaults files and inlists. [DONE]

- `options.py`: Data model and utilities for MESA defaults/inlist options. [DONE]

- `utils.py`: Low-level utility helpers for MESA value normalization and conversion. [DONE]

- `model.py`: Model objects and lifecycle state for individual MESA runs. [DONE]

- `work_setup.py`: Work-directory setup, synchronization, and export utilities for models. [DONE]

- `project_setup.py`: Project-directory creation utilities for MESA runs. [DONE]

- `compile.py`: Compilation helpers for project-level MESA executables. [DONE]

- `run.py`: Single-model run orchestration for foreground and background execution. [DONE]

- `run_types.py`: Shared runtime data types for model execution workflows. [DONE]

- `errors.py`: Shared exception hierarchy for run, orchestration, and persistence layers. [DONE]

- `grid_run.py`: Grid orchestration contracts for multi-model execution. [DONE]

- `repository.py`: Persistence abstraction and adapter hooks for run metadata. [DONE]

- `status.py`: Status view contracts for live and persisted model execution state. [DONE]


