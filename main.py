"""
Proof2Pay Agent System — Main Entry Point

Starts the Slack bot listener and the daily scheduler.
Run with: python main.py
"""

import os
import sys
import logging
import threading

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent_system.log"),
    ],
)
logger = logging.getLogger("proof2pay-agents")


def main():
    logger.info("=" * 60)
    logger.info("PROOF2PAY AGENT SYSTEM STARTING")
    logger.info("=" * 60)

    # Initialize components
    from integrations.anthropic_client import AnthropicClient
    from integrations.google_drive import GoogleDriveClient
    from integrations.github_client import GitHubClient
    from integrations.web_search import WebSearchClient
    from orchestrator.memory_manager import MemoryManager
    from orchestrator.runner import AgentRunner
    from orchestrator.dispatcher import Dispatcher
    from orchestrator.agent_tools import AgentToolHandler
    from orchestrator.scheduler import DailyScheduler
    from integrations.slack_bot import SlackBot

    # Core services
    anthropic = AnthropicClient()
    drive = GoogleDriveClient()
    github = GitHubClient()
    web_search = WebSearchClient()
    tool_handler = AgentToolHandler(github_client=github, web_search_client=web_search)
    memory = MemoryManager(drive_client=drive)
    runner = AgentRunner(anthropic, memory, tool_handler=tool_handler)
    dispatcher = Dispatcher(runner, memory)

    logger.info(f"Loaded {len(runner.agents)} agents from config")

    # Slack bot
    slack_bot = SlackBot(runner=runner, dispatcher=dispatcher)
    logger.info("Slack bot initialized")

    # Scheduler
    scheduler = DailyScheduler(
        runner=runner,
        dispatcher=dispatcher,
        memory=memory,
        slack_bot=slack_bot,
        drive_client=drive,
    )
    scheduler.start()
    logger.info("Scheduler started")

    # Start Slack bot (this blocks)
    logger.info("Starting Slack listener...")
    try:
        slack_bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.stop()
        logger.info("Agent system stopped")


if __name__ == "__main__":
    main()
