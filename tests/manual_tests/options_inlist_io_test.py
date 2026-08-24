import morpy as mrun
from pathlib import Path
from tempfile import TemporaryDirectory

version_name = 'r12778'

test_data_dir_general = Path('/Users/janhenneco/GitHub/MOrPy/tests/data_for_tests')

with TemporaryDirectory() as tmp:
    mesa_dir = Path(tmp) / version_name
    mesa_dir.mkdir(parents=True, exist_ok=True)
    config = mrun.MesaConfig.setup(version_name=version_name, mesa_dir=mesa_dir)
    defaults = mrun.build_defaults_options(defaults_dir=test_data_dir_general / version_name / 'defaults', config=config)

    inlist = mrun.parse_inlist(source_path=test_data_dir_general / version_name / 'inlists' / 'inlist_massive_1', config=config, default_options=defaults)

    out_dir = Path(__file__).parent / "output_tests"
    out_dir.mkdir(parents=True, exist_ok=True)

    options = inlist.search('factor')

    view = mrun.preview(inlist.search('factor'))

    print(view.to_string(index=False))

    # print(mrun.preview(option))



    # new_inlist_path = inlist.write(out_dir / 'options_inlist_io_test', include_additional_options=True)

# print(new_inlist_path)
