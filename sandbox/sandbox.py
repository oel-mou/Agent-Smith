from typing import Any, Callable, BinaryIO
from types import FrameType
import tempfile
import time
import resource
import signal
import builtins
from multiprocessing.connection import Connection, wait
from multiprocessing import Process, Pipe
import json
from sandbox.mcp_client import MCPClient

from sandbox.config import SandboxConfig
from contextlib import redirect_stdout, redirect_stderr
from io import FileIO
from sandbox.security import (
    install_filesystem_guard,
    install_network_guard,
    install_process_guard,
    validate_code,
    make_safe_import,
)
from sandbox.output import (
    BoundedTextCapture,
    SandboxError,
    SandboxResult,
    MCPToolError,
)

class Sandbox:
    """Execute restricted Python and manage its MCP connection."""
    def __init__(
        self,
        config: SandboxConfig,
        mcp_stdio: str | None = None,
        mcp_server: str | None = None,
        max_output_bytes: int = 10000
    ) -> None:
        """Store execution limits and an optional MCP connection target."""
        if mcp_stdio and mcp_server:
            raise ValueError(
                "Use either mcp_stdio or mcp_server, not both."
            )

        if (not isinstance(max_output_bytes, int)
            or max_output_bytes <= 0
            or isinstance(max_output_bytes, bool)
        ):
            raise ValueError("max_output_bytes Must be Positive. and > 0")
        self.max_output_bytes = max_output_bytes

        self.config = config
        self.mcp_stdio = mcp_stdio
        self.mcp_server = mcp_server

        self.mcp_client: MCPClient | None = None
        self.tools: list[dict[str, Any]] | None = None
        self.connection: Connection | None = None
        self.started = False

    def start(self) -> None:
        """Connect to MCP and discover tools, if configured."""
        if self.started:
            return

        target = self.mcp_stdio or self.mcp_server

        if target is None:
            #if no mcp target is provided,we just start the sandbox without MCP
            self.started = True
            return

        self.mcp_client = MCPClient(target)

        try:
            self.mcp_client.start()
            self.tools = self.mcp_client.list_tools()
            # prevent MCP tool names from conflicting with Sandbox helpers
            for tool in self.tools:
                if tool["name"] in {
                    "final_answer",
                    "__builtins__",
                    "list_resources",
                    "read_resource",
                    "list_prompts",
                    "get_prompt",
                }:
                    raise ValueError(
                        f"MCP tool name '{tool['name']}' is reserved by Sandbox."
                    )

        except Exception:
            try:
                self.mcp_client.stop()
            except Exception:
                pass

            self.mcp_client = None
            self.tools = None
            raise

        self.started = True

    def close(self) -> None:
        """Close MCP and reset state, propagating cleanup errors."""
        try:
            if self.mcp_client is not None:
                self.mcp_client.stop()

        finally:
            self.mcp_client = None
            self.tools = None
            self.started = False


    def run(self, code: str) -> SandboxResult:
        """Run Python in a child and return output, status, and any answer."""
        if not self.started:
            raise RuntimeError("Sandbox is not started.")
       
        # Create temporary files for capturing stdout and stderr.
        stdout_file = tempfile.TemporaryFile(mode="w+b", buffering=0)
        stderr_file = tempfile.TemporaryFile(mode="w+b", buffering=0)
        result: SandboxResult | None = None
       
        # creat 2 endpoints for the parent and child processes to communicate
        parent_conn, child_conn = Pipe()
        # create a child process to run the code in a restricted environment
        process = Process(
            target=self._child_entry,
            args=(
                code,
                child_conn,
                parent_conn,
                stdout_file,
                stderr_file,
            )
        )
        process_started = False

        try:
            process.start()
            process_started = True

            # The parent must not retain the child's endpoint.
            child_conn.close()
            # set a deadline for the execution time limit
            deadline = (
                time.monotonic()
                + self.config.max_execution_time_seconds
            )

            while True:
                remaining = deadline - time.monotonic()

                if remaining <= 0:

                    result = SandboxResult(
                        status="timeout",
                        output_partial=True,
                        error=SandboxError(
                            kind="runtime",
                            type="TimeoutError",
                            message="Execution time exceeded the limit.",
                        ),
                    )
                    return result
                
                # wait for either a message from the 
                # child or the child process to exit
                ready = wait(
                    [parent_conn, process.sentinel],
                    timeout=remaining,
                )

                if not ready:
                    continue 

                # Read pending messages before handling process exit.
                if parent_conn in ready:
                    try:
                        message = parent_conn.recv()
                    except (EOFError, OSError):
                        break

                    if message["type"] == "mcp_call":
                        mcp_started = time.monotonic()

                        try:
                            if self.mcp_client is None:
                                raise RuntimeError(
                                    "MCP client is not initialized."
                                )

                            operation = message.get("operation", "call_tool")
                            arguments = message["arguments"]

                            if operation == "call_tool":
                                response = self.mcp_client.call_tool(
                                    message["tool_name"],
                                    arguments,
                                )
                            elif operation == "list_resources":
                                response = self.mcp_client.list_resources()
                            elif operation == "read_resource":
                                response = self.mcp_client.read_resource(
                                    uri=arguments["uri"],
                                )
                            elif operation == "list_prompts":
                                response = self.mcp_client.list_prompts()
                            elif operation == "get_prompt":
                                response = self.mcp_client.get_prompt(
                                    name=arguments["name"],
                                    arguments=arguments.get("arguments"),
                                )
                            else:
                                raise ValueError(f"Unknown MCP operation: {operation}")

                        except Exception as e:
                            # meke error reply to the child with the exception details
                            reply = {
                                "type": "mcp_error",
                                "error": str(e),
                                "error_type": type(e).__name__,
                            }

                        else:
                            # make reply to the child with the result of the MCP call
                            reply = {
                                "type": "mcp_response",
                                "result": response,
                            }
                        finally:
                            # MCP waiting does not consume the code's time budget.
                            deadline += time.monotonic() - mcp_started

                        try:
                            # send the reply back to the child process
                            parent_conn.send(reply)
                        except (EOFError, OSError):
                            # if the child has already closed its connection
                            # we just break the loop
                            break

                    elif message["type"] == "control":
                        if message["exception"] == "KeyboardInterrupt":
                            raise KeyboardInterrupt

                        if message["exception"] == "SystemExit":
                            raise SystemExit(message.get("code"))

                        raise RuntimeError("Unknown child control exception.")

                    elif message["type"] == "result":
                        result = message["result"]

                        if not isinstance(result, SandboxResult):
                            raise RuntimeError(
                                "Child returned an invalid execution result."
                            )

                        return result

                    else:
                        raise RuntimeError(
                            "Child sent an unknown message type."
                        )

                elif process.sentinel in ready:
                    break

            result = SandboxResult(
                status="child_crash",
                output_partial=True,
                error=SandboxError(
                    kind="infrastructure",
                    type="ChildProcessError",
                    message="Child exited without returning a result.",
                ),
            )
            return result

        finally:
            try:
                parent_conn.close()
                child_conn.close()

                if process_started:
                    process.join(timeout=1)

                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

                    if process.is_alive():
                        process.kill()
                        process.join(timeout=1)

                    if process.is_alive():
                        raise RuntimeError(
                            "Sandbox child could not be stopped."
                        )

                process.close()

                if result is not None:
                    # Read output after stopping the child, including partial output.
                    limit = self.max_output_bytes

                    stdout_file.seek(0)
                    stderr_file.seek(0)

                    stdout_data = stdout_file.read(limit + 1)
                    stderr_data = stderr_file.read(limit + 1)

                    result.truncated_streams = []

                    if len(stdout_data) > limit:
                        result.truncated_streams.append("stdout")

                    if len(stderr_data) > limit:
                        result.truncated_streams.append("stderr")

                    result.stdout = stdout_data[:limit].decode(
                        "utf-8", errors="replace"
                    )
                    result.stderr = stderr_data[:limit].decode(
                        "utf-8", errors="replace"
                    )
            finally:
                stdout_file.close()
                stderr_file.close()

    def _child_entry(
        self,
        code: str,
        connection: Connection,
        unused_connection: Connection,
        stdout_file: BinaryIO,
        stderr_file: BinaryIO,
    ) -> None:
        """Run code in the child and send its result or control exception."""
        # The child must not retain the parent's endpoint.
        unused_connection.close()
        
        self.connection = connection
        
        self._stdout_capture = BoundedTextCapture(
            stdout_file,
            self.max_output_bytes,
        )
        self._stderr_capture = BoundedTextCapture(
            stderr_file,
            self.max_output_bytes,
        )

        def send_to_parent(message: dict[str, Any]) -> None:
            """Send a message unless the parent has already closed its pipe."""
            try:
                connection.send(message)
            except (OSError, EOFError):
                pass

        try:
            try:
                result = self._execute(code)

            except KeyboardInterrupt:
                send_to_parent({
                    "type": "control",
                    "exception": "KeyboardInterrupt",
                })

            except SystemExit as e:
                exit_code = e.code

                # Keep the control message limited to simple values.
                if exit_code is not None and not isinstance(exit_code, (int, str)):
                    exit_code = "Sandbox requested exit."

                send_to_parent({
                    "type": "control",
                    "exception": "SystemExit",
                    "code": exit_code,
                })

            else:
                send_to_parent({
                    "type": "result",
                    "result": result,
                })

        finally:
            connection.close()
            self.connection = None
            self._stdout_capture.close()
            self._stderr_capture.close()

    def _make_callable(
        self,
        tool_name: str,
        operation: str = "call_tool",
        param_names=()
    ) -> Callable[..., Any]:
        """Return a callable that forwards an MCP request to the parent."""
        def wrapper(*args, **kwargs: Any) -> Any:
            """Return the MCP response or raise an MCPToolError."""
            if len(args) > len(param_names):
                raise TypeError(
                    f"{tool_name}() takes {len(param_names)} positional "
                    f"arguments but {len(args)} were given."
                )
            for name, value in zip(param_names, args):
                if name in kwargs:
                    raise TypeError(
                        f"{tool_name}() got multiple values for argument '{name}'."
                    )
                kwargs[name] = value

            if self.connection is None:
                raise ValueError("Sandbox connection is not initialized.")
            
            remaining_time = signal.alarm(0) # Pause the child alarm during MCP.
            try:
                self.connection.send({"type": "mcp_call",
                    "operation": operation,
                    "tool_name": tool_name,
                    "arguments": kwargs,
                })

                response = self.connection.recv()

                if response.get("type") == "mcp_error":
                    error = MCPToolError(response["error"])
                    error.tool_name = tool_name # type: ignore
                    error.original_type = response.get( # type: ignore
                        "error_type", "MCPToolError"
                    )
                    raise error

                if response.get("type") == "mcp_response":
                    return response["result"]

                raise RuntimeError("Invalid response from sandbox parent.") 

            finally:
                if remaining_time > 0:
                    signal.alarm(remaining_time)

        return wrapper

    def _get_tools(self) -> dict[str, object]:
        """Return discovered tools and MCP helpers as Python callables."""

        if self.tools is None:
            raise ValueError("Tools are not available.")
        
        tools: dict[str, object] = {}
        for tool in self.tools:
            schema = tool.get("inputSchema", tool.get("input_schema", {}))
            param = tuple(schema.get("properties", {}).keys())
            tools[tool["name"]] = self._make_callable(tool["name"],
                                                      param_names=param)

        for operation in ( "list_resources",  "read_resource", "list_prompts",
                            "get_prompt",):
        
            tools[operation] = self._make_callable(
                tool_name=operation,
                operation=operation,
            )
        return tools


    def _execute(self, code: str) -> SandboxResult:
        """Execute restricted Python and return a structured SandboxResult."""

        def signal_handler(signum: int, frame: FrameType | None) -> None:
            """Raise TimeoutError when the execution alarm fires."""
            raise TimeoutError("Execution time exceeded the limit.")

        BLOCKED = {
            "open", "exec", "eval", "compile",
            "__import__", "input", "memoryview",
            "__loader__", "__spec__",
            "getattr", "setattr", "delattr",
            "vars", "globals", "locals",
            "help", "breakpoint", "exit", "quit",
        }       
        # Build a separate builtin namespace for generated code.
        safe_builtins = {
            name: func 
            for name, func in vars(builtins).items()
            if name not in BLOCKED
        }
        # Route Python import statements through the allowlist.
        safe_builtins["__import__"] = make_safe_import(self.config.authorized_imports)
        
        safe_globals: dict[str, Any] = {
            "__builtins__": safe_builtins,
        }

        # Ordinary except Exception blocks must not swallow submission.
        completion_signal = type(
            "_FinalAnswerException",
            (BaseException,),
            {},
        )
        answer_state = {
            "submitted": False,
            "answer": None,
        }
        answer_globals = {
            "__builtins__": safe_builtins,
            "_FinalAnswerException": completion_signal,
            "_answer_state": answer_state,
        }

        # Define the helper here so its globals do not expose this host module.
        exec(
            "def final_answer(solution: str) -> None:\n"
            "    \"\"\"Record the first answer and signal completion.\"\"\"\n"
            "    if not isinstance(solution, str):\n"
            "        raise TypeError('final_answer() requires a string.')\n"
            "    if not _answer_state['submitted']:\n"
            "        _answer_state['answer'] = solution\n"
            "        _answer_state['submitted'] = True\n"
            "    print(solution)\n"
            "    raise _FinalAnswerException(solution)\n",
            answer_globals,
        )

        safe_globals["final_answer"] = answer_globals["final_answer"]

        if self.tools is not None:
            safe_globals.update(self._get_tools()) 
        # RLIMIT_AS limits the child's virtual address space in bytes.
        limit = self.config.max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    
        # The child alarm complements the parent's execution deadline.
        signal.signal(signal.SIGALRM, signal_handler)
        
        signal.alarm(self.config.max_execution_time_seconds)
        
        stdout_capture = self._stdout_capture
        stderr_capture = self._stderr_capture

        result = SandboxResult(status="ok")

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture): #type: ignore
                install_filesystem_guard(self.config.allowed_directories)
                install_network_guard()
                install_process_guard()
                validate_code(code) 
                exec(code, safe_globals)

        except completion_signal as e:
            result.status = "final_answer"
            result.final_answer = e.args[0]
        
        except TimeoutError as e:
            result.status = "timeout"
            result.output_partial = True
            result.error = SandboxError(
                kind="runtime",
                type=type(e).__name__,
                message=str(e),
            )

        except MemoryError:
            result.status = "memory_limit"
            result.output_partial = True
            result.error = SandboxError(
                kind="runtime",
                type="MemoryError",
                message="Memory limit exceeded.",
            )

        except Exception as e:
            result.status = "error"
            result.error = SandboxError(
                kind=(
                    "mcp" if isinstance(e, MCPToolError)
                    else "syntax" if isinstance(e, SyntaxError)
                    else "security" if isinstance(e, PermissionError)
                    else "runtime"
                ),
                type=getattr(e, "original_type", type(e).__name__),
                message=str(e),
                tool_name=getattr(e, "tool_name", None),
                
            ) 

        finally:
            signal.alarm(0)
            stdout_capture.flush()
            stderr_capture.flush()


        if (answer_state["submitted"] and
            result.status not in ("timeout", "memory_limit")):

            result.status = "final_answer"
            result.final_answer = answer_state["answer"]
        
        return result
        

    def get_manual(self) -> str:
        """Return execution rules and dynamically discovered tool schemas."""
        if not self.started:
            raise RuntimeError("Sandbox is not started.")

        sections = [
            "Sandbox manual",
            "",
            "Write Python code to execute in the sandbox.",
            "Each execution starts with a fresh namespace.",
            "Variables and functions do not persist between executions.",
            "Use print() to make returned values visible in observations.",
            "",
            f"Allowed imports: {', '.join(self.config.authorized_imports)}",
            f"Allowed filesystem directories: {self.config.allowed_directories}",
            "Builtin open() is unavailable. Use MCP tools for task files.",
            f"Execution time limit: {self.config.max_execution_time_seconds} seconds.",
            "Time waiting for MCP tools is excluded from that execution limit.",
            f"Memory limit: {self.config.max_memory_mb} MB.",
            f"Captured output limit: {self.max_output_bytes} bytes per stream.",
            "When output is truncated, only its beginning is shown.",
            "",
            "Submission:",
            "Call final_answer(solution='your answer here') to submit your answer.",
            "For MBPP, submit the solution's Python source code.",
            "For SWE-bench, submit the git patch.",
            "final_answer is provided by Sandbox, not by the MCP server.",
            "",
            "Available MCP tools:",
        ]

        if not self.tools:
            sections.append("No MCP tools are available.")

        for tool in self.tools or []:
            schema = tool.get(
                "inputSchema",
                tool.get("input_schema", {}),
            )

            sections.extend([
                "",
                f"Tool: {tool['name']}",
                "Call this function using keyword arguments.",
                f"Description: {tool.get('description') or 'Not provided.'}",
                "Argument schema:",
                json.dumps(schema, indent=2, ensure_ascii=False),
            ])

        if self.mcp_client is not None:
            sections.extend([
                "",
                "MCP resources and prompts:",
                "Use these helpers when you need additional data or guidance.",
                "list_resources(): returns available resource descriptions and URIs.",
                "read_resource(uri='...'): returns resource content blocks.",
                "list_prompts(): returns prompt descriptions and argument definitions.",
                "get_prompt(name='...', arguments={...}): returns rendered prompt messages.",
                "Call helpers using keyword arguments.",
                "Use print() to make their results visible in observations.",
            ])

        return "\n".join(sections)    

    @staticmethod
    def format_tool(tool: dict) -> str:
        """Return a human-readable description of a tool and its arguments."""
        def _type_name(prop: dict) -> str:
                """Return a human-readable type name for a JSON schema property."""
                t = prop.get("type", "any")
                if t == "array":
                    return f"list[{_type_name(prop.get('items', {}))}]"
                if "enum" in prop:
                    return "Literal[" + ", ".join(repr(v) for v in prop["enum"]) + "]"
                return {"string": "str", "integer": "int", "number": "float",
                        "boolean": "bool", "object": "dict", "null": "None"}.get(t, t)
        schema = tool.get("inputSchema", tool.get("input_schema", {}))
        props = schema.get("properties", {})
        required = set(schema.get("required", []))

        params = []
        for name, prop in props.items():
            text = f"{name}: {_type_name(prop)}"
            if name not in required:
                text += " = ..."
            params.append(text)

        desc = " ".join((tool.get("description") or "").split())
        lines = [f"- {tool['name']}({', '.join(params)}): {desc}"]
        for name, prop in props.items():
            if prop.get("description"):
                lines.append(f"    {name}: {' '.join(prop['description'].split())}")
        return "\n".join(lines)

    def get_mcp_tools(self) -> str:
        """Return a human-readable description of all available MCP tools."""
        if not self.started:
            raise RuntimeError("Sandbox is not started.")

        if not self.tools:
            return "No MCP tools are available."

        lines = ["Tools:"]
        for tool in self.tools:
            lines.append(self.format_tool(tool))
        return "\n".join(lines)
