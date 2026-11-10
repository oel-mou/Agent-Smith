*This project has been created as part of the 42 curriculum by oel--mou, mmouis, aaliouan.*

# Agent Smith

## Description

Agent Smith is an agent framework for solving programming tasks through a
controlled Python execution environment and Model Context Protocol (MCP)
tools. The project focuses on two workloads:

- **SWE-bench**: an LLM investigates a real repository, edits files, runs
  tests, and submits a patch.
- **MBPP**: an LLM implements and validates Python programming solutions.

The goal is to make the complete agent workflow reproducible and observable:
the model receives a task, explores the target through discovered tools,
executes actions in a sandbox, and produces a structured solution with step
metrics and evaluation output.

## System architecture

The system is split into four layers:

1. **Agent loops** ([`agent_swebench/`](agent_swebench/),
   [`agent_mbpp/`](agent_mbpp/)) load tasks, maintain the conversation with
   the model, extract executable actions, and record metrics.
2. **LLM/provider layer** ([`agent/`](agent/)) provides model selection,
   request handling, response parsing, retries, token accounting, and typed
   task/solution models.
3. **Sandbox layer** ([`sandbox/`](sandbox/)) runs generated Python in a child
   process with resource limits, captures output, and brokers MCP requests.
4. **MCP tool servers** ([`mcp_tools_swebench.py`](mcp_tools_swebench.py) and
   [`mcp_tools_mbpp.py`](mcp_tools_mbpp.py)) expose task-specific filesystem,
   test, and submission operations locally or inside Docker.

For SWE-bench, the flow is:

```text
task JSON -> agent loop -> Sandbox -> MCP client -> tool server
                  ^          |
                  |          v
             observation <- repository/testbed
```

## Agent loop

Each task uses an iterative **Thought -> Code -> Observation** loop:

1. Load the task and initialize the sandbox and MCP connection.
2. Build the system prompt from the task instructions and the sandbox's
   dynamically discovered tool manual.
3. Ask the configured LLM for the next action.
4. Extract executable Python from the response.
5. Execute it in the sandbox; MCP calls are forwarded to the parent process.
6. Return stdout, stderr, tool results, and errors to the model as the next
   observation.
7. Record tokens, request timing, retries, generated code, and observations.
8. Continue until `final_answer()` is submitted or the iteration budget is
   reached.

The SWE-bench loop allows at most 30 iterations per task and writes a typed
`solution.json` containing the final answer and step metrics.

## Sandbox design

The sandbox executes generated code in a separate child process. The parent
process owns the MCP connection and communicates with the child over a pipe,
which prevents generated code from directly owning the external connection.

Security and reliability controls include:

- authorized-import and filesystem guards;
- blocked network and process operations;
- configurable execution time and memory limits;
- bounded stdout/stderr capture;
- timeout, memory-limit, child-crash, and parsing-error statuses;
- cleanup of the child process and MCP client;
- dynamic tool discovery instead of hard-coded tool signatures.

The sandbox can connect to an MCP server over stdio or Streamable HTTP. A
typical SWE-bench setup is created by the agent with:

```python
Sandbox(
    config=SandboxConfig(),
    mcp_stdio="python -m mcp_tools_swebench --task-file task.json",
    max_output_bytes=20_000,
)
```

## Tool implementation details

The MCP servers are built with FastMCP. They provide focused operations rather
than unrestricted shell access:

- `read_file`: read a bounded, numbered range of known source lines;
- `edit_file`: replace one exact, uniquely matching text block;
- `list_files` and `list_directories`: recursively find names below the
  authorized worktree;
- `search_code`: search file contents with `grep`;
- definition and reference search helpers for Python symbols;
- test and submission tools for the relevant benchmark.

The SWE-bench server uses `LocalManager` when `TESTBED_PATH` is set and
`DockerManager` when a Docker image is supplied. Both managers normalize paths,
verify the worktree, restrict commands to it, and return structured output,
errors, and exit codes. Docker mode uses `/testbed` as its working directory.
The server also supports stdio and HTTP transports.

