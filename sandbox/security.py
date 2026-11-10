import ast
from pathlib import Path
import os
import sys
from typing import Any, List, Mapping, Sequence, Callable
import builtins
from types import ModuleType


def make_safe_import(authorized_imports: List[str]) -> Callable[..., ModuleType]:
    """Return an import function that enforces the allowlist."""
    def is_allowed(name: str) -> bool:
        """Return whether a module matches an exact or wildcard rule."""
        return name in authorized_imports or any(
            name == pattern[:-2]
            or name.startswith(pattern[:-2] + ".")
            for pattern in authorized_imports 
            if pattern.endswith(".*")
        )

    def safe_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        """Return an allowed module with restricted helpers filtered out."""
        if level != 0:
            raise ImportError(
                "Relative imports are not supported in the sandbox."
            )

        if not is_allowed(name):
            raise ImportError(
                f"Import of '{name}' is not allowed in the sandbox."
            )

        for imported_name in fromlist or ():
            if imported_name.startswith("_"):
                raise PermissionError(
                    "Importing private names is blocked in the sandbox."
                )

        module = builtins.__import__(
            name, globals, locals, fromlist, level
        )

        restricted_names = {
            "operator": {"attrgetter", "methodcaller"},
            "string": {"Formatter"},
        }

        if module.__name__ in restricted_names:
            restricted = ModuleType(module.__name__)
            blocked = restricted_names[module.__name__]

            for attribute, value in vars(module).items():
                if attribute.startswith("_") or attribute in blocked:
                    continue

                setattr(restricted, attribute, value)

            module = restricted 
        # Check module objects exposed by a from-import.
        names = fromlist or ()

        if "*" in names:
            names = getattr(
                module,
                "__all__",
                [key for key in vars(module) if not key.startswith("_")],
            )

        for item in names:
            value = getattr(module, item, None)

            if isinstance(value, ModuleType):
                if not is_allowed(value.__name__):
                    raise ImportError(
                        f"Import of '{value.__name__}' "
                        "is not allowed in the sandbox."
                    )

        return module

    return safe_import


def validate_code(code: str) -> None:
    """Reject direct access to private names and frame internals."""
    tree = ast.parse(code)

    blocked_attributes = {
        "gi_frame", "cr_frame", "ag_frame",
        "f_globals", "f_locals", "f_builtins", "f_back",
        "tb_frame", "tb_next",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if (
                node.attr.startswith("_")
                or node.attr in blocked_attributes
            ):
                raise PermissionError(
                    f"Access to attribute '{node.attr}' is blocked."
                )

        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise PermissionError(
                    f"Access to name '{node.id}' is blocked."
                )


def is_allowed_path(path: str, allowed_directories: List[str]) -> bool:
    """Return whether the resolved path is inside an allowed directory."""
    resolved = Path(path).resolve()

    return any(
        resolved.is_relative_to(Path(directory).resolve())
        for directory in allowed_directories
    )


def install_filesystem_guard(allowed_directories: List[str]) -> None:
    """Install a child audit hook for supported filesystem operations."""
    def audit(event: str, args: tuple[Any, ...]) -> None:
        """Reject filesystem events that violate the path policy."""
        if event not in {
            "open", "os.listdir", "os.scandir",
            "os.remove", "os.rmdir", "os.mkdir",
            "os.rename", "os.link", "os.symlink",
            "os.chmod", "os.chown", "os.utime", "os.truncate",
        }:
            return
        
        if event in {"os.chmod", "os.chown", "os.utime", "os.truncate"}:
            raise PermissionError(
                "Changing file metadata or truncating files is not supported "
                "in the sandbox. Use MCP tools."
            )

        if event in {"os.rename", "os.link", "os.symlink"}:
            raise PermissionError(
                "Renaming and creating links are not supported "
                "in the sandbox. Use MCP tools."
            ) 

        if event == "os.mkdir":
            # mkdir reports (path, mode, dir_fd); deletion uses (path, dir_fd).
            if args[2] not in (None, -1):
                raise PermissionError(
                    "Directory creation using a directory descriptor is blocked."
                )
        if event in {"os.remove", "os.rmdir"}:
            if args[1] not in (None, -1):
                raise PermissionError(
                    "Deletion using a directory descriptor is blocked."
                ) 

        path = args[0]

        # Listing without a path means the current directory.
        if path is None:
            path = os.getcwd()

        if isinstance(path, int):
            raise PermissionError(
                "Opening existing file descriptors is blocked."
            )

        if not is_allowed_path(os.fsdecode(path), allowed_directories):
            raise PermissionError(
                "File access outside allowed_directories is blocked."
            )
    sys.addaudithook(audit)


def install_process_guard() -> None:
    """Install a child audit hook that blocks process creation."""
    def audit(event: str, args: tuple[Any, ...]) -> None:
        """Reject audited commands, forks, and subprocess launches."""
        if event in {
            "os.system",
            "os.exec",
            "os.spawn",
            "os.posix_spawn",
            "os.fork",
            "os.forkpty",
            "subprocess.Popen",
        }:
            raise PermissionError(
                "Starting external processes is blocked in the sandbox."
            )
    sys.addaudithook(audit)


def install_network_guard() -> None:
    """Install a child audit hook that blocks socket events."""
    def audit(event: str, args: tuple[Any, ...]) -> None:
        """Reject socket operations in generated code."""
        if event.startswith("socket."):
            raise PermissionError(
                "Network access is blocked in the sandbox."
            )
    sys.addaudithook(audit)
