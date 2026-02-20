"""
Task dispatcher. Handles Chief of Staff delegation to specialist agents.
Parses dispatch instructions and executes them via the agent runner.
"""

import logging
from datetime import date
from typing import Optional

from orchestrator.runner import AgentRunner
from orchestrator.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

# Daily spend guards
DAILY_TOKEN_LIMIT = 150_000
DISPATCH_LIMIT = 8

# Tool definition for the Chief of Staff to dispatch tasks
DISPATCH_TOOL = {
    "name": "dispatch_agent",
    "description": (
        "Dispatch a task to a specialist agent. The agent will execute the task "
        "with the specified context and return the result. Use this when a founder "
        "request requires specialist work (research, analysis, content creation) "
        "or when you identify a task during the daily cycle that should be delegated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": (
                    "The agent to dispatch to. One of: compliance, market_research, "
                    "fundraising, competitive_intel, technical_pm, regulatory, brand_marketing"
                ),
                "enum": [
                    "compliance",
                    "market_research",
                    "fundraising",
                    "competitive_intel",
                    "technical_pm",
                    "regulatory",
                    "brand_marketing",
                ],
            },
            "task": {
                "type": "string",
                "description": "Clear description of what the agent should do.",
            },
            "context_from_agents": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of agent IDs whose memory summaries should be included "
                    "as context for this task. E.g., ['market_research', 'brand_marketing']"
                ),
            },
            "additional_context": {
                "type": "string",
                "description": "Any additional context to pass to the agent.",
            },
            "priority": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Task priority level.",
            },
            "model": {
                "type": "string",
                "enum": ["opus", "sonnet", "haiku"],
                "description": (
                    "Model tier to use. 'opus' for complex multi-step reasoning, "
                    "cross-domain synthesis, or high-stakes outputs. "
                    "'sonnet' (default) for standard research and analysis. "
                    "'haiku' for simple lookups, summarization, or classification."
                ),
            },
        },
        "required": ["agent_id", "task"],
    },
}

# Tool for reading specific agent outputs
READ_AGENT_OUTPUT_TOOL = {
    "name": "read_agent_output",
    "description": (
        "Read a specific agent's most recent output or summary. "
        "Use this to check what an agent has already produced before dispatching."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "The agent whose output to read.",
            },
            "output_type": {
                "type": "string",
                "enum": ["summary", "latest_output"],
                "description": "Whether to read the running summary or the latest full output.",
            },
        },
        "required": ["agent_id", "output_type"],
    },
}

COS_TOOLS = [DISPATCH_TOOL, READ_AGENT_OUTPUT_TOOL]


