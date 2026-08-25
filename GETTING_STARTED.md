# Getting Started

This guide is meant to get new users on their way to use `MOrPy`.

## 1. Install

Follow the "Installation Instructions" section in the [`README.md`](README.md) file.

## 2. How to use `MOrPy`

### 2.1 Preparing and running a single model

The instructions to prepare and run a single model are provided in the example [`prepare_and_run_single_model.ipynb`](docs/examples/scripts_and_notebooks/prepare_and_run_single_model.ipynb). The example notebook [`option_explorer.ipynb`](docs/examples/scripts_and_notebooks/option_explorer.ipynb) shows how to use `morpy` to explore and consult `MESA`'s many inlist options without having to dig for them in the `MESA` installation directory.

### 2.2 Setting up and running a grid of `MESA` models

As alluded to in the project's [`README.md`](README.md), there are two ways to run multiple `MESA` models in parallel with `MOrPy`.

The "`local`" method (backend) uses `Python`'s built-in `concurrent.futures` functionality to spawn multiple threads to compute models in parallel. This method is referred to as "local" since it only works on a single-node setup, i.e. a single laptop, desktop, or node of a compute cluster. The advantage of using the `local` backend is that it can be run from within a Jupyter notebook, as shown in the example [`run_a_grid.ipynb`](docs/examples/scripts_and_notebooks/run_a_grid.ipynb).

The "`mpi`" backend uses `mpi4py` to spawn multiple separate processes, each computing a `MESA` model. The advantage of the `mpi` backend is that it uses `MPI` (Message Passing Interface), which works both on single-node and multi-node processes. In other words, this backend is ideal for large grid computations on compute clusters. A downside of this backend is that it cannot be run from a Jupyter notebook and instead needs to be run from a regular `Python` script. This makes the setup of the grid (grid parameters, inlist setup etc.) somewhat less easy. Therefore, we recommend using the [`option_explorer.ipynb`](docs/examples/scripts_and_notebooks/option_explorer.ipynb) and/or a Jupyter notebook for the setup of the grid, and copying this over to the `Python` script afterwards. 

Apart from this, the `mpi` backend is more tricky to set up, since the MPI processes (= "ranks") do not communicate automatically. Please follow the example [`run_a_grid_with_mpi4py.py`](docs/examples/scripts_and_notebooks/run_a_grid_with_mpi4py.py) closely when creating your own script to make sure the work is distributed and the information is shared correctly over the ranks.

### 2.3 Status and termination

A big part of running model grids is keeping track of how the computations are progressing and being able to intervene when necessary. The `status` module of `MOrPy` provides a function to print the status of any models that are (1) running and (2) registered in a designated database file (see "Tracking" in the examples mentioned above.) 

When you launched a model or a grid of models (see the difference between "launching" and "running" in the examples above), you can use the `print_grid_status()` function within the same `Python` session to consult the status of the grid.

However, if you ran a model or grid (in a blocking way) and/or the original `Python` session is inaccessible or closed, you can still consult the grid status from another `Python` session. To make life easier, the `cli` module defines a CLI command to print the status of the grid if you provide the location of the database file. Simply load the `morpy` environment (see "Installation Instructions" in [README.md](README.md)) and run

```
morpy_status <PATH_TO_PROJECT_DIR> <DATABASE_FILE_NAME> <REFRESH SECONDS>
```
(see the `run_grid_*` examples for more details.)

If, for some reason, you wish to terminate the grid computations prematurely and you still have access to the `Python` session that launched the computations, you can use the `grid_run` module's `stop_grid()` function. Similar to the status function, there also exists a CLI command to do so, namely

```
morpy_stop <PATH_TO_PROJECT_DIR> <DATABASE_FILE_NAME>
```

### 2.4 Timeout and restarts

Some systems, such as compute clusters, have limits on how long a certain computation can run (e.g. 24 hours). To avoid your grid or model computations to be cut off abruptly, the `MOrPy` run/launch functions have a `timeout` option, in which you can specify after how much time the process should terminate (in seconds.) At this point, models will be flagged as "restart" and will be restarted again from their latest `photos` file. Depending on the chosen `RestartPolicy`, defined in the `grid_run` module and used in the [`run_a_grid_with_mpi4py.py`](docs/examples/scripts_and_notebooks/run_a_grid_with_mpi4py.py) example, `MOrPy` can also pick up and restart models flagged as "failed". 

Specifically, when a model is terminated before any `photo` files are written and is labelled as a "restart", it will fail upon restart of the grid and be flagged as "failed". Upon the next restart, these failed models will be picked up again and restarted from the beginning (although this can be disabled with the `RestartPolicy`.)

To be able to use this functionality efficiently, the `photo_interval` option, part of the `controls` namelist should be sufficiently low (the exact number depends on the duration of a single timestep, the timeout duration, and your own preferences.) Low values for `photo_interval` can quickly lead to a lot of storage usage by each model's `photos` folder. These should either be cleaned out manually from time to time (e.g. once a model is complete) or via a subroutine in `run_star_extras.f`. The functionality to let `MOrPy` take care of `photo` file removal is planned but not yet implemented.

Lastly, the database file (called `runs.db` in the examples) does not only serve `morpy`'s tracking capabilities, it also acts as safeguard again accidental data deletion. Once a database file is initialised the contents of previously existing (i.e. registered in the database file) models cannot be overwritten when using the `prepare_grid()` function. If you want to reinitialise a project directory and its model (work) directories, you should manually remove the database file first, as the RuntimeError you get suggests. Note that this safeguard is only built into the `prepare_grid()` function (defined in the `project_setup` module), which uses the user-accessible `create_modeldir()` function. Know that if you choose to use the latter function yourself with `overwrite=True`, you might accidentally delete model output if you are not careful.

