"""Tests for the offline DOL LCA employer index that replaced h1bdata.info."""
from __future__ import annotations

import pytest

from screening.lca_index import LcaIndex, compact


def test_compact_drops_case_spaces_and_punctuation():
    assert compact("JPMorgan Chase & Co") == "jpmorganchaseco"
    assert compact("amazon.com services") == "amazoncomservices"
    assert compact("  ") == ""


def test_long_query_matches_as_prefix_of_a_filer():
    index = LcaIndex({"microsoft", "amazoncomservices"})
    assert index.matches("microsoft") is True
    assert index.matches("amazoncom") is True
    assert index.matches("amazon") is True


def test_long_query_with_no_filer_prefix_is_a_miss():
    index = LcaIndex({"microsoft"})
    assert index.matches("ghoststaffing") is False


def test_three_letter_query_matches_as_prefix():
    # DRW files as "DRW Holdings" and CGI as "CGI Technologies and Solutions".
    index = LcaIndex({"drwholdings", "cgitechnologiesandsolutions"})
    assert index.matches("drw") is True
    assert index.matches("cgi") is True


def test_two_letter_query_needs_an_exact_filer():
    # "ey" as a prefix would also hit "eyeq monitoring" and every other "ey..."
    index = LcaIndex({"eyeqmonitoring"})
    assert index.matches("ey") is False
    assert LcaIndex({"ey"}).matches("ey") is True


def test_empty_query_never_matches():
    assert LcaIndex({"microsoft"}).matches("") is False


def test_save_then_load_round_trips_keys_and_provenance(tmp_path):
    path = tmp_path / "filers.txt"
    LcaIndex({"microsoft", "ibm"}, built="2026-10-09",
             sources=["LCA_Disclosure_Data_FY2025_Q4.xlsx"]).save(path)

    loaded = LcaIndex.load(path)

    assert loaded is not None
    assert len(loaded) == 2
    assert loaded.matches("microsoft") is True
    assert loaded.built == "2026-10-09"
    assert loaded.sources == ["LCA_Disclosure_Data_FY2025_Q4.xlsx"]


def test_load_of_missing_file_returns_none(tmp_path):
    assert LcaIndex.load(tmp_path / "absent.txt") is None


def test_load_of_empty_index_returns_none(tmp_path):
    # An index with no employers would drop every company; treat it as absent.
    path = tmp_path / "filers.txt"
    LcaIndex(set(), built="2026-10-09").save(path)
    assert LcaIndex.load(path) is None
