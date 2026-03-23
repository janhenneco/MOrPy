from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path

"""Custom type for the MESA defaults namelist files
"""
MesaNameList = Literal['controls', 'star_job', 'binary_controls', 'binary_job', 'kap', 'eos']

@dataclass
class ParserConfig:
    """Holds the configuration for the parser module.

    Attributes:
        mesa_version: The MESA version for which the default options are parsed
        mesa_dir: Optional path to the MESA source directory. If None, the parser should
            auto-detect it from the environment variables.
    """
    mesa_version: str
    mesa_dir: Path | None = None

@dataclass
class MesaOption:
   """Represents a single MESA inlist option parsed from a defaults file.

    Attributes:
        name: The option name as it appears in the MESA defaults file (e.g. `initial_mass`).
        default_option: The raw default value string as defined in the defaults
            file, preserving Fortran notation (e.g. `1d0`).
        description: The description comment from the defaults file (`!` lines).
        namelist: The type of the defaults file this option belongs to (e.g. controls.defaults)
    """
   name: str
   default_option: str
   description: str
   namelist: MesaNameList

@dataclass
class DefaultsFile:
    """Class for a MESA defaults file.

    Attributes:
        namelist: The type of default namelist file this instance belongs to
        source_path: Path to the defaults file from which this object was parsed.
        options: A dictionary containing the parsed contents (i.e. MesaOption objects) 
            of the namelist file at `source_path`
        mesa_version: The MESA version for which the default options are parsed
        
    """
    namelist: MesaNameList
    source_path: Path
    options: dict[str, MesaOption] = field(default_factory=dict)
    mesa_version: str

def parse_defaults_file(namelist: MesaNameList, source_path: Path, config: ParserConfig) -> DefaultsFile:
    df = DefaultsFile(namelist = namelist, 
                      source_path = source_path, 
                      mesa_version = config.mesa_version)
    


    return df




