import argparse
import json
import os
import sys
import ipaddress

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self
from typing import List
from dotenv import load_dotenv

from agent.error import ParsingError
from agent.models import MBPPTaskInput, SWEBenchTaskInput


class Args(BaseModel):
    task_file: str = Field(..., description="Path to task.json")
    output: str = Field(..., description="Path to write solution.json")
    model_name: str = Field(..., description="Model identifier")
    provider_url: str = Field(..., description="Base URL of the LLM API")
    mcp_stdio: str | None = Field(None, description="Path to mcp_tools_mbpp.py for stdio transport")
    mcp_server: str | None = Field(None, description="Path to mcp_tools_mbpp.py for server transport")

    @model_validator(mode="before")
    def validate_before(self) -> Self:
        print(self, file=sys.stderr)
        return self

    @model_validator(mode="after")
    def validate_args(self) -> Self:
        # Validate that all arguments are provided and non-empty,
        # and that the task file is a valid JSON.
        is_empty(self.task_file, "Task file path cannot be empty.")
        is_empty(self.output, "Output file path cannot be empty.")
        is_empty(self.model_name, "Model name cannot be empty.")
        is_empty(self.provider_url, "Provider URL cannot be empty.")
        if self.mcp_stdio and self.mcp_server:
            raise ParsingError("Only one of mcp_stdio or mcp_server should be provided.")
        if not self.mcp_stdio and not self.mcp_server:
            # If neither is provided, default to stdio transport
            self.mcp_stdio = f"python mcp_tools_mbpp.py --task-file {self.task_file}"
        return self


class ServerArgs(BaseModel):
    task_file: str | None = Field(..., description="Path to task.json")
    transport: str = Field(..., description="Path to write solution.json")
    host: str = Field(..., description="Host of the MCP Server")
    port: int = Field(..., description="Port of the MCP Server")

    @model_validator(mode="after")
    def validate(self) -> Self:
        if self.task_file is not None:
            is_empty(self.task_file, "Task file path cannot be empty.")
        is_empty(self.transport, "Transport cannot be empty.")
        is_empty(self.host, "Host cannot be empty.")

        # 1. Validate IP address safely
        try:
            ip = ipaddress.ip_address(self.host)
        except ValueError:
            raise ParsingError(
                f"host '{self.host}' is not a valid IP address.")

        if ip.version != 4:
            raise ParsingError(f"host '{self.host}' is not a valid IPv4 address.")

        # 2. Validate Port
        if not (0 <= self.port <= 65535):
            raise ParsingError("Port must be between 0 and 65535.")

        # 3. Validate Transport (Fixed typo: self.trasport -> self.transport)
        if self.transport not in {"stdio", "http"}:
            raise ParsingError(
                f"transport need to be 'http' or 'stdio'! Received '{self.transport}'"
            )

        return self


def get_args() -> Args:
    """Parse command-line arguments and return an Args instance."""

    def _build_parser() -> argparse.ArgumentParser:
        """Builds the argument parser for command-line arguments."""
        parser = argparse.ArgumentParser(description="MBPP solving agent")
        parser.add_argument("--task-file", required=True,
                            help="Path to task.json")
        parser.add_argument("--output", required=True,
                            help="Path to write solution.json")
        parser.add_argument("--model-name", default="qwen/qwen3.8-27b",
                            help="Model identifier, e.g. 'qwen/qwen3-235b'")
        parser.add_argument("--provider-url",
                            default="https://api.groq.com/openai/v1",
                            help="Base URL of the LLM API")
        connection = parser.add_mutually_exclusive_group()
        connection.add_argument("--mcp-stdio")
        connection.add_argument("--mcp-server")

        return parser

    parser = _build_parser()
    args = parser.parse_args()
    result = Args(**vars(args))
    print(f"Agent args: {result}", file=sys.stderr)
    return result


def get_server_args() -> ServerArgs:
    """Parse the server CLI arguments"""

    parser = argparse.ArgumentParser(description="MBPP MCP server")

    parser.add_argument("--task-file", default=None,
                        help="Path to task.json")
    parser.add_argument("--transport", default="stdio",
                        help="Transport method for the server (stdio or http)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Host of the MCP Server")
    parser.add_argument("--port", default="8000",
                        help="Port of the MCP Server")

    args = parser.parse_args()
    result = ServerArgs(**vars(args))
    # print(f"MCP Server args: {result}", file=sys.stderr)
    return result


def get_supported_providers() -> dict:
    """Get supported providers from providers.json"""
    try:
        with open("providers.json", "r") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        raise ParsingError("providers.json file not found.")
    except json.JSONDecodeError:
        raise ParsingError("Error decoding providers.json file.")


def get_api_keys(provider_url: str) -> List[str]:
    """Retrieve API keys for the provider from environment variables."""
    providers = get_supported_providers()
    if not load_dotenv():
        raise ParsingError(".env file is empty or .env is disabled")
    env_var_name = ""
    for provider_name, api_url in providers.items():
        if api_url == provider_url:
            env_var_name = f"{provider_name.upper()}_API_KEY"
            break
    if not env_var_name:
        raise ParsingError(f"Provider URL '{provider_url}' is not supported.")
    value = os.environ.get(env_var_name)
    if value is None:
        raise ParsingError("Environment variable " f"'{env_var_name}' not found.")
    lst = [key.strip() for key in value.split(",") if key.strip()] if value else []
    if not lst:
        raise ParsingError(
            "No API keys found for provider "
            f"'{provider_name}' in environment"
            f" variable '{env_var_name}'."
        )
    return lst


def is_empty(string: str, error_message: str) -> None:
    """Check if a string is empty and raise ParsingError if it is."""
    if not isinstance(string, str):
        raise ParsingError("Provided value is not a string.")
    if string is None or not string.strip():
        raise ParsingError(error_message)
    if not string.strip():
        raise ParsingError(error_message)


def load_task(task_file: str,
              task_name: str) -> MBPPTaskInput | SWEBenchTaskInput:
    """Load the MBPP | SWEbench task from a JSON file."""
    try:
        with open(task_file, "r") as f:
            data = json.load(f)
        if task_name == "swebench":
             return SWEBenchTaskInput(**data)
        elif task_name == "mbpp":
            return MBPPTaskInput(**data)
        else:
            raise ParsingError(f"Task name '{task_file}' is not handled.\n"
                               "Use swebench or mbpp")
    except FileNotFoundError:
        raise ParsingError(f"Task file '{task_file}' not found.")
    except json.JSONDecodeError:
        raise ParsingError(f"Task file '{task_file}' is not a valid JSON.")
    except Exception as e:
        raise ParsingError(f"Error loading task: {str(e)}")
