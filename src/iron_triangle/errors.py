"""Error types shared across the Iron Triangle bridge."""


class BridgeError(RuntimeError):
    """Operator-facing failure. Rendered as JSON on stderr with exit code 2."""


class PolicyViolation(BridgeError):
    """A fail-closed invariant was about to be broken."""


class EventStreamTruncated(BridgeError):
    """An append-only event stream shrank; the watcher must stop fail-closed."""
