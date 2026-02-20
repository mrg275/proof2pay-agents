"""
Daily scheduler. Runs agents on their configured cadences and
triggers the Chief of Staff daily briefing.
"""

import os
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from orchestrator.runner import AgentRunner
from orchestrator.dispatcher import Dispatcher, COS_TOOLS
from orchestrator.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class DailyScheduler:
    """Manages scheduled agent runs and daily briefings."""

    def __init__(
        self,
        runner: AgentRunner,
        dispatcher: Dispatcher,
        memory: MemoryManager,
        slack_bot=None,
        drive_client=None,
    ):
        self.runner = runner
        self.dispatcher = dispatcher
        self.memory = memory
        self.slack_bot = slack_bot
        self.drive = drive_client
        self.scheduler = BackgroundScheduler()
        self._last_run_dates = {}

    def start(self):
        """Start the scheduler with configured agent cadences."""
        hour = int(os.environ.get("DAILY_BRIEFING_HOUR", 7))
        minute = int(os.environ.get("DAILY_BRIEFING_MINUTE", 0))
        tz = os.environ.get("TIMEZONE", "America/New_York")

        # Daily cycle runs every morning
        self.scheduler.add_job(
            self.run_daily_cycle,
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            id="daily_cycle",
            name="Daily Agent Cycle",
        )

        self.scheduler.start()
        logger.info(f"Scheduler started. Daily cycle at {hour:02d}:{minute:02d} {tz}")

    def stop(self):
        """Shutdown the scheduler."""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    def run_daily_cycle(self):
        """
        Execute the full daily agent cycle:
        1. Run research agents that are due
        2. Run Chief of Staff briefing
        3. Execute any tasks the Chief of Staff dispatches
        4. Post briefing to Slack
        """
        logger.info("=" * 60)
        logger.info("DAILY CYCLE STARTING")
        logger.info("=" * 60)

        today = datetime.now().date()

        # Define which agents run on what schedule
        schedule_map = {
            "daily": 1,
            "weekly": 7,
            "biweekly": 14,
        }

        research_agents = [
            "compliance",
            "market_research",
            "fundraising",
            "competitive_intel",
            "regulatory",
            "brand_marketing",
        ]

        # Run research agents that are due
        for agent_id in research_agents:
            agent_config = self.runner.agents.get(agent_id, {})
            schedule = agent_config.get("schedule", "weekly")
            interval_days = schedule_map.get(schedule, 7)

            last_run = self._last_run_dates.get(agent_id)
            if last_run and (today - last_run).days < interval_days:
                logger.info(f"Skipping {agent_id} (last ran {last_run}, interval={interval_days}d)")
                continue

            try:
                self._run_research_agent(agent_id)
                self._last_run_dates[agent_id] = today
            except Exception as e:
                logger.error(f"Failed to run {agent_id}: {e}")

        # Run Chief of Staff briefing
        try:
            briefing = self._run_chief_of_staff_briefing()
            if self.slack_bot and briefing:
                channel = os.environ.get("SLACK_CHANNEL_DAILY_BRIEFING")
                if channel:
                    self.slack_bot.post_message(channel, briefing)
                    logger.info("Daily briefing posted to Slack")
        except Exception as e:
            logger.error(f"Chief of Staff briefing failed: {e}")

        # Update Google Drive knowledge index
        if self.drive:
            try:
                self._update_knowledge_index()
            except Exception as e:
                logger.error(f"Knowledge index update failed: {e}")

        logger.info("=" * 60)
        logger.info("DAILY CYCLE COMPLETE")
        logger.info("=" * 60)

    def _run_research_agent(self, agent_id: str):
        """Run a research agent with its default task."""
        logger.info(f"Running research agent: {agent_id}")

        default_tasks = {
            "compliance": (
                "Conduct your regular research cycle. Check for any updates to FedRAMP, "
                "GovRAMP, SOC 2, or NIST 800-53 that affect Proof2Pay. Review the current "
                "compliance gap analysis and update if needed. Identify any new compliance "
                "insights that should be surfaced in the daily briefing."
            ),
            "market_research": (
                "Conduct your regular research cycle. Look for new information about "
                "government human services agencies that could be prospects. Check for "
                "GovTech news, procurement announcements, technology mandates, or "
                "leadership changes. Update agency target rankings if new info warrants it."
            ),
            "fundraising": (
                "Conduct your regular research cycle. Look for new GovTech investment "
                "activity, fund announcements, or relevant funding rounds. Update the "
                "investor pipeline with any new findings. Refine market sizing if new "
                "data is available."
            ),
            "competitive_intel": (
                "Conduct your regular scan. Check competitor websites, GovTech news, "
                "and government contract award databases for any movements in the "
                "grant management and invoice compliance space. Flag any new entrants "
                "or significant product announcements."
            ),
            "regulatory": (
                "Conduct your regular research cycle. Check for changes to 2 CFR 200, "
                "FAR, or OMB circulars. Look for state-specific grant compliance updates. "
                "Identify any new rule patterns that should be added to the common "
                "patterns library."
            ),
            "brand_marketing": (
                "Conduct your regular creative cycle. Review current brand positioning "
                "against competitive landscape. Check for any GovTech brand examples "
                "worth studying. Refine messaging framework if new market or competitive "
                "intelligence is available. Identify any materials that need creation "
                "or updating."
            ),
        }

        task = default_tasks.get(agent_id, "Conduct your regular research cycle and report findings.")

        result = self.runner.run(agent_id=agent_id, task=task)

        # Update the agent's summary by asking a quick summarization
        self._update_agent_summary(agent_id, result["content"])

        return result

    def _update_agent_summary(self, agent_id: str, new_output: str):
        """Update an agent's running summary with the latest output."""
        current_summary = self.memory.get_summary(agent_id)

        summarize_prompt = (
            "You are a summarization assistant. Your job is to maintain a concise "
            "running summary of an agent's key findings, decisions, and outputs. "
            "The summary must stay under 3000 characters. Focus on facts, findings, "
            "and actionable items. Drop old items that have been superseded."
        )

        message = (
            f"Here is the current running summary:\n\n{current_summary or '(No previous summary)'}\n\n"
            f"Here is the latest output to incorporate:\n\n{new_output}\n\n"
            f"Produce an updated running summary that incorporates the new findings. "
            f"Keep it under 3000 characters. Prioritize actionable and current information."
        )

        response = self.runner.client.call(
            system_prompt=summarize_prompt,
            user_message=message,
            model=self.runner.client.HAIKU,  # Use Haiku for cheap summarization
            max_tokens=2048,
        )

        self.memory.update_summary(agent_id, response["content"])

    def _run_chief_of_staff_briefing(self) -> str:
        """Run the Chief of Staff daily briefing with dispatch capability."""
        logger.info("Running Chief of Staff daily briefing...")

        system_prompt = self.runner._load_system_prompt("chief_of_staff")
        context = self.runner._assemble_context("chief_of_staff")
        full_system = f"{system_prompt}\n\n---\n\n{context}"

        task = (
            "Generate today's daily briefing. Review all agent summaries and recent "
            "outputs. Identify: (1) critical items requiring founder action, (2) key "
            "research findings from overnight runs, (3) cross-domain connections, "
            "(4) any tasks you want to dispatch to specialist agents today. "
            "Use the dispatch_agent tool if you identify tasks worth running. "
            "Format the briefing clearly with the most important items first."
        )

        messages = [{"role": "user", "content": task}]

        # Initial call with tools
        response = self.runner.client.call_with_conversation(
            system_prompt=full_system,
            messages=messages,
            tools=COS_TOOLS,
        )

        # Handle any dispatch loops
        if response.get("tool_calls"):
            final_content = self.dispatcher.execute_dispatch_loop(
                initial_response=response,
                system_prompt=full_system,
                original_messages=messages,
            )
        else:
            final_content = response.get("content", "")

        # Save the briefing
        self.memory.save_output(
            agent_id="chief_of_staff",
            output=final_content,
            task="daily_briefing",
        )

        return final_content

    def _update_knowledge_index(self):
        """Rebuild the knowledge index on Google Drive from all agent summaries."""
        all_summaries = self.memory.get_all_summaries()
        if not all_summaries:
            return

        index_parts = [
            "# Proof2Pay Knowledge Index",
            f"*Auto-generated: {datetime.now().isoformat()}*\n",
        ]
        for agent_id, summary in all_summaries.items():
            agent_name = self.runner.agents.get(agent_id, {}).get("name", agent_id)
            index_parts.append(f"## {agent_name}\n\n{summary[:500]}\n")

        self.drive.update_knowledge_index("\n".join(index_parts))
        logger.info("Knowledge index updated on Drive")

    def run_now(self):
        """Trigger the daily cycle immediately (for testing)."""
        self.run_daily_cycle()
