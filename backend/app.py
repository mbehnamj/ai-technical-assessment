"""
LexiDraft Backend — Flask Application
=======================================
Main entry point for the legal document generation API.

Routes:
  POST /api/chat              → SSE-streamed conversational response
  POST /api/conversation/reset → Reset a session
  GET  /api/conversation/state → Get current session state
  GET  /api/health             → Health check

SSE Orchestration Loop:
  1. Receive user message, get/create session state
  2. Compose multi-layer system prompt via PromptComposer
  3. Call Claude with tools enabled (streaming)
  4. Stream text tokens → SSE message events
  5. Detect tool_use blocks → execute handlers → continue with results
  6. Emit document_update when document changes
  7. Emit metadata with current state
  8. Emit done signal
"""

import json
import os
import time
import uuid
from threading import Lock

import anthropic
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from functions import TOOLS, ToolHandler
from prompts import PromptComposer
from streaming import SSEManager

load_dotenv()

# ────────────────────────────────────────────────────────────────────────
# App Setup
# ────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(
    app,
    origins=["http://localhost:5173", "http://localhost:3000"],
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
    expose_headers=["Content-Type"],
)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
composer = PromptComposer()
sse = SSEManager()

# In-memory session store (no DB required per spec)
sessions: dict[str, dict] = {}
sessions_lock = Lock()

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ITERATIONS = 8          # Safety limit for agentic loops
CONTEXT_WINDOW_MESSAGES = 40     # Max messages to send to Claude


# ────────────────────────────────────────────────────────────────────────
# Session Management
# ────────────────────────────────────────────────────────────────────────

def new_session() -> dict:
    """Create a fresh session state."""
    return {
        "phase": "intake",
        "document_type": None,
        "user_expertise": "unknown",
        "extracted_data": {},
        "missing_fields": [],
        "document_sections": {},
        "current_document": "",
        "document_updated": False,
        "conflicts": [],
        "has_conflicts": False,
        "can_finalize": False,
        "completeness_score": 0.0,
        "clause_suggestions": [],
        "revision_history": [],
        "all_flags": [],
        "assumed_fields": [],
        "history": [],  # Claude message history
        "created_at": time.time(),
        "last_active": time.time(),
    }


def get_session(session_id: str) -> dict:
    """Get existing session or create a new one."""
    with sessions_lock:
        if session_id not in sessions:
            sessions[session_id] = new_session()
        sessions[session_id]["last_active"] = time.time()
        return sessions[session_id]


def trim_history(history: list[dict], max_messages: int = CONTEXT_WINDOW_MESSAGES) -> list[dict]:
    """
    Context window management: keep recent messages while preserving
    the conversation flow. Always keeps the first user message for context.

    Strategy: keep first message + last (max_messages - 1) messages,
    ensuring alternating user/assistant roles are maintained.
    """
    if len(history) <= max_messages:
        return history

    # Always keep the first message for context
    first = history[:1]
    recent = history[-(max_messages - 1):]

    # Ensure the first recent message is a user message (Claude API requirement)
    while recent and recent[0].get("role") == "assistant":
        recent = recent[1:]

    return first + recent


# ────────────────────────────────────────────────────────────────────────
# SSE Streaming Core
# ────────────────────────────────────────────────────────────────────────

