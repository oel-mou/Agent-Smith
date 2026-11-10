try:
    from agent import (
        DockerManager, LocalManager, ServerArgs, SWEBenchTaskInput,
        load_task, get_server_args)
    from fastmcp import FastMCP
    import shlex
    import signal
    import os

    # Path of the repository inside the SWE-bench container. Agents (and tests)
    # always use it; in local mode it is mapped to TESTBED_PATH on the host.
    VIRTUAL_ROOT = "/testbed"

    # Executed inside the container by edit_file.
    # The path, old_str and new_str arrive through sys.argv, never inside
    # the code itself, so quotes, backslashes, $ or newlines can't break it.
    EDIT_FILE_SCRIPT = """
import sys

path, old, new = sys.argv[1:4]
if not old:
    sys.exit("Error: old_str is empty")

try:
    # newline="" keeps the file's original line endings (\\r\\n stays \\r\\n)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
except OSError as e:
    sys.exit(f"Error: cannot read {path}: {e}")

n = text.count(old)
if n != 1:
    sys.exit(f"Error: old_str found {n} times in {path}, expected exactly 1!"
             "Try to be more precise about old_str by giving more"
             "context of it."
             "The read_file() tool tend to add 1 additional space between the colon and"
             " the content. Take that in consideration."
             "Ex:"
             "read_file ourput --> [200: print('hello world')]"
             "real_file_content --> [print('hello world')]"
             f"old_str received:{old}")

with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(text.replace(old, new, 1))
print(f"Successfully edited {path}")
"""
except ImportError as e:
    print(f"Failed to import required modules: {e}")
    exit(1)
except Exception as e:
    print(f"An unexpected error occurred during initialization: {e}")
    exit(1)
except KeyboardInterrupt:
    print("Execution interrupted by user.")
    exit(1)


