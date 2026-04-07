from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path
from .config import MesaVersion
from .utils import inlist_values_match, normalize_inlist_value_for_output


# Custom type for the MESA defaults namelist files
MesaNameList = Literal['controls', 'star_job', 'binary_controls', 'binary_job', 'kap', 'eos', 'pgstar', 'pgbinary']

# MESA version at which separate pgbinary defaults inlist and the pgbinary block become a thing
PGBINARY_SPLIT_VERSION = MesaVersion.parse_mesa_version("r23.05.1")

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
    def get_file(self, namelist_type: MesaNameList) -> DefaultsFile | None:
        return getattr(self, namelist_type)

    def __getitem__(self, namelist_type: MesaNameList) -> DefaultsFile | None:
        return self.get_file(namelist_type)

@dataclass
class UnclassifiedNamelist:
    """ Class that holds (currently) unrecognised namelist blocks in a MESA inlist.

    Attributes:
        name: name of the unrecognised inlist block
        body: contents of the unrecognised inlist block 
    """
    name: str
    body: str

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
    additional_options: list[UnclassifiedNamelist] = field(default_factory=list)

    def _add_option(self, opt: MesaOption) -> None:
        self.options[opt.name] = opt
    
    def _remove_option(self, option_name: str) -> bool:
        is_removed = self.options.pop(option_name, None)
        return is_removed is not None
    
    def write(self, output_path: Path | None = None, include_additional_options: bool = False) -> Path:
        target = output_path or self.source_path

        def output_block_name(block: MesaNameList) -> str:
            if block == "pgbinary" and self.mesa_version < PGBINARY_SPLIT_VERSION:
                return "binary_pgstar"
            return block

        block_order: tuple[MesaNameList, ...] = (
            "star_job",
            "eos",
            "kap",
            "controls",
            "pgstar",
            "binary_job",
            "binary_controls",
            "pgbinary"  
        )

        grouped: dict[MesaNameList, list[MesaOption]] = {name: [] for name in block_order}
        for opt in self.options.values():
            grouped[opt.namelist].append(opt)

        has_star_job = len(grouped["star_job"]) > 0
        has_binary_job = len(grouped["binary_job"]) > 0
        has_kap_or_eos_options = len(grouped["kap"]) > 0 or len(grouped["eos"]) > 0

        # If binary_job is present, kap/eos options must not be present.
        if has_binary_job and has_kap_or_eos_options:
            raise ValueError("binary_job options present, so kap/eos options must not be present.")

        # Avoid ambiguous mixed star and binary mode in one inlist object.
        if has_star_job and has_binary_job:
            raise ValueError("Both star_job and binary_job options are present; cannot infer kap/eos policy.")

        # If star_job is present, kap and eos blocks are required (even if empty).
        required_empty_blocks: set[MesaNameList] = set()
        if has_star_job:
            required_empty_blocks.update({"kap", "eos", "pgstar"})
        if has_binary_job:
            required_empty_blocks.add("pgbinary")

        lines: list[str] = []

        for block in block_order:
            # In binary mode, do not write kap/eos blocks at all.
            if has_binary_job and block in {"kap", "eos"}:
                continue

            opts = grouped[block]
            must_emit = block in required_empty_blocks
            if not opts and not must_emit:
                continue

            out_block = output_block_name(block)
            lines.append(f"&{out_block}")

            if opts:
                for opt in opts:
                    raw_value = opt.current_value if opt.current_value is not None else opt.default_option
                    if raw_value is None or raw_value.strip() == "":
                        continue

                    out_value = normalize_inlist_value_for_output(raw_value)
                    is_default = inlist_values_match(raw_value, opt.default_option)
                    suffix = " ! DEFAULT" if is_default else ""
                    lines.append(f"   {opt.name} = {out_value}{suffix}")
            else:
                # readability spacer for intentionally empty required blocks
                lines.append("")

            lines.append(f"/ ! end of {out_block} namelist")
            lines.append("")
        
        if include_additional_options:
            for block in self.additional_options:
                lines.append(f"&{block.name}")
                if block.body:
                    lines.extend(block.body.splitlines())
                lines.append(f"/ ! end of {block.name} namelist")
                lines.append("")

        text = "\n".join(lines).rstrip() + "\n"
        target.write_text(text, encoding="utf-8")
        return target