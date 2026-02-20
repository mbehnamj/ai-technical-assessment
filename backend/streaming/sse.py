"""
SSE (Server-Sent Events) utilities for real-time streaming.

Event types:
  - message:         Regular conversational tokens from the LLM
  - function_call:   Notification that a tool is being invoked
  - function_result: The result returned by a tool handler
  - document_update: The document content has changed
  - error:           An error occurred (with recovery info)
  - metadata:        Token counts, phase info, timing
  - done:            Stream is complete
"""

import json
import time
from typing import Any


class SSEManager:
    """
    Formats and emits Server-Sent Events according to the SSE spec (RFC 8895).

    Each event is formatted as:
        event: <event_type>\n
        data: <json_payload>\n
        \n
    """

    def emit(self, event_type: str, data: dict[str, Any]) -> str:
        """Return a fully formatted SSE event string."""
        json_data = json.dumps(data, ensure_ascii=False, default=str)
        return f"event: {event_type}\ndata: {json_data}\n\n"

    # ------------------------------------------------------------------ #
    #  Convenience helpers                                                 #
    # ------------------------------------------------------------------ #

    def message(self, content: str) -> str:
        """Emit a text token from the LLM."""
        return self.emit("message", {"content": content})

    def function_call(self, name: str, tool_id: str) -> str:
        """Emit a notification that a tool is being invoked."""
        return self.emit("function_call", {"name": name, "id": tool_id})

    def function_result(
        self, name: str, result: dict[str, Any], success: bool = True
    ) -> str:
        """Emit the result produced by a tool handler."""
        return self.emit(
            "function_result",
            {"name": name, "success": success, "result": result},
        )

    def document_update(
        self,
        document: str,
        sections: dict[str, Any],
        document_type: str | None = None,
    ) -> str:
        """Emit the full current document state."""
        return self.emit(
            "document_update",
            {
                "document": document,
                "sections": list(sections.keys()),
                "document_type": document_type,
                "char_count": len(document),
            },
        )

    def error(
        self,
        message: str,
        phase: str = "unknown",
        recoverable: bool = True,
        details: str | None = None,
    ) -> str:
        """Emit an error event."""
        payload: dict[str, Any] = {
            "message": message,
            "phase": phase,
            "recoverable": recoverable,
        }
        if details:
            payload["details"] = details
        return self.emit("error", payload)

    def metadata(self, state: dict[str, Any], iteration: int = 1) -> str:
        """Emit metadata about the current session state."""
        return self.emit(
            "metadata",
            {
                "phase": state.get("phase", "unknown"),
                "document_type": state.get("document_type"),
                "user_expertise": state.get("user_expertise", "unknown"),
                "missing_fields": state.get("missing_fields", []),
                "completeness_score": state.get("completeness_score", 0),
                "sections_generated": list(state.get("document_sections", {}).keys()),
                "iteration": iteration,
                "timestamp": time.time(),
            },
        )

    def done(self) -> str:
        """Emit the stream-complete event."""
        return self.emit("done", {"status": "complete", "timestamp": time.time()})
