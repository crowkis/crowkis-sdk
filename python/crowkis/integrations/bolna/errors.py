"""The one error the Bolna adapter raises on its own."""

from ...client import CrowkisError


class CrowkisBolnaError(CrowkisError):
    """Setting up the Crowkis provider in Bolna failed (an unknown or unusable base provider).

    Never raised during a call: a failure inside a live call fails open to Bolna's own LLM."""

    retryable = False
