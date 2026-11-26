"""The AI backend the app uses, and what it last said about itself."""

from showrunner.app.ai.watch import FRESH_SECONDS, AiStatus, AiWatch, ai_models
from showrunner.tools.ai import OllamaBackend

# The one backend of this version. A second backend makes this a choice in Settings.
AI = AiWatch(OllamaBackend())

__all__ = ["AI", "FRESH_SECONDS", "AiStatus", "AiWatch", "ai_models"]
