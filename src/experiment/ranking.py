"""Ranking formulas for daily signal prioritisation.

Given a set of signals firing on the same day, rank them so the top N
get sent. Each formula is a callable that takes a record dict and returns
a numeric score (higher = better).
"""


def _flags_count(flags):
    return sum([flags.get("fvg", False), flags.get("eq", False),
                flags.get("idm", False), flags.get("time", False)])


# Each formula takes a signal record with keys:
#   rr     -> planned R:R
#   flags  -> {"fvg", "eq", "idm", "time"}
#   hour   -> UTC hour
# and returns a numeric score (higher = preferred).

RANK_FORMULAS = {
    "F1_RR_only": lambda r: r["rr"],

    "F2_ConfluenceCount": lambda r: _flags_count(r["flags"]) * 10 + r["rr"],

    "F3_IDM_priority": lambda r: (100 if r["flags"]["idm"] else 0) + r["rr"],

    "F4_Detailed": lambda r: (
        r["rr"] * 1.0
        + (3.0 if r["flags"]["idm"] else 0)
        + (1.0 if r["flags"]["eq"] else 0)
        + (0.5 if r["flags"]["fvg"] else 0)
        + (0.5 if r["flags"]["time"] else 0)
    ),

    "F5_Random": None,  # handled with random tiebreak
}

FORMULA_DESCRIPTIONS = {
    "F1_RR_only": "Rank by planned R:R (highest first)",
    "F2_ConfluenceCount": "Rank by number of confluences, tiebreak by R:R",
    "F3_IDM_priority": "Signals with IDM first, then by R:R",
    "F4_Detailed": "R:R + 3×IDM + 1×EQ + 0.5×FVG + 0.5×TIME",
    "F5_Random": "Random selection (control)",
}
