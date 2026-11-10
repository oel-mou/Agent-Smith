try:
    from agent import Args, DockerManager, SWEBenchTaskInput, get_args, load_task
    from .swe_agent_loop import SWEBenchAgentLoop
except ImportError as e:
    print(f"Failed to import required modules: {e}")
    exit(1)
except Exception as e:
    print(f"An unexpected error occurred during initialization: {e}")
    exit(1)
except KeyboardInterrupt:
    print("Execution interrupted by user.")
    exit(1)


def start():
    args: Args = get_args()
    task: SWEBenchTaskInput = load_task(args.task_file, "swebench")

    # pull the image now, so it won't take long to run the container later
    DockerManager.pull_image(task.docker_image)

    agent_loop = SWEBenchAgentLoop(args.model_name, args.provider_url)
    agent_loop.run_task_from_file(args.task_file, args.output)


if __name__ == "__main__":

    try:
        start()
    except Exception as e:
        print(f"\n{e}")
    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
