"""Structured error taxonomy.

Anything that can go wrong in ORCA maps to one of these, so that the API layer
can turn a failure into a *typed*, user-explainable warning rather than a 500.
"""

from __future__ import annotations


class OrcaError(Exception):
    code = "orca_error"
    user_message = "ORCA could not complete this request."

    def __init__(self, message: str = "", **context):
        super().__init__(message or self.user_message)
        self.message = message or self.user_message
        self.context = context

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "context": self.context}


class ProviderError(OrcaError):
    code = "provider_error"
    user_message = "A marine data source could not be reached."


class ProviderTimeout(ProviderError):
    code = "provider_timeout"
    user_message = "A marine data source did not respond in time."


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    user_message = "A marine data source is currently unavailable."


class ProviderNotConfigured(ProviderError):
    code = "provider_not_configured"
    user_message = "This data source is not configured in this deployment."


class ProviderPayloadError(ProviderError):
    code = "provider_payload_error"
    user_message = "A marine data source returned data ORCA could not interpret."


class AgentError(OrcaError):
    code = "agent_error"
    user_message = "An ORCA agent failed."


class AgentTimeout(AgentError):
    code = "agent_timeout"
    user_message = "An ORCA agent exceeded its time budget."


class LocationNotFound(OrcaError):
    code = "location_not_found"
    user_message = "ORCA could not identify that location."


class TimeNotUnderstood(OrcaError):
    code = "time_not_understood"
    user_message = "ORCA could not work out which time you meant."


class InsufficientEvidence(OrcaError):
    code = "insufficient_evidence"
    user_message = (
        "ORCA does not have enough current data to make a safety judgement."
    )


class UnsupportedCapability(OrcaError):
    code = "unsupported_capability"
    user_message = "That capability is not implemented in this prototype."
