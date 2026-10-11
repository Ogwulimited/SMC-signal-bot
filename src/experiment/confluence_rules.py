"""Confluence rule definitions for OB quality gates.

Each rule is a callable that takes a signal's confluence flags and
returns True if the OB passes the rule.
"""

RULES = {
    "A_FVG_only":        lambda f: f["fvg"],
    "B_FVG_or_EQ":       lambda f: f["fvg"] or f["eq"],
    "C_FVG_or_IDM":      lambda f: f["fvg"] or f["idm"],
    "D_FVG_or_TIME":     lambda f: f["fvg"] or f["time"],
    "E_any_of_four":     lambda f: f["fvg"] or f["eq"] or f["idm"] or f["time"],
    "F2_score_at_least_2": lambda f: sum([f["fvg"], f["eq"], f["idm"], f["time"]]) >= 2,
    "F3_score_at_least_3": lambda f: sum([f["fvg"], f["eq"], f["idm"], f["time"]]) >= 3,
    "F4_score_all_four":   lambda f: all([f["fvg"], f["eq"], f["idm"], f["time"]]),
}


def flags_from_confluences(confluences):
    """Convert the confluences list to a flag dict."""
    return {
        "fvg": "FVG" in confluences,
        "eq": "EQH/EQL" in confluences,
        "idm": "IDM" in confluences,
        "time": "TIME_LIQ" in confluences,
    }
