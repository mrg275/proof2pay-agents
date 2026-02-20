"""
Anthropic API client wrapper.
Handles API calls with retry logic, token tracking, and model selection.
"""

import os
import time
import logging
from typing import Optional
from anthropic import Anthropic

logger = logging.getLogger(__name__)


class AnthropicClient:
    """Wrapper around the Anthropic API with retry logic and token tracking."""

    # Model tiers
    OPUS = "claude-opus-4-5-20250514"
    SONNET = "claude-sonnet-4-5-20250514"
    HAIKU = "claude-haiku-3-5-20241022"

    def __init__(self):
        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0

    def call(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        tools: Optional[list] = None,
        retries: int = 3,
        extended_thinking: bool = False,
        thinking_budget: int = 5000,
    ) -> dict:
        """
        Make an API call to Claude.

        Returns:
            dict with keys: 'content' (str), 'tool_calls' (list), 'input_tokens' (int),
            'output_tokens' (int), 'model' (str), 'stop_reason' (str)
        """
        model = model or self.SONNET

        for attempt in range(retries):
            try:
                kwargs = {
                    "model": model,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                }

                if extended_thinking:
                    kwargs["temperature"] = 1
                    kwargs["max_tokens"] = max_tokens + thinking_budget
                    kwargs["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": thinking_budget,
                    }
                else:
                    kwargs["temperature"] = temperature
                    kwargs["max_tokens"] = max_tokens

                if tools:
                    kwargs["tools"] = tools

                response = self.client.messages.create(**kwargs)

                # Track tokens
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                self.total_input_tokens += input_tokens
                self.total_output_tokens += output_tokens
                self.total_calls += 1

                # Parse response (filter out thinking blocks)
                content_text = ""
                tool_calls = []
                for block in response.content:
                    if block.type == "text":
                        content_text += block.text
                    elif block.type == "tool_use":
                        tool_calls.append({
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                    elif block.type == "thinking":
                        logger.debug(f"Thinking block: {block.thinking[:200]}...")

                logger.info(
                    f"API call complete: model={model}, "
                    f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
                    f"stop_reason={response.stop_reason}"
                )

                return {
                    "content": content_text,
                    "tool_calls": tool_calls,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model": model,
                    "stop_reason": response.stop_reason,
                }

            except Exception as e:
                logger.warning(f"API call attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API call failed after {retries} attempts")
                    raise

    def call_with_conversation(
        self,
        system_prompt: str,
        messages: list[dict],
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        tools: Optional[list] = None,
        extended_thinking: bool = False,
        thinking_budget: int = 5000,
    ) -> dict:
        """
        Make an API call with a full conversation history.
        Messages should be in Anthropic format: [{"role": "user"|"assistant", "content": "..."}]
        """
        model = model or self.SONNET

        kwargs = {
            "model": model,
            "system": system_prompt,
            "messages": messages,
        }

        if extended_thinking:
            kwargs["temperature"] = 1
            kwargs["max_tokens"] = max_tokens + thinking_budget
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
        else:
            kwargs["temperature"] = temperature
            kwargs["max_tokens"] = max_tokens

        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_calls += 1

        content_text = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif block.type == "thinking":
                logger.debug(f"Thinking block: {block.thinking[:200]}...")

        return {
            "content": content_text,
            "tool_calls": tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "stop_reason": response.stop_reason,
        }

    def get_usage_summary(self) -> dict:
        """Get cumulative token usage stats."""
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": self._estimate_cost(),
        }

    def _estimate_cost(self) -> float:
        """Rough cost estimate based on Sonnet pricing."""
        # Approximate pricing - adjust as rates change
        input_cost = (self.total_input_tokens / 1_000_000) * 3.0
        output_cost = (self.total_output_tokens / 1_000_000) * 15.0
        return round(input_cost + output_cost, 4)
