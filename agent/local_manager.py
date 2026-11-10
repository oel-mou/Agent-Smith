import sys
import os
import pathlib
import subprocess


class LocalManager:
    def __init__(self, workdir: str):
        if not self.verif_workdir(workdir):
            raise NotADirectoryError(
                f"Invalid workdir: {workdir} does not exist")
        self.workdir = workdir

    def verif_workdir(self, directory):
        """Verify if the workdir exist in the host"""
        return os.path.isdir(directory)

    def is_authorized_path(self, path) -> bool:
        """Verify if the given path is authorized or not"""
        return pathlib.PurePosixPath(
             os.path.normpath(path)).is_relative_to(self.workdir)

    def _abs(self, path: str) -> str:
        return os.path.normpath(os.path.join(self.workdir, path))

    def exec_command(
        self,
        command: str | list[str],
        workdir=None,
        timeout: int = 10,
        max_bytes: int | None = 19_000,
        tries: int = 0,
    ) -> dict[str, str | int]:
        """
        Execute the given command in the host,
        with a timeout, and a maximum byte to output.

        command can be:
            - a list: executed directly, every element is passed as-is
              to the program (no shell, so no quoting/escaping issues).
            - a string: executed with bash -c (pipes, &&, globs...).
              Any user value inside it must be wrapped with shlex.quote().

        max_bytes is set to 10k, mcp server limit is 19k
        """
        if workdir:
            workdir = self._abs(workdir)
            if not self.is_authorized_path(workdir):
                return {"output": "",
                        "errors": "Unauthorized path: "
                                  f"{workdir}\n"
                                  f"Only commands inside {self.workdir} "
                                  "are authorized",
                        "exit_code": 1}
            elif not self.verif_workdir(workdir):
                return {"output": "",
                        "errors": "Invalid path: "
                                  f"{workdir}\n"
                                  f"Directory not found",
                        "exit_code": 1}
        workdir = self.workdir

        if isinstance(command, str):
            # to activate bash and the python environment
            command = ["/bin/bash", "-c", command]

        out = subprocess.run(
            ["timeout", "--kill-after=5", str(timeout), *command],
            capture_output=True, text=True, cwd=workdir
        )

        output = out.stdout
        errors = out.stderr
        exit_code = out.returncode
        truncated_err, truncated_out = False, False

        if max_bytes:
            n = len(out.stdout)
            if n > max_bytes:
                output = output[n - max_bytes: n]
                truncated_out = True
            n = len(out.stderr)
            if n > max_bytes:
                errors = errors[n - max_bytes: n]
                truncated_err = True

        if truncated_out:
            output += f"\n[Output too long, returned the last {max_bytes} bytes]"
        if truncated_err:
            errors += f"\n[Errors were too long returned the last {max_bytes} bytes]"

        if exit_code == 124:
            errors += f"\n[Command timed out after {timeout}s]"
        # in case process did not respond to timeout
        elif exit_code == 137:
            errors += f"\n[process was killed after {timeout + 5}s]"

        return {"output": output,
                "errors": errors,
                "exit_code": exit_code}

    def shutdown(self):
        pass


# # test
# if __name__ == "__main__":
#     manager = LocalManager("/home/aaliouan")
#     print(manager.exec_command("sleep 10"))