class SWEBenchServer:
    def __init__(self, transport: str, host: str, port: int,
                 eval_script: str | None=None,
                 docker_image: str | None=None) -> None:
        """
        If there is no docker image and the variable TESTBED_PATH
        have beed given, then use the local manager.

        If there is a docker image, then use the docker manager
        """

        signal.signal(signal.SIGTERM, lambda signum, frame: exit(0))

        if not docker_image:
            try:
                self.workdir = os.path.abspath(os.environ["TESTBED_PATH"])
            except KeyError:
                raise KeyError("TESTBED_PATH not found.")
            self.manager = LocalManager(self.workdir)
        else:
            self.workdir = VIRTUAL_ROOT
            self.manager = DockerManager(docker_image, self.workdir)

        # initialise the server
        self.server = FastMCP("SWE_bench server")
        self._build_tools()
        self._build_prompt()
        self._build_resource()

        self.transport = transport
        self.host = host
        self.port = port

        if eval_script:
            self.eval_script = self._build_eval_script(eval_script)
        else:
            self.eval_script = None

    def run_server(self) -> None:
        """
        Start the http or stdio server based on the transport method.
        Shutdown the server after it's usage.
        """
        try:
            if self.transport in {"http", "streamable-http"}:
                self.server.run(
                    transport="streamable-http",
                    host=self.host,
                    port=self.port,
                    show_banner=False
                )

            elif self.transport == "stdio":
                self.server.run(show_banner=False)
        finally:
            self.shutdown_server()

    def _build_eval_script(self, eval_script: str):
        """
        Format the eval_script to place the output
        of the setup and teardown in /dev/null and only
        show the actual runned tests
        """
        test_start = ": '>>>>> Start Test Output'"
        test_end = ": '>>>>> End Test Output'"

        if test_start not in eval_script or test_end not in eval_script:
            return eval_script

        setup, rest = eval_script.split(test_start, 1)
        tests, teardown = rest.split(test_end, 1)

        return (f"{{\n{setup}\n}} > /dev/null 2>&1\n"
                "set +x\n"      # the script uses set -x: stop tracing commands
                f"{tests.strip()} 2>&1\n"
                "rc=$?\n"
                f"{{\n{teardown}\n}} > /dev/null 2>&1\n"
                "exit $rc"
        )

    def _host_path(self, path: str) -> str:
        """Map a /testbed/... path to the real workdir (identity in docker mode)"""
        if not path or self.workdir == VIRTUAL_ROOT:
            return path
        norm = os.path.normpath(path)
        if norm == VIRTUAL_ROOT or norm.startswith(VIRTUAL_ROOT + "/"):
            return self.workdir + norm[len(VIRTUAL_ROOT):]
        return path

    def _virtual_paths(self, text: str) -> str:
        """Show host paths as /testbed/... so the agent sees consistent paths"""
        if self.workdir == VIRTUAL_ROOT:
            return text
        return text.replace(self.workdir, VIRTUAL_ROOT)

    def _build_tools(self):
        """Build the tools that the server will procure to clients"""

        def format_code_tools_output(output: str) -> str:
            """
            format the code output:
                file:line:content ---> file:line content
            """
            lines = []
            for line in output.splitlines():
                blocks = line.split(":", 2)

                # Keep lines that don't match (truncation notice, errors...)
                if len(blocks) != 3:
                    lines.append(line)
                else:
                    lines.append(f"{blocks[0]}:{blocks[1]} {blocks[2]}")
            
            return "\n".join(lines)

        def format_filesystem_output(output: str) -> str:
            """
            format a filesystem output:
                   line    content ---> line: content
            """
            lines = []
            for l in output.splitlines():
                line = l.strip()

                line_num = ""
                for i in line:
                    if i.isnumeric():
                        line_num += i
                    else:
                        break
                # 1 is the initial tab that there was.
                # We do that to keep indentation clean.
                line = line[len(line_num):][1:]

                lines.append(f"{line_num}: {line}")

            return "\n".join(lines)

        def _find_cmd(directory: str, ftype: str, pattern: str) -> list[str]:
            excluded = [".git", ".venv", "venv", "env", "__pycache__", "node_modules",
                        "build", "*.egg-info", ".circleci", ".mypy_cache", ".pytest_cache"]

            prune = []
            for d in excluded:
                prune += ["-o", "-name", d] if prune else ["-name", d]
            return ["find", directory,
                    "(", *prune, ")", "-prune",
                    "-o", "-type", ftype, "-name", pattern, "-print"]

        def _to_str(output: str, errors: str, exit_code: int):
            return self._virtual_paths(f"{output}\n\n{errors}\n\n{exit_code}")

        ############# File system tools #############
        @self.server.tool
        def read_file(filepath: str, start_line: int, end_line: int) -> str:
            """Read lines start_line..end_line (inclusive, 1-based) of a source file.

            USE WHEN: you already know the file AND the line number (from
            search_code / search_function_or_class_definition_in_code) and
            need to see the code before editing it.
            DO NOT USE: to browse or "skim" a file, or to read test files.

            LIMIT: read at most 60 lines per call. Center the range on the
            line you found (e.g. found line 340 -> read 320..380).

            Output, one line per file line:
                <line_number>: <exact line content>
            The "<line_number>: " prefix is NOT in the file. Remove it when
            you copy text into edit_file's old_str.
            """
            filepath = self._host_path(filepath)
            if start_line <= 0 or end_line <= 0:
                return "Error: Line need to be superior to 0"

            modified_end = False
            if end_line - start_line > 60:
                end_line = start_line + 60
                modified_end = True

            # A pipe needs bash, so every value is quoted/cast before interpolation
            docker_output = self.manager.exec_command(
                f"cat -n {shlex.quote(filepath)} | sed -n '{start_line},{end_line}p'",
                workdir=os.path.dirname(filepath))
            docker_output["output"] = format_filesystem_output(docker_output["output"])
            if modified_end:
                docker_output["errors"] += ("Too much line to read. Max 60!\n"
                                            "End line have been changed "
                                            f"to {end_line}")
            return _to_str(**docker_output)

        @self.server.tool
        def edit_file(filepath: str, old_str: str, new_str: str) -> str:
            """Replace one exact block of text in a file. This is the ONLY way to change code.

            USE WHEN: you have read the target lines with read_file in an
            earlier step and know exactly what to change.

            old_str: text copied from read_file output WITHOUT the
                "<line_number>: " prefixes, with the exact indentation
                (spaces). It must appear exactly once in the file; if not,
                add 1-2 neighbouring lines to make it unique.
            new_str: the replacement text, with correct indentation.
            Use triple-quoted strings ('''...''') for multi-line text.

            If it fails, re-read the lines with read_file and retry with
            corrected old_str. Do not retry the same call unchanged.
            """
            filepath = self._host_path(filepath)

            # list form: no shell, each argument reaches python untouched
            docker_output = self.manager.exec_command(
                ["python", "-c", EDIT_FILE_SCRIPT, filepath, old_str, new_str],
                workdir=os.path.dirname(filepath)
            )
            return _to_str(**docker_output)

        @self.server.tool
        def list_files(directory: str, pattern: str) -> str:
            """Find files by NAME (recursive) under directory.

            USE WHEN: you know (part of) a file name but not where it is,
            e.g. directory="/testbed/django/db", pattern="query*.py".
            DO NOT USE: to search file contents (use search_code), or with
            a broad pattern like "*.py" on /testbed (output is huge).

            pattern: shell glob matched on the file name only, not the path.
            """
            directory = self._host_path(directory)

            docker_output = self.manager.exec_command(
                _find_cmd(directory, "f", pattern), workdir=directory
            )

            return _to_str(**docker_output)

        @self.server.tool
        def list_directories(directory: str, pattern: str) -> str:
            """Find directories by NAME (recursive) under directory.

            USE WHEN: you need a rough idea of the package layout, e.g.
            directory="/testbed", pattern="*" is too big; prefer a precise
            pattern like pattern="forms" or a deeper directory.
            Rarely needed: search_code usually finds the code faster.

            pattern: shell glob matched on the directory name only.
            """
            directory = self._host_path(directory)

            docker_output = self.manager.exec_command(
                _find_cmd(directory, "d", pattern), workdir=directory
            )
            return _to_str(**docker_output)

        ############# Code search tools #############
        @self.server.tool
        def search_code(pattern: str, file_pattern: str) -> str:
            """Search file CONTENTS in the whole repository (grep -E). Your main exploration tool.

            USE WHEN: you look for an error message, a string, an attribute
            or any text from the issue / failing test output.
            Search specific, rare text (an exact error message, a unique
            name), not common words, to keep the output small.

            pattern: extended regex, e.g. "must be a positive integer".
            file_pattern: glob on file names, usually "*.py".
            Output: "file:line content" for each match. Then use read_file
            around that line.
            """

            # --include match only filename (basename only)
            # this don't work with directory search like path/to/*.py
            # because it will compare path/to/*.py with hello.py which return false.
            # So I split the file_pattern to
            # get a name glob and a search directory

            directory, _, name = file_pattern.rpartition("/")
            directory.replace("/**", "").removesuffix("**")    # -r is already recursive
            search_dir = os.path.join(self.workdir, directory)

            output = self.manager.exec_command(
                ["grep", "-rnE", f"--include={name or '*.py'}", pattern, search_dir]
            )
            output["output"] = format_code_tools_output(output["output"])

            if output["exit_code"] == 1:
                output["output"] += f"\nNo match found for {pattern} in {file_pattern}"

            return _to_str(**output)

        @self.server.tool
        def search_function_or_class_definition_in_code(name: str) -> str:
            """Find where a Python function, method or class is DEFINED ("def name" / "class name").

            USE WHEN: the issue or a traceback mentions a name and you need
            its source. Fastest way to jump to the code to fix.

            name: the bare name only, e.g. "get_prep_value" (no dots, no
            parentheses, no module path).
            Output: "file:line content". Then read_file around that line.
            """

            # -E is needed for | and \s, \b avoids matching "foo" in "foobar"
            output = self.manager.exec_command(
                ["grep", "-rnE", "--include=*.py",
                 rf"^\s*(async\s+)?(def|class)\s+{name}\b", self.workdir]
            )
            output["output"] = format_code_tools_output(output["output"])
            return _to_str(**output)

        @self.server.tool
        def find_references(name: str, filepath: str = "", line: int = 0) -> str:
            """Find where a symbol is USED (called, imported, referenced), not where it is defined.

            USE WHEN: you changed (or plan to change) a function's behaviour
            or signature and must check its callers.
            DO NOT USE: to find the definition (use
            search_function_or_class_definition_in_code).

            name: bare symbol name, e.g. "_parse_header".
            filepath: optional, limit the search to this one file.
            line: optional, keep only matches on this line of filepath.
            Output: "file:line content".
            """
            filepath = self._host_path(filepath)
            if line == 0:
                line = 1

            # -w matches whole words only: "foo" won't match "foobar"
            # -F treats name as plain text, not a regex

            pattern = r'(?<!class\s)(?<!def\s)\b' + name

            # search in all the files
            command = ["grep", "-rnP", "--include=*.py", pattern, self.workdir]
            output = self.manager.exec_command(command,
                                               workdir=os.path.dirname(filepath))


            output["output"] = format_code_tools_output(output["output"])
            return _to_str(**output)

        ############# Execution tools #############
        @self.server.tool
        def run_tests() -> str:
            """Run the official tests for this issue. The ONLY allowed way to test code.

            USE WHEN:
              1. At the start, to see which tests fail and why (error and
                 traceback point you to the code to fix).
              2. After each fix, to verify it.
            Takes no arguments. Always call it as print(run_tests()).
            Never write your own test scripts and never run tests through
            run_command.

            If all tests pass, your next and final step is exactly:
                final_answer(get_patch())
            """
            if not self.eval_script:
                return "No eval script found"

            docker_output = self.manager.exec_command(
                self.eval_script,
                max_bytes=10_000,
                timeout=100
            )

            lines = [i for i in docker_output["output"].splitlines() if not i.startswith("PASSED")]
            docker_output["output"] = "\n".join(lines)

            if docker_output["exit_code"] == 0:
                docker_output["output"] += (
                    "\n\nStatus: all tests passed.\n"
                    "use final_answer(get_patch()) alone in one step."
                    )
            else:
                docker_output["errors"] += (
                    "\n\nStatus: Test failed.\n"
                    "Read the errors failures, correct the code "
                    "and run print(run_tests()) again."
                    )
            return _to_str(**docker_output)

        @self.server.tool
        def get_patch() -> str:
            """Return the git diff of your changes. Use it ONLY as: final_answer(get_patch())

            USE WHEN: run_tests() passed. Call it inside final_answer in a
            single step; never copy the patch text by hand.
            """
            docker_output = self.manager.exec_command("git -c core.fileMode=false diff",
                                                             max_bytes=19_000,
                                                             timeout=100)
            return _to_str(**docker_output)

        @self.server.tool
        def run_command(command: str, workdir: str) -> str:
            """Run a shell command in workdir. LAST RESORT tool.

            USE ONLY WHEN no other tool can do it, e.g. checking a file's
            size with "wc -l file.py" or "git status".
            DO NOT USE for: reading files (cat/head/sed -> use read_file),
            searching (grep/find -> use search_code / list_files), editing
            files (sed -i, echo > -> use edit_file), running tests or python
            scripts (-> use run_tests), installing packages, or starting
            servers.
            Returns stdout, stderr and exit code.
            """
            workdir = self._host_path(workdir)

            docker_output = self.manager.exec_command(command, workdir=workdir)
            return _to_str(**docker_output)

    def _build_prompt(self):
        @self.server.prompt
        def a_prompt():
            """return a life lesson"""
            return "Aim hight!"

    def _build_resource(self):
        @self.server.resource("resource://greeting")
        def a_resource():
            """Greet the traveler"""
            return "greeting traveler!"

    def shutdown_server(self) -> None:
        """Shutdown and remove the container"""
        self.manager.shutdown()


if __name__ == "__main__":
    args: ServerArgs = get_server_args()

    if args.task_file:
        task_input: SWEBenchTaskInput = load_task(args.task_file, "swebench")
        serv = SWEBenchServer(
            docker_image=task_input.docker_image,
            transport=args.transport,
            eval_script=task_input.eval_script,
            host=args.host,
            port=args.port
        )
    else:
        serv = SWEBenchServer(
            transport=args.transport,
            host=args.host,
            port=args.port
        )

    serv.run_server()
