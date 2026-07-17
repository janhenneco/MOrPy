import morpy as mrun
from pathlib import Path
from tempfile import TemporaryDirectory

version_name = 'r24.08.1'
defaults_type = 'star_job'
test_data_dir_general = Path('/Users/janhenneco/GitHub/mesa-runner/tests/data_for_tests') 

with TemporaryDirectory() as tmp:
    mesa_dir = Path(tmp) / version_name
    mesa_dir.mkdir(parents=True, exist_ok=True)

    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir, version_name=version_name)

    df = mrun.parse_defaults_file(
        source_path=test_data_dir_general / version_name / 'defaults' / f"{defaults_type}.defaults",
        namelist=defaults_type,
        config=config
    )

for key in df.options.keys():
    print(df.options[key].name)
    print(df.options[key].default_option)
    print(df.options[key].description)
    print(' ')
    print('=========================')
    print(' ') 
