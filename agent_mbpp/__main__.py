try:
    from agent.parsing import Args, get_args, get_api_keys
    from agent.error import AgentError
    from agent_mbpp.agent_mbpp_loop import MBPPAgent
except ImportError as e:
    print(f"Failed to import required modules: {e}")
    exit(1)
except Exception as e:
    print(f"An unexpected error occurred during initialization: {e}")
    exit(1)
except KeyboardInterrupt:
    print("Execution interrupted by user.")
    exit(1)


def main():
    agent = None
    try:
        args: Args = get_args()
        api_keys = get_api_keys(args.provider_url)
        agent = MBPPAgent(
            model_name=args.model_name,
            provider_url=args.provider_url,
            api_keys=api_keys,
            args=args)
        solution = agent.run_task_from_file(task_file=args.task_file)
        agent.save_solution_to_file(solution, output_file=args.output)
    finally:
        if agent:
            agent.stop()  # Ensure the sandbox is stopped after execution


if __name__ == "__main__":
    try:
        main()
    except AgentError as e:
        print(e)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    except KeyboardInterrupt:
        print("Execution interrupted by user.")
