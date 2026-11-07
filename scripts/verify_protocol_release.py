"""Rerun the historical independent protocol probes with new evidence paths.

The historical test source/results are kept intact. Its worker imports this
checkout's production modules; ports19000/19001 must be free.
"""
from pathlib import Path
import importlib.util
import sys

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'audits/final_2026_10_26/protocol_security/audit_protocol.py'
spec=importlib.util.spec_from_file_location('release_protocol_probes',source)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.OUT=ROOT/'audits/release_2026_11_07/protocol'
if __name__=='__main__': raise SystemExit(module.main())
