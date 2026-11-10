try:
    import asyncio
    import ast
    import sys
    import textwrap
    import os
    import json

    from fastmcp import FastMCP

    from agent.docker_manager import DockerManager
    from agent.models import MBPPTaskInput
    from agent.parsing import ServerArgs, get_server_args, load_task

    mcp = FastMCP("Agent Smith: MBPP Tools")

    RED = "\033[91m"
    GREEN = "\033[92m"
    RESET = "\033[0m"
    YELLOW = "\033[93m"

    TEST_TIMEOUT_SECONDS = 10
    TIMEOUT_EXIT_CODE = 124
    MAX_OUTPUT_CHARS = 600
    TRACEBACK_TAIL_LINES = 6

    DOCKER_IMAGE = "python:3.11-slim"
    DOCKER_WORKDIR = "/"
    DOCKER_CONTAINER_NAME = "mbpp_tools_container"
except ImportError as e:
    print(f"Failed to import required modules: {e}")
    exit(1)
except Exception as e:
    print(f"An unexpected error occurred during initialization: {e}")
    exit(1)
except KeyboardInterrupt:
    print("Execution interrupted by user.")
    exit(1)


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Cut text to `limit` characters and say so."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


def _tail(text: str, lines: int = TRACEBACK_TAIL_LINES) -> str:
    """Keep the last lines of a traceback, where the error message is."""
    return "\n".join(text.strip().splitlines()[-lines:])


def mcp_print(message: str, status: str = "") -> None:
    """Print a message to the MCP console."""
    if status == "error":
        print(f"{RED}{message}{RESET}", file=sys.stderr)
    elif status == "success":
        print(f"{GREEN}{message}{RESET}")
    elif status == "log":
        print(f"{YELLOW}{message}{RESET}")
    else:
        print(message, file=sys.stderr)


class MBPPTools:
    """MCP tools for checking an MBPP solution inside a Docker container."""

    def __init__(self, task: MBPPTaskInput | None = None) -> None:
        self.task = task
        self.container: DockerManager = self._init_container()
        self.register_tools()
        self.register_prompt()
        self.register_resource()

    def _init_container(self) -> DockerManager:
        """Initialize the Docker container with the necessary packages."""
        name = DOCKER_CONTAINER_NAME
        for i in range(3):  # Retry up to 3 times
            mcp_print(f"Attempting to initialize Docker container {name}",
                      "log")
            try:
                container = DockerManager(
                    docker_image=DOCKER_IMAGE,
                    workdir=DOCKER_WORKDIR,
                    name=name)
                mcp_print(f"Successfully initialized Docker container {name}",
                          "success")
                return container
            except Exception as e:
                if i == 2:  # Last attempt
                    raise
                mcp_print(f"Initializing Docker container failed: {e}. Retrying...", "error")
                name = f"{DOCKER_CONTAINER_NAME}_{i + 1}"

    def _build_script(self, code: str, test: str) -> str:
        """Join the test imports, the solution and one test case."""
        imports = ("\n".join(self.task.test_imports) if self.task
                   and self.task.test_imports else "")
        parts = [
            imports,
            textwrap.dedent(code).strip("\n"),
            textwrap.dedent(test).strip("\n"),
        ]
        return "\n\n".join(p for p in parts if p) + "\n"

    def _check(self, code: str, test_list: list[str]) -> str:
        """Return a PASSED/FAILED verdict string for the given solution."""
        if test_list is None or not test_list:
            return "FAILED: no test_list provided."
        if not code or not code.strip():
            return "FAILED: no code provided."

        try:
            ast.parse(textwrap.dedent(code))
        except SyntaxError as e:
            detail = (e.text or "").strip()
            return _truncate(
                f"FAILED: SyntaxError line {e.lineno}: {e.msg}\n{detail}"
            )

        for test in test_list:
            script = self._build_script(code, test)
            res = self.container.exec_command(
                ["timeout", str(TEST_TIMEOUT_SECONDS), "python", "-c", script]
            )
            exit_code = res.get("exit_code", 0)

            if exit_code == TIMEOUT_EXIT_CODE:
                return (
                    f"FAILED: timed out after {TEST_TIMEOUT_SECONDS}s "
                    f"on test `{test}`"
                )
            if exit_code != 0:
                error = res.get("errors", "") or res.get("output", "")
                return _truncate(f"FAILED: test `{test}`\n{_tail(error)}")

        return "PASSED: all tests passed."

    def register_tools(self) -> None:
        """Register the tools with FastMCP."""

        @mcp.tool()
        def run_tests(code: str,
                      test_list: list[str] | None = None
                      ) -> str:
            """Run a solution against the task's test cases.

            Args:
                code: Complete Python source of the solution (the function
                    only, without test code).
                test_list: Optional list of test cases to run. If None, use the task's
                    default test_list.

            Returns:
                A string starting with PASSED or FAILED. On failure it shows
                the first failing test and the end of its error message.
            """
            no_task_msg = (
                "FAILED: no tests are provided. "
                "You must use test_list argument to specify tests. "
                "Example: run_tests(code=src, "
                "test_list=[\"assert add(1, 2) == 3\"]")

            def _build_output_str(status: bool, result: str) -> str:
                if not result:
                    result = "No output"
                return json.dumps({"success": status, "output": result})

            try:
                # Getting the tests
                if test_list is None or not test_list:
                    if self.task is None or not self.task.test_list:
                        return _build_output_str(False, no_task_msg)
                    else:
                        tests = self.task.test_list
                else:
                    tests = test_list

                # Running the tests
                result = self._check(code, tests)

                # Returning the result
                if result.startswith("PASSED"):
                    return _build_output_str(True, result)
                else:
                    return _build_output_str(False, result)
            except Exception as e:
                msg = _truncate(f"FAILED: tool error: {e}")
                return _build_output_str(False, msg)

    def register_prompt(self) -> None:
        """Register a prompt for the run_tests tool."""

        @mcp.prompt
        def a_prompt():
            """Check if a function passes all the tests."""
            return (
                "You are given a Python function and a list of test cases. "
                "Your task is to determine whether the function passes all the tests. "
                "If it does, return 'PASSED'. If it fails any test, return 'FAILED' "
                "followed by the first failing test and the error message."
            )

    def register_resource(self):
        """Register a resource for the MBPPTools."""

        @mcp.resource("resource://greeting")
        def a_resource():
            """A simple resource that returns a greeting message."""
            return "Hello from MBPPTools! RESOURCE is working."

    def stop(self) -> None:
        """Shut down the Docker container."""
        if self.container:
            self.container.shutdown()