def stream_response(session_id: str, user_message: str):
    """
    Generator function that orchestrates the LLM agentic loop and yields
    SSE-formatted events.

    Flow:
      while iterations < MAX:
        1. Compose system prompt from state
        2. Call Claude with tools (streaming)
        3. Stream text → emit 'message' events
        4. Accumulate tool_use blocks
        5. After stream ends: execute tools → emit 'function_result' events
        6. If no more tool calls: break
        7. Continue loop with tool results in history
      Emit document_update if document changed
      Emit metadata + done
    """
    state = get_session(session_id)

    # Add user message to history
    state["history"].append({"role": "user", "content": user_message})

    iteration = 0
    handler = ToolHandler(state)

    try:
        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1

            # ── Compose system prompt ──────────────────────────────────
            system_prompt = composer.compose(state)

            # ── Trim message history ───────────────────────────────────
            messages = trim_history(state["history"])

            # ── Stream from Claude ─────────────────────────────────────
            text_accumulated = ""
            tool_calls: list[dict] = []
            current_tool: dict | None = None
            stop_reason = "end_turn"

            try:
                with client.messages.stream(
                    model=MODEL,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=messages,
                    tools=TOOLS,
                    temperature=0.3,
                ) as stream:
                    for event in stream:
                        event_type = getattr(event, "type", None)

                        # ── Content block started ──────────────────────
                        if event_type == "content_block_start":
                            block = getattr(event, "content_block", None)
                            if block and getattr(block, "type", None) == "tool_use":
                                current_tool = {
                                    "type": "tool_use",
                                    "id": block.id,
                                    "name": block.name,
                                    "input": {},
                                    "_raw_json": "",
                                }
                                yield sse.function_call(block.name, block.id)

                        # ── Content block delta ────────────────────────
                        elif event_type == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if delta:
                                delta_type = getattr(delta, "type", None)
                                if delta_type == "text_delta":
                                    text_accumulated += delta.text
                                    yield sse.message(delta.text)
                                elif delta_type == "input_json_delta" and current_tool:
                                    current_tool["_raw_json"] += getattr(delta, "partial_json", "")

                        # ── Content block ended ────────────────────────
                        elif event_type == "content_block_stop":
                            if current_tool:
                                # Parse accumulated JSON input
                                raw_json = current_tool.pop("_raw_json", "")
                                try:
                                    current_tool["input"] = json.loads(raw_json) if raw_json else {}
                                except json.JSONDecodeError:
                                    current_tool["input"] = {}
                                tool_calls.append(dict(current_tool))
                                current_tool = None

                        # ── Message delta (stop reason) ────────────────
                        elif event_type == "message_delta":
                            delta = getattr(event, "delta", None)
                            if delta:
                                stop_reason = getattr(delta, "stop_reason", stop_reason) or stop_reason

                    # Retrieve final message for accurate stop_reason
                    final_msg = stream.get_final_message()
                    stop_reason = final_msg.stop_reason or stop_reason

            except anthropic.APIStatusError as api_err:
                yield sse.error(
                    message=f"API error: {api_err.message}",
                    phase=state.get("phase", "unknown"),
                    recoverable=api_err.status_code < 500,
                    details=str(api_err.status_code),
                )
                yield sse.done()
                return

            # ── Build assistant message for history ────────────────────
            assistant_content: list[dict] = []
            if text_accumulated:
                assistant_content.append({"type": "text", "text": text_accumulated})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })

            state["history"].append({
                "role": "assistant",
                "content": assistant_content if assistant_content else [{"type": "text", "text": ""}],
            })

            # ── If no tool calls, we're done with this turn ────────────
            if not tool_calls or stop_reason == "end_turn":
                break

            # ── Execute tools and collect results ─────────────────────
            tool_results: list[dict] = []
            for tc in tool_calls:
                try:
                    result = handler.execute(tc["name"], tc["input"])
                    yield sse.function_result(tc["name"], result, success=result.get("success", True))
                    result_content = json.dumps(result, default=str)
                except Exception as exc:
                    result_content = json.dumps({"success": False, "error": str(exc)})
                    yield sse.function_result(tc["name"], {"success": False, "error": str(exc)}, success=False)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result_content,
                })

            # Add tool results as user message (Claude API requirement)
            state["history"].append({
                "role": "user",
                "content": tool_results,
            })

        # ── Emit document update if document changed ───────────────────
        if state.get("document_updated") and state.get("current_document"):
            yield sse.document_update(
                document=state["current_document"],
                sections=state.get("document_sections", {}),
                document_type=state.get("document_type"),
            )
            state["document_updated"] = False

        # ── Emit metadata ──────────────────────────────────────────────
        yield sse.metadata(state, iteration=iteration)

    except Exception as exc:
        yield sse.error(
            message=f"Unexpected error: {str(exc)}",
            phase=state.get("phase", "unknown"),
            recoverable=False,
            details=type(exc).__name__,
        )

    finally:
        yield sse.done()


# ────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Main SSE endpoint. Accepts a JSON body with session_id and message,
    returns a Server-Sent Events stream.
    """
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id") or str(uuid.uuid4())
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "message is required"}), 400

    def generate():
        yield from stream_response(session_id, message)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.route("/api/conversation/reset", methods=["POST"])
def reset_conversation():
    """Reset a session, clearing all state and history."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    with sessions_lock:
        if session_id in sessions:
            del sessions[session_id]

    return jsonify({"success": True, "session_id": session_id, "message": "Session reset."})


@app.route("/api/conversation/state", methods=["GET"])
def get_conversation_state():
    """Return the current state of a session (for debugging/UI sync)."""
    session_id = request.args.get("session_id")
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Session not found"}), 404

    state = sessions[session_id]
    return jsonify({
        "session_id": session_id,
        "phase": state.get("phase"),
        "document_type": state.get("document_type"),
        "user_expertise": state.get("user_expertise"),
        "completeness_score": state.get("completeness_score", 0),
        "missing_fields": state.get("missing_fields", []),
        "sections_generated": list(state.get("document_sections", {}).keys()),
        "has_document": bool(state.get("current_document")),
        "has_conflicts": state.get("has_conflicts", False),
        "can_finalize": state.get("can_finalize", False),
        "revision_count": len(state.get("revision_history", [])),
        "message_count": len(state.get("history", [])),
        "flags": state.get("all_flags", []),
        "clause_suggestions": state.get("clause_suggestions", []),
    })


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "model": MODEL,
        "active_sessions": len(sessions),
        "timestamp": time.time(),
    })


@app.route("/api/conversation/document", methods=["GET"])
def get_document():
    """Return the current generated document for a session."""
    session_id = request.args.get("session_id")
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Session not found"}), 404

    state = sessions[session_id]
    return jsonify({
        "document": state.get("current_document", ""),
        "sections": {
            name: {
                "content": data.get("content", ""),
                "confidence": data.get("confidence", 1.0),
                "flags": data.get("flags", []),
                "word_count": data.get("word_count", 0),
            }
            for name, data in state.get("document_sections", {}).items()
        },
        "document_type": state.get("document_type"),
        "flags": state.get("all_flags", []),
        "assumed_fields": state.get("assumed_fields", []),
        "can_finalize": state.get("can_finalize", False),
    })


# ────────────────────────────────────────────────────────────────────────
# Entry Point
# ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    debug = os.getenv("FLASK_ENV", "development") == "development"
    print(f"LexiDraft backend starting on port {port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
