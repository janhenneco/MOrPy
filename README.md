# MESA Runner (`mesa-runner`)

A `Python` package to serve as an interface for the stellar structure and evolution code Modules for Experiments in Stellar Astrophysics (`MESA`, https://mesastar.org). Its main capabilities are building ready-to-run work directories, run MESA models from within Python, and run multiple models in parallel using `MPI` and/or `multiprocessing`.

The `mesa-runner` package's main modules are:

- `config.py`: A module that gets and holds information about the `MESA` version. [DONE]

- `parser.py`: A module that parses (1) the `MESA` defaults files: `controls.defaults`, `star_job.defaults`, `binary_controls.defaults`, `binary_job.defaults`, `kap.defaults`, `eos.defaults`, `pgstar.defaults`, and `pgbinary.defaults` files to gather all the inlist options and (2) parses existing `MESA` inlists so that they can be used as templates. [DONE]

- `options.py`: A module that holds the classes and methods related to store, manipulate, and write out `MESA` inlist options. [WIP]

- `utils.py`: A collection of helper functions. [WIP] 

- `work_setup.py`: A module to create `MESA` work directories based on inlist specifications. [PLANNED]

- `runner.py`: A module to start a `MESA` run, collect its terminal output, and report any errors [PLANNED]

- `status.py`: A module to provide status information on currently running models and models waiting in the queue. This module provides a method to get the current status and a method to display an automatically updating status panel. [PLANNED]

- `grid_run.py`: A module to run multiple models in parallel using `MPI` or `multiprocessing` when `MPI` is not available. [PLANNED]

- `compile.py`: A module to compile the `Fortran` executable. [PLANNED]


##TODO:

- Pandas should be added as an optional requirement. -> Done -> this should be clear in the README later!

- There is currently a problem with inlist init and write:
the source_path in Inlist seems to be a relic from the DefaultsFile implementation
and is nonsensical. The empty and write methods treat this as a valid path. I need to remove source path, or make it optional and onpy set when an inlist was read. nevertheless, I should then make sure that the output_path in write() is not optional and does not use source path. if I want to overwrite inlists, I can still do 

if Inlist.source_path is not None
    write(output_path = source_path)
