from pathlib import Path
import warnings
from .config import MesaConfig, MesaVersion
from .options import (Inlist, 
                      DefaultsOptions, 
                      DefaultsFile, 
                      MesaOption, 
                      UnclassifiedNamelist, 
                      MesaNameList)

# MESA version at which kap and eos get separate defaults namelists
KAP_EOS_SPLIT_VERSION = MesaVersion.parse_mesa_version("r15140")

# MESA version at which separate pgbinary defaults inlist and the pgbinary block become a thing
PGBINARY_SPLIT_VERSION = MesaVersion.parse_mesa_version("r23.05.1")

# All MESA namelist blocks that the code can currently handle
KNOWN_NAMELISTS = {"controls",
                   "star_job",
                   "binary_controls",
                   "binary_job",
                   "kap",
                   "eos",
                   "pgstar",
                   "pgbinary"}

def _option_is_known_in_defaults(name: str, defaults_file: DefaultsFile) -> bool:
    """Return True if option name is present in defaults, including array-style names."""
    if name in defaults_file.options:
        return True

    if "(" in name:
        array_name = name.partition("(")[0]
        for opt in defaults_file.options.values():
            if array_name == opt.name.partition("(")[0]:
                return True

    return False

def build_defaults_options(defaults_dir: Path | str, config: MesaConfig) -> DefaultsOptions:
    """Method to parse all the available defaults files and store them into this class.
    Args:
        defaults_dir: Path to the base location of the defaults files, usually the MESA installation directory
        config: MesaConfig instance

    Returns:
        A DefaultsOptions instance with parsed MESA defaults files as DefaultsFiles instances
    
    """
    # Note to self: technically this implementation only works with a self-provided
    #   path to the defaults files directory if that directory has the same structure as in the
    #   MESA installation directory. If ever necessary, I should make his more flexible.

    defaults_dir = Path(defaults_dir)

    controls = parse_defaults_file(
        namelist="controls",
        source_path=defaults_dir / "star" / "defaults" / "controls.defaults",
        config=config,
    )
    star_job = parse_defaults_file(
        namelist="star_job",
        source_path=defaults_dir / "star" / "defaults" / "star_job.defaults",
        config=config,
    )
    binary_controls = parse_defaults_file(
        namelist="binary_controls",
        source_path=defaults_dir / "binary" / "defaults" / "binary_controls.defaults",
        config=config,
    )
    binary_job = parse_defaults_file(
        namelist="binary_job",
        source_path=defaults_dir / "binary" / "defaults" / "binary_job.defaults",
        config=config,
    )
    
    pgstar = parse_defaults_file(
        namelist="pgstar",
        source_path=defaults_dir / "star" / "defaults" / "pgstar.defaults",
        config=config,
    )

    pgbinary: DefaultsFile | None = None
    try:
        pgbinary = parse_defaults_file(
            namelist="pgbinary",
            source_path=defaults_dir / "binary" / "defaults" / "pgbinary.defaults",
            config=config,
        )
    except FileNotFoundError:
        warnings.warn(
            "pgbinary.defaults not found for this MESA version; pgbinary defaults were not loaded.",
            RuntimeWarning,
            stacklevel=2,
        )

    kap: DefaultsFile | None = None
    eos: DefaultsFile | None = None
    if config.mesa_version >= KAP_EOS_SPLIT_VERSION:
        kap = parse_defaults_file(
            namelist="kap",
            source_path=defaults_dir / "kap" / "defaults" / "kap.defaults",
            config=config,
        )
        eos = parse_defaults_file(
            namelist="eos",
            source_path=defaults_dir / "eos" / "defaults" / "eos.defaults",
            config=config,
        )

    return DefaultsOptions(
        mesa_version=config.mesa_version,
        controls=controls,
        star_job=star_job,
        binary_controls=binary_controls,
        binary_job=binary_job,
        pgstar=pgstar,
        kap=kap,
        eos=eos,
        pgbinary=pgbinary
    )

