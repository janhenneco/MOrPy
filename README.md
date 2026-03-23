# MESA Runner (`mesa-runner`)

A `Python` package to serve as an interface for the stellar structure and evolution code Modules for Experiments in Stellar Astrophysics (`MESA`, https://mesastar.org). Its main capabilities are building ready-to-run work directories, run MESA models from within Python, and run multiple models in parallel using `MPI` and/or `multiprocessing`.

The `mesa-runner` package's main modules are:

- `parser.py`: A module that handles reading the activated `MESA` version, and parsing the `controls.defaults`, `star_job.defaults`, `binary_controls.defaults`, and `binary_job.defaults` files to gather all the inlist options, so that they can be specified from within `Python`. [WIP]

- `work_setup.py`: A module to create `MESA` work directories based on inlist specifications. [PLANNED]

- `inlist_setup.py`: A module to create inlists from within `Python`. [PLANNED]

- `runner.py`: A module to start a `MESA` run, collect its terminal output, and report any errors [PLANNED]

- `status.py`: A module to provide status information on currently running models and models waiting in the queue. This module provides a method to get the current status and a method to display an automatically updating status panel. [PLANNED]

- `grid_run.py`: A module to run multiple models in parallel using `MPI` or `multiprocessing` when `MPI` is not available. [PLANNED]

- `activate.py`: A module to activate the desired `MESA` version and compile the `Fortran` executable. [PLANNED]

- `config.py`: A module that gets and holds information about the `MESA` version. [DONE]