# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath("../../src"))

project = 'MOrPy'
author = 'Jan Henneco'
copyright = f"{datetime.now():%Y}, {author}"


version = '0.1'
release = '0.1.0.dev0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "myst_parser"
    ]

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
autodoc_inherit_docstrings = False
autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = True

templates_path = ["_templates"]
exclude_patterns = []

html_theme = "furo"
html_title = "MOrPy Documentation"
html_theme_options = {
    "source_repository": "https://github.com/janhenneco/MOrPy/",
    "source_branch": "main",
    "source_directory": "docs/source/",
    "navigation_with_keys": True,
}

language = 'en'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# html_theme = 'alabaster'
# html_static_path = ['_static']


### REGENERATE DOCS: 
# sphinx-build -b html docs/source docs/build/html
