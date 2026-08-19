'''
In this example, we will see how to use the morpy package to prepare and run a grid of MESA models with Python. Contrary to the example in `run_a_grid.ipynb`,
we will use MPI via `mpi4py` to run the grid, which is great for multi-node computations. To use MPI, we need to make use of a `Python` (`.py`) script
instead of a Jupyter Notebook and the grid will be launched by calling this script in a specific way (see later).

Since we don't have any interactive capabilities in a `.py` script, you can use the `option_explorer.ipynb` script provided here.
Alternatively, you can also consider setting up the grid in a notebooks just like in `run_a_grid.ipynb` and copy-pasting the 
setup code into a `.py` script once you're satisfied.

The script contains a "if rank == 0" conditional. Although not super
elegant, this is required to make sure the grid setup and registration
of the models in the database is not repeated by every rank (worker).
'''

### 1. IMPORTS ###
import morpy as mp
import numpy as np
from pathlib import Path
from mpi4py import MPI

# MPI specific setup:
comm = MPI.COMM_WORLD
rank = comm.Get_rank()

### 2.1 GENERAL SETTINGS ###

# Adjust these paths to match your local desired MESA installation.
MESA_DIR = Path('/Users/janhenneco/software/mesa/mesa-r24.08.1')
MESASDK_ROOT = Path('/Applications/mesasdk-25.12.1/')
OMP_THREADS  = 1 # Number of threads used per MESA model. Can be specified on a model-per-model basis when running/launching the models.
MESA_VERSION = 'r24.08.1'

### 2.2 USER SETTINGS ###
# RESTART? --   set this to True of you want to restart earlier computations.
#               this will make sure noring is overwritten!
RESTART = True
DB_NAME = 'runs.db'

# Resume (restart) policy
resume_policy = mp.ResumePolicy(
    enabled=True,                 # turn resume logic on/off
    match_policy="id_or_path",    # "id_only" or "id_or_path" (fallback match by model_path)
    skip_completed=True,          # don't rerun models already marked "completed"
    failed_policy="rerun",        # "rerun" or "skip" for models that ended "failed"
    cancelled_policy="rerun",     # "rerun" or "skip" for models that ended "cancelled"
    hydrate_timestamps=True,      # copy started_at/updated_at/finished_at from DB into Model
)

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
inlist1.set_option(name='xa_central_lower_limit_species(1)', value='h1', namelist='controls', defaults=def_opts)
inlist1.set_option(name='xa_central_lower_limit(1)', value=1e-6, namelist='controls', defaults=def_opts)
inlist2.set_option(name='xa_central_lower_limit_species(1)', value='h1', namelist='controls', defaults=def_opts)
inlist2.set_option(name='xa_central_lower_limit(1)', value=1e-6, namelist='controls', defaults=def_opts)

### 6. CONSTRUCT AND SET UP A GRID ###

# Everything in this block should only be executed once
if rank == 0:

    # Create a project directory
    project_dir = Path('/Users/janhenneco/GitHub/MOrPy/docs/examples/example_output/run_a_grid_with_mpi4py/project_dir')
    project_dir = mp.create_projectdir(project_dir, mode='binary', config=mconf)


    primary_masses = np.arange(10, 22, 1)
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

    grid_list = []
    for key in model_dict.keys():
        model = model_dict[key]
        grid_list.append(mp.GridRunItem(model=model))
           
    tracker0 = mp.prepare_grid(project_dir, grid_list, db_name=DB_NAME, restart=RESTART, config=mconf)

### 7. COMPILE MESA ###

    compile_result = mp.compile_project(projectdir_path=project_dir, mode='binary')
    print(compile_result.pretty(2000))


else:
    project_dir = None
    grid_list = None

# Now we share all the required objects with all ranks
project_dir = comm.bcast(project_dir, root=0)
grid_list = comm.bcast(grid_list, root=0)

# Here we let each rank connect to the prebuilt and fully populated DB file
tracker = mp.Tracker.create(db_path=project_dir / DB_NAME)

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

### 8. SETTING UP GRID RUN FUNCTION

grid_handle = mp.run_grid(grid_list,
                            backend='mpi',
                            sync_before_run=True,
                            default_options=def_opts,
                            config=mconf,
                            capture_output=True,
                            tracker=tracker,
                            command_name='rn', timeout=300, resume_policy=resume_policy)

if rank == 0:
    print(grid_handle)

### 9. RUN THE GRID ###

'''
The last thing we need to do now is run the grid using a specific command, in which we'll
also specify the number of models we want to run at the same time (equivalent of `max_workers`
in the `run/launch_grid` functions).

The command is the following:

```
mpirun -n N python run_a_grid_with_mpi4py.py
```

where N = the number of models to run in parallel
'''

### 10. TRACK GRID STATUS OR STOP GRID

'''
To make life easier, there are two CLI function available to see the live status or stop the grid.
They need to be called from an active `morpy` environment and you need to know the location of the 
project directory and the name of the database file.

```
morpy_status <PATH_TO_PROJECT_DIR> <DATABASE_FILE_NAME> <REFRESH SECONDS>
```

```
morpy_stop <PATH_TO_PROJECT_DIR> <DATABASE_FILE_NAME>
```
'''