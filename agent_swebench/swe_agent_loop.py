from agent import (SWEBenchTaskInput, StepMetrics,
                   SolutionOutput, ExtractorOutput,
                   LLMResult, LLMResultStatus,
                   SWEBENCH_SYSTEM_INSTRUCTIONS,
                   extract_code, load_task,
                   get_provider)

from sandbox.sandbox import Sandbox
from sandbox.config import SandboxConfig
from sandbox.output import SandboxResult

from dataclasses import dataclass
import time
import json
import signal
import sys

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


@dataclass
class RequestData:
    finished_task: bool = False
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    start_time: float = time.monotonic()


class GracefullExit(Exception):
    pass


class SWEBenchAgentLoop:
    def __init__(self, model_name: str, provider_url: str):
        self.provider = get_provider(model_name, provider_url,
                                     300_000, 10_000)
        self.data = RequestData()
        self.steps = []
        signal.signal(signal.SIGTERM, self.clean_shutdown)

    def clean_shutdown(self, signum, frame) -> None:
        """Handle the Timeout by converting SIGTERM to GracefullExit"""
        raise GracefullExit(f"Caught signal {signum}")

    def _init_sandbox(self, task_file: str):
        """Initialise the sandbox"""
        self.sandbox = Sandbox(config=SandboxConfig(),
                               max_output_bytes=20_000,
                               mcp_stdio="python -m"
                                         "mcp_tools_swebench "
                                         f"--task-file {task_file}")
        self.sandbox.start()

    def _init_context(self, task: SWEBenchTaskInput) -> list[dict[str, str]]:
        """
        Initialise the base context, which is the system prompt
        and the user request
        """
        system_prompt = (f"{SWEBENCH_SYSTEM_INSTRUCTIONS}{self.sandbox.get_manual()}")

        # add task.hints if there is any.
        user_prompt = (f"User requeste: {task.problem_statement}\n"
                       f"hints: {task.hints_text}" if task.hints_text else "")

        self.context = [{
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        }]

    def _update_context(self, model_answer: LLMResult,
                        observation: SandboxResult) -> None:
        """
        Update the context by adding the model output as assistant role
        and sandbox output as user role.
        """
        if model_answer.thought:
            assistant_context = (f"Thought:\n{model_answer.thought}\n\n"
                                 f"Action:\n{model_answer.content}")
        else:
            assistant_context = (f"\n{model_answer.content}")

        # We can give this format to the model directly, it handles it.
        self.context.extend([{
            "role": "assistant",
            "content": assistant_context
        },
        {
            "role": "user",
            "content": f"output: {observation.stdout}\n\n"
                       f"errors: {observation.stderr}"
        }])

    def _update_steps(self, index: int,
                   model_response: LLMResult,
                   code: ExtractorOutput, observation: SandboxResult) -> None:
        """Add a step to the list self.steps"""
        self.steps.append(
            StepMetrics(
                step=index,
                input_tokens=model_response.input_tokens,
                output_tokens=model_response.output_tokens,
                request_time_ms=model_response.request_time_ms,
                api_url=self.provider.provider_url,
                model_name=self.provider.model_name,
                llm_output=f"{model_response.thought}\n\n{model_response.content}",
                sandbox_input=code.result,
                sandbox_output="\n".join([observation.stdout, observation.stderr]),
                retries=model_response.retries
            )
        )

    def _update_crashed_step(self, index: int, model_response: LLMResult) -> None:
        """Add the step that crashed due to buggy model output"""
        if model_response:
            model_answer = model_response.thought if model_response.thought else ""
            model_answer += model_response.content if model_response.content else ""
        else:
            model_answer = ""

        self.steps.append(
            StepMetrics(
                step=index,
                input_tokens=model_response.input_tokens,
                output_tokens=model_response.output_tokens,
                request_time_ms=model_response.request_time_ms,
                api_url=self.provider.provider_url,
                model_name=self.provider.model_name,
                llm_output=model_answer,
                sandbox_input="",
                sandbox_output="",
                retries=model_response.retries
            )
        )

    def _update_data(self, model_answer: LLMResult) -> None:
        """Update the values of the dataclass RequestData"""
        self.data.total_input_tokens += model_answer.input_tokens
        self.data.total_output_tokens += model_answer.output_tokens
        self.data.total_requests += model_answer.retries + 1

    def run_task_from_file(self,
                        task_file: str,
                        output_file: str) -> SolutionOutput:
        """Run the swebench agent on a task loaded from a JSON file."""

        task: SWEBenchTaskInput = load_task(task_file, "swebench")
        print(f"Loaded task: {task.instance_id}")

        try:
            self._init_sandbox(task_file)
            self._init_context(task)
            solution: SolutionOutput = self.run(task)
        finally:
            self.sandbox.close()

        # Write the solution to the output JSON file
        with open(output_file, "w") as f:
            json.dump(solution.model_dump(), f, indent=4)
            print(f"solution has been put in {output_file}")

        return solution

    def run(self, task: SWEBenchTaskInput):
        max_iterations = 30

        for i in range(1, max_iterations + 1):
            # error = "" so no old error get written to the solution
            #
            # observation start with a status of error except if overwriten
            # So if a crash happen from the beginning observation will already 
            # be defined.
            error = ""
            observation = SandboxResult(status='error')
            try:
                model_answer = self.provider.send_request(messages=self.context,
                                                          reasoning='low',
                                                          stop=["<end_code>"],
                                                          timeout=30)

                # Handle error in the model output.
                if model_answer.status != LLMResultStatus.OK:
                    print("not ok status", file=sys.stderr)
                    self._update_crashed_step(i, model_answer)
                    self._update_data(model_answer)
                    error = "Error during the model answer"
                    continue

                # Extract code in the model output,
                # and add all errors to the observation errors.
                code = extract_code(model_answer.content)
                if code.result:
                    observation = self.sandbox.run(code.result)
                if code.error:
                    observation.stderr += f"\n error while parsing code: {code.error}"
                if observation.error:
                    observation.stderr += ("error found in the answered "
                                           f"code: {observation.error.message}")

                # Update the steps, context and data.
                self._update_steps(i, model_answer, code, observation)
                self._update_context(model_answer, observation)
                self._update_data(model_answer)

                # Debug print
                print(f"{bcolors.OKBLUE} {self.context[-2]['content']} {bcolors.ENDC}")
                print(f"{bcolors.OKCYAN} {code.result} {bcolors.ENDC}")
                print(f"{bcolors.OKGREEN} {observation.stdout} {bcolors.ENDC}")
                print(f"{bcolors.WARNING} {observation.stderr} {bcolors.ENDC}")

                # if final answer found, the model finished the task.
                if observation.final_answer:
                    self.data.finished_task = True
                    break

            # Catch error if found one, and place it in final result.
            except Exception as e:
                error = str(e)
                break

        # the last step the model did if it solved the task
        solution = observation.stdout if self.data.finished_task else ""
        if not error and i == max_iterations:
            error = "Reached the max_iterations"

        return SolutionOutput(
            task_id=task.instance_id,
            benchmark="swebench",
            success=self.data.finished_task,
            solution=solution,
            system_prompt=self.context[0]["content"],
            iterations=i,
            total_requests=self.data.total_requests,
            total_input_tokens=self.data.total_input_tokens,
            total_output_tokens=self.data.total_output_tokens,
            total_time_seconds=int(time.monotonic() - self.data.start_time),
            steps=self.steps,
            error=error
        )
