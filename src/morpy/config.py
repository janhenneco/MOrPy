"""Configuration and environment utilities.

This module resolves MESA installation metadata and runtime shell environment.

- MesaVersion parses and compares MESA version strings.
- MesaConfig stores resolved MESA directory and version information.
- setup_mesa_env configures MESA_DIR and MESASDK runtime variables for Python runs.

It also provides active-config helpers so other modules can use a shared
MesaConfig context without repeatedly passing it through every call.
"""

from dataclasses import dataclass
from functools import total_ordering
import re
from pathlib import Path
import os
from typing import Self, Mapping
import shlex
import subprocess
from contextvars import ContextVar

# This bit is here to make the active MesaConfig available by all modules
# and avoid users having to pass a MesaVersion object when initialising Inlist and Model
# instances.
_ACTIVE_CONFIG: ContextVar["MesaConfig | None"] = ContextVar("_ACTIVE_CONFIG", default=None)

def set_active_config(config: "MesaConfig") -> None:
    _ACTIVE_CONFIG.set(config)

def get_active_config() -> "MesaConfig | None":
    return _ACTIVE_CONFIG.get()

def require_active_config() -> "MesaConfig":
    cfg = get_active_config()
    if cfg is None:
        raise RuntimeError(
            "No active MesaConfig found. Run MesaConfig.setup(...) first, "
            "or pass mesa_version/config explicitly."
        )
    return cfg

@total_ordering
@dataclass(frozen = True)
class MesaVersion:
    """Class that holds and sets the MESA version in raw and normalised numeric format to allow comparisons.

    Attributes:
        version_name: Raw format of the MESA version
        scheme: revision (rXXXXX), release (rXX.XX.X), or git hash (XXXXX) scheme
        revision: Optional attribute set in case `version_name` is in revision format
        year: Optional attribute set in case `version_name` is in release format. 
            Represents the first pair of digits of rXX.XX.X
        month: Optional attribute set in case `version_name` is in release format. 
            Represents the second pair of digits of rXX.XX.X 
        patch: Optional attribute set in case `version_name` is in release format. 
            Represents the last digit of rXX.XX.X 
    """
    version_name: str
    scheme: str
    revision: int | None = None
    year: int | None = None
    month: int | None = None
    patch: int = 1

    @classmethod
    def parse_mesa_version(cls, version_name: str) -> Self:
        """ Parse the raw MESA version string into a normalised MesaVersion.

        Args:
            version_name: Raw MESA version string, for example `r23.05.1`, `12786`,
                or a git hash.

        Returns:
            A MesaVersion instance with detected scheme and parsed numeric fields.

        Raises:
            ValueError: If `version_name` does not match a supported format.
        """
        # strip whitespaces and quotation marks
        text = version_name.strip().strip('"\'')
        # check if the version name is in the release format, i.e. rXX.XX.X
        release_match = re.fullmatch(r"r?(\d+)\.(\d+)(?:\.(\d+))?", text, re.IGNORECASE)
        # if in the release format, then extract year, month, and patch number
        if release_match:
            return cls(
                version_name = version_name, 
                scheme = "release",
                year = int(release_match.group(1)),
                month = int(release_match.group(2)),
                patch = int(release_match.group(3) or 1)
            )
        
        # if version_name was not in release format, it is likely (otherwise wrong format) in revision format
        revision_match = re.fullmatch(r"r?(\d+)", text, re.IGNORECASE)
        if revision_match:
            return cls(
                version_name = version_name,
                scheme = "revision",
                revision = int(revision_match.group(1))
            )
        
        # Git hash format: 7 to 40 hex characters
        git_match = re.fullmatch(r"[0-9a-f]{7,40}", text, re.IGNORECASE)
        if git_match:
            return cls(
                version_name = version_name,
                scheme="git",
            )

        # if the `return` statement has not been triggered by now, there is something wrong with the format
        raise ValueError(f"Could not parse MESA version: {version_name!r}")
    
    def _comparison_key(self) -> tuple[int, int, int, int]:
        if self.scheme == "revision":
            return (0, self.revision or 0, 0, 0)
        if self.scheme == "git":
            return (2, 0, 0, 0)
        return (1, self.year or 0, self.month or 0, self.patch)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, MesaVersion):
            return NotImplemented
        return self._comparison_key() < other._comparison_key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MesaVersion):
            return NotImplemented
        return self._comparison_key() == other._comparison_key()
        

