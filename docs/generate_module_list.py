import ast
from pathlib import Path

# Ordered as they should appear in the README
MODULE_ORDER = [
    "config",
    "parser",
    "options",
    "utils",
    "model",
    "work_setup",
    "project_setup",
    "compile",
    "run",
    "run_types",
    "errors",
    "grid_run",
    "repository",
    "status",
]

src = Path(__file__).parent.parent / "src" / "mesa_runner"

for name in MODULE_ORDER:
    path = src / f"{name}.py"
    if not path.exists():
        print(f"- `{name}.py`: *(file not found)*\n")
        continue

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstring = ast.get_docstring(tree) or "*(no module docstring)*"
    # Use only the first paragraph (up to first blank line)
    summary = docstring.split("\n\n")[0].replace("\n", " ").strip()
    print(f"- `{name}.py`: {summary}\n")