# def test() -> None:
#     """Run the MBPPTools in a standalone mode for testing."""
#     tools = MBPPTools()
#     code = """
# def find_Element(arr, ranges, rotations, index):
#     for i in range(rotations):
#         r = i % len(ranges)
#         start, end = ranges[r]
#         sub = arr[start:end+1]
#         arr = list(arr)
#         arr[start:end+1] = sub[1:] + sub[:1]
#     return arr[index]
# """
#     tests = [
#         "assert find_Element([1,2,3,4,5],[[0,2],[0,3]],2,1) == 3",
#         "assert find_Element([1,2,3,4],[[0,1],[0,2]],1,2) == 3",
#         "assert find_Element([1,2,3,4,5,6],[[0,1],[0,2]],1,1) == 1"]
#     result = tools._check(code, tests)
#     mcp_print(result)
#     tools.stop()


def main() -> None:
    args: ServerArgs = get_server_args()
    if args.task_file:
        mcp_print(f"Loading task from {args.task_file}...")
        task = load_task(args.task_file, "mbpp")
        tools = MBPPTools(task)
    else:
        tools = MBPPTools()

    try:
        if args.transport == "http":
            mcp.run(
                transport="http",
                host=args.host,
                port=args.port,
                show_banner=False,
            )
        else:
            mcp.run(show_banner=False)
    except KeyboardInterrupt:
        mcp_print(f"{RED}Shutting down MBPP Tools...{RESET}")
    finally:
        if tools:
            tools.stop()
        if args.transport == "stdio":
            os._exit(0)  # Exit immediately for stdio transport


if __name__ == "__main__":
    try:
        # test()
        main()
    except asyncio.exceptions.CancelledError:
        pass
    except Exception as e:
        mcp_print(f"{RED}Unexpected Error Accured: {e}{RESET}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("Execution interrupted by user.")