@dataclass
class MesaConfig:
    """ Class that holds the configuration related to the used MESA version.
    
    Attributes:
        mesa_dir: Path to the MESA source directory.
        mesa_version: MesaVersion object
        version_raw: Optional attribute with the raw MESA version name. 
            Only needed when the MESA version cannot be recovered from the MESA directory. 
    """
    mesa_dir: Path
    mesa_version: MesaVersion
    version_raw: str | None = None

    @classmethod
    def setup(cls, mesa_dir: Path | str | None = None, version_name: str | None = None) -> Self:
        """Create a MesaConfig from a MESA source directory.

        Args:
            mesa_dir: Optional path to the MESA source directory. If omitted, uses
                the `MESA_DIR` environment variable.
            version_name: Optional manual version override. Required when automatic
                detection yields a git hash.

        Returns:
            A MesaConfig instance with resolved path and parsed version.

        Raises:
            EnvironmentError: If `MESA_DIR` is not set and `mesa_dir` is not provided.
            FileNotFoundError: If the resolved MESA directory does not exist.
            ValueError: If version parsing fails or a git hash requires manual input.
        """
        if mesa_dir is not None:
            resolved = Path(mesa_dir).expanduser().resolve()
        else:
            env_value = os.environ.get("MESA_DIR")
            if not env_value:
                raise EnvironmentError(
                    "MESA_DIR is not set and no mesa_dir was provided."
                )
            resolved = Path(env_value).expanduser().resolve()

        if not resolved.is_dir():
            raise FileNotFoundError(f"MESA directory does not exist: {resolved}")

        version_raw: str | None = None

        # If provided explicitly, do not require reading data/version_number
        if version_name is not None:
            mesa_version = MesaVersion.parse_mesa_version(version_name)
        else:
            version_file = resolved / "data" / "version_number"
            if not version_file.is_file():
                raise FileNotFoundError(f"MESA version file does not exist: {version_file}")

            version_raw = version_file.read_text(encoding="utf-8").strip()
            mesa_version = MesaVersion.parse_mesa_version(version_raw)

            if mesa_version.scheme == "git":
                raise ValueError(
                    f"MESA version detected as git hash ({version_raw}). "
                    "Cannot determine version scheme automatically. "
                    "Please specify version_name manually: "
                    "MesaConfig.setup(version_name='r23.05.1')"
                )

        cfg = cls(
            mesa_dir=resolved,
            mesa_version=mesa_version,
            version_raw=version_raw,
        )
        set_active_config(cfg)
        return cfg
    
    def set_mesa_env(
        self,
        *,
        mesasdk_root: Path | str,
        omp_num_threads: int | None = None,
        apply_to_process: bool = True,
        shell_executable: Path | str = "/bin/bash",
        base_env: Mapping[str, str] | None = None
        ) -> dict[str, str]:
        """Set the MESA_DIR and MESASDK_ROOT variables and execute the initialisation scripts.

        Args:
            mesasdk_root: Location of the MESA SDK directory (MESASDK_ROOT)
            omp_num_threads: Number of CPU threads to use for a single MESA run (OMP_NUM_THREADS).
        apply_to_process: If True, update the current Python process environment (os.environ) 
            with the resolved MESA/MESASDK variables, so later code in this process automatically 
            sees them. If False, do not modify os.environ; the method still returns the environment 
            dictionary, which you can pass explicitly to subprocess calls.
        shell_executable: Path to the shell used to run the MESASDK init script. 
            Most users should keep the default "/bin/bash".
            Change this only if your system requires a different shell executable.
        base_env:
            Optional starting environment mapping. If None, the current process environment (os.environ) is used.
            Provide this when you want a controlled or reproducible environment (for example in tests, CI, or isolated runs).
            Values from MESA setup always override base_env for MESA_DIR, MESASDK_ROOT, and OMP_NUM_THREADS.

        Returns:
            env: The returned dict is the final runtime environment after sourcing MESASDK and applying 
            explicit MESA variables. If apply_to_process is True, this final environment is also written to os.environ.

        """
        sdk_root = Path(mesasdk_root).expanduser().resolve()
        if not sdk_root.is_dir():
            raise FileNotFoundError(f"MESASDK root does not exist: {sdk_root}")

        init_script = sdk_root / "bin" / "mesasdk_init.sh"
        if not init_script.is_file():
            raise FileNotFoundError(f"MESASDK init script not found: {init_script}")

        threads = omp_num_threads
        if threads is None:
            threads = max(1, os.cpu_count() or 1)
        if threads < 1:
            raise ValueError(f"omp_num_threads must be >= 1, got: {threads}")

        env = dict(os.environ if base_env is None else base_env)
        explicit = {
            "MESA_DIR": str(self.mesa_dir),
            "MESASDK_ROOT": str(sdk_root),
            "OMP_NUM_THREADS": str(threads),
        }
        env.update(explicit)

        quoted_script = shlex.quote(str(init_script))
        cmd = f"source {quoted_script} >/dev/null 2>&1 && env -0"

        completed = subprocess.run(
            [str(shell_executable), "-lc", cmd],
            env=env,
            capture_output=True,
            check=False,
        )

        if completed.returncode != 0:
            stderr_text = completed.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                "Failed to source MESASDK init script. "
                f"Script: {init_script} | stderr: {stderr_text.strip()}"
            )

        sourced_env: dict[str, str] = {}
        for entry in completed.stdout.split(b"\x00"):
            if not entry:
                continue
            key, sep, value = entry.partition(b"=")
            if not sep:
                continue
            sourced_env[key.decode("utf-8", errors="replace")] = value.decode(
                "utf-8", errors="replace"
            )

        # Keep explicit user-requested values authoritative.
        sourced_env.update(explicit)
        env = sourced_env

        if apply_to_process:
            os.environ.update(env)

        return env
    
