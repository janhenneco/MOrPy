# MESA Runner (`mesa-runner`)

A `Python` package to serve as an interface for the stellar structure and evolution code Modules for Experiments in Stellar Astrophysics (`MESA`, https://mesastar.org). Its main capabilities are building ready-to-run work directories, run MESA models from within Python, and run multiple models in parallel using `MPI` and/or `multiprocessing`.

The `mesa-runner` package's main modules are:

- `parser.py`: A module that parses (1) the `MESA` defaults files: `controls.defaults`, `star_job.defaults`, `binary_controls.defaults`, `binary_job.defaults`, `kap.defaults`, `eos.defaults`, `pgstar.defaults`, and `pgbinary.defaults` files to gather all the inlist options and (2) parses existing `MESA` inlists so that they can be used as templates. [DONE]

- `work_setup.py`: A module to create `MESA` work directories based on inlist specifications. [PLANNED]

- `inlist_setup.py`: A module to create inlists from within `Python`. [PLANNED]

- `runner.py`: A module to start a `MESA` run, collect its terminal output, and report any errors [PLANNED]

- `status.py`: A module to provide status information on currently running models and models waiting in the queue. This module provides a method to get the current status and a method to display an automatically updating status panel. [PLANNED]

- `grid_run.py`: A module to run multiple models in parallel using `MPI` or `multiprocessing` when `MPI` is not available. [PLANNED]

- `activate.py`: A module to activate the desired `MESA` version and compile the `Fortran` executable. [PLANNED]

- `config.py`: A module that gets and holds information about the `MESA` version. [DONE]

- `utils.py`: A collection of helper functions. [WIP] 