## Instructions

### Requirements

- Python 3.10
- [`uv`](https://docs.astral.sh/uv/)
- Docker, when running SWE-bench in container mode
- API credentials for the selected LLM provider

Install dependencies from the repository root:

```bash
uv sync
cp .env.example .env
```

Set the provider credentials in `.env`. Never commit `.env` or API keys.

### Running the sandbox and agents

Run the sandbox CLI with a JSON configuration and an MCP server command:

```bash
uv run sandbox path/to/config.json --mcp-stdio \
  "python -m mcp_tools_swebench --task-file path/to/task.json"
```

The agent entry points can be run as Python modules. Use their `--help`
output for the current task, model, provider, and output-file options:

```bash
uv run python -m agent_swebench --help
uv run python -m agent_mbpp --help
```

For local SWE-bench execution, set the repository under test:

```bash
export TESTBED_PATH=/absolute/path/to/testbed
```

For Docker execution, provide the image through the SWE-bench command-line
options. The exact benchmark task format and validation commands are described
in [`exams/exam_scripts_instructions.md`](exams/exam_scripts_instructions.md).

### Tests

Run the project tests with:

```bash
uv run pytest
```

## Benchmark results and analysis

The benchmark compares five models on the same three SWE-bench tasks:
`scikit-learn__scikit-learn-13439`, `pytest-dev__pytest-7432`, and
`django__django-11099`. The complete measurements and backing solution files
are in [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md) and
[`benchmark/`](benchmark/).

| Model | Provider | Solved | Average iterations |
|---|---|---:|---:|
| `gemini-flash-lite-latest` | Google AI Studio | 2/3 | 14.0 |
| `nvidia/nemotron-3-ultra` | OpenRouter | 1/3 | 23.3 |
| `nvidia/nemotron-3.5-super-vl` | OpenRouter | 2/3 | 10.3 |
| `qwen/qwen3.8-27b` | Groq | 0/3 | 3.0 |
| `recursive/flint-v1.0` | OpenRouter | 1/3 | 3.7 |

The strongest observed balance was `nvidia/nemotron-3.5-super-vl`: it solved
two tasks with the fewest average iterations among the models achieving that
score. Gemini achieved the same solve rate with much lower output-token use
and shorter wall-clock time in this run. Nemotron Ultra spent substantially
more tokens and often reached the iteration limit, while Qwen's results were
dominated by provider errors. These results show that provider reliability,
response limits, and tool-use discipline matter as much as raw model
capability; they should not be interpreted as a general ranking from only
three tasks.

## Resources

- [Model Context Protocol documentation](https://modelcontextprotocol.io/)
- [FastMCP documentation](https://gofastmcp.com/)
- [Docker SDK for Python](https://docker-py.readthedocs.io/)
- [Python `multiprocessing` documentation](https://docs.python.org/3/library/multiprocessing.html)
- [SWE-bench](https://www.swebench.com/)
- [MBPP benchmark](https://github.com/google-research/google-research/tree/master/mbpp)
- [uv documentation](https://docs.astral.sh/uv/)
- [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md), for raw benchmark methodology
  and results
- [`SANDBOX_AGENT_HANDOFF.md`](SANDBOX_AGENT_HANDOFF.md), for the sandbox
  integration contract

### AI usage

AI models are the runtime subject of this project: they generate repository
exploration actions, code edits, test commands, and final patches during the
MBPP and SWE-bench workflows. AI assistance was also used during development
to help design and review the agent loop, MCP tool interfaces, sandbox
boundaries, parsing, error handling, and benchmark documentation. Humans
remain responsible for the project choices, integration, validation, and
interpretation of benchmark results.

## Project documentation

- [`STRUCTURE.md`](STRUCTURE.md): repository layout and expected deliverables.
- [`SANDBOX_AGENT_HANDOFF.md`](SANDBOX_AGENT_HANDOFF.md): public sandbox API
  and integration guidance.
- [`exams/`](exams/): validation scripts and exam execution instructions.