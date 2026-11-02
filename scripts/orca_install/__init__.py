"""Backup-aware installer for the Orca advanced orchestration change bundle.

The package deliberately depends only on the Python standard library and Git.
It manages source files inside a supported Orca checkout; it never builds,
packages, launches, or migrates an Orca installation.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
