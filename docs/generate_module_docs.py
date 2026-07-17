from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from pathlib import Path
from typing import Iterable

PACKAGE_NAME = "morpy"          # <-- change
OUT_DIR = Path("docs/source/api")    # <-- change if needed

# You can tweak how module pages are named:
def module_to_page(mod_name: str) -> str:
    # e.g. mesa_runner.options -> module_mesa_runner_options
    # keep it simple and stable
    return "module_" + mod_name.replace(".", "_")

def iter_modules(package_name: str) -> Iterable[str]:
    pkg = importlib.import_module(package_name)
    yield pkg.__name__
    if not hasattr(pkg, "__path__"):
        return

    for mod in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        yield mod.name

def render_rst_for_module(mod_name: str) -> str:
    mod = importlib.import_module(mod_name)

    title = f"{mod_name} module"
    underline = "=" * len(title)

    # Collect classes + functions
    classes = []
    functions = []

    for name, obj in vars(mod).items():
        # Only document things defined in THIS module (optional but recommended)
        if getattr(obj, "__module__", None) != mod.__name__:
            continue

        if inspect.isclass(obj):
            classes.append((name, obj))
        elif inspect.isfunction(obj):
            functions.append((name, obj))

    classes.sort(key=lambda x: x[0])
    functions.sort(key=lambda x: x[0])

    # IMPORTANT:
    # - We show module docstring via automodule :members: removed.
    # - Then we show explicit autosummary entries for classes/functions.
    # autosummary_generate will create stub pages for each entry (optional but common).
    lines = []
    lines.append(title)
    lines.append(underline)
    lines.append("")
    lines.append("Module")
    lines.append("-------")
    lines.append("")
    lines.append(f".. automodule:: {mod_name}")
    lines.append("   :members:")  # you can set this to nothing if you want ONLY docstring
    lines.append("   :noindex:")
    lines.append("")
    # If you truly want ONLY the module docstring (no class/function dump on the module page),
    # replace the block above with:
    #   .. automodule:: {mod_name}
    #      :members: (remove entirely or set :members: omitted)
    # leaving only the directive, like:
    #   lines.append(f".. automodule:: {mod_name}")
    #   lines.append("   :no-members:")
    # But Sphinx may not show docstring without members unless you use it properly.
    #
    # We'll keep it as :members: but the next sections are explicit and readable.

    # Classes section
    lines.append("Classes")
    lines.append("--------")
    lines.append("")
    if classes:
        lines.append(".. autosummary::")
        lines.append("   :nosignatures:")
        lines.append("")
        for name, _ in classes:
            # fully qualified path for autosummary
            lines.append(f"   {mod_name}.{name}")
    else:
        lines.append("_No classes found in this module._")

    lines.append("")
    # Functions section
    lines.append("Functions")
    lines.append("---------")
    lines.append("")
    if functions:
        lines.append(".. autosummary::")
        lines.append("   :nosignatures:")
        lines.append("")
        for name, _ in functions:
            lines.append(f"   {mod_name}.{name}")
    else:
        lines.append("_No functions found in this module._")

    lines.append("")
    return "\n".join(lines)

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    module_names = list(iter_modules(PACKAGE_NAME))

    pages = []
    for mod_name in module_names:
        page = module_to_page(mod_name)
        rst_path = OUT_DIR / f"{page}.rst"
        rst_path.write_text(render_rst_for_module(mod_name), encoding="utf-8")
        pages.append(page)

    # Also write/update modules.rst to link them (optional)
    modules_index = OUT_DIR / "modules.rst"
    toctree_lines = "\n".join(f"   {p}" for p in sorted(pages))
    modules_index.write_text(
        "API (Modules)\n"
        "=============\n\n"
        ".. toctree::\n"
        "   :maxdepth: 1\n\n"
        f"{toctree_lines}\n",
        encoding="utf-8",
    )

if __name__ == "__main__":
    main()