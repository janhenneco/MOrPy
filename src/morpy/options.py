"""Data model and utilities for MESA defaults/inlist options.

This module defines the core in-memory representation of MESA namelist content:

- MesaOption: one option (name, default value, current value, description, namelist)
- DefaultsFile: all options parsed from one defaults file
- DefaultsOptions: version-aware collection of DefaultsFile objects
- Inlist: editable model inlist with validation, search, sync, and write support
- UnclassifiedNamelist: unknown namelist blocks preserved during parse/write

The design separates parsing from data manipulation:
parser.py creates these objects from files, while this module provides methods
to inspect, set, remove, compare, synchronize, and write options.

Version-aware behavior is built in (for example kap/eos and pgbinary support),
so option availability and output format follow the configured MESA version.
"""

from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path
import warnings
from collections.abc import Mapping, Iterable
from copy import deepcopy
from .config import MesaVersion, MesaConfig, require_active_config
from .utils import (
    inlist_values_match,
    python_value_to_inlist_value, 
    fortran_value_to_python_value
)


# Custom type for the MESA defaults namelist files
MesaNameList = Literal['controls', 'star_job', 'binary_controls', 'binary_job', 'kap', 'eos', 'pgstar', 'pgbinary']

# MESA version at which separate pgbinary defaults inlist and the pgbinary block become a thing
PGBINARY_SPLIT_VERSION = MesaVersion.parse_mesa_version("r23.05.1")

# MESA version at which kap and eos get separate defaults namelists
KAP_EOS_SPLIT_VERSION = MesaVersion.parse_mesa_version("r15140")


