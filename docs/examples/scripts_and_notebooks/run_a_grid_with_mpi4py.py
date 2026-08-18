'''
In this example, we will see how to use the morpy package to prepare and run a grid of MESA models with Python. Contrary to the example in `run_a_grid.ipynb`,
we will use MPI via `mpi4py` to run the grid, which is great for multi-node computations. To use MPI, we need to make use of a `Python` (`.py`) script
instead of a Jupyter Notebook and the grid will be launched by calling this script in a specific way (see later).

Since we don't have any interactive capabilities in a `.py` script, you can use the `option_explorer.ipynb` script provided here.
Alternatively, you can also consider setting up the grid in a notebooks just like in `run_a_grid.ipynb` and copy-pasting the 
setup code into a `.py` script once you're satisfied.

The script contains multiple "if rank == 0" conditionals. These are there
to ensure tha the enclosed code is only executed by the MPI communicator,
not by each MPi worker.
'''

### 1. IMPORTS ###
import morpy as mp
import numpy as np
from pathlib import Path
from mpi4py import MPI

# MPI specific setup:
comm = MPI.COMM_WORLD
rank = comm.Get_rank()

### 2. GENERAL SETTINGS ###

# Adjust these paths to match your local desired MESA installation.
MESA_DIR = Path('/stars/software/mesa/mesa-r23.05.1/')
MESASDK_ROOT = Path('/stars/software/mesasdk/24.7.1/')
OMP_THREADS  = 1 # Number of threads used per MESA model. Can be specified on a model-per-model basis when running/launching the models.
MESA_VERSION = 'r23.05.1'

### 3. SET UP MESA ENVIRONMENT AND PARSE DEFAULT OPTION FILES ###

mconf = mp.setup_mesa_env(mesa_dir=MESA_DIR, mesasdk_root=MESASDK_ROOT, omp_num_threads=OMP_THREADS, version_name=MESA_VERSION)
def_opts = mp.build_defaults_options_from_config(mconf)
if rank == 0:
    print('MESA version:', mconf.mesa_version.version_name)
    print('     - year:', mconf.mesa_version.year)
    print('     - month:', mconf.mesa_version.month)
    print('     - patch:', mconf.mesa_version.patch)
    print('     - scheme:', mconf.mesa_version.scheme)
    print('     - revision:', mconf.mesa_version.revision)


### 4. CREATE BASE INLISTS AND MODEL ###

base_model = mp.Model.empty(name='base')
mp.import_inlists_from_dir(model=base_model, source_dir=MESA_DIR / 'binary' / 'work', default_options=def_opts, config=mconf)

### 5. ADJUST BASE INLIST SETTINGS ###

inlist_project = base_model.inlists['inlist_project']

inlist_project.set_options(defaults=def_opts,
                           binary_controls={'max_tries_to_achieve': 100,
                                           'initial_period_in_days': 100,
                                           'mdot_scheme': 'Kolb'},
                           binary_job={'evolve_both_stars': True}
                          )
inlist1 = base_model.inlists['inlist1']
inlist2 = base_model.inlists['inlist2']

to_remove = [name for name, opt in inlist1.options.items() if opt.namelist == 'pgstar']
for name in to_remove:
    inlist1.remove_option(name)
inlist1.set_option(name='pgstar_flag', value=False, namelist='star_job', defaults=def_opts)
inlist1.set_option(name='profile_interval', value=500, namelist='controls', defaults=def_opts)
inlist2.set_option(name='profile_interval', value=500, namelist='controls', defaults=def_opts)

### 6. CONSTRUCT A GRID ###

# Create a project directory
project_dir = Path('/home/njh462/software/MOrPy/docs/examples/example_output/run_a_grid_with_mpi4py/project_dir')
if rank == 0:
    project_dir = mp.create_projectdir(project_dir, mode='binary', config=mconf)
comm.Barrier()

primary_masses = np.arange(10, 21, 1)
mass_ratios = np.arange(0.1, 1.0, 0.1)

name_template = 'mi%s_qi%s'
model_dict = {}

