"""Rules for the EQ-focused confluence test.

Baseline from the previous experiment: EQ-only (Rule G) was the strongest
rule with +0.365 R expectancy and 45.6% WR.

This experiment tests whether adding IDM and/or FVG to EQ improves it.
"""

RULES = {
    "EQ_only":          lambda f: f["eq"],
    "EQ_AND_IDM":       lambda f: f["eq"] and f["idm"],
    "EQ_AND_FVG":       lambda f: f["eq"] and f["fvg"],
    "EQ_AND_IDM_AND_FVG": lambda f: f["eq"] and f["idm"] and f["fvg"],
}

RULE_DESCRIPTIONS = {
    "EQ_only":           "EQH/EQL only (baseline — best from prior experiment)",
    "EQ_AND_IDM":        "EQH/EQL AND inducement sweep",
    "EQ_AND_FVG":        "EQH/EQL AND FVG",
    "EQ_AND_IDM_AND_FVG":"EQH/EQL AND IDM AND FVG",
}

# Minimum sample for the verdict to be trustworthy
MIN_TRADES_FOR_VERDICT = 30


def flags_from_confluences(confluences):
    return {
        "fvg": "FVG" in confluences,
        "eq": "EQH/EQL" in confluences,
        "idm": "IDM" in confluences,
        "time": "TIME_LIQ" in confluences,
    }
