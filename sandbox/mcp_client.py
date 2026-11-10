import asyncio
import shlex
import threading
from concurrent.futures import (
    Future,
    TimeoutError as FutureTimeoutError,
)
import os
from typing import Any
import pickle
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import math

class MCPClient:
    """Expose synchronous MCP operations backed by an event-loop thread."""
    def __init__(self, server: str, timeout: float = 30.0, 
                 init_timeout: float = 10.0,
                 shutdown_timeout: float = 3.0,
                 startup_timeout: float = 15.0
                 ) -> None:
        """Configure connection deadlines and prepare the event-loop thread."""
        for name, value in (
            ("timeout", timeout),
            ("init_timeout", init_timeout),
            ("startup_timeout", startup_timeout),
            ("shutdown_timeout", shutdown_timeout),):
            
            if not math.isfinite(value) or value <= 0:
                    raise ValueError(f"{name} must be finite and greater than zero.")

        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout        
        
        self.timeout = timeout
        self.init_timeout = init_timeout

        self.server = server
        self.transport = self._build_transport(server)

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
        )

        self.client: Client | None = None
        self.stop_event: asyncio.Event | None = None

        self.start_event = threading.Event()
        self.client_future: Future[None] | None = None

        self.started = False

    def _build_transport(self, server: str) -> str | StdioTransport:
        """Return an HTTP URL or a subprocess-backed stdio transport."""
        # HTTP connects to an existing server; stdio launches the command.
        if server.startswith(("http://", "https://")):
            return server

        # stdio
        command = shlex.split(server)

        if not command:
            raise ValueError("MCP server command cannot be empty.")

        return StdioTransport(
            command=command[0],
            args=command[1:],
            keep_alive=False,
            env=dict(os.environ)
        )

    def _run_loop(self) -> None:
        """Run the loop, then cancel remaining tasks and close it."""
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)

                for task in pending:
                    task.cancel()

                if pending:
                    done, still_pending = self.loop.run_until_complete(
                        asyncio.wait(
                            pending,
                            timeout=self.shutdown_timeout,
                        )
                    )

                    if done:
                        self.loop.run_until_complete(
                            asyncio.gather(
                                *done,
                                return_exceptions=True,
                            )
                        )
            finally:
                self.loop.close()

    async def _run_client(self) -> None:
        """Keep the MCP session open until shutdown is requested."""
        self.stop_event = asyncio.Event()

        try:
            async with Client(
                self.transport,
                timeout=self.timeout,
                init_timeout=self.init_timeout) as client:

                self.client = client
                self.start_event.set()
                await self.stop_event.wait()
        finally:
            self.client = None

    def start(self) -> None:
        """Start the session or raise its startup error after cleanup."""
        if self.started:
            raise RuntimeError("MCP client is already started.")

        # Python threads cannot be started twice; use a new client after stop().
        if self.thread.ident is not None or self.loop.is_closed():
            raise RuntimeError(
                "This MCPClient has already been stopped; create a new instance."
            )

        try:
            self.thread.start()

            self.client_future = asyncio.run_coroutine_threadsafe(
                self._run_client(),
                self.loop,
            )

            # Wake the caller on either successful connection or failure.
            # avoid waiting for the full timeout if the client fails to start.
            # and return the original exception to the caller.
            self.client_future.add_done_callback(
                lambda _: self.start_event.set()
            )
            
            # block until connected or failed; the timeout stops a hung startup
            if not self.start_event.wait(timeout=self.startup_timeout):
                raise TimeoutError(
                    "MCP startup exceeded its deadline."
                )
            
            # If the client_future is done, check for exceptions and raise them
            if self.client_future.done():
                self.client_future.result()
        
            if self.client is None:
                raise RuntimeError(
                    "MCP session ended before startup completed."
                )

            self.started = True

        except BaseException as startup_error:
            # Includes interruption during startup. Preserve the original error.
            try:
                self.stop()
            except Exception as cleanup_error:
                raise startup_error from cleanup_error 

            raise 

    def stop(self) -> None:
        """Request session shutdown and stop the event-loop thread."""
        # Also allow cleanup before startup or after an earlier stop.
        if not self.thread.is_alive():
            if not self.loop.is_closed():
                self.loop.close()
            self.started = False
            return

        try:
            if self.stop_event is not None:
                self.loop.call_soon_threadsafe(self.stop_event.set)

            if self.client_future is not None:
                try:
                    self.client_future.result(
                        timeout=self.shutdown_timeout
                    )
                except FutureTimeoutError:
                    self.client_future.cancel()
                    raise TimeoutError(
                        "MCP session shutdown exceeded its deadline."
                    )

        finally:
            # Stop the loop even when session cleanup raises an error.
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(
                timeout=self.shutdown_timeout + 1
            )

            self.started = False

            if self.thread.is_alive():
                raise RuntimeError(
                    "MCP event-loop thread did not stop."
                )

            self.client = None
            self.stop_event = None

    def list_resources(self) -> list[dict[str, Any]]:
        """Return the server resource descriptions as JSON-compatible dicts."""
        if self.client is None:
            raise RuntimeError("MCP client is not started.")

        future = asyncio.run_coroutine_threadsafe(
            self.client.list_resources(),
            self.loop,
        )

        try:
            resources = future.result(timeout=self.timeout)
        except (FutureTimeoutError, KeyboardInterrupt, SystemExit):
            future.cancel()
            raise

        return [
            resource.model_dump(mode="json")
            for resource in resources
        ]
    
    def read_resource(self, uri: str) -> list[dict[str, Any]]:
        """Return the content blocks for a resource URI."""
        if self.client is None:
            raise RuntimeError("MCP client is not started.")

        future = asyncio.run_coroutine_threadsafe(
            self.client.read_resource(uri),
            self.loop,
        )

        try:
            contents = future.result(timeout=self.timeout)
        except (FutureTimeoutError, KeyboardInterrupt, SystemExit):
            future.cancel()
            raise

        return [
            content.model_dump(mode="json")
            for content in contents
        ]
    
    def list_tools(self) -> list[dict[str, Any]]:
        """Return the dynamically discovered tool descriptions and schemas."""
        if self.client is None:
            raise RuntimeError("MCP client is not started.")

        future = asyncio.run_coroutine_threadsafe(
            self.client.list_tools(),
            self.loop,
        )

        try:
            tools = future.result(timeout=self.timeout)
        except (FutureTimeoutError, KeyboardInterrupt, SystemExit):
            future.cancel()
            raise 

        return [
            tool.model_dump(mode="json")
            for tool in tools
        ]

    def list_prompts(self) -> list[dict[str, Any]]:
        """Return available prompt descriptions and argument definitions."""
        if self.client is None:
            raise RuntimeError("MCP client is not started.")

        future = asyncio.run_coroutine_threadsafe(
            self.client.list_prompts(),
            self.loop,
        )

        try:
            prompts = future.result(timeout=self.timeout)
        except (FutureTimeoutError, KeyboardInterrupt, SystemExit):
            future.cancel()
            raise

        return [
            prompt.model_dump(mode="json")
            for prompt in prompts
        ]
    
    def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a rendered prompt using the supplied arguments."""
        if self.client is None:
            raise RuntimeError("MCP client is not started.")

        future = asyncio.run_coroutine_threadsafe(
            self.client.get_prompt(name, arguments or {}),
            self.loop,
        )

        try:
            result = future.result(timeout=self.timeout)
        except (FutureTimeoutError, KeyboardInterrupt, SystemExit):
            future.cancel()
            raise

        return result.model_dump(mode="json")
    
    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Return a tool result as parsed data or content blocks."""
        if self.client is None:
            raise RuntimeError("MCP client is not started.")

        future = asyncio.run_coroutine_threadsafe(
            self.client.call_tool(
                tool_name,
                arguments,
                timeout=self.timeout,
            ),
            self.loop,
        )

        try:
            result = future.result(timeout=self.timeout + 1)
        except (FutureTimeoutError, KeyboardInterrupt, SystemExit):
            future.cancel()
            raise
        

        # If the tool returned structured data, attempt to pickle it. 
        #If pickling fails, return the structured content instead.
        if result.data is not None:
            try:
                pickle.dumps(result.data)
            except (pickle.PicklingError, TypeError, AttributeError):
                return result.structured_content

            return result.data

        # Generic fallback for MCP servers returning only content blocks.
        return [
            block.model_dump()
            if hasattr(block, "model_dump")
            else block
            for block in result.content
        ]