for mi in primary_masses:
    for qi in mass_ratios:
        name = name_template % (str(mi), str(round(qi, 2)).replace('.', 'p'))
        # print(name)
        this_model = base_model.copy(model_copy_name=name, deep_copy=True)
        this_model.inlists['inlist_project'].set_options(defaults=def_opts, 
                                                         binary_controls={'m1': mi, 'm2': mi*qi})
        model_dict[name] = this_model

# Create model directories for all models, add the models to GridRunItem wrappers and add those to a list
grid_list = []
for key in model_dict.keys():
    model = model_dict[key]
    grid_list.append(mp.GridRunItem(model=model))
    

if rank == 0:
    for item in grid_list:
        mp.create_modeldir(model=item.model, projectdir_path=project_dir, overwrite=True)
    print(f'{len(grid_list)} models prepared.')
    for item in grid_list:
        print(f'  {item.model.name}  --->  {item.model.model_path}')
comm.Barrier()

### 7. COMPILE MESA ###

if rank == 0:
    compile_result = mp.compile_project(projectdir_path=project_dir, mode='binary')
    print(compile_result.pretty(2000))
comm.Barrier()

### 8. ENABLE TRACKING FUNCTIONALIY ###

# Path to the SQLite database file that stores information about models (important for tracking).
DB_PATH = project_dir / 'runs.db'

if rank == 0:
    if DB_PATH.exists():
        DB_PATH.unlink()
    tracker = mp.Tracker.create(db_path=DB_PATH)
    models = [item.model for item in grid_list]
    tracker.repo.add_models_to_repo(models=models)
    print(DB_PATH)
comm.Barrier()

# Every rank (including rank 0) opens the now-existing database.
tracker = mp.Tracker.create(db_path=DB_PATH)

'''
At this point, let's check if the tracker works. Since we'll have to track the progress of the grid in another
Python session with the MPI backend anyway, let's try to get the grid status from an interactive Python session.

Load the `morpy` environment and run `ipython`. In there, run the following liens of code:

```
import morpy as mp

from pathlib import Path

project_dir = Path('/home/njh462/software/MOrPy/docs/examples/example_output/run_a_grid_with_mpi4py/project_dir')

DB_PATH = project_dir / 'runs.db'

tracker = mp.Tracker.create(db_path=DB_PATH)

mp.print_grid_status(tracker=tracker)
```

This should give teh follwoign result when the grid is not running yet:

Summary: total=99  completed=0  strict_resume=99  resume_with_retries=99  failed=0  cancelled=0

[2026-08-18 16:07:28 UTC+01:00]

MODEL       STATE  PID  RC
----------  -----  ---  --
mi10_qi0p1  draft         
mi10_qi0p2  draft         
mi10_qi0p3  draft         
mi10_qi0p4  draft         
mi10_qi0p5  draft         
... and so on ...

We can also let this status view update once every X seconds for real-time status reports:

```
mp.print_grid_status(tracker=tracker, refresh_seconds=5, clear_screen=true)
```

'''

### 9. SETTING UP GRID RUN FUNCTION

grid_handle = mp.run_grid(grid_list,
                            backend='mpi',
                            sync_before_run=True, # Sync any changes made to inlist files with Model objects in memory
                            default_options=def_opts,
                            config=mconf,
                            capture_output=True, # Store terminal output in individual models' RunResults
                            tracker=tracker,
                            command_name='rn')

print(grid_handle)

if rank == 0:
    print(grid_handle)
### 10. RUN THE GRID ###

'''
The last thing we need to do now is run the grid using a specific command, in which we'll
also specify the number of models we want to run at the same time (equivalent of `max_workers`
in the `run/launch_grid` functions).

The command is the following:

```
mpirun -n N python run_a_grid_with_mpi4py.py
```

where N = the number of models to be run in parallel + 1
'''


# print('--------- inlist_project ---------')
# to_print = mp.preview(model_dict['mi18_qi0p2'].inlists['inlist_project'].options)
# print(to_print, '\n')

# print('--------- inlist1 ---------')
# to_print = mp.preview(base_model.inlists['inlist1'].options)
# print(to_print, '\n')

# print('--------- inlist2 ---------')
# to_print = mp.preview(base_model.inlists['inlist2'].options)
# print(to_print, '\n')