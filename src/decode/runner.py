"""Swappable decode runner.

Subscription mode (now) is realized by the /decode skill, which spawns a fresh
subagent per label -- so it does not use this module. This interface and the
gated ApiRunner stub exist so that, if the project is ever deployed, an API
decoder drops in behind the same contract with no change to the harness or gold.
"""
import os
from abc import ABC, abstractmethod


class DecodeRunner(ABC):
    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Make ONE fresh, stateless model call for `prompt` and return raw text."""


class ApiRunner(DecodeRunner):
    """Future API decoder. Importing this module never requires the SDK; the SDK
    and key are only needed when an ApiRunner is actually constructed."""

    def __init__(self, model, api_key_env="ANTHROPIC_API_KEY", temperature=0.0, max_tokens=1500):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"API mode needs {api_key_env}. For now use the /decode skill "
                "(subscription mode) instead."
            )
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "API mode needs the 'anthropic' package, which is not a project "
                "dependency yet. Use the /decode skill (subscription mode) instead."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, prompt: str) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
