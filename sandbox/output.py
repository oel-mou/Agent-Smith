import io
from typing import BinaryIO, Literal
from pydantic import BaseModel, Field


class BoundedTextCapture(io.TextIOBase):
    """Capture a bounded UTF-8 prefix of a text stream."""
    def __init__(self, file: BinaryIO, limit: int) -> None:
        """Store the output file and byte limit."""
        self._file = file
        self._capacity = limit + 1  # One extra byte marks truncated output.
        self._written = 0

    def writable(self) -> bool:
        """Return True because this stream accepts writes."""
        return True

    def write(self, text: str) -> int:
        """Capture available bytes and return the input character count."""
        remaining = self._capacity - self._written

        if remaining > 0:
            # convert to bytes, replacing invalid characters with backslash escapes
            # why? Because the 
            data = text[:remaining].encode(
                "utf-8", errors="backslashreplace"
            )[:remaining]

            written = self._file.write(data)
            self._written += written

        return len(text)

    def flush(self) -> None:
        """Flush buffered output to the backing file."""
        self._file.flush()

    def close(self) -> None:
        """Flush the stream and close its backing file."""
        if not self.closed:
            try:
                super().close()
            finally:
                self._file.close()


class MCPToolError(RuntimeError):
    """An MCP tool call failed."""


class SandboxError(BaseModel):
    """Describe an execution failure and its optional MCP operation."""
    kind: Literal[
        "syntax", "runtime", "security", "mcp", "infrastructure"
    ]
    type: str
    message: str
    tool_name: str | None = None


class SandboxResult(BaseModel):
    """Hold execution status, captured streams, errors, and a final answer."""
    status: Literal[
        "ok",
        "final_answer",
        "error",
        "timeout",
        "memory_limit",
        "child_crash",
    ]

    stdout: str = ""
    stderr: str = ""
    final_answer: str | None = None
    error: SandboxError | None = None
    output_partial: bool = False

    truncated_streams: list[str] = Field(default_factory=list)
