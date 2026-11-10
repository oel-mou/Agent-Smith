import time
import tiktoken

from openai import (OpenAI, APIStatusError, AuthenticationError, OpenAIError)

from agent.error import LLMError
from agent.models import LLMResult, LLMResultStatus

RED = "\033[91m"
GREEN = "\033[92m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

MAX_RETRIES = 10  # Maximum number of retries for API requests
RATE_LIMIT_THRESHOLD = 2  # Threshold for rate limit errors before banning an API key


class LLM:
    """A class to interact with the OpenAI LLM API, handling multiple API keys and errors."""

    def __init__(self,
                 model_name: str,
                 provider_url: str,
                 api_keys: list[str],
                 max_input_tokens: int,
                 max_output_tokens: int):

        self.model_name = model_name
        self.provider_url = provider_url
        self.api_keys = api_keys
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens

        self.encoder = tiktoken.get_encoding("cl100k_base")
        self.ratelimit_counter = {idx: 0 for idx in range(len(api_keys))}
        self.active_api_key_index = 0
        self.banned_api_keys = set()
        self.attempts = 0
        self.client = OpenAI(
            api_key=self.api_keys[self.active_api_key_index],
            base_url=provider_url
        )

    def send_request(self,
                     messages: list[dict],
                     reasoning: str | None = None,
                     max_tokens: int | None = None,
                     stop: list[str] | str | None = None,
                     timeout: int = 10):
        """Send a request to the LLM, handling retries and errors.
        Args:
            messages (list[dict]): The messages to send to the LLM.
            reasoning (str | None): Optional reasoning for the request.
            stop (list[str] | None): Optional stop sequences for the LLM.
        Returns:
            LLMResult: The result of the LLM request, including status, content, and token usage.
        Raises:
            LLMError: If an error occurs during the request.
        """
        self.attempts = 0
        self._verify_token_limits(messages)
        for _ in range(MAX_RETRIES):
            try:
                self.attempts += 1
                result = self._send_request_internal(messages, reasoning,
                                                     max_tokens, stop,
                                                     timeout)
                self._update_token_limits(result)
                return result
            except AuthenticationError as e:
                print(f"{RED}Authentication error with API key index "
                      f"{self.active_api_key_index}: {e}{RESET}")
                self._ban_current_key()           # permanent
                self._rotate_api_key()
            except APIStatusError as e:
                print(f"{RED}API status error with API key index "
                      f"{self.active_api_key_index}: {e}{RESET}")

                self.ratelimit_counter[self.active_api_key_index] += 1
                if self.ratelimit_counter[self.active_api_key_index] > RATE_LIMIT_THRESHOLD:
                    self._ban_current_key()           # permanent
                self._rotate_api_key()            # no permanent ban
                if self.attempts % len(self.api_keys) == 0:
                    time.sleep(min(2 ** (self.attempts // len(self.api_keys)), 10))
            except OpenAIError as e:
                raise LLMError(f"OpenAI error: {e}") from e
        raise LLMError("Max retries exceeded. "
                       "All API keys may be exhausted or failed.")

    def _update_token_limits(self, llm_response: LLMResult) -> None:
        """Update the token limits based on the LLM response."""
        self.max_input_tokens -= llm_response.input_tokens
        self.max_output_tokens -= llm_response.output_tokens

    def _ban_current_key(self) -> None:
        """Ban the current API key and rotate to the next one."""
        self.banned_api_keys.add(self.active_api_key_index)
        if len(self.banned_api_keys) == len(self.api_keys):
            raise LLMError("All API keys have been banned.")
        print(f"{RED}Banned API key index: {self.active_api_key_index}{RESET}")

    def _rotate_api_key(self) -> None:
        """Rotate to the next API key in the list."""

        if len(self.banned_api_keys) == len(self.api_keys):
            raise LLMError("All API keys have been banned.")
        for _ in range(len(self.api_keys)):
            self.active_api_key_index = (self.active_api_key_index + 1) % len(self.api_keys)
            if self.active_api_key_index not in self.banned_api_keys:
                break
        self.client = OpenAI(
            api_key=self.api_keys[self.active_api_key_index],
            base_url=self.provider_url
        )
        print(f"Rotated to API key index: {self.active_api_key_index}")

    def _verify_token_limits(self, message: list[dict]):
        """
        Estimate if we reached or not the
        input and output tokens limit,
        """

        # A security of 15% because the tokenizer
        # can be unaccurate based on the model
        security = 15 / 100
        text = "".join([val for i in message for val in i.values()])

        estimation = len(self.encoder.encode(text))
        estimation = estimation + int(estimation * security)

        if estimation >= self.max_input_tokens:
            raise LLMError("Max input token reached")

        if self.max_output_tokens <= 0:
            raise LLMError("Not enought output tokens remaining")

    def _get_max_tokens(self, max_tokens: int | None) -> int:
        """
        Get the max tokens to use for the request.
        If max_tokens is None, use the remaining output tokens.
        """
        if max_tokens is None:
            return self.max_output_tokens
        return min(max_tokens, self.max_output_tokens)

    def _send_request_internal(self,
                               messages: list[dict],
                               reasoning: str | None = None,
                               max_tokens: int | None = None,
                               stop: list[str] | str | None = None,
                               timeout: int = 10) -> LLMResult:
        """Send a request to the LLM and handle errors.
        Args:
            messages (list[dict]): The messages to send to the LLM.
            reasoning (str | None): Optional reasoning for the request.
            stop (list[str] | None): Optional stop sequences for the LLM.
        Returns:
            LLMResult: The result of the LLM request, including status, content, and token usage.
        Raises:
            LLMError: If an error occurs during the request.
        """
        start = time.perf_counter()
        completion = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            max_tokens=self._get_max_tokens(max_tokens),
            reasoning_effort=reasoning,
            stop=stop,
            timeout=timeout  # Set a timeout for the request
        )
        end = time.perf_counter()
        print(f"{GREEN}LLM Completion )Response:\n{completion}{RESET}")

        choice = completion.choices[0]
        content = choice.message.content if choice.message.content else ""
        finish_reason = choice.finish_reason
        input_tokens = completion.usage.prompt_tokens
        output_tokens = completion.usage.completion_tokens
        request_time_ms = (end - start) * 1000  # Convert to milliseconds

        if reasoning and hasattr(choice.message, "reasoning"):
            thought = choice.message.reasoning
        else:
            thought = None

        if content is None:
            return LLMResult(
                status=LLMResultStatus.EMPTY_DUE_TO_LENGTH,
                content=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_time_ms=request_time_ms,
                retries=self.attempts - 1,
                finish_reason=finish_reason,
                raw_error=None,
                thought=thought,
            )

        if finish_reason == "length":
            return LLMResult(
                status=LLMResultStatus.TRUNCATED_CONTENT,
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_time_ms=request_time_ms,
                retries=self.attempts - 1,
                finish_reason=finish_reason,
                raw_error=None,
                thought=thought,
            )

        return LLMResult(
            status=LLMResultStatus.OK,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_time_ms,
            retries=self.attempts - 1,
            finish_reason=finish_reason,
            raw_error=None,
            thought=thought,
        )


def get_provider(model_name: str, url: str,
                 max_input_tokens: int,
                 max_output_tokens: int) -> LLM:
    """Return the right provider based on the name found in the url"""
    from agent.parsing import get_api_keys
    api_keys = get_api_keys(url)

    return LLM(model_name, url,
               api_keys,
               max_input_tokens,
               max_output_tokens)