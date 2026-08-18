### 1. IMPORTS ###
import morpy as mp
import numpy as np
from pathlib import Path

### 2. GENERAL SETTINGS ###

# Adjust these paths to match your local desired MESA installation.
MESA_DIR = Path('/stars/software/mesa/mesa-r23.05.1/')
MESASDK_ROOT = Path('/stars/software/mesasdk/24.7.1/')
OMP_THREADS  = 1 # Number of threads used per MESA model. Can be specified on a model-per-model basis when running/launching the models.
MESA_VERSION = 'r23.05.1'

### 3. SET UP MESA ENVIRONMENT AND PARSE DEFAULT OPTION FILES ###

mconf = mp.setup_mesa_env(mesa_dir=MESA_DIR, mesasdk_root=MESASDK_ROOT, omp_num_threads=OMP_THREADS, version_name=MESA_VERSION)
def_opts = mp.build_defaults_options_from_config(mconf)
print('MESA version:', mconf.mesa_version.version_name)
print('     - year:', mconf.mesa_version.year)
print('     - month:', mconf.mesa_version.month)
print('     - patch:', mconf.mesa_version.patch)
print('     - scheme:', mconf.mesa_version.scheme)
print('     - revision:', mconf.mesa_version.revision)


### 4. CREATE BASE INLISTS AND MODEL ###

base_model = mp.Model.empty(name='base')
mp.import_inlists_from_dir(model=base_model, source_dir=MESA_DIR / 'binary' / 'work', default_options=def_opts, config=mconf)

print(base_model)