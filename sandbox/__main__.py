try:
    import argparse
    from sandbox.config import SandboxConfig
    from sandbox.sandbox import Sandbox
    import json
    import sys

    # ANSI escape codes
    RED = "\033[31m"
    GREEN = "\033[32m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
except ImportError as e:
    print(f"Failed to import required modules: {e}")
    exit(1)
except Exception as e:
    print(f"An unexpected error occurred during initialization: {e}")
    exit(1)
except KeyboardInterrupt:
    print("Execution interrupted by user.")
    exit(1)


def read_config(config_file: str) -> SandboxConfig:
    """Return validated JSON configuration or raise ValueError."""

    try:
        with open(config_file, "r") as f:
            config_data = json.load(f)
            return SandboxConfig(**config_data)
    except Exception as e:
        raise ValueError(f"Error reading configuration file: {e}")


def main() -> int:
    """Run the interactive or piped CLI and return its exit code."""
    parser = argparse.ArgumentParser(description="Sandbox CLI")
    parser.add_argument("config_file", nargs="?")

    # Accept one connection mode per invocation.
    connection = parser.add_mutually_exclusive_group()
    connection.add_argument("--mcp-stdio")
    connection.add_argument("--mcp-server")

    args = parser.parse_args()
    sandbox = None
    exit_code = 0

    try:
        config = (
            read_config(args.config_file)
            if args.config_file
            else SandboxConfig()
        )

        sandbox = Sandbox(
            config,
            mcp_stdio=args.mcp_stdio,
            mcp_server=args.mcp_server,
        )
        sandbox.start()

        if sys.stdin.isatty():
            print(f"{BOLD}Enter Python; a blank line executes it.")
            print(
                f"Use {RED}:manual{RESET} {BOLD}for documentation or" 
                f"{RED}{BOLD}:quit{RESET} {BOLD}to exit.{RESET}")

            while True:
                # Gather one code block; a blank line submits it.
                lines = []

                while True:

                    line = input(
                        f"{GREEN}>>> {RESET}" 
                        if not lines else f"{GREEN}... {RESET}")

                    if not lines and line == ":quit":
                        raise EOFError 

                    if not lines and line == ":manual":
                        print(sandbox.get_manual())
                        break

                    if not line:
                        if lines:
                            result = sandbox.run("\n".join(lines))
                            print(result.model_dump_json())
                        break

                    lines.append(line)
        else:
            result = sandbox.run(sys.stdin.read())
            print(result.model_dump_json())
            if result.status not in {"ok", "final_answer"}:
                exit_code = 1

    except EOFError:
        pass
    except KeyboardInterrupt:
        # Conventional shell status for SIGINT: 128 + 2.
        exit_code = 130
    except Exception as e:
        print(f"{RED}{BOLD}Sandbox error:{RESET} {e}", file=sys.stderr)
        exit_code = 1
    finally:
        if sandbox is not None:
            try:
                sandbox.close()
            except Exception as e:
                print(
                    f"{RED}{BOLD}Sandbox cleanup failed:{RESET} {e}",
                    file=sys.stderr)

                if exit_code == 0:
                    exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
