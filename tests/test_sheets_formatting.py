"""Guards against invalid Google Sheets API ConditionType enum values.

sheets/formatting.py used "NUMBER_LESS_THAN" (not a real enum value — the
correct one is "NUMBER_LESS"), which silently rejected the entire
format_daily() batch_update on every run for weeks: no frozen header, no
Status dropdown, no conditional formatting, and no error surfaced to the
console since format_all_sheets() catches and logs per-tab.
"""
from unittest.mock import MagicMock

from sheets.formatting import (
    format_daily, format_audit, format_materials, format_tracker,
)

# The full Google Sheets API ConditionType enum. Any condition `type` used by
# this module must be a member of this set.
_VALID_CONDITION_TYPES = {
    "NUMBER_GREATER", "NUMBER_GREATER_THAN_EQ", "NUMBER_LESS",
    "NUMBER_LESS_THAN_EQ", "NUMBER_EQ", "NUMBER_NOT_EQ",
    "NUMBER_BETWEEN", "NUMBER_NOT_BETWEEN",
    "TEXT_CONTAINS", "TEXT_NOT_CONTAINS", "TEXT_STARTS_WITH",
    "TEXT_ENDS_WITH", "TEXT_EQ", "TEXT_NOT_EQ", "TEXT_IS_EMAIL", "TEXT_IS_URL",
    "DATE_EQ", "DATE_NOT_EQ", "DATE_BEFORE", "DATE_AFTER",
    "DATE_ON_OR_BEFORE", "DATE_ON_OR_AFTER", "DATE_BETWEEN", "DATE_NOT_BETWEEN",
    "ONE_OF_RANGE", "ONE_OF_LIST", "BLANK", "NOT_BLANK",
    "CUSTOM_FORMULA", "BOOLEAN", "FILTER_EXPRESSION",
}


def _condition_types_in(requests: list[dict]) -> set[str]:
    found = set()
    for req in requests:
        for key in ("addConditionalFormatRule", "setDataValidation"):
            block = req.get(key)
            if not block:
                continue
            rule = block.get("rule", {})
            condition = (
                rule.get("booleanRule", {}).get("condition")
                or rule.get("condition")
            )
            if condition and "type" in condition:
                found.add(condition["type"])
    return found


def _fake_spreadsheet():
    ws = MagicMock()
    ws.id = 1
    spreadsheet = MagicMock()
    spreadsheet.fetch_sheet_metadata.return_value = {"sheets": []}
    return spreadsheet, ws


def test_format_daily_uses_only_valid_condition_types():
    spreadsheet, ws = _fake_spreadsheet()
    format_daily(spreadsheet, ws)
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    used = _condition_types_in(requests)
    assert used, "expected at least one conditional/validation rule"
    assert used <= _VALID_CONDITION_TYPES, f"invalid enum(s): {used - _VALID_CONDITION_TYPES}"


def test_format_audit_uses_only_valid_condition_types():
    spreadsheet, ws = _fake_spreadsheet()
    format_audit(spreadsheet, ws)
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    assert _condition_types_in(requests) <= _VALID_CONDITION_TYPES


def test_format_materials_uses_only_valid_condition_types():
    spreadsheet, ws = _fake_spreadsheet()
    format_materials(spreadsheet, ws)
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    used = _condition_types_in(requests)
    assert used <= _VALID_CONDITION_TYPES, f"invalid enum(s): {used - _VALID_CONDITION_TYPES}"


def test_format_tracker_uses_only_valid_condition_types():
    spreadsheet, ws = _fake_spreadsheet()
    format_tracker(spreadsheet, ws)
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    used = _condition_types_in(requests)
    assert used <= _VALID_CONDITION_TYPES, f"invalid enum(s): {used - _VALID_CONDITION_TYPES}"
