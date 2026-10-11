"""Confluence rule definitions — AND logic.

Each rule takes a signal's confluence flags and returns True if the
signal passes the gate. Rules here use AND logic: multiple confluences
must be present simultaneously.

Rule G is a control (EQH/EQL only, no FVG) to isolate whether FVG adds
value or drags performance.
"""

RULES = {
    "A_FVG_only":           lambda f: f["fvg"],
    "B_FVG_AND_EQ":         lambda f: f["fvg"] and f["eq"],
    "C_FVG_AND_IDM":        lambda f: f["fvg"] and f["idm"],
    "D_FVG_AND_TIME":       lambda f: f["fvg"] and f["time"],
    "E_FVG_EQ_TIME":        lambda f: f["fvg"] and f["eq"] and f["time"],
    "F_FVG_EQ_IDM_TIME":    lambda f: f["fvg"] and f["eq"] and f["idm"] and f["time"],
    "G_EQ_only":            lambda f: f["eq"],
}

RULE_DESCRIPTIONS = {
    "A_FVG_only":        "FVG only (current live bot)",
    "B_FVG_AND_EQ":      "FVG AND EQH/EQL",
    "C_FVG_AND_IDM":     "FVG AND inducement sweep",
    "D_FVG_AND_TIME":    "FVG AND time-based liquidity",
    "E_FVG_EQ_TIME":     "FVG AND EQH/EQL AND time-based liquidity",
    "F_FVG_EQ_IDM_TIME": "FVG AND EQH/EQL AND IDM AND time-based",
    "G_EQ_only":         "EQH/EQL only (control — no FVG)",
}


def flags_from_confluences(confluences):
    """Convert the confluences list to a flag dict."""
    return {
        "fvg": "FVG" in confluences,
        "eq": "EQH/EQL" in confluences,
        "idm": "IDM" in confluences,
        "time": "TIME_LIQ" in confluences,
    }
