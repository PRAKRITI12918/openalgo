"""
brokers.py - Dynamic Schema-Driven Broker Registry for OpenAlgo.

Single Source of Truth for 37+ Indian and Global Brokerage APIs.
Provides schema validation, field metadata, documentation URLs,
and connection testing abstractions without hardcoded if/else branching.
"""

import json
import os
import re
from typing import Any


def _load_schema_from_json() -> dict[str, Any]:
    """Load the central broker schema from broker_schema.json."""
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "broker_schema.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": "1.0.0", "brokers": {}, "categories": ["All", "Discount", "Full-Service", "XTS", "Crypto", "Sandbox"]}


# Central In-Memory Schema Registry
BROKER_SCHEMA_REGISTRY: dict[str, Any] = _load_schema_from_json()


def get_all_brokers() -> dict[str, Any]:
    """Retrieve metadata and field schemas for all registered brokers."""
    return BROKER_SCHEMA_REGISTRY.get("brokers", {})


def get_broker_schema(broker_id: str) -> dict[str, Any] | None:
    """Get the field definition and configuration schema for a specific broker."""
    brokers = get_all_brokers()
    return brokers.get(broker_id.lower().strip())


def validate_broker_credentials(broker_id: str, credentials: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate submitted credentials against the broker's schema.

    Returns:
        (is_valid, error_message)
    """
    schema = get_broker_schema(broker_id)
    if not schema:
        return False, f"Unknown broker identifier: '{broker_id}'"

    fields = schema.get("fields", [])
    for field in fields:
        field_name = field.get("name")
        label = field.get("label", field_name)
        val = str(credentials.get(field_name, "")).strip()

        # Check required fields
        if field.get("required") and not val:
            return False, f"Missing required field: '{label}' for {schema.get('name', broker_id)}"

        # Check regex validation if present and value is provided
        validation_pattern = field.get("validation")
        if validation_pattern and val and val != "************":
            try:
                if not re.match(validation_pattern, val):
                    return False, f"Invalid format for '{label}'. Please check the requirements."
            except re.error:
                pass

    return True, None


def get_broker_categories() -> list[str]:
    """Get all available broker classification categories."""
    return BROKER_SCHEMA_REGISTRY.get("categories", ["All", "Discount", "Full-Service", "XTS", "Crypto", "Sandbox"])


def get_broker_docs_url(broker_id: str) -> str:
    """Get documentation URL for a specific broker."""
    schema = get_broker_schema(broker_id)
    if schema and schema.get("docs_url"):
        return schema["docs_url"]
    return f"https://docs.openalgo.in/connect-brokers/brokers/{broker_id}"
