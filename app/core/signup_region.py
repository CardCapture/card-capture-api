"""
Region preference for sign-up sheets.

Sign-up sheets have no reliable city/state column, so school search and address
lookup need a hint. Mississippi College is the only school using sign-up sheets,
so this is a plain constant: Mississippi first, then its neighbors, then
everywhere else. Make it a per-school setting if another school adopts sheets.
"""

SIGNUP_HOME_STATE = "MS"

# Checked in order after the row's own state
SIGNUP_PREFERRED_STATES = ["MS", "LA", "AL", "TN", "AR"]

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
}


def signup_state_search_order(row_state: str = "") -> list:
    """The row's own state (if it's a real US state), then the preferred region."""
    row_state = (row_state or "").strip().upper()
    order = [row_state] if row_state in US_STATE_CODES else []
    return order + [s for s in SIGNUP_PREFERRED_STATES if s not in order]
