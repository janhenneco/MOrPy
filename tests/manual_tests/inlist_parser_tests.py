from pathlib import Path
import mesa_runner as mr

inlist_path = Path("/Users/janhenneco/work/mesa/projects/project_Joey/base_mesadir/inlist")

config = mr.MesaConfig.setup(version_name='r24.08.1')

# 4) Parse inlist (DefaultsOptions will be auto-created)
inlist = mr.parse_inlist(source_path=inlist_path, config=config)

for key in inlist.options.keys():
    print(inlist.options[key].name)
    print(inlist.options[key].current_value)
    print(inlist.options[key].default_option)
    print(inlist.options[key].description)
    print(inlist.options[key].namelist)
    print(' ')
    print('=========================')
    print(' ') 