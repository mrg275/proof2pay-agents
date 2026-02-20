"""
Slack bot integration.
Listens for messages, routes to appropriate agents, and posts responses.
"""

import os
import re
import logging
import threading
from typing import Optional

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

logger = logging.getLogger(__name__)


class SlackBot:
    """Slack bot that routes messages to agents and posts responses."""

    def __init__(self, runner=None, dispatcher=None):
        self.runner = runner
        self.dispatcher = dispatcher

        self.app = App(
            token=os.environ["SLACK_BOT_TOKEN"],
            signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
        )
        self.client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

        # Channel ID -> agent mapping (populated from env vars)
        self.channel_agent_map = {}
        self._setup_channel_mapping()
        self._setup_handlers()

    def _setup_channel_mapping(self):
        """Map Slack channel IDs to agent IDs."""
        cos_channel = os.environ.get("SLACK_CHANNEL_CHIEF_OF_STAFF")
        domain_channel = os.environ.get("SLACK_CHANNEL_DOMAIN_INTEL")

        if cos_channel:
            self.channel_agent_map[cos_channel] = "chief_of_staff"
        if domain_channel:
            self.channel_agent_map[domain_channel] = "domain_intelligence"

    def _setup_handlers(self):
        """Register Slack event handlers."""

        @self.app.event("message")
        def handle_message(event, say):
            self._handle_message(event, say)

        @self.app.event("file_shared")
        def handle_file(event, say):
            self._handle_file_shared(event, say)

        @self.app.event("app_mention")
        def handle_mention(event, say):
            self._handle_message(event, say)

    def _handle_message(self, event: dict, say):
        """Route incoming messages to the appropriate agent."""
        # Ignore bot messages to prevent loops
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        channel = event.get("channel", "")
        user = event.get("user", "")
        text = event.get("text", "")

        if not text.strip():
            return

        agent_id = self.channel_agent_map.get(channel)
        if not agent_id:
            return  # Message in an unmapped channel, ignore

        logger.info(f"Message in {channel} -> agent {agent_id}: {text[:80]}...")

        # Use thread_ts as conversation ID for continuity
        thread_ts = event.get("thread_ts", event.get("ts", ""))
        conversation_id = f"{channel}_{thread_ts}"

        try:
            if agent_id == "chief_of_staff":
                response = self._handle_chief_of_staff_message(text, conversation_id)
            else:
                response = self._handle_agent_message(agent_id, text, conversation_id)

            # Post response in thread
            say(text=response, thread_ts=event.get("ts"))

        except Exception as e:
            logger.error(f"Error handling message for {agent_id}: {e}")
            say(
                text=f"I ran into an error processing that. Let me try again or rephrase your request.",
                thread_ts=event.get("ts"),
            )

    def _handle_chief_of_staff_message(self, text: str, conversation_id: str) -> str:
        """Handle a message to the Chief of Staff with dispatch capability."""
        from orchestrator.dispatcher import COS_TOOLS

        if not self.runner or not self.dispatcher:
            return "Agent system not fully initialized."

        # Load system prompt and context
        system_prompt = self.runner._load_system_prompt("chief_of_staff")
        context = self.runner._assemble_context("chief_of_staff")
        full_system = f"{system_prompt}\n\n---\n\n{context}"

        # Get conversation history
        history = self.runner.memory.get_conversation("chief_of_staff", conversation_id)
        messages = []
        for turn in history[-20:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": text})

        # Call with tools enabled
        response = self.runner.client.call_with_conversation(
            system_prompt=full_system,
            messages=messages,
            tools=COS_TOOLS,
        )

        # Handle dispatch loops if the CoS wants to delegate
        if response.get("tool_calls"):
            final_content = self.dispatcher.execute_dispatch_loop(
                initial_response=response,
                system_prompt=full_system,
                original_messages=messages,
            )
        else:
            final_content = response.get("content", "")

        # Save conversation
        self.runner.memory.save_conversation_turn(
            "chief_of_staff", conversation_id, "user", text
        )
        self.runner.memory.save_conversation_turn(
            "chief_of_staff", conversation_id, "assistant", final_content
        )

        return final_content

    def _handle_agent_message(self, agent_id: str, text: str, conversation_id: str) -> str:
        """Handle a message to any interactive agent (e.g., Domain Intelligence)."""
        if not self.runner:
            return "Agent system not fully initialized."

        return self.runner.run_interactive(
            agent_id=agent_id,
            user_message=text,
            conversation_id=conversation_id,
        )

    def _handle_file_shared(self, event: dict, say):
        """Handle file uploads - download and pass to the relevant agent."""
        channel = event.get("channel_id", "")
        file_id = event.get("file_id", "")

        agent_id = self.channel_agent_map.get(channel)
        if not agent_id:
            return

        try:
            # Get file info
            file_info = self.client.files_info(file=file_id)
            file_data = file_info["file"]
            filename = file_data.get("name", "unknown")
            filetype = file_data.get("filetype", "")
            file_url = file_data.get("url_private_download", "")

            logger.info(f"File shared in {channel}: {filename} ({filetype})")

            # For now, notify the agent about the file
            # Full file processing (download, OCR, etc.) can be added later
            if self.runner:
                message = (
                    f"A file has been shared: {filename} (type: {filetype}). "
                    f"Please acknowledge receipt and analyze this document through "
                    f"a product-readiness lens as described in your instructions."
                )

                thread_ts = event.get("event_ts", "")
                conversation_id = f"{channel}_{thread_ts}"

                response = self._handle_agent_message(agent_id, message, conversation_id)
                # Post in the channel (not in thread since file_shared doesn't have a thread)
                self.post_message(channel, response)

        except Exception as e:
            logger.error(f"Error handling file: {e}")

    def post_message(self, channel: str, text: str, thread_ts: Optional[str] = None):
        """Post a message to a Slack channel."""
        # Slack has a 4000 char limit per message, split if needed
        if len(text) > 3900:
            chunks = self._split_message(text)
            for i, chunk in enumerate(chunks):
                self.client.chat_postMessage(
                    channel=channel,
                    text=chunk,
                    thread_ts=thread_ts,
                )
        else:
            self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
            )

    def _split_message(self, text: str, max_len: int = 3900) -> list[str]:
        """Split a long message into chunks at paragraph boundaries."""
        chunks = []
        current = ""

        for paragraph in text.split("\n\n"):
            if len(current) + len(paragraph) + 2 > max_len:
                if current:
                    chunks.append(current.strip())
                current = paragraph
            else:
                current += "\n\n" + paragraph if current else paragraph

        if current:
            chunks.append(current.strip())

        return chunks or [text[:max_len]]

    def start(self):
        """Start the Slack bot using Socket Mode."""
        app_token = os.environ.get("SLACK_APP_TOKEN")
        if not app_token:
            logger.error("SLACK_APP_TOKEN not set. Cannot start Socket Mode.")
            return

        handler = SocketModeHandler(self.app, app_token)
        logger.info("Slack bot starting in Socket Mode...")
        handler.start()
