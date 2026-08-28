"""Canonical validation messages for notification rules and destinations.

Single source of truth used by the ORM validators, the UI dialogs, the MCP tools,
and the REST endpoints so a receiver can rely on message stability across surfaces.
Do not duplicate these strings.
"""


# Addressing (rules)
ADDRESSING_BOTH = "A notification rule must address either a recipient list or a destination, not both."
ADDRESSING_NEITHER = "A notification rule must address either a recipient list or a destination."

# Destination fields
NAME_REQUIRED = "Destination name is required."
NAME_TOO_LONG = "Destination name is too long (max 100 characters)."
RECIPIENTS_REQUIRED = "At least one recipient is required."

# Rule fields
INVALID_TRIGGER = "Invalid notification trigger."
SCORE_THRESHOLD_MISSING = "At least one score threshold must be set."

# Lookups
DESTINATION_NOT_FOUND = "Destination not found in this project."


def name_already_exists(name: str) -> str:
    return f"A destination named '{name}' already exists in this project."


def invalid_email(address: str) -> str:
    return f"{address} is not a valid email address."


def score_threshold_out_of_range(label: str) -> str:
    return f"The {label} score threshold must be between 0 and 100."


def unsupported_destination_type(destination_type: str | None) -> str:
    return f"Unsupported destination type: {destination_type}."
