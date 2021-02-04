# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#

import datetime
import os
import subprocess
import sys

import sphinx_rtd_theme
# import pydata_sphinx_theme

sys.path.insert(0, os.path.abspath("."))
sys.path.append(os.path.abspath("./_ext"))
# top = os.path.realpath(os.path.dirname(os.path.dirname(__file__)))
# sys.path.insert(0, top)

# -- Project information -----------------------------------------------------

project = u"metview"
copyright = u"2017-, European Centre for Medium-Range Weather Forecasts (ECMWF)."
author = "ECMWF"


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx_rtd_theme",
    # "pydata_sphinx_theme",
    "nbsphinx",
    "sphinx.ext.intersphinx",
    "metview_sphinx"
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# The suffix of source filenames.
source_suffix = ".rst"

# The encoding of source files.
# source_encoding = 'utf-8-sig'

# The master toctree document.
master_doc = "index"

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "sphinx_rtd_theme"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static", "_static/gallery"]

html_css_files = ["css/custom_style.css", "css/gallery.css"]


html_logo = "_static/metview.png"

rst_prolog = """
.. role:: mval
"""

def setup(app):
    # this is a pre-build step to generate RST files with running "make metview". 
    # We need to put this code here because the Makefile is not run by
    # Read The Docs (it directly runs sphinx-build instead!).  
    if os.environ.get("READTHEDOCS", "") != "":
        before = {**(os.environ)}
        try:
            r = subprocess.run(["make", "metview"], check=True)
        except Exception as e:
            print(f"  Failed to preprocess step. {e}")
        after = {**(os.environ)}
        for k in before.keys():
            if before[k] != after[k]:
                print(f"diff {k} {before[k]} != {after[k]}")