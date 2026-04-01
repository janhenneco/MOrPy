from pathlib import Path
import warnings
from .config import MesaConfig, MesaVersion
from .options import Inlist, DefaultsOptions, DefaultsFile, MesaOption, MesaNameList

# Version at which kap and eos get separate defaults namelists
KAP_EOS_SPLIT_VERSION = MesaVersion.parse_mesa_version("r15140")

def build_defaults_options(defaults_dir: Path, config: MesaConfig) -> DefaultsOptions:
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
            "pgbinary.defaults not found for this MESA version; pgbinary defaults were not loaded from this file but are loaded from the pgstar file.",
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


def parse_defaults_file(namelist: MesaNameList, source_path: Path, config: MesaConfig) -> DefaultsFile:
    """Method to parse a MESA defaults file and store its contents as MesaOption objects in a DefaultsFile instance,

    Args:
        namelist: The kind of defaults file ("controls", "star_job", ...). Type: MesaNameList
        source_path: The Path object to the defaults file
        config: The MesaConfig instance
    Returns:
        A DefaultsFile instance containing the MesaOption objects with the names, default values and descriptions
            of the MESA defaults file.
    """
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

def parse_inlist(source_path: Path, config: MesaConfig, default_options: DefaultsOptions | None = None) -> Inlist:
    """Read the contents of an inlist and store it inside an Inlist object.

    Args:
        source_path: The Path object pointing to the location of the inlist file
        config: The MesaConfig instance
        default_options: The DefaultsOptions object required to look up descriptions and default values
            of the parsed inlist options. Will be created automatically based on MESA installation directory 
            if not provided my user. When multiple inlists are read, it is advisable to build this instance once and
            provide it explicitly as an argument.
    Returns:
        Inlist object with MesaOption instances.
    """
    if default_options is None:
        default_options = build_defaults_options_from_config(config)
    
    il = Inlist(source_path = source_path, mesa_version = config.mesa_version)

    lines = source_path.read_text(encoding="utf-8").splitlines()

    block_type: MesaNameList | None = None
    defaults_file: DefaultsFile | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Determine which block type = MesaNameList type we're in
        if stripped.startswith('&'):
            potential_block_type = stripped.lstrip('&').strip()
            block_type = potential_block_type
            defaults_file = default_options[block_type]
            continue
        
        if stripped.startswith('/'):
            block_type = None
            defaults_file = None
            continue
        
        if "=" in line and not stripped.startswith("!"):
            if block_type is None or defaults_file is None:
                continue

            name, _, value_part = line.partition("=")
            name = name.strip()

            if "!" in value_part:
                value_part = value_part.split("!", 1)[0]
            value = value_part.strip()

            if not (name and value):
                continue
            
            # find the corresponding name, default_value and description in the defaults
            description = ""
            default_value = ""

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

    return il



