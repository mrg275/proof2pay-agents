"""
Memory manager for agent system.
Each agent has persistent memory: a running summary and timestamped output history.
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "./memory"))


class MemoryManager:
    """Manages per-agent memory: running summaries and output history."""

    def __init__(self, memory_root: Optional[Path] = None, drive_client=None):
        self.root = memory_root or MEMORY_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self.drive = drive_client

    def _agent_dir(self, agent_id: str) -> Path:
        """Get or create an agent's memory directory."""
        d = self.root / agent_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "outputs").mkdir(exist_ok=True)
        return d

    # ─── Summary Management ───

    def get_summary(self, agent_id: str) -> str:
        """Get an agent's running summary. Returns empty string if none exists."""
        summary_path = self._agent_dir(agent_id) / "summary.md"
        if summary_path.exists():
            return summary_path.read_text()
        return ""

    def update_summary(self, agent_id: str, summary: str):
        """Overwrite an agent's running summary."""
        summary_path = self._agent_dir(agent_id) / "summary.md"
        summary_path.write_text(summary)
        logger.info(f"Updated summary for {agent_id} ({len(summary)} chars)")

    def get_all_summaries(self) -> dict[str, str]:
        """Get running summaries for all agents. Used by Chief of Staff."""
        summaries = {}
        if self.root.exists():
            for agent_dir in self.root.iterdir():
                if agent_dir.is_dir():
                    summary_path = agent_dir / "summary.md"
                    if summary_path.exists():
                        summaries[agent_dir.name] = summary_path.read_text()
        return summaries

    # ─── Output History ───

    def save_output(self, agent_id: str, output: str, task: str = "", metadata: Optional[dict] = None):
        """Save a timestamped output from an agent run."""
        agent_dir = self._agent_dir(agent_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save the output
        output_file = agent_dir / "outputs" / f"{timestamp}.md"
        output_file.write_text(output)

        # Save metadata alongside it
        meta = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "output_length": len(output),
            **(metadata or {}),
        }
        meta_file = agent_dir / "outputs" / f"{timestamp}_meta.json"
        meta_file.write_text(json.dumps(meta, indent=2))

        logger.info(f"Saved output for {agent_id}: {output_file.name}")

        # Upload to Google Drive if configured
        if self.drive:
            try:
                drive_filename = f"{timestamp}_{agent_id}.md"
                file_id = self.drive.upload_file(
                    filename=drive_filename,
                    content=output,
                    subfolder=agent_id,
                )
                if file_id and metadata:
                    self.drive.upload_metadata(
                        document_name=drive_filename,
                        subfolder=agent_id,
                        metadata={**meta, "drive_file_id": file_id, "local_path": str(output_file)},
                    )
                logger.info(f"Uploaded to Drive: {drive_filename} (ID: {file_id})")
            except Exception as e:
                logger.error(f"Drive upload failed for {agent_id}, continuing: {e}")

        return str(output_file)

    def get_recent_outputs(self, agent_id: str, n: int = 5) -> list[dict]:
        """Get the N most recent outputs for an agent."""
        agent_dir = self._agent_dir(agent_id)
        outputs_dir = agent_dir / "outputs"

        if not outputs_dir.exists():
            return []

        # Get all .md files sorted by name (which is timestamp-based)
        output_files = sorted(outputs_dir.glob("*.md"), reverse=True)[:n]

        results = []
        for f in output_files:
            meta_file = f.with_name(f.stem + "_meta.json")
            meta = {}
            if meta_file.exists():
                meta = json.loads(meta_file.read_text())

            results.append({
                "filename": f.name,
                "content": f.read_text(),
                "metadata": meta,
            })

        return results

    def get_output_by_filename(self, agent_id: str, filename: str) -> Optional[str]:
        """Retrieve a specific output by filename."""
        output_file = self._agent_dir(agent_id) / "outputs" / filename
        if output_file.exists():
            return output_file.read_text()
        return None

    # ─── Conversation Memory (for interactive agents) ───

    def get_conversation(self, agent_id: str, conversation_id: str) -> list[dict]:
        """Get conversation history for an interactive agent session."""
        conv_dir = self._agent_dir(agent_id) / "conversations"
        conv_dir.mkdir(exist_ok=True)
        conv_file = conv_dir / f"{conversation_id}.json"

        if conv_file.exists():
            return json.loads(conv_file.read_text())
        return []

    def save_conversation_turn(
        self, agent_id: str, conversation_id: str, role: str, content: str
    ):
        """Append a turn to a conversation."""
        conv_dir = self._agent_dir(agent_id) / "conversations"
        conv_dir.mkdir(exist_ok=True)
        conv_file = conv_dir / f"{conversation_id}.json"

        history = []
        if conv_file.exists():
            history = json.loads(conv_file.read_text())

        history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })

        # Keep conversation history manageable (last 50 turns)
        if len(history) > 50:
            history = history[-50:]

        conv_file.write_text(json.dumps(history, indent=2))

    def get_recent_conversations(self, agent_id: str, n: int = 3) -> list[dict]:
        """Get the N most recent conversation summaries for an agent."""
        conv_dir = self._agent_dir(agent_id) / "conversations"
        if not conv_dir.exists():
            return []

        conv_files = sorted(conv_dir.glob("*.json"), reverse=True)[:n]
        results = []
        for f in conv_files:
            history = json.loads(f.read_text())
            if history:
                results.append({
                    "conversation_id": f.stem,
                    "turns": len(history),
                    "last_message": history[-1] if history else None,
                    "started": history[0].get("timestamp", "") if history else "",
                })
        return results
