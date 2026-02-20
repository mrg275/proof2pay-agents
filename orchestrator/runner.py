"""
Agent runner. Executes any agent by assembling context and making API calls.
"""

import os
import logging
from pathlib import Path
from typing import Optional

import yaml

from integrations.anthropic_client import AnthropicClient
from orchestrator.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class AgentRunner:
    """Executes agents with proper context assembly and memory management."""

    def __init__(
        self,
        anthropic_client: AnthropicClient,
        memory_manager: MemoryManager,
        config_path: str = "./config/agents.yaml",
        tool_handler=None,
    ):
        self.client = anthropic_client
        self.memory = memory_manager
        self.config = self._load_config(config_path)
        self.agents = self._load_agents()
        self.tool_handler = tool_handler

    def _load_config(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    def _load_agents(self) -> dict:
        """Load agent configurations from YAML."""
        return self.config.get("agents", {})

    def _load_system_prompt(self, agent_id: str) -> str:
        """Load an agent's system prompt from its module."""
        prompt_path = Path(f"./agents/{agent_id}.py")
        if not prompt_path.exists():
            logger.warning(f"No prompt file found for {agent_id}")
            return ""

        # Import the module and get SYSTEM_PROMPT
        import importlib.util

        spec = importlib.util.spec_from_file_location(agent_id, prompt_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "SYSTEM_PROMPT", "")

    def _load_shared_context(self) -> str:
        """Load shared product documents that all agents can access."""
        context_parts = []

        context_dir = Path("./config/context")
        if context_dir.exists():
            for f in sorted(context_dir.glob("*.md")):
                context_parts.append(f"## {f.stem}\n\n{f.read_text()}")

        return "\n\n---\n\n".join(context_parts)

    def _load_priorities(self) -> str:
        """Load current company priorities."""
        priorities_path = Path("./config/priorities.md")
        if priorities_path.exists():
            return priorities_path.read_text()
        return ""

    def _assemble_context(
        self,
        agent_id: str,
        additional_context: Optional[str] = None,
        include_agent_summaries: Optional[list[str]] = None,
    ) -> str:
        """
        Assemble the full context for an agent run.
        Combines: shared docs + priorities + agent's own memory + requested cross-agent summaries + additional context.
        """
        parts = []

        agent_config = self.agents.get(agent_id, {})
        context_includes = agent_config.get("context_includes", [])

        # Shared product docs
        if "product_docs" in context_includes:
            shared = self._load_shared_context()
            if shared:
                parts.append(f"# Product Documentation\n\n{shared}")

        # Priorities
        if "priorities" in context_includes:
            priorities = self._load_priorities()
            if priorities:
                parts.append(f"# Company Priorities\n\n{priorities}")

        # Agent's own memory summary
        if "own_memory" in context_includes or True:  # Always include own memory
            summary = self.memory.get_summary(agent_id)
            if summary:
                parts.append(f"# Your Previous Work & Memory\n\n{summary}")

        # All agent summaries (for Chief of Staff)
        if "all_agent_summaries" in context_includes:
            all_summaries = self.memory.get_all_summaries()
            if all_summaries:
                summary_text = "\n\n".join(
                    f"## {name} Agent Summary\n\n{s}"
                    for name, s in all_summaries.items()
                    if name != agent_id
                )
                parts.append(f"# All Agent Summaries\n\n{summary_text}")

        # Specific cross-agent summaries
        if include_agent_summaries:
            for other_agent_id in include_agent_summaries:
                summary = self.memory.get_summary(other_agent_id)
                if summary:
                    other_name = self.agents.get(other_agent_id, {}).get("name", other_agent_id)
                    parts.append(f"# {other_name} Agent Summary\n\n{summary}")

        # Named cross-agent summaries from config
        for inc in context_includes:
            if inc.endswith("_summary"):
                ref_agent = inc.replace("_summary", "")
                if ref_agent != agent_id:
                    summary = self.memory.get_summary(ref_agent)
                    if summary:
                        ref_name = self.agents.get(ref_agent, {}).get("name", ref_agent)
                        parts.append(f"# {ref_name} Agent Summary\n\n{summary}")

        # Codebase context (for Technical PM and Domain Intelligence)
        if "codebase_context" in context_includes:
            codebase_path = Path("./config/context/codebase_context.md")
            if codebase_path.exists():
                parts.append(f"# Current Codebase Context\n\n{codebase_path.read_text()}")

        # Additional context passed by dispatcher
        if additional_context:
            parts.append(f"# Additional Context for This Task\n\n{additional_context}")

        return "\n\n---\n\n".join(parts)

    def run(
        self,
        agent_id: str,
        task: str,
        additional_context: Optional[str] = None,
        include_agent_summaries: Optional[list[str]] = None,
        model_override: Optional[str] = None,
    ) -> dict:
        """
        Execute an agent with a specific task.

        Returns:
            dict with: 'content' (str), 'agent_id' (str), 'task' (str),
            'tokens' (dict), 'output_file' (str)
        """
        agent_config = self.agents.get(agent_id)
        if not agent_config:
            raise ValueError(f"Unknown agent: {agent_id}")

        logger.info(f"Running agent: {agent_id} | Task: {task[:100]}...")

        # Load system prompt
        system_prompt = self._load_system_prompt(agent_id)
        if not system_prompt:
            raise ValueError(f"No system prompt found for agent: {agent_id}")

        # Assemble context
        context = self._assemble_context(
            agent_id,
            additional_context=additional_context,
            include_agent_summaries=include_agent_summaries,
        )

        # Build the user message with context + task
        user_message = f"{context}\n\n---\n\n# Your Task\n\n{task}"

        # Choose model
        model = model_override or agent_config.get("model", AnthropicClient.SONNET)

        # Check if this agent has tools
        agent_tools = self._get_agent_tools(agent_id)

        if agent_tools and self.tool_handler:
            # Tool-using agent: use conversation-style call with tool loop
            response = self._run_with_tools(
                system_prompt=system_prompt,
                user_message=user_message,
                model=model,
                tools=agent_tools,
            )
        else:
            # Standard single-turn agent
            response = self.client.call(
                system_prompt=system_prompt,
                user_message=user_message,
                model=model,
            )

        # Save output to memory
        output_file = self.memory.save_output(
            agent_id=agent_id,
            output=response["content"],
            task=task,
            metadata={
                "model": response["model"],
                "input_tokens": response["input_tokens"],
                "output_tokens": response["output_tokens"],
            },
        )

        logger.info(
            f"Agent {agent_id} complete. "
            f"Output: {len(response['content'])} chars, "
            f"Tokens: {response['input_tokens']}in/{response['output_tokens']}out"
        )

        return {
            "content": response["content"],
            "agent_id": agent_id,
            "task": task,
            "tokens": {
                "input": response["input_tokens"],
                "output": response["output_tokens"],
            },
            "output_file": output_file,
        }

    def _get_agent_tools(self, agent_id: str) -> list:
        """Get tool definitions for an agent, if any."""
        from orchestrator.agent_tools import TECHNICAL_PM_TOOLS, RESEARCH_AGENT_TOOLS

        tool_map = {
            "technical_pm": TECHNICAL_PM_TOOLS,
            "market_research": RESEARCH_AGENT_TOOLS,
            "competitive_intel": RESEARCH_AGENT_TOOLS,
            "fundraising": RESEARCH_AGENT_TOOLS,
        }
        return tool_map.get(agent_id, [])

    def _run_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        tools: list,
        max_iterations: int = 8,
    ) -> dict:
        """Run an agent with tool access, handling the tool call loop."""
        messages = [{"role": "user", "content": user_message}]

        response = self.client.call_with_conversation(
            system_prompt=system_prompt,
            messages=messages,
            model=model,
            tools=tools,
        )

        total_input = response.get("input_tokens", 0)
        total_output = response.get("output_tokens", 0)
        iterations = 0

        while response.get("tool_calls") and iterations < max_iterations:
            iterations += 1

            # Build assistant message with tool uses
            assistant_content = []
            if response.get("content"):
                assistant_content.append({"type": "text", "text": response["content"]})
            for tc in response["tool_calls"]:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tool calls
            tool_results = []
            for tc in response["tool_calls"]:
                result = self.tool_handler.handle_tool_call(tc)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result["result"],
                })
            messages.append({"role": "user", "content": tool_results})

            # Get next response
            response = self.client.call_with_conversation(
                system_prompt=system_prompt,
                messages=messages,
                model=model,
                tools=tools,
            )
            total_input += response.get("input_tokens", 0)
            total_output += response.get("output_tokens", 0)

        return {
            "content": response.get("content", ""),
            "input_tokens": total_input,
            "output_tokens": total_output,
            "model": model,
            "stop_reason": response.get("stop_reason", ""),
        }

    def run_interactive(
        self,
        agent_id: str,
        user_message: str,
        conversation_id: str,
        additional_context: Optional[str] = None,
    ) -> str:
        """
        Run an interactive agent with conversation memory.
        Used for Slack-based agents (Chief of Staff, Domain Intelligence).
        """
        agent_config = self.agents.get(agent_id)
        if not agent_config:
            raise ValueError(f"Unknown agent: {agent_id}")

        # Load system prompt
        system_prompt = self._load_system_prompt(agent_id)

        # Assemble context
        context = self._assemble_context(agent_id, additional_context=additional_context)

        # Full system prompt with context
        full_system = f"{system_prompt}\n\n---\n\n{context}"

        # Get conversation history
        history = self.memory.get_conversation(agent_id, conversation_id)

        # Build messages in Anthropic format
        messages = []
        for turn in history[-20:]:  # Last 20 turns to stay within context
            messages.append({
                "role": turn["role"],
                "content": turn["content"],
            })
        messages.append({"role": "user", "content": user_message})

        # Make API call
        model = agent_config.get("model", AnthropicClient.SONNET)
        response = self.client.call_with_conversation(
            system_prompt=full_system,
            messages=messages,
            model=model,
        )

        # Save conversation turns
        self.memory.save_conversation_turn(agent_id, conversation_id, "user", user_message)
        self.memory.save_conversation_turn(agent_id, conversation_id, "assistant", response["content"])

        return response["content"]
