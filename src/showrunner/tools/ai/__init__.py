"""Local AI backends behind one interface (`Backend`): Ollama now; a llama.cpp server joins as a second class."""

from showrunner.tools.ai.base import AiError, Backend, ChatAnswer, ChatRequest, ErrorKind, Message, Role
from showrunner.tools.ai.ollama import OllamaBackend

__all__ = ["AiError", "Backend", "ChatAnswer", "ChatRequest", "ErrorKind", "Message", "OllamaBackend", "Role"]