class Dispatcher:
    """Handles task dispatch from Chief of Staff to specialist agents."""

    # Map of model tier names to Anthropic model IDs
    MODEL_TIER_MAP = {
        "opus": "claude-opus-4-5-20250514",
        "sonnet": "claude-sonnet-4-5-20250929",
        "haiku": "claude-haiku-4-5-20251001",
    }

    def __init__(self, runner: AgentRunner, memory: MemoryManager):
        self.runner = runner
        self.memory = memory
        self._daily_tokens = 0
        self._daily_dispatches = 0
        self._last_reset = self._today()

    def _today(self) -> str:
        return date.today().isoformat()

    def _reset_if_new_day(self):
        if self._today() != self._last_reset:
            self._daily_tokens = 0
            self._daily_dispatches = 0
            self._last_reset = self._today()
            logger.info("Daily spend counters reset for new day.")

    def _check_budget(self, agent_id: str) -> Optional[str]:
        """Returns an error string if budget exceeded, None if ok to proceed."""
        self._reset_if_new_day()
        if self._daily_tokens >= DAILY_TOKEN_LIMIT:
            return (
                f"Daily token limit ({DAILY_TOKEN_LIMIT:,}) reached. "
                f"Used: {self._daily_tokens:,}. Dispatch to {agent_id} blocked. "
                f"Resets tomorrow."
            )
        if self._daily_dispatches >= DISPATCH_LIMIT:
            return (
                f"Daily dispatch limit ({DISPATCH_LIMIT}) reached. "
                f"Dispatch to {agent_id} blocked. Resets tomorrow."
            )
        return None

    def handle_tool_call(self, tool_call: dict) -> dict:
        """
        Execute a tool call from the Chief of Staff.

        Returns:
            dict with 'tool_use_id', 'result' (str), and 'success' (bool)
        """
        name = tool_call["name"]
        inputs = tool_call["input"]

        if name == "dispatch_agent":
            return self._handle_dispatch(tool_call["id"], inputs)
        elif name == "read_agent_output":
            return self._handle_read_output(tool_call["id"], inputs)
        else:
            return {
                "tool_use_id": tool_call["id"],
                "result": f"Unknown tool: {name}",
                "success": False,
            }

    def _handle_dispatch(self, tool_id: str, inputs: dict) -> dict:
        """Execute a dispatch_agent tool call."""
        agent_id = inputs["agent_id"]
        task = inputs["task"]
        context_from = inputs.get("context_from_agents", [])
        additional_context = inputs.get("additional_context", "")
        priority = inputs.get("priority", "medium")
        model_tier = inputs.get("model")
        model_override = self.MODEL_TIER_MAP.get(model_tier) if model_tier else None

        # Budget check before every dispatch
        budget_error = self._check_budget(agent_id)
        if budget_error:
            logger.warning(f"Budget guard blocked dispatch to {agent_id}: {budget_error}")
            return {
                "tool_use_id": tool_id,
                "result": budget_error,
                "success": False,
            }

        logger.info(
            f"Dispatching task to {agent_id}: {task[:80]}... "
            f"(priority: {priority}, model: {model_tier or 'default'})"
        )

        try:
            result = self.runner.run(
                agent_id=agent_id,
                task=task,
                additional_context=additional_context,
                include_agent_summaries=context_from,
                model_override=model_override,
            )

            # Track spend
            tokens = result.get("tokens", {})
            self._daily_tokens += tokens.get("input", 0)
            self._daily_tokens += tokens.get("output", 0)
            self._daily_dispatches += 1

            logger.info(
                f"Dispatch complete: {agent_id}. "
                f"Daily spend: {self._daily_tokens:,} tokens, "
                f"{self._daily_dispatches}/{DISPATCH_LIMIT} dispatches."
            )

            return {
                "tool_use_id": tool_id,
                "result": result["content"],
                "success": True,
                "tokens": result["tokens"],
            }

        except Exception as e:
            logger.error(f"Dispatch to {agent_id} failed: {e}")
            return {
                "tool_use_id": tool_id,
                "result": f"Dispatch failed: {str(e)}",
                "success": False,
            }

    def _handle_read_output(self, tool_id: str, inputs: dict) -> dict:
        """Execute a read_agent_output tool call."""
        agent_id = inputs["agent_id"]
        output_type = inputs["output_type"]

        if output_type == "summary":
            content = self.memory.get_summary(agent_id)
            if not content:
                content = f"No summary available for {agent_id} yet."
        elif output_type == "latest_output":
            outputs = self.memory.get_recent_outputs(agent_id, n=1)
            if outputs:
                content = outputs[0]["content"]
            else:
                content = f"No outputs available for {agent_id} yet."
        else:
            content = f"Unknown output type: {output_type}"

        return {
            "tool_use_id": tool_id,
            "result": content,
            "success": True,
        }

    def execute_dispatch_loop(
        self,
        initial_response: dict,
        system_prompt: str,
        original_messages: list,
        max_iterations: int = 5,
    ) -> str:
        """
        Handle a multi-turn dispatch loop where the Chief of Staff may make
        multiple tool calls before producing a final response.

        Returns the final text response from the Chief of Staff.
        """
        messages = list(original_messages)
        response = initial_response
        iterations = 0

        while response.get("tool_calls") and iterations < max_iterations:
            iterations += 1

            # Build assistant message with tool use
            assistant_content = []
            if response.get("content"):
                assistant_content.append({
                    "type": "text",
                    "text": response["content"],
                })
            for tc in response["tool_calls"]:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call
            tool_results = []
            for tc in response["tool_calls"]:
                result = self.handle_tool_call(tc)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result["result"],
                })

            messages.append({"role": "user", "content": tool_results})

            # Get next response from Chief of Staff
            response = self.runner.client.call_with_conversation(
                system_prompt=system_prompt,
                messages=messages,
                tools=COS_TOOLS,
            )

        # Return the final text
        return response.get("content", "")