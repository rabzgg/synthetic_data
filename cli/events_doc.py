"""
events_doc.py — write docs/EVENTS.md (events, their parameters, the device compatibility tables and
the scenario list) from the code and the config files.

Usage: python3 cli/events_doc.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.events.doc import DOC, markdown

if __name__ == "__main__":
    with open(DOC, "w") as fh:
        fh.write(markdown())
    print(f"wrote {os.path.relpath(DOC, ROOT)}")
