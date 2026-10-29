"""
update_docs.py — regenerate every generated doc after a change in configs/:
docs/EVENTS.md (events, devices, scenarios), docs/PARAMETER_MAPPING.md (quantities, parameters) and the
generic table in docs/PRESALES.md (generic parts). Tests fail with "run: python3 cli/update_docs.py"
when one of them is out of date.
Usage: python3 cli/update_docs.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import importlib  # noqa: E402

DOCS = [importlib.import_module(m) for m in ("core.events.doc", "core.quantities.normalize", "core.devices.generic_doc")]

if __name__ == "__main__":
    for mod in DOCS:
        text = mod.markdown()
        with open(mod.DOC, "w") as fh:
            fh.write(text)
        print(f"wrote {os.path.relpath(mod.DOC, ROOT)}")