def build_defaults_options_from_config(config: MesaConfig) -> DefaultsOptions:
    """Get the `defaults_dir` from the `MesaConfig` object for automatic parsing of defaults files.

    Args:
        config: MesaConfig instance

    Returns:
        Calls `build_defaults_options` method to parse all available defaults files.
    """
    return build_defaults_options(config.mesa_dir, config)


def parse_defaults_file(namelist: MesaNameList, source_path: Path | str, config: MesaConfig) -> DefaultsFile:
    """Method to parse a MESA defaults file and store its contents as MesaOption objects in a DefaultsFile instance,

    Args:
        namelist: The kind of defaults file ("controls", "star_job", ...). Type: MesaNameList
        source_path: The Path object to the defaults file
        config: The MesaConfig instance
    Returns:
        A DefaultsFile instance containing the MesaOption objects with the names, default values and descriptions
            of the MESA defaults file.
    """
    source_path = Path(source_path)

    df = DefaultsFile(namelist = namelist, 
                      source_path = source_path, 
                      mesa_version = config.mesa_version)
    
    lines = source_path.read_text(encoding="utf-8").splitlines()
    pending_description: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith("!"):
            comment_text = stripped.lstrip("!").strip()

            # decoration-only lines like =====, ~~~~~, ----
            is_decorator = bool(comment_text) and all(c in "=~:- " for c in comment_text)

            # old-format headers like !# title or !### title
            is_hash_header = comment_text.startswith("#")

            # single uppercase token headers (optional legacy guard)
            is_upper_header = comment_text.isupper() and len(comment_text.split()) == 1

            # new-format heading line: text followed by a decorator line
            next_is_decorator = False
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt.startswith("!"):
                    nxt_text = nxt.lstrip("!").strip()
                    next_is_decorator = bool(nxt_text) and all(c in "=~:- " for c in nxt_text)

            if not is_decorator and not is_hash_header and not is_upper_header and not next_is_decorator:
                # keep line-level formatting; empty comment lines become blank lines
                pending_description.append(comment_text)

        elif "=" in line and not stripped.startswith("!"):
            name, _, value_part = line.partition("=")
            name = name.strip()

            if "!" in value_part:
                value_part = value_part.split("!", 1)[0]
            value = value_part.strip()

            if name and value:
                df.options[name] = MesaOption(
                    name=name,
                    default_option=value,
                    description="\n".join(pending_description).strip("\n"),
                    namelist=namelist,
                )
                pending_description = []
    
    return df

