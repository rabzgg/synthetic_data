"""
parameter_mapping.py — write docs/PARAMETER_MAPPING.md from the quantity catalog, the model
parameters and the normalisation rules (core/quantities/). The doc is never edited by hand.

Usage: python3 cli/parameter_mapping.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.quantities.normalize import DOC, markdown

if __name__ == "__main__":
    with open(DOC, "w") as fh:
        fh.write(markdown())
    print(f"wrote {os.path.relpath(DOC, ROOT)}")
