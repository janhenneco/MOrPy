from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path
from .config import MesaVersion

# Custom type for the MESA defaults namelist files
MesaNameList = Literal['controls', 'star_job', 'binary_controls', 'binary_job', 'kap', 'eos', 'pgstar', 'pgbinary']

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
   current_value: str | None = field(default=None)


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
    mesa_version: MesaVersion
    options: dict[str, MesaOption] = field(default_factory=dict)

@dataclass
class DefaultsOptions:
    """Class that holds all DefaultsFiles.

    Attributes:
        mesa_version: The MESA version for which the default options are parsed
        controls: the `controls` DefaultsFile
        star_job: the `star_job` DefaultsFile
        kap: the `kap` DefaultsFile
        eos: the `eos` DefaultsFile
        binary_controls: the `binary_controls` DefaultsFile
        binary_job: the `binary_job` DefaultsFile
        pgstar: the `pgstar` DefaultsFile
        pgbinary: the `pgbinary` DefaultsFile
        
    """
    mesa_version: MesaVersion
    controls: DefaultsFile
    star_job: DefaultsFile
    binary_controls: DefaultsFile
    binary_job: DefaultsFile
    pgstar: DefaultsFile
    kap: DefaultsFile | None = None
    eos: DefaultsFile | None = None
    pgbinary: DefaultsFile | None = None

    # These are two functions allowing the MesaNameList types to be linked to the attributes of this class.
    def get_file(self, namelist_type: MesaNameList) -> DefaultsFile:
        return getattr(self, namelist_type)

    def __getitem__(self, namelist_type: MesaNameList) -> DefaultsFile:
        return self.get_file(namelist_type)
    
@dataclass
class Inlist:
    """Class for a MESA inlist (Fortran namelist) file.

    Attributes:
        source_path: Path to the defaults file from which this object was parsed.
        options: A dictionary containing the parsed contents (i.e. MesaOption objects) 
            of the inlist file at `source_path`
        mesa_version: The MESA version for which the inlist is parsed
        
    """
    source_path: Path
    mesa_version: MesaVersion
    options: dict[str, MesaOption] = field(default_factory=dict)