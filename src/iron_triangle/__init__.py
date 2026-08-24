"""Iron Triangle protocol tooling: controller-agnostic bridge core."""

TOOL_VERSION = "0.3.2"

# Bump when the runtime-config shape changes; see config.py for migrations
# and schemas/runtime-config.schema.json for the published contract.
CONFIG_SCHEMA_VERSION = 2

__all__ = ["TOOL_VERSION", "CONFIG_SCHEMA_VERSION"]
