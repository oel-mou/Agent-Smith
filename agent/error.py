class AgentError(Exception):
    """Base class for all agent-related errors."""

    pass


class LLMError(AgentError):
    """Base class for LLM-related errors."""

    def __init__(self, message: str):
        super().__init__(f"LLMError: {message}")


class ParsingError(AgentError):
    """Base class for parsing-related errors."""

    def __init__(self, message: str):
        super().__init__(f"ParsingError: {message}")


class SandboxError(AgentError):
    """Base class for sandbox-related errors."""

    def __init__(self, message: str):
        super().__init__(f"SandboxError: {message}")
