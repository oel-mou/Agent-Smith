import json

from typing import List, Optional

from agent import LLM, LLMResult
from agent.models import MBPPTaskInput, SolutionOutput, StepMetrics
from agent.parsing import load_task, Args
from agent.prompts import MBPP_SYSTEM_PROMPT, MBPP_EXAMPLE
from agent.error import AgentError
from agent.extractor import extract_python, ExtractorOutput
from sandbox.sandbox import Sandbox, SandboxResult, SandboxConfig

# ANSI Color Codes
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

MAX_ITERATIONS = 10
MAX_INPUT_TOKENS = 6000
MAX_OUTPUT_TOKENS = 1500
TASK_TIMEOUT_SECONDS = 120

REASONING_EFFORT = "none"  # Reasoning effort level for the LLM requests
MAX_ITERATION_TOKEN_LIMIT = None  # Maximum tokens allowed for each LLM request


class MBPPAgent:
    def __init__(
        self,
        model_name: str,
        provider_url: str,
        api_keys: dict,
        args: Optional[Args] = None,
    ):
        self.llm: LLM = LLM(
            model_name=model_name,
            provider_url=provider_url,
            api_keys=api_keys,
            max_input_tokens=MAX_INPUT_TOKENS,
            max_output_tokens=MAX_OUTPUT_TOKENS
        )
        self.input_tokens_used: int = 0
        self.output_tokens_used: int = 0
        self.step_counter: int = 0
        self.steps: List[StepMetrics] = []
        self.args: Args = args
        self.sanbox = self._init_sandbox()

    def stop(self) -> None:
        """Stop the sandbox and clean up resources."""
        if self.sanbox:
            self.sanbox.close()
            print(f"{BLUE}Sandbox stopped.{RESET}")

    def run(self, task: MBPPTaskInput) -> SolutionOutput:
        """Run the MBPP agent on a given task."""
        try:
            # Prepare the messages for the LLM
            system_prompt = self._build_system_prompt()
            initial_user_context = self._build_user_context(task)
            user_context = initial_user_context

            for _ in range(MAX_ITERATIONS):
                messages = [
                    {
                        "role": "system",
                        "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_context},
                ]

                # Generate a solution using the LLM
                print(f"\n\n{RED}====================================={RESET}")
                print(f"{MAGENTA}USER CONTEXT:\n{user_context}{RESET}")

                llm_response: LLMResult = self.llm.send_request(
                    messages=messages,
                    reasoning=REASONING_EFFORT,
                    max_tokens=MAX_ITERATION_TOKEN_LIMIT,
                    stop=["<end_code>"]
                )
                self._update_tokens_used(llm_response)
                print(f"{BLUE}LLM Response:\n{llm_response}{RESET}")

                extra: ExtractorOutput = extract_python(llm_response.content)
                if extra.error:
                    user_context = self._update_user_context(
                        llm_response,
                        "You must define src=function code and call run_tests(code=src) to check it.",
                        initial_user_context)
                    continue
                code = extra.result
                print(f"\n{YELLOW}Extracted Code:\n{code}{RESET}")

                result: SandboxResult = self.sanbox.run(code)
                print(f"\n{GREEN}Sandbox Result:\n{result}{RESET}")
                print(f"{RED}========================================={RESET}")

                self._update_steps(code, llm_response, result)
                user_context = self._update_user_context(llm_response,
                                                         result,
                                                         initial_user_context)
                if result.final_answer:
                    break

            # print(f"{GREEN} {self.steps}{RESET}")

            solution = SolutionOutput(
                task_id=str(task.task_id),
                benchmark="mbpp",
                success=True,
                solution=result.stdout.strip(),
                system_prompt=system_prompt,
                iterations=len(self.steps),
                total_requests=sum([step.retries + 1 for step in self.steps]),
                total_input_tokens=sum([step.input_tokens for step in self.steps]),
                total_output_tokens=sum([step.output_tokens for step in self.steps]),
                total_time_seconds=sum([(step.request_time_ms/1000) for step in self.steps]),
                steps=self.steps,
            )

            return solution
        except Exception as e:
            print(f"{RED}Error during task execution: {e}{RESET}")
            return SolutionOutput(
                task_id=str(task.task_id),
                benchmark="mbpp",
                success=False,
                solution="",
                system_prompt=system_prompt,
                iterations=len(self.steps),
                total_requests=sum([step.retries + 1 for step in self.steps]),
                total_input_tokens=sum([step.input_tokens for step in self.steps]),
                total_output_tokens=sum([step.output_tokens for step in self.steps]),
                total_time_seconds=sum([(step.request_time_ms/1000) for step in self.steps]),
                steps=self.steps,
                error=str(e))

    def run_task_from_file(self, task_file: str) -> SolutionOutput:
        """Run the MBPP agent on a task loaded from a JSON file."""
        task: MBPPTaskInput = load_task(task_file, "mbpp")
        print(f"Loaded task: {task.task_id}")
        solution: SolutionOutput = self.run(task)
        return solution

    def save_solution_to_file(self, solution: SolutionOutput, output_file: str) -> None:
        """Save the solution to a JSON file."""

        def _save_solution(solution: SolutionOutput,
                           output_file: str) -> None:
            """Save the solution to a JSON file."""
            with open(output_file, "w") as f:
                json.dump(solution.model_dump(), f, indent=4)
                print(f"{GREEN}Solution saved to {output_file}{RESET}")

        def _create_path_and_save(solution: SolutionOutput,
                                  output_file: str) -> None:
            """Create the directory for the output file and save the solution."""
            import os
            print(f"{YELLOW}Attempting to create the directory for the output file...{RESET}")
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            _save_solution(solution, output_file)

        try:
            _save_solution(solution, output_file)
        except FileNotFoundError:
            print(f"{RED}Error: Output file path '{output_file}' not found.{RESET}")
            _create_path_and_save(solution, output_file)

    def _allowed_token_limit(self) -> int:
        """Calculate the maximum tokens allowed for the LLM request."""
        res = MAX_OUTPUT_TOKENS - self.output_tokens_used
        print(f"{YELLOW}Allowed token limit for LLM request: {res}{RESET}")
        if res <= 0:
            raise AgentError(
                f"Input token limit exceeded: {self.output_tokens_used}/{MAX_OUTPUT_TOKENS}"
            )
        return res

    def _update_tokens_used(self, llm_result: LLMResult) -> None:
        self.input_tokens_used += llm_result.input_tokens
        self.output_tokens_used += llm_result.output_tokens

    def _build_user_context(self, task: MBPPTaskInput) -> str:
        tests = "\n".join(task.test_list)
        user_context = (
            f"Task Difinition: {task.task_definition}\n\n"
            f"Function Signature: {task.function_definition}\n\n"
            f"Tests:\n{tests}"
        )
        return user_context

    def _update_user_context(self,
                             llm_response: LLMResult,
                             result: SandboxResult | str,
                             user_context: str) -> None:

        if isinstance(result, SandboxResult) and result.status == "ok":
            sandbox_output = result.stdout.strip()
        else:
            sandbox_output = str(result)

        new_context = (
            f"{user_context}"
            f"\n\nAssisstant = {llm_response.content}"
            f"\n\nObservation = {sandbox_output}")

        if "'success': True" in sandbox_output:
            new_context += ("\n\nDefine src with the source code "
                            "you just tested and call final_answer(src).")
        else:
            new_context += ("\n\nYou must fix the code and call "
                            "run_tests(code=src) with the fixed code.")
        return new_context
        # print(f"{YELLOW}UPDATED PROMPT: \n{user_context}{RESET}")

    def _build_system_prompt(self) -> str:
        tmp = (f"{MBPP_SYSTEM_PROMPT}\n\n"
               f"{self.sanbox.get_mcp_tools()}\n\n"
               f"{MBPP_EXAMPLE}")
        print(f"{YELLOW}Initialized system prompt:\n{tmp}{RESET}")
        return tmp

    def _update_steps(
            self,
            code: str,
            model_response: LLMResult,
            sandbox_result: SandboxResult) -> None:
        """Update the steps list with the latest step metrics."""
        self.step_counter += 1
        step = StepMetrics(
            step=self.step_counter,
            input_tokens=model_response.input_tokens,
            output_tokens=model_response.output_tokens,
            request_time_ms=model_response.request_time_ms,
            api_url=self.llm.provider_url,
            model_name=self.llm.model_name,
            llm_output=model_response.content,
            sandbox_input=code if code else "",
            sandbox_output=str(sandbox_result),
            retries=model_response.retries,
        )
        self.steps.append(step)

    def _init_sandbox(self) -> Sandbox:
        # try:
        print(f"{BLUE}Initializing Sandbox...{RESET}")
        conf = SandboxConfig()
        sandbox = Sandbox(
            config=conf,
            mcp_stdio=self.args.mcp_stdio if self.args else None,
            mcp_server=self.args.mcp_server if self.args else None,
        )
        sandbox.start()
        return sandbox
        # except Exception as e:
        #     raise SandboxError(f"Failed to initialize Sandbox. Error: {e}")
