"""
CLI tool for testing agents locally without Slack.
Run with: python cli.py <agent_id> "<task>"

Examples:
    python cli.py chief_of_staff "Generate a daily briefing"
    python cli.py domain_intelligence "Analyze this budget template for product gaps"
    python cli.py compliance "Produce a SOC 2 preparation checklist"
    python cli.py technical_pm "Review the current data model for edge cases in split-funding budgets"
    python cli.py market_research "Research the top 5 state human services agencies by NPO contract volume"
    python cli.py fundraising "Identify 10 GovTech-focused seed investors"
    python cli.py regulatory "Catalog the 20 most common invoice validation rules from 2 CFR 200"
    python cli.py brand_marketing "Draft a brand territory document"
    python cli.py competitive_intel "Map the current grant management software landscape"

Flags:
    --interactive    Run in interactive mode (conversation loop)
    --daily          Trigger the daily cycle now
    --summary        Show an agent's current memory summary
    --usage          Show token usage stats
"""

import os
import sys
import argparse

from dotenv import load_dotenv

load_dotenv()

from integrations.anthropic_client import AnthropicClient
from integrations.google_drive import GoogleDriveClient
from integrations.github_client import GitHubClient
from integrations.web_search import WebSearchClient
from orchestrator.memory_manager import MemoryManager
from orchestrator.runner import AgentRunner
from orchestrator.dispatcher import Dispatcher
from orchestrator.agent_tools import AgentToolHandler


def main():
    parser = argparse.ArgumentParser(description="Proof2Pay Agent CLI")
    parser.add_argument("agent_id", nargs="?", help="Agent to run")
    parser.add_argument("task", nargs="?", help="Task to execute")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--daily", action="store_true", help="Run daily cycle")
    parser.add_argument("--summary", "-s", action="store_true", help="Show agent summary")
    parser.add_argument("--usage", "-u", action="store_true", help="Show token usage")
    parser.add_argument("--list", "-l", action="store_true", help="List all agents")
    args = parser.parse_args()

    # Init
    anthropic = AnthropicClient()
    drive = GoogleDriveClient()
    github = GitHubClient()
    web_search = WebSearchClient()
    tool_handler = AgentToolHandler(github_client=github, web_search_client=web_search)
    memory = MemoryManager(drive_client=drive)
    runner = AgentRunner(anthropic, memory, tool_handler=tool_handler)
    dispatcher = Dispatcher(runner, memory)

    # List agents
    if args.list:
        print("\nAvailable agents:")
        for aid, config in runner.agents.items():
            print(f"  {aid:20s} — {config.get('name', '')} ({config.get('schedule', '')})")
        return

    # Daily cycle
    if args.daily:
        from orchestrator.scheduler import DailyScheduler

        scheduler = DailyScheduler(runner, dispatcher, memory, drive_client=drive)
        print("Running daily cycle...\n")
        scheduler.run_now()
        _print_usage(anthropic)
        return

    if not args.agent_id:
        parser.print_help()
        return

    # Show summary
    if args.summary:
        summary = memory.get_summary(args.agent_id)
        if summary:
            print(f"\n--- {args.agent_id} Summary ---\n")
            print(summary)
        else:
            print(f"No summary found for {args.agent_id}")
        return

    # Interactive mode
    if args.interactive:
        print(f"\nInteractive mode with {args.agent_id}. Type 'quit' to exit.\n")
        conv_id = f"cli_{args.agent_id}"

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            response = runner.run_interactive(
                agent_id=args.agent_id,
                user_message=user_input,
                conversation_id=conv_id,
            )
            print(f"\n{args.agent_id}: {response}\n")

        _print_usage(anthropic)
        return

    # Single task run
    if not args.task:
        print("Error: task required (or use --interactive)")
        return

    print(f"\nRunning {args.agent_id}: {args.task[:80]}...\n")
    result = runner.run(agent_id=args.agent_id, task=args.task)

    print("--- Output ---\n")
    print(result["content"])
    print(f"\n--- Tokens: {result['tokens']['input']}in / {result['tokens']['output']}out ---")
    print(f"--- Saved to: {result['output_file']} ---")

    _print_usage(anthropic)


def _print_usage(client: AnthropicClient):
    if args_global_usage:
        usage = client.get_usage_summary()
        print(f"\n--- Session Usage ---")
        print(f"Calls: {usage['total_calls']}")
        print(f"Input tokens: {usage['total_input_tokens']:,}")
        print(f"Output tokens: {usage['total_output_tokens']:,}")
        print(f"Est. cost: ${usage['estimated_cost_usd']:.4f}")


args_global_usage = "--usage" in sys.argv or "-u" in sys.argv

if __name__ == "__main__":
    main()
