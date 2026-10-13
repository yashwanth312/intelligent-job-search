"""Tests for turning DOL LCA disclosure rows into H-1B employer index keys."""
from __future__ import annotations

import importlib.util
import pathlib

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "build_lca_index.py"
_spec = importlib.util.spec_from_file_location("build_lca_index", _PATH)
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)
collect_filer_keys = _builder.collect_filer_keys


def _row(name, status="Certified", visa="H-1B", dba=""):
    return {"CASE_STATUS": status, "VISA_CLASS": visa,
            "EMPLOYER_NAME": name, "TRADE_NAME_DBA": dba}


def test_certified_h1b_filers_are_collected():
    keys = collect_filer_keys([_row("MICROSOFT CORPORATION"), _row("IBM Corporation")])
    assert keys == {"microsoft", "ibm"}


def test_certified_withdrawn_still_counts_as_a_filing():
    assert collect_filer_keys([_row("Stripe, Inc.", status="Certified - Withdrawn")]) == {"stripe"}


def test_denied_and_never_certified_rows_are_ignored():
    rows = [_row("Denied Co", status="Denied"), _row("Pulled Co", status="Withdrawn")]
    assert collect_filer_keys(rows) == set()


def test_other_visa_classes_are_ignored():
    rows = [_row("Aussie Co", visa="E-3 Australian"), _row("Chile Co", visa="H-1B1 Chile")]
    assert collect_filer_keys(rows) == set()


def test_trade_name_is_indexed_alongside_the_legal_name():
    keys = collect_filer_keys([_row("Advanced Micro Devices, Inc.", dba="AMD")])
    assert keys == {"advancedmicrodevices", "amd"}


def test_blank_and_missing_names_are_skipped():
    rows = [_row(None), _row("  "), {"CASE_STATUS": "Certified", "VISA_CLASS": "H-1B"}]
    assert collect_filer_keys(rows) == set()
