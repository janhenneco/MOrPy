# MESA Orchestrator in Python (MOrPy)

<div align="center">
  <img src="docs/images/MOrPy_logo.svg" alt="MOrPy Diagram" width="500" style="background-color: white; padding: 20px; border-radius: 6px;" />
</div>

The MESA Orchestrator in Python (MOrPy) software is designed to serve as an interface between the [Modules for Experiments in Stellar Astrophysics (`MESA`)](https://mesastar.org/) code and `Python`. It consists of a `Python` package (`morpy`) that allows the user to create ready-to-run `MESA` work directories, load, construct, edit, and inspect inlists, and consult and search `MESA` "settings" (i.e. default options) using `Python`. Moreover, it allows the user to compile and run `MESA`, construct model grids, run these grids, and consult their status, all from within a `Python` session or `Jupyter Notebook`. The code uses `Python`'s built-in `concurrent.futures` or `mpi4py` (for multi-node setups) for parallel computations.

This software is currently still a work in progress and any feedback or feature requests are more than welcome via the GitHub Issues tool.

**DISCLAIMER:** `MOrPy` is not intended to be used as a replacement for learning how to properly and responsibly use `MESA`. The user is expected to know how to [use `MESA`](https://docs.mesastar.org/en/26.4.1/using_mesa.html); how inlists work and are structured, how a work directory is structured, how to test convergence, and generally what the [best practices](https://docs.mesastar.org/en/26.4.1/using_mesa/best_practices.html) are. `MOrPy` is merely a tool that works as an interface with `Python` and thus facilitates and smooths out the process of setting up and running `MESA` computations, especially for model grids. 

## Installation Instructions

### 1. Requirements

Core:
- Operating system: Linux or macOS
- Python version: `Python 3.11.x`
- Environment managers: `conda` or `Python` `venv`
- [Modules for Experiments in Stellar Astrophysics (MESA)](https://mesastar.org/)<sup>*</sup>

(*) `MOrPy` is version aware and should work with `MESA` versions `>=r10398` (feel free to test it for older versions). Found some incompatibilities with a certain `MESA` version? Please report it via GitHub [Issues](https://github.com/janhenneco/MOrPy/issues)!

Optional: 
- `pandas>=2.0` (preview)
- `mpi4py>=4.0` (mpi)
- `sphinx>=7.0`, `furo>=2024.0.0` and `myst-parser>=2.0` (docs)
- `ipykernel` (ipykernel)
- `jupyter` (jupyter)
- For MPI: OpenMPI/MPICH

### 2. Download the code

Clone or download the repository, if necessary extract it, and move into the root directory of the repository.

### 3. Installation

#### 3.1 Basic Installation

1. Create a `Python` environment:

conda:
```
conda create -n morpy python=3.11
conda activate morpy
```

venv:
```
python3.11 -m venv .venv
source .venv/bin/activate
```

2. Install the `morpy` package:

```
python -m pip install --upgrade pip setuptools wheel
python -m pip install .
```

or install with all optional dependencies:

```
python -m pip install ".[preview,mpi,docs,notebooks]"
```

#### 3.2 MPI-aware installation (for HPC users)

In some cases, the installed `mpi4py` package and the `MPI` installation are not compatible by default. If this is the case for you, follow these instructions:

1. **Verify the MPI installation**

Verify if and what version of MPI is installed and loaded by using:

```
ompi_info
```

Depending on your system/cluster, the MPI installation will have to be loaded via environment modules. If unsure, please consult your system/cluster's documentation or contact your system administrator. 

2. **Find MPI location**

Next, you want to see where MPI lives. You can do this by running:

```
which mpicc
```

Ideally, this outputs something like `/usr/bin/mpicc`. Take note of this location for later. 

3. **Install `mpi4py` compiled against your MPI version**

With your desired conda/venv environment activated, install `mpi4py` using `pip` while specifying the location of your MPI installation:

```
MPICC=/PATH_TO_MPI_BINARY pip install --no-binary=mpi4py mpi4py
```
Here, `/PATH_TO_MPI_BINARY` should be the path to the MPI binary, e.g. `/usr/bin/mpicc`.
The `no-binary` option prevents `pip` from installing a pre-built version of `mpi4py` and compiles it against your desired MPI installation.

4. **Install `morpy` without reinstalling `mpi4py`**
```
python -m pip install -e ".[preview,docs,notebooks]"
``` 

### 4. Verify installation

To verify if `morpy` was installed successfully, just run

```
python -c "import morpy; print('MOrPy installed successfully')"
```

### 5. Install `ipykernel` (OPTIONAL)

If you are already running a Jupyter server and want to be able to use `morpy` environment without installing Jupyter in said environment and running an additional server, you can avoid this by creating a kernel for `morpy`. Installing `ipykernel` can be achieved by installing the optional `ipykernel` dependency (see instructions above).

With `ipykernel` installed, create the kernel and give it a recognisable name (in this case "MOrPy")

```
python -m ipykernel install --user --name morpy --display-name "MOrPy"
```

After that, just restart your pre-existing Jupyter server if it was already running. When you want to execute a Jupyter notebook on this server, you just have to select the `MOrPy` kernel, which should be in your kernel list now.

## Getting started

Check out the [Getting Started guide](GETTING_STARTED.md).

## Documentation

Feel free to check out the documentation here: [index.html](docs/build/html/index.html)


More comprehensive documentation, please use the provided [examples](docs/examples/).


## MOrPy Modules

The `morpy` package's main modules are:

- `config.py`: Configuration and environment utilities.

- `parser.py`: Parsing utilities for MESA defaults files and inlists.

- `options.py`: Data model and utilities for MESA defaults/inlist options.

- `utils.py`: Low-level utility helpers for MESA value normalisation and conversion.

- `model.py`: Model objects and lifecycle state for individual MESA runs.

- `work_setup.py`: Work-directory setup, synchronisation, and export utilities for models.

- `project_setup.py`: Project-directory creation utilities for MESA runs.

- `compile.py`: Function to compile the MESA executables.

- `run.py`: Single-model run orchestration for foreground and background execution.

- `run_types.py`: Shared runtime data types for model execution workflows.

- `errors.py`: Shared exception hierarchy for run, orchestration, and persistence layers.

- `grid_run.py`: Grid orchestration classes and objects for multi-model execution.

- `repository.py`: Persistence handling, fucntions related to database files.

- `status.py`: Model and grid status view functions.

- `cli.py`: CLI functions for status and grid termination.

- `log.py`: Basic setup for log messages. Also implements the ability do disable them.

## Issues

Please use the repository's [Issues](https://github.com/janhenneco/MOrPy/issues) functionality to ask questions, report bugs, or make feature requests.

## Acknowledgements
The general idea and many of the concepts of a `Python`-based tool to run grids of `MESA` models using the `mpi4py` stem from the `mesa-runner` in-house code that was developed at the Heidelberg Institute for Theoretical Physics (HITS, Germany) by Fabian Schneider and later maintained by Fabian Schneider and myself. 

A very big thank you to all the people who tested `MOrPy` so far and provided valuable feedback: Eva Laplace, Inmaculada Moyano, Sofia Mesini, Vazsony Varga, Lorens Niehof, Flore Poelmans, and Zihan Wang. 

I gratefully acknowledge UK Research and Innovation (UKRI) in the form of a Frontier Research grant under the UK government’s ERC Horizon Europe funding guarantee (SYMPHONY; PI Bowman; grant number: EP/Y031059/1).


## Generative AI Disclosure
Some code was drafted using generative AI tools. All prompts were provided by the author, and all AI-generated content was reviewed and approved by the author before being included. No generative AI was used without human review. `MOrPy`'s concept, design, and artwork are entirely the author's own work.


