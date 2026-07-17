# MESA Runner (`mesa-runner`)

A `Python` package to serve as a modular interface for the stellar structure and evolution code Modules for Experiments in Stellar Astrophysics (`MESA`, https://mesastar.org). Its main capabilities are building ready-to-run work directories, run MESA models from within Python, and run multiple models in parallel using `concurrent.futures` or `mpi4py`.

The `mesa-runner` package's main modules are:

- `config.py`: Configuration and environment utilities.

- `parser.py`: Parsing utilities for MESA defaults files and inlists.

- `options.py`: Data model and utilities for MESA defaults/inlist options.

- `utils.py`: Low-level utility helpers for MESA value normalization and conversion.

- `model.py`: Model objects and lifecycle state for individual MESA runs.

- `work_setup.py`: Work-directory setup, synchronization, and export utilities for models.

- `project_setup.py`: Project-directory creation utilities for MESA runs.

- `compile.py`: Compilation helpers for project-level MESA executables.

- `run.py`: Single-model run orchestration for foreground and background execution.

- `run_types.py`: Shared runtime data types for model execution workflows.

- `errors.py`: Shared exception hierarchy for run, orchestration, and persistence layers.

- `grid_run.py`: Grid orchestration contracts for multi-model execution.

- `repository.py`: Persistence abstraction and adapter hooks for run metadata.

- `status.py`: Status view contracts for live and persisted model execution state.

## Installation instructions

[TODO]

## Generative AI Disclosure
Some code was drafted using generative AI tools. All prompts were provided by the author, and all AI-generated content was reviewed and approved by the author before being included. No generative AI was used without human review.


