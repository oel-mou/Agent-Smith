from enum import Enum, auto
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class LLMResultStatus(Enum):
    """Enum representing the status of an LLM result."""

    OK = auto()
    EMPTY_DUE_TO_LENGTH = auto()
    TRUNCATED_CONTENT = auto()
    REFUSAL = auto()
    ERROR = auto()


class LLMResult(BaseModel):
    """Result of an LLM call, including status, content, and token usage."""

    status: LLMResultStatus
    content: str | None = Field(default=None)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    retries: int = Field(default=0)
    request_time_ms: float
    finish_reason: str | None = Field(default=None)
    raw_error: str | None = None
    thought: str | None = None


class MBPPTaskInput(BaseModel):
    """Input for MBPP task evaluation."""

    task_id: int
    task_definition: str
    function_definition: str
    test_imports: List[str] = Field(default_factory=list)
    test_list: List[str] = Field(default_factory=list)


class SWEBenchTaskInput(BaseModel):
    """Input for a SWE-bench task, provided by the moulinette.
    Your agent receives this and must produce a git patch that fixes
    the issue.
    """
    instance_id: str
    problem_statement: str
    docker_image: str
    eval_script: str
    hints_text: str = Field(default="")
    repo: str = Field(default="")


class StepMetrics(BaseModel):
    """Metrics for a single agent step."""
    step: int
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    api_url: str
    model_name: str
    llm_output: str
    sandbox_input: str
    sandbox_output: str
    retries: int
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class SolutionOutput(BaseModel):
    """Output from student solution - this is what students must
    produce."""
    task_id: str
    benchmark: str  # "mbpp" or "swebench"
    success: bool
    solution: str  # Code for MBPP, patch for SWE-bench
    system_prompt: str
    iterations: int
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_time_seconds: float
    steps: List[StepMetrics] = Field(default_factory=list)
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())