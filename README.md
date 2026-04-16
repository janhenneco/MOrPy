# MESA Runner (`mesa-runner`)

A `Python` package to serve as an interface for the stellar structure and evolution code Modules for Experiments in Stellar Astrophysics (`MESA`, https://mesastar.org). Its main capabilities are building ready-to-run work directories, run MESA models from within Python, and run multiple models in parallel using `MPI` and/or `multiprocessing`.

The `mesa-runner` package's main modules are:

- `config.py`: A module that gets and holds information about the `MESA` version. [DONE]

- `parser.py`: A module that parses (1) the `MESA` defaults files: `controls.defaults`, `star_job.defaults`, `binary_controls.defaults`, `binary_job.defaults`, `kap.defaults`, `eos.defaults`, `pgstar.defaults`, and `pgbinary.defaults` files to gather all the inlist options and (2) parses existing `MESA` inlists so that they can be used as templates. [DONE]

- `options.py`: A module that holds the classes and methods related to store, manipulate, and write out `MESA` inlist options. [DONE]

- `model.py`: A module for the Model class, which keeps track of the model's status and holds its inlists.

- `utils.py`: A collection of helper functions. [WIP] 

- `work_setup.py`: A module to read and create `MESA` workdirs. Serves as a layer between the Model objects and the system storage. [WIP]

- `runner.py`: A module to start a `MESA` run, collect its terminal output, and report any errors [PLANNED]

- `status.py`: A module to provide status information on currently running models and models waiting in the queue. This module provides a method to get the current status and a method to display an automatically updating status panel. [PLANNED]

- `grid_run.py`: A module to run multiple models in parallel using `MPI` or `multiprocessing` when `MPI` is not available. [PLANNED]

- `compile.py`: A module to compile the `Fortran` executable. [PLANNED]


##TODO:

- Pandas should be added as an optional requirement. -> Done -> this should be clear in the README later!
- It should be clear from the instructions that users should preferable always initiate the MesaConfig object, 
    since this will allow the MesaVersion to be automatically passed to intialisations of Inlist and Model objects. 
- There should be a general philosophy in the README:
    - The user is ultimately responsible for creating and parsing sensible and correct inlists.
    - The disk is the truth: any changes made to inlist files and their contents after their inception on the disk
        will be synced upon runtime. 