def setup_mesa_env(
    *,
    mesa_dir: Path | str,
    mesasdk_root: Path | str,
    version_name: str | None = None,
    omp_num_threads: int | None = None,
    apply_to_process: bool = True,
    shell_executable: Path | str = "/bin/bash"
    ) -> MesaConfig:
    """Wrapper function to initialise a MesaConfig object (MesaConfig.setup) and
        set the MESA environment variables to be able to compile and run MESA 
        (as usually done in .*rc scripts or module files)
    
    Args:
        mesa_dir: Location of the MESA installation directory (MESA_DIR)
        mesasdk_root: Location of the MESA SDK directory (MESASDK_ROOT)
        version_name: Optional manual version override. Required when automatic
            detection yields a git hash.
        omp_num_threads: Number of CPU threads to use for a single MESA run (OMP_NUM_THREADS).
        apply_to_process: If True, update the current Python process environment (os.environ) 
            with the resolved MESA/MESASDK variables, so later code in this process automatically 
            sees them. If False, do not modify os.environ; the method still returns the environment 
            dictionary, which you can pass explicitly to subprocess calls.
        shell_executable: Path to the shell used to run the MESASDK init script. 
            Most users should keep the default "/bin/bash".
            Change this only if your system requires a different shell executable.
    Returns:
        cfg: MesaConfig object.

    """
    cfg = MesaConfig.setup(
    mesa_dir=mesa_dir,
    version_name=version_name)
    cfg.set_mesa_env(
        mesasdk_root=mesasdk_root,
        omp_num_threads=omp_num_threads,
        apply_to_process=apply_to_process,
        shell_executable=shell_executable)
    return cfg