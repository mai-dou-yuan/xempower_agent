from __future__ import annotations


class AgentError(Exception):
    """Expected application error with a stable API code."""

    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CSVValidationError(AgentError):
    pass

