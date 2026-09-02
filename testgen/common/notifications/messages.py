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

# Webhook fields
WEBHOOK_TYPE_REQUIRED = "Webhook type is required."
WEBHOOK_URL_REQUIRED = "Webhook URL is required."
WEBHOOK_URL_NOT_HTTPS = "Webhook URL must start with https://."
WEBHOOK_URL_INVALID = "Webhook URL is not a valid URL."
WEBHOOK_URL_ADDRESS_REFUSED = "Webhook URL resolves to an address that is not allowed."
WEBHOOK_PROXY_UNVERIFIABLE = (
    "Webhook delivery cannot verify the destination address through an HTTP proxy."
)
WEBHOOK_AUTH_HEADER_NAME_MISSING = "Authorization header name is required when a header value is set."
WEBHOOK_AUTH_HEADER_NAME_INVALID = "Authorization header name is not valid."
WEBHOOK_AUTH_HEADER_ONLY_GENERIC = "Authorization headers are only supported on the generic webhook type."
WEBHOOK_AUTH_HEADER_NAME_RESERVED = "Authorization header name is reserved and cannot be overridden."
WEBHOOK_AUTH_HEADER_REQUIRED_FOR_NEW_URL = (
    "Re-enter the authorization header value to send a test to a different URL."
)

# Lookups
DESTINATION_NOT_FOUND = "Destination not found in this project."
DESTINATION_TYPE_IMMUTABLE = (
    "A destination's type cannot be changed. Delete this destination and create a new one."
)


def name_already_exists(name: str) -> str:
    return f"A destination named '{name}' already exists in this project."


def invalid_email(address: str) -> str:
    return f"{address} is not a valid email address."


def score_threshold_out_of_range(label: str) -> str:
    return f"The {label} score threshold must be between 0 and 100."


def unsupported_destination_type(destination_type: str | None) -> str:
    return f"Unsupported destination type: {destination_type}."


def invalid_webhook_type(webhook_type: str | None) -> str:
    return f"Invalid webhook type: {webhook_type}."