def _canonical_option_name(requested_name: str, template_name: str) -> str:
    """Return a recognized option name using its defaults-file spelling."""
    canonical_base = template_name.partition("(")[0].strip()
    requested_name = requested_name.strip()
    index_start = requested_name.find("(")
    if index_start == -1:
        return canonical_base
    return canonical_base + requested_name[index_start:].strip()

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

   def to_python_value(self, use_current: bool = True) -> bool | int | float | str:
        if use_current:
            if self.current_value is None:
                warnings.warn("use_current = True (default) but self.current_value is None. Passed self.default_option instead.", UserWarning)
                raw = self.default_option
            else:
                raw = self.current_value
        else:
            raw = self.default_option
        return fortran_value_to_python_value(raw)


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

    def option_names(self, pattern: str | None = None) -> list[str]:
        """Function to list all MesaOptions in the DefaultsFile that have certain
            pattern in their name.

        Args:
            pattern: string containing the pattern to look for. If None, all
                names in the DefaultsFile will be returned.
        Returns:
            list of strings with the MesaOption names that match the pattern.
        """
        names = sorted(self.options.keys())
        if pattern is None:
            return names
        p = pattern.lower()
        return [n for n in names if p in n.lower()]

    def search(self, query: str, in_description: bool = True) -> list[MesaOption]:
        """Function to look for a pattern inside the names and descriptions of 
            the MesaOption objects in the DefaultsFile.
        
        Args:
            query: string with pattern to look for in the MesaOption names and descriptions.
            in_description: If True, look for pattern in descriptions, if False,
                only look for pattern in names.
        Returns:
            List of MesaOptions
        """
        q = query.lower()
        out: list[MesaOption] = []
        for opt in self.options.values():
            hit_name = q in opt.name.lower()
            hit_desc = in_description and q in opt.description.lower()
            if hit_name or hit_desc:
                out.append(opt)
        return sorted(out, key=lambda o: o.name.lower())

    def describe(self, name: str) -> str:
        """Function to print out the default & current value, and the description of a
            MesaOption with the given name.
        
        Args:
            name: string containing the name of the MesaOption
        Returns:
            Structured string with information about the MesaOption corresponding to
            the provided name.
        """
        opt = self.options[name]
        current = f"\ncurrent: {opt.current_value}" if opt.current_value is not None else ""
        return (
            f"{opt.name}\n"
            f"namelist: {opt.namelist}\n"
            f"default: {opt.default_option}"
            f"{current}\n"
            f"description:\n{opt.description}"
        )

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
    
    def iter_files(self) -> list[DefaultsFile]:
        files: list[DefaultsFile] = []
        for name in (
            "controls",
            "star_job",
            "binary_controls",
            "binary_job",
            "kap",
            "eos",
            "pgstar",
            "pgbinary",
        ):
            defaults_file = getattr(self, name)
            if defaults_file is not None:
                files.append(defaults_file)
        return files
    
    def _base_option_name(self, option_name: str) -> str:
        return option_name.partition("(")[0].strip()

    def _resolve_option_in_defaults_file(
        self,
        *,
        name: str,
        defaults_file: DefaultsFile,
    ) -> MesaOption | None:
        # Exact match first, ignoring Fortran identifier case.
        for option_name, option in defaults_file.options.items():
            if name.casefold() == option_name.casefold():
                return option

        base = self._base_option_name(name).casefold()
        matches = [
            opt
            for opt in defaults_file.options.values()
            if self._base_option_name(opt.name).casefold() == base
        ]

        if not matches:
            return None

        # Prefer canonical array template.
        for opt in matches:
            if "(:)" in opt.name:
                return opt

        # Indexed array request (e.g. foo(7)) with only numbered defaults.
        if "(" in name and ")" in name:
            return matches[0]

        # Scalar ambiguity should still fail loudly.
        if len(matches) > 1:
            matching_names = ", ".join(sorted(opt.name for opt in matches))
            raise ValueError(
                f"Ambiguous option '{name}' in namelist '{defaults_file.namelist}': "
                f"{matching_names}"
            )

        return matches[0]

    def find_option(
        self,
        name: str,
        namelist: MesaNameList | None = None,
    ) -> MesaOption:
        if namelist is not None:
            defaults_file = self[namelist]
            if defaults_file is None:
                raise ValueError(
                    f"Namelist '{namelist}' is not available for MESA version {self.mesa_version.version_name}."
                )

            resolved = self._resolve_option_in_defaults_file(
                name=name,
                defaults_file=defaults_file,
            )
            if resolved is None:
                raise KeyError(
                    f"Option '{name}' was not found in namelist '{namelist}'."
                )
            return resolved

        matches: list[MesaOption] = []
        for defaults_file in self.iter_files():
            resolved = self._resolve_option_in_defaults_file(
                name=name,
                defaults_file=defaults_file,
            )
            if resolved is not None:
                matches.append(resolved)

        if not matches:
            raise KeyError(f"Option '{name}' was not found in the loaded defaults.")

        unique_namelists = sorted({opt.namelist for opt in matches})
        if len(unique_namelists) > 1:
            matching_namelists = ", ".join(unique_namelists)
            raise ValueError(
                f"Option '{name}' exists in multiple namelists: {matching_namelists}. "
                "Please specify namelist explicitly."
            )

        return matches[0]

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
        name: Name for this inlist object, which will be the filename when writing 
            out the Inlist object to a file.
        options: A dictionary containing the parsed contents (i.e. MesaOption objects) 
            of the inlist file at `source_path`
        mesa_version: The MESA version for which the inlist is parsed
        source_path: Path to the inlist file from which this object was parsed,
            None if this Inlist object was not initialised from a file.
        additional_options: UnclassifiedNamelist object
        comment_block: String containing any information about the inlist 
            to be placed at the top of the inlist file (text will be commented
            automatically upon write).
        empty_namelists: Known MESA namelist blocks that were present in the
            source inlist but contained no options.
        
    """
    name: str
    mesa_version: MesaVersion | None = None
    options: dict[str, MesaOption] = field(default_factory=dict)
    additional_options: list[UnclassifiedNamelist] = field(default_factory=list)
    empty_namelists: set[MesaNameList] = field(default_factory=set)
    comment_block: str | None = None
    source_path: Path | None = None

    def __post_init__(self) -> None:
        """Method looking for mesa_version from active MesaConfig if mesa_version is not specified.
        Since Inlist is a dataclass, the __post_init__ method is called automatically.
        """
        if self.mesa_version is None:
            self.mesa_version = require_active_config().mesa_version

    def _add_option(self, opt: MesaOption) -> None:
        """Method to add an option to the options attribute.

        Agrs:
            opt: MesaOption to be added
        Returns:
            None
        """
        if (
            opt.namelist in {"kap", "eos"}
            and self.mesa_version < KAP_EOS_SPLIT_VERSION
        ):
            raise ValueError(
                f"{opt.namelist} options are not supported for MESA version "
                f"{self.mesa_version}."
            )

        self.options[opt.name] = opt

    def _stored_option_name(self, name: str) -> str | None:
        """Find an inlist option key without regard to Fortran identifier case."""
        for stored_name in self.options:
            if stored_name.casefold() == name.casefold():
                return stored_name
        return None

    def _remove_option(self, option_name: str) -> bool:
        """Method to remove an option from the options attribute.

        Agrs:
            option_name: name of the MesaOption object to be removed from the 
                options attribute
        Returns:
            Boolean, True if removed, false if not present and, therefore, not removed
        """
        stored_name = self._stored_option_name(option_name)
        if stored_name is None:
            return False
        is_removed = self.options.pop(stored_name)
        return is_removed is not None
    
    @classmethod
    def empty(cls, name: str, mesa_version: MesaVersion | None = None,  source_path: Path | str | None = None) -> "Inlist":
        """Method to initiate and empty Inlist object which can be populated later.

        Args:
            name: Name for this inlist object, which will be the filename when writing 
                out the Inlist object to a file.
            mesa_version: MesaVersion of the Inlist object
            source_path: Optional Path to source file. Here for compatibility
                with the class interface, but only set by parser.parse_inlist()
        Returns:
            Inlist object
        """
        if source_path is not None:
            source_path = Path(source_path)
        return cls(name=name, source_path=source_path, mesa_version=mesa_version)

    def set_option(
        self,
        name: str,
        value: object,
        defaults: DefaultsOptions,
        namelist: MesaNameList | None = None,
    ) -> MesaOption:
        """Method to set a specific MesaOption for the Inlist object in question.

        Args:
            name: Name of the MesaOption. The method will check if this name is 
                part of any of the DefaultsFiles to ensure it is valid
            value: Desired value for the MesaOption
            defaults: DefaultsOptions object that holds all information about
                MESA defaults
            namelist: Optional attribute that specifies to which 
                MESA namelist (MesaNamelist type) the specified option belongs.
                Will be required for MesaOptions that occur in multiple namelists.
        Returns:
            MesaOption object that was set
        """

        # This method will verify whether the specified option is valid and return 
        # the MesaOption template if so
        template = defaults.find_option(name=name, namelist=namelist)

        canonical_name = _canonical_option_name(name, template.name)
        new_option = MesaOption(
            name=canonical_name,
            default_option=template.default_option,
            description=template.description,
            namelist=template.namelist,
            current_value=python_value_to_inlist_value(
                value,
                default_option=template.default_option,
            ),
        )

        self._add_option(new_option)
        return new_option
    
    def set_options(
        self,
        defaults: DefaultsOptions,
        *,
        options: dict[str, object] | None = None,
        controls: dict[str, object] | None = None,
        star_job: dict[str, object] | None = None,
        binary_controls: dict[str, object] | None = None,
        binary_job: dict[str, object] | None = None,
        kap: dict[str, object] | None = None,
        eos: dict[str, object] | None = None,
        pgstar: dict[str, object] | None = None,
        pgbinary: dict[str, object] | None = None,
    ) -> None:
        """Set many options at once, optionally grouped by namelist.

        Args:
            defaults: DefaultsOptions object with parsed MESA defaults.
            options: Mixed-namelist option dictionary. Use only when option
                names are unambiguous across namelists.
            controls: Option dictionary for controls namelist.
            star_job: Option dictionary for star_job namelist.
            binary_controls: Option dictionary for binary_controls namelist.
            binary_job: Option dictionary for binary_job namelist.
            kap: Option dictionary for kap namelist.
            eos: Option dictionary for eos namelist.
            pgstar: Option dictionary for pgstar namelist.
            pgbinary: Option dictionary for pgbinary namelist.
        """

        if options is not None:
            for name, value in options.items():
                self.set_option(name=name, value=value, defaults=defaults)

        named_groups: dict[MesaNameList, dict[str, object] | None] = {
            "controls": controls,
            "star_job": star_job,
            "binary_controls": binary_controls,
            "binary_job": binary_job,
            "kap": kap,
            "eos": eos,
            "pgstar": pgstar,
            "pgbinary": pgbinary,
        }

        for namelist, group in named_groups.items():
            if group is None:
                continue
            for name, value in group.items():
                self.set_option(
                    name=name,
                    value=value,
                    defaults=defaults,
                    namelist=namelist,
                )

    def remove_option(self, name: str) -> bool:
        """Public method to remove an option from the Inlist.

        Args:
            name: Name of the MesaOption to be removed.

        Returns:
            True if an option was removed, False otherwise.
        """
        if not self._remove_option(name):
            warnings.warn(
                f"Option '{name}' is not present in this inlist; nothing was removed.",
                UserWarning,
                stacklevel=2,
            )
            return False
        return True
    
    def _option_snapshot(self, *, ignore_default_valued: bool = False) -> dict[str, tuple[MesaNameList, str]]:
        """Build a normalized option snapshot for semantic comparisons between inlists.
        Args:
            ignore_default_valued: True if options that have the default value should not be 
                included in the comparison.
        Returns:
            Dictionary with MesaOption.name as key and a tuple containing MesaOption.namelist and MesaOption.value
        """
        snapshot: dict[str, tuple[MesaNameList, str]] = {}
        for name, opt in self.options.items():
            value = opt.current_value if opt.current_value is not None else opt.default_option

            # Semantic mode: omit options that are effectively at default.
            if (
                ignore_default_valued
                and opt.default_option.strip() != ""
                and inlist_values_match(value, opt.default_option)
            ):
                continue

            snapshot[name] = (opt.namelist, value)
        return snapshot


    def _options_equal(self, other: "Inlist", *, ignore_default_valued: bool = False) -> bool:
        """Function to see if two inlists have effectively the same options.
        
        Args:
            other: Inlist object to compare to.
        Returns:
            True if two inlists are effectively the same, False if not.
        """
        mine = self._option_snapshot(ignore_default_valued=ignore_default_valued)
        theirs = other._option_snapshot(ignore_default_valued=ignore_default_valued)

        if mine.keys() != theirs.keys():
            return False

        for name, (my_namelist, my_value) in mine.items():
            other_namelist, other_value = theirs[name]
            if my_namelist != other_namelist:
                return False
            if not inlist_values_match(my_value, other_value):
                return False

        return True

    def sync_with_source(self, 
                         default_options: DefaultsOptions,
                         config: MesaConfig | None = None, 
                         *, 
                         on_difference: Literal["decouple", "update"] = "decouple", 
                         compare_additional_options: bool = True, 
                         ignore_default_valued_options: bool = True
                         ) -> bool:
        """Compare this object with the current contents of source_path.

        Args:
            config: MesaConfig
            default_options: DefaultsOptions

        Returns:
            True if a difference was detected, False otherwise.
        Behaviour on difference:
            - decouple: set source_path to None
            - update: replace options/additional_options/mesa_version from disk
        """
        if self.source_path is None:
            return False
        
        if config is None:
            config = require_active_config()

        # Local import avoids module-level circular import:
        # parser imports Inlist from options.
        from .parser import parse_inlist

        parsed = parse_inlist(
            source_path=self.source_path,
            config=config,
            default_options=default_options,
        )

        changed = not self._options_equal(
            parsed,
            ignore_default_valued=ignore_default_valued_options,
        )

        if compare_additional_options and not changed:
            mine_extra = [(b.name, b.body) for b in self.additional_options]
            parsed_extra = [(b.name, b.body) for b in parsed.additional_options]
            changed = mine_extra != parsed_extra
            
        empty_drift = self.empty_namelists != parsed.empty_namelists
        if not changed and empty_drift:
            warnings.warn(
                "Only empty known namelist blocks changed on disk; refreshing from source.",
                UserWarning,
                stacklevel=2,
            )
            self.options = parsed.options
            self.additional_options = parsed.additional_options
            self.empty_namelists = set(parsed.empty_namelists)
            self.mesa_version = parsed.mesa_version
            return True

        if not changed:
            changed = empty_drift

        if not changed:
            return False

        if on_difference == "decouple":
            self.source_path = None
        elif on_difference == "update":
            self.options = parsed.options
            self.additional_options = parsed.additional_options
            self.empty_namelists = set(parsed.empty_namelists)
            self.mesa_version = parsed.mesa_version
            # keep existing self.name unchanged intentionally
        else:
            raise ValueError("on_difference must be 'decouple' or 'update'.")

        return True

    def write(self, output_path: Path | str, include_additional_options: bool = False, include_comment_block: bool = True) -> Path:
        """Method to write the contents of an Inlist object to an inlist file that
            can be read by MESA.

        Args:
            output_path: Path object for the location and filename of the inlist file.
            include_additional_options: Optional argument to write any additional
                UnclassifiedNamelist objects to the inlist. Default = False
            include_comment_block: If True, the Inlist.comment_block is
                placed at the top of the inlist file.
        Returns: 
            Path object pointing to location of written inlist file.
        Raises: 
            ValueError when no output_path is specified
        """

        if output_path is None:
            raise ValueError("Output path to write the inlist file to is required.")
        output_path = Path(output_path)
        target = output_path / self.name

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

        # If star_job is present, kap and eos blocks are required (even if empty),
        # but only for newer MESA versions.
        required_empty_blocks: set[MesaNameList] = set()
        if has_star_job:
            required_empty_blocks.add("pgstar")
            if self.mesa_version >= KAP_EOS_SPLIT_VERSION:
                required_empty_blocks.update({"kap", "eos"})
        if has_binary_job:
            required_empty_blocks.add("pgbinary")

        # Preserve known empty blocks from parsed source inlists.
        explicit_empty_blocks: set[MesaNameList] = set(self.empty_namelists)

        lines: list[str] = []

        if include_comment_block and self.comment_block is not None:
            comment_lines = self.comment_block.splitlines()
            lines.extend(f"! {line}" for line in comment_lines)
            lines.append("")
        

        for block in block_order:
            # In binary mode, do not write kap/eos blocks at all.
            if has_binary_job and block in {"kap", "eos"}:
                continue

            opts = grouped[block]
            must_emit = (block in required_empty_blocks) or (block in explicit_empty_blocks)
            if not opts and not must_emit:
                continue

            out_block = output_block_name(block)
            lines.append(f"&{out_block}")

            if opts:
                for opt in opts:
                    raw_value = opt.current_value if opt.current_value is not None else opt.default_option
                    if raw_value is None or raw_value.strip() == "":
                        continue

                    out_value = python_value_to_inlist_value(raw_value,default_option=opt.default_option)
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
    
    def option_names(self, pattern: str | None = None) -> list[str]:
        """Function to list all MesaOptions in the Inlist that have certain
            pattern in their name.

        Args:
            pattern: string containing the pattern to look for. If None, all
                names in the Inlist will be returned.
        Returns:
            list of strings with the MesaOption names that match the pattern.
        """
        names = sorted(self.options.keys())
        if pattern is None:
            return names
        p = pattern.lower()
        return [n for n in names if p in n.lower()]

    def search(self, query: str, in_description: bool = True) -> list[MesaOption]:
        """Function to look for a pattern inside the names and descriptions of 
            the MesaOption objects in the Inlist.
        
        Args:
            query: string with pattern to look for in the MesaOption names and descriptions.
            in_description: If True, look for pattern in descriptions, if False,
                only look for pattern in names.
        Returns:
            List of MesaOptions
        """
        q = query.lower()
        out: list[MesaOption] = []
        for opt in self.options.values():
            hit_name = q in opt.name.lower()
            hit_desc = in_description and q in opt.description.lower()
            if hit_name or hit_desc:
                out.append(opt)
        return sorted(out, key=lambda o: o.name.lower())

    def describe(self, name: str) -> str:
        """Function to print out the default & current value, and the description of a
            MesaOption with the given name.
        
        Args:
            name: string containing the name of the MesaOption
        Returns:
            Structured string with information about the MesaOption corresponding to
            the provided name.
        """
        stored_name = self._stored_option_name(name)
        if stored_name is None:
            raise KeyError(f"Option '{name}' is not present in this inlist.")
        opt = self.options[stored_name]
        current = f"\ncurrent: {opt.current_value}" if opt.current_value is not None else ""
        return (
            f"{opt.name}\n"
            f"namelist: {opt.namelist}\n"
            f"default: {opt.default_option}"
            f"{current}\n"
            f"description:\n{opt.description}"
        )
    
    def get_python_value(self, name: str, use_current: bool = True) -> bool | int | float | str:
        stored_name = self._stored_option_name(name)
        if stored_name is None:
            raise KeyError(f"Option '{name}' is not present in this inlist.")
        return self.options[stored_name].to_python_value(use_current=use_current)
    
    def copy(
        self,
        name: str | None = None,
        *,
        deep_copy: bool = True,
    ) -> "Inlist":
        new_name = name or self.name

        copied = Inlist.empty(
            name=new_name,
            mesa_version=self.mesa_version,
            source_path=self.source_path,
        )

        if deep_copy:
            copied.options = deepcopy(self.options)
            copied.additional_options = deepcopy(self.additional_options)
            copied.empty_namelists = set(self.empty_namelists)
        else:
            copied.options = dict(self.options)
            copied.additional_options = list(self.additional_options)
            copied.empty_namelists = set(self.empty_namelists)

        return copied

def preview(options: list[MesaOption] | dict[str, MesaOption] | Iterable[MesaOption],
            max_desc: int = 100, 
            prefer_pandas: bool = True):
    """Method to display a table of MesaOption objects.
        Uses a pandas DataFrame if pandas is available (optional dependency),
        uses plain text output if not.
    
    Args:
        options: MesaOption collection. Accepted:
            - list[MesaOption]
            - dict[str, MesaOption] (e.g. DefaultsFile.options, Inlist.options)
            - any iterable of MesaOption
        max_desc: Maxiumum number of charachters used to print the 
            MesaOption.description attribute
        prefer_pandas: Use pandas if available. Default = True
    Returns:
        None

    """
    # Preview MesaOptions as pandas DataFrame (if available) or text table.
    if isinstance(options, Mapping):
        option_items = list(options.values())
    else:
        option_items = list(options)

    rows: list[dict[str, str]] = []
    for o in option_items:
        desc = " ".join(o.description.split())
        if len(desc) > max_desc:
            desc = desc[: max_desc - 3] + "..."
        rows.append(
            {
                "namelist": o.namelist,
                "name": o.name,
                "default": o.default_option,
                "current": "" if o.current_value is None else o.current_value,
                "description": desc,
            }
        )

    if prefer_pandas:
        try:
            import pandas as pd
            return pd.DataFrame(
                rows,
                columns=["namelist", "name", "default", "current", "description"],
            )
        except ImportError:
            pass

    # Plain-text fallback
    if not rows:
        return "(no options)"

    headers = ["namelist", "name", "default", "current", "description"]
    widths = {h: len(h) for h in headers}
    for r in rows:
        for h in headers:
            widths[h] = min(max(widths[h], len(str(r[h]))), 60)

    def fmt_row(r: dict[str, str]) -> str:
        return " | ".join(str(r[h]).ljust(widths[h]) for h in headers)

    sep = "-+-".join("-" * widths[h] for h in headers)
    out = [fmt_row({h: h for h in headers}), sep]
    out.extend(fmt_row(r) for r in rows)
    return "\n".join(out)

# TODO: would be cool to create a function that automatically adds the cache directory options to all
# star_job blocks and creates the cache directory structure if not present. 
# The cache directory should probably created at the time of config if not present and optional, because not every 
# project needs its own caches. 