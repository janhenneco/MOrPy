from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path
from .config import MesaVersion
from .utils import (
    inlist_values_match,
    normalize_inlist_value_for_output,
    python_value_to_inlist_value, 
    fortran_value_to_python_value
)


# Custom type for the MESA defaults namelist files
MesaNameList = Literal['controls', 'star_job', 'binary_controls', 'binary_job', 'kap', 'eos', 'pgstar', 'pgbinary']

# MESA version at which separate pgbinary defaults inlist and the pgbinary block become a thing
PGBINARY_SPLIT_VERSION = MesaVersion.parse_mesa_version("r23.05.1")

# MESA version at which kap and eos get separate defaults namelists
KAP_EOS_SPLIT_VERSION = MesaVersion.parse_mesa_version("r15140")

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
        raw = self.current_value if use_current and self.current_value is not None else self.default_option
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
            try:
                return defaults_file.options[name]
            except KeyError as exc:
                raise KeyError(
                    f"Option '{name}' was not found in namelist '{namelist}'."
                ) from exc

        matches = [
            defaults_file.options[name]
            for defaults_file in self.iter_files()
            if name in defaults_file.options
        ]

        if not matches:
            raise KeyError(f"Option '{name}' was not found in the loaded defaults.")

        if len(matches) > 1:
            matching_namelists = ", ".join(sorted(opt.namelist for opt in matches))
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
        if (
            opt.namelist in {"kap", "eos"}
            and self.mesa_version < KAP_EOS_SPLIT_VERSION
        ):
            raise ValueError(
                f"{opt.namelist} options are not supported for MESA version "
                f"{self.mesa_version}."
            )

        self.options[opt.name] = opt

    def _remove_option(self, option_name: str) -> bool:
        is_removed = self.options.pop(option_name, None)
        return is_removed is not None
    
    @classmethod
    def empty(cls, source_path: Path, mesa_version: MesaVersion) -> "Inlist":
        return cls(source_path=source_path, mesa_version=mesa_version)

    def set_option(
        self,
        name: str,
        value: object,
        defaults: DefaultsOptions,
        namelist: MesaNameList | None = None,
    ) -> MesaOption:
        template = defaults.find_option(name=name, namelist=namelist)

        new_option = MesaOption(
            name=template.name,
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

    def remove_option(self, name: str) -> None:
        if not self._remove_option(name):
            raise KeyError(f"Option '{name}' is not present in this inlist.")
    
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

        # If star_job is present, kap and eos blocks are required (even if empty),
        # but only for newer MESA versions.
        required_empty_blocks: set[MesaNameList] = set()
        if has_star_job:
            required_empty_blocks.add("pgstar")
            if self.mesa_version >= KAP_EOS_SPLIT_VERSION:
                required_empty_blocks.update({"kap", "eos"})
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
        opt = self.options[name]
        current = f"\ncurrent: {opt.current_value}" if opt.current_value is not None else ""
        return (
            f"{opt.name}\n"
            f"namelist: {opt.namelist}\n"
            f"default: {opt.default_option}"
            f"{current}\n"
            f"description:\n{opt.description}"
        )
    
    def get_python_value(self, name: str, use_current: bool = True) -> bool | int | float | str:
        return self.options[name].to_python_value(use_current=use_current)

def preview(options: list[MesaOption], 
            max_desc: int = 100, 
            prefer_pandas: bool = True):
       

    # Preview MesaOptions as pandas DataFrame (if available) or text table.
    rows: list[dict[str, str]] = []
    for o in options:
        desc = " ".join(o.description.split())
        if len(desc) > max_desc:
            desc = desc[: max_desc - 3] + "..."
        rows.append(
            {
                "name": o.name,
                "namelist": o.namelist,
                "default": o.default_option,
                "current": "" if o.current_value is None else o.current_value,
                "description": desc,
            }
        )

    if prefer_pandas:
        try:
            import pandas as pd  # optional dependency
            return pd.DataFrame(rows, columns=["name", "namelist", "default", "current", "description"])
        except ImportError:
            pass

    # Plain-text fallback
    if not rows:
        return "(no options)"

    headers = ["name", "namelist", "default", "current", "description"]
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