def parse_inlist(source_path: Path | str, 
                 config: MesaConfig, 
                 default_options: DefaultsOptions | None = None, 
                 allow_unknown_options: bool = False) -> Inlist:
    """Read the contents of an inlist and store it inside an Inlist object.

    Args:
        source_path: The Path object pointing to the location of the inlist file
        config: The MesaConfig instance
        default_options: The DefaultsOptions object required to look up descriptions and default values
            of the parsed inlist options. Will be created automatically based on MESA installation directory 
            if not provided my user. When multiple inlists are read, it is advisable to build this instance once and
            provide it explicitly as an argument.
        allow_unknown_options: If True, give a warning about inlist options that are not found in the defaults files. 
            If False, raise an exception when inlist options are found that re not found in the defaults files
    Returns:
        Inlist object with MesaOption instances.
    """

    source_path = Path(source_path)

    if default_options is None:
        default_options = build_defaults_options_from_config(config)
    
    il = Inlist(name = source_path.name, source_path = source_path, mesa_version = config.mesa_version)

    lines = source_path.read_text(encoding="utf-8").splitlines()

    block_type: MesaNameList | None = None
    defaults_file: DefaultsFile | None = None
    active_unclassified_block_name: str | None = None
    active_unclassified_block_lines: list[str] = []
    block_had_option = False # track if we're dealing with an empty block

    # Collector for unknown options
    unknown_options: dict[str, set[str]] = {}
    
    for i, line in enumerate(lines):
        stripped = line.strip()

        # If we are inside an unknown block, keep raw lines until closing "/".
        if active_unclassified_block_name is not None:
            if stripped.startswith("/"):
                il.additional_options.append(
                    UnclassifiedNamelist(
                        name=active_unclassified_block_name,
                        body="\n".join(active_unclassified_block_lines),
                    )
                )
                active_unclassified_block_name = None
                active_unclassified_block_lines = []
            else:
                active_unclassified_block_lines.append(line)
            continue

        # Determine which block type = MesaNameList type we're in
        if stripped.startswith('&'):
            potential_block_type = stripped.lstrip('&').strip()

            # Take care of the fact that older MESA version do not have a pgbinary
            # namelist but instead have a binary_pgstar namelist.
            # We want to treat this as a pgbinary namelist internally.
            if potential_block_type == "binary_pgstar" and config.mesa_version < PGBINARY_SPLIT_VERSION:
                normalised_block_type = "pgbinary"
            else:
                normalised_block_type = potential_block_type
            
            # Check if we're dealing with a regular namelist or an unrecognised namelist
            if normalised_block_type in KNOWN_NAMELISTS:
                # Normnal behaviour for regular namelist
                block_type = normalised_block_type
                defaults_file = default_options[block_type]
                block_had_option = False
            else:
                # Start collecting unknown block body as raw text.
                block_type = None
                defaults_file = None
                active_unclassified_block_name = potential_block_type
                active_unclassified_block_lines = []
            continue
        
        if stripped.startswith('/'):
            if block_type is not None and not block_had_option:
                il.empty_namelists.add(block_type)
            block_type = None
            defaults_file = None
            block_had_option = False
            continue
        
        if "=" in line and not stripped.startswith("!"):
            if block_type is None:
                continue

            name, _, value_part = line.partition("=")
            name = name.strip()

            if "!" in value_part:
                value_part = value_part.split("!", 1)[0]
            value = value_part.strip()

            if not (name and value):
                continue
            
            if defaults_file is not None:
                known = _option_is_known_in_defaults(name, defaults_file)
                if not known:
                    unknown_options.setdefault(block_type, set()).add(name)
                    if not allow_unknown_options:
                         continue
            # find the corresponding name, default_value and description in the defaults
            description = ""
            default_value = ""

            if defaults_file is not None: # This is for the binary_pgstar blocks, which have no dedicated defaults file.
                if "(" in name:
                    array_name = name.partition("(")[0]
                    for opt in defaults_file.options.values():
                        if array_name == opt.name.partition("(")[0]:
                            description = opt.description
                            default_value = opt.default_option
                            break
                elif name in defaults_file.options:
                    description = defaults_file.options[name].description
                    default_value = defaults_file.options[name].default_option

            il.options[name] = MesaOption(
                name=name,
                default_option=default_value,
                current_value=value,
                description=description,
                namelist=block_type,
            )
            block_had_option = True
    
    if active_unclassified_block_name is not None:
        raise ValueError(
            f"Unclosed namelist block '&{active_unclassified_block_name}' in {source_path}."
        )
    
    if not allow_unknown_options and unknown_options:
        details = "; ".join(
            f"{namelist}: {', '.join(sorted(names))}"
            for namelist, names in sorted(unknown_options.items())
        )
        raise ValueError(
            f"Unknown options found in {source_path} for loaded MESA defaults: {details}"
        )

    if allow_unknown_options and unknown_options:
        details = "; ".join(
            f"{namelist}: {', '.join(sorted(names))}"
            for namelist, names in sorted(unknown_options.items())
        )
        warnings.warn(
            f"Unknown inlist options found in {source_path} for loaded MESA defaults: {details}",
            RuntimeWarning,
            stacklevel=2,
        )

    return il

# TODO: curently, empty namelist blocks will be skipped in inlits.write becasue there are no options in 
# inlist.options with that namelist type. I should change the inlist parser and Inlist class 
# so that empty blocks are added to an Inlist attribute and subsequently written as empty blocks if there
# are still no options for that namelist at the time Inlist.write() is called.


