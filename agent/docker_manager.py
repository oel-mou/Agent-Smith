import docker
import sys
import os
import pathlib
import time
import shlex


class DockerManager:
    client = docker.from_env()

    def __init__(self, docker_image: str, workdir: str, name: str | None = None):
        # The docker SDK automatically tracks the ID under the hood.
        # You can still view it with container.id
        self.container = self.run_container(docker_image, name)
        self.up = True
        if not self.verif_dir(workdir):
            raise NotADirectoryError(
                f"Invalid workdir: '{workdir}' does not exist"
            )
        self.workdir = workdir

    @classmethod
    def pull_image(cls, docker_image):
        """Verify if the image is present in local, if not then pull it from docker hub"""

        try:
            cls.client.images.get(docker_image)
        except docker.errors.NotFound:
            print(
                f"image not found localy, pulling {docker_image} from dockerhub.",
                file=sys.stderr,
            )

            try:
                # need the flag platefrom when I'm one mac
                cls.client.images.pull(docker_image, platform="linux/amd64")
            except docker.errors.NotFound:
                raise ValueError(
                    f"Error: Image [{docker_image}] not found on dockerhub.\n"
                    "Please retry with a valid image."
                )
        except Exception as e:
            raise ValueError(f"An error occured while pulling the image:\n{e}")

    @classmethod
    def run_container(
        cls, docker_image: str, name: str | None = None
    ) -> docker.models.containers.Container:
        """Run a container from the given image"""

        # The image will be pulled if not already present
        # Http will pull it here, stdio will run it immediately,
        # because it already pulled it with pull_image()
        run_options = {"command": "sleep infinity",
                       "detach": True,
                       "platform": "linux/amd64"}
        if name is not None:
            run_options["name"] = name

        container = cls.client.containers.run(docker_image, **run_options)
        return container

    def verif_dir(self, dir: str):
        exit_code, _ = self.container.exec_run(
            cmd=["test", "-d", dir],
            demux=True
        )
        if exit_code != 0:
            return False
        return True

    def is_authorized_path(self, path) -> bool:
        """Verify if the given path is authorized or not"""
        return pathlib.PurePosixPath(path).is_relative_to(self.workdir)

    def _abs(self, directory):
        return os.path.normpath(os.path.join(self.workdir, directory))

    def exec_command(
        self,
        command: str | list[str],
        workdir=None,
        timeout: int = 10,
        max_bytes: int | None = 10_000,
        tries: int=0,
    ) -> dict[str, str | int]:
        """
        Execute the given command inside the container object,
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
            elif not self.verif_dir(workdir):
                return {"output": "",
                        "errors": "Invalid path: "
                                  f"{workdir}\n"
                                  f"Directory not found",
                        "exit_code": 1}
        workdir = self.workdir

        if isinstance(command, str):
            # to activate bash and the python environment
            command = ["/bin/bash", "-c",
                       "source /opt/miniconda3/bin/activate"
                       " && conda activate testbed && " + command]

        exit_code, out = self.container.exec_run(
            cmd=["timeout", "--kill-after=5", str(timeout), *command],
            workdir=workdir,
            demux=True
        )
        b_output = out[0] if out[0] else b""
        b_errors = out[1] if out[1] else b""

        truncated_err, truncated_out = False, False

        if max_bytes:
            n = len(b_output)
            if n > max_bytes:
                b_output = b_output[n - max_bytes: n]
                truncated_out = True
            n = len(b_errors)
            if n > max_bytes:
                b_errors = b_errors[n - max_bytes: n]
                truncated_err = True

        output = b_output.decode('utf8', errors='replace')
        errors = b_errors.decode('utf8', errors='replace')

        if truncated_out:
            output += f"\n[Output too long, returned the last {max_bytes} bytes]"
        if truncated_err:
            errors += f"\n[Errors were too long returned the last {max_bytes} bytes]"

        if exit_code == 124:
            errors += f"\n[Command timed out after {timeout}s]"
        # in case process did not respond to timeout
        elif exit_code == 137:
            errors += f"\n[process was killed after {timeout + 5}s]"

        # problem with exec (rare but possible)
        elif exit_code == 126 and tries < 3:
            print("Problem with exec found, retrying...", file=sys.stderr)
            time.sleep(2)
            return self.exec_command(command,
                                     workdir=workdir,
                                     timeout=timeout,
                                     max_bytes=max_bytes,
                                     tries=tries + 1)

        return {"output": output,
                "errors": errors,
                "exit_code": exit_code}

    def shutdown(self):
        """stop then remove the running conrainer"""
        if self.up:
            self.container.remove(force=True)
            self.up = False

# # test
# if __name__ == "__main__":
#     try:
#         manager = DockerManager('swebench/sweb.eval.x86_64.django_1776_django-11603:latest', "/testbed")
#         print(manager.exec_command("sleep 10"))
#     finally:
#         manager.shutdown()
