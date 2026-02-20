# System Architecture

## 1. System Component Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                           │
│                                                                    │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐  │
│  │  ChatPanel  │    │   DocumentPanel  │    │ PhaseIndicator  │  │
│  │  (messages, │    │   (live preview, │    │ (phase, progress│  │
│  │   input)    │    │   copy/download) │    │  completeness)  │  │
│  └──────┬──────┘    └────────┬─────────┘    └────────┬────────┘  │
│         │                   │                         │            │
│         └───────────────────┼─────────────────────────┘           │
│                             │                                      │
│                     ┌───────▼────────┐                            │
│                     │   useChat.ts   │                            │
│                     │   (SSE hook,   │                            │
│                     │   state mgmt)  │                            │
│                     └───────┬────────┘                            │
└─────────────────────────────┼──────────────────────────────────────┘
                              │
                  POST /api/chat (SSE stream)
                  @microsoft/fetch-event-source
                              │
┌─────────────────────────────▼──────────────────────────────────────┐
│                      BACKEND (Flask)                               │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                    app.py (Routes)                          │  │
│  │   POST /api/chat  →  stream_response() generator            │  │
│  │   POST /api/conversation/reset                              │  │
│  │   GET  /api/conversation/state                              │  │
│  │   GET  /api/health                                          │  │
│  └────────┬────────────────────────────────────────────────────┘  │
│           │                                                        │
│    ┌──────▼──────┐  ┌─────────────────┐  ┌───────────────────┐   │
│    │   Prompt    │  │    Functions     │  │    Streaming      │   │
│    │  Composer   │  │   (7 tools)      │  │   SSE Manager     │   │
│    │             │  │                  │  │                   │   │
│    │ base.py     │  │ schemas.py       │  │ sse.py            │   │
│    │ legal_      │  │ handlers.py      │  │ (format events)   │   │
│    │   domain.py │  │                  │  │                   │   │
│    │ tasks.py    │  │                  │  │                   │   │
│    └──────┬──────┘  └────────┬─────────┘  └───────────────────┘   │
│           │                  │                                     │
│    ┌──────▼──────────────────▼──────────┐                         │
│    │         Session State (in-memory)  │                         │
│    │  phase, document_type, extracted   │                         │
│    │  data, document_sections, history  │                         │
│    └────────────────────────────────────┘                         │
└─────────────────────────────┬──────────────────────────────────────┘
                              │
                    Anthropic Python SDK
                    (streaming, tool_use)
                              │
┌─────────────────────────────▼──────────────────────────────────────┐
│                   Claude claude-sonnet-4-6 (LLM)                              │
│   - 200k context window                                            │
│   - Tool use (function calling)                                    │
│   - Streaming text + tool_use events                               │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow: Complete Document Generation

```
User types: "I need an NDA for sharing code with a contractor"
                              │
                    POST /api/chat
                    {session_id, message}
                              │
                    ┌─────────▼──────────┐
                    │  get_session()     │  → creates new session
                    │  append to history │    (phase: intake)
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ compose() called   │  Layer 1: safety rails
                    │ (PromptComposer)   │  Layer 2: legal domain
                    │                    │  Layer 3: intake task
                    │                    │  Layer 4: empty state
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
          ┌─────────│  Claude API call   │─────────────────────────┐
          │         │  (streaming)       │                         │
          │         └────────────────────┘                         │
          │                                                         │
  text_delta events                               content_block_start
  → SSE 'message' events                          (tool_use: analyze_request)
  → "I'll help you create an NDA..."              │
                                                  ↓
                                        ┌──────────────────────────┐
                                        │  SSE 'function_call' evt │
                                        │  {name: analyze_request} │
                                        └──────────┬───────────────┘
                                                   │
                                        ┌──────────▼───────────────┐
                                        │  handler._analyze_req()  │
                                        │  → phase: clarification  │
                                        │  → doc_type: nda         │
                                        │  → expertise: intermediate│
                                        │  → missing_fields: [     │
                                        │      party_1_name,       │
                                        │      party_2_name,       │
                                        │      governing_law]      │
                                        └──────────┬───────────────┘
                                                   │
                                        ┌──────────▼───────────────┐
                                        │  SSE 'function_result'   │
                                        │  {success: true, ...}    │
                                        └──────────┬───────────────┘
                                                   │
                                        Continue loop with tool result
                                                   │
                                        Claude responds: "Great! I'll
                                        help you draft an NDA. What are
                                        the full legal names of both
                                        parties?"
                                                   │
                                        SSE 'message' events (tokens)
                                        SSE 'metadata' event
                                        SSE 'done' event

═══ [User provides party names, effective date, jurisdiction] ═══

                    [Clarification phase: extract_structured_data × N]
                    [validate_completeness → ready_to_generate: true]
                    [suggest_clauses: non_solicitation, arbitration]
                    [Phase transitions to: generation]

═══ [Generation Phase] ═══

For each section (header → recitals → ... → signature_block):
    1. Claude reasons through section requirements (chain-of-thought)
    2. generate_document_section() called with:
       - section_content: "NON-DISCLOSURE AGREEMENT\n\nThis NDA..."
       - reasoning: "Header needs document title, effective date..."
       - confidence: 0.95
    3. handler stores section, rebuilds document
    4. SSE 'function_result' emitted
    5. SSE 'document_update' emitted (live preview update)

After all sections:
    detect_conflicts() called
    → conflicts_found: false
    → phase transitions to: complete
    → SSE 'document_update' (final document)
    → SSE 'metadata' (phase: complete)
    → SSE 'done'
```

---

## 3. SSE Event Reference

| Event | Payload | Purpose |
|-------|---------|---------|
| `message` | `{content: string}` | Text token from LLM |
| `function_call` | `{name, id}` | Tool being invoked |
| `function_result` | `{name, success, result}` | Tool execution result |
| `document_update` | `{document, sections, document_type, char_count}` | Document changed |
| `error` | `{message, phase, recoverable, details?}` | Error occurred |
| `metadata` | `{phase, document_type, missing_fields, ...}` | Session state snapshot |
| `done` | `{status, timestamp}` | Stream complete |

---

## 4. Error Handling Strategy

### Layered Error Handling

```
Level 1: Tool execution errors
  → Handler always returns {success: false, error: "...", retry_hint: "..."}
  → LLM receives the error and can retry with corrected input
  → Emits SSE 'function_result' with success=false

Level 2: API errors
  → anthropic.APIStatusError caught in stream_response()
  → Recoverable (4xx): emit error event with recoverable=true
  → Non-recoverable (5xx): emit error event with recoverable=false

Level 3: Stream errors
  → try/except around entire streaming loop
  → Graceful degradation: emit error + done signals
  → Session state preserved for retry

Level 4: Frontend errors
  → fetchEventSource onerror handler
  → Displays error in chat as system message
  → Reset button always available
```

### Retry Logic

```python
# Tool call retry within the agentic loop:
# If a tool returns {success: False}, Claude receives the error message
# and can choose to:
#   a) Retry with corrected parameters
#   b) Ask the user for clarification
#   c) Proceed with a different approach

# Loop protection:
MAX_TOOL_ITERATIONS = 8  # Prevents infinite loops
# If exceeded, loop terminates and emits final response
```

### Graceful Degradation

- If document generation fails mid-way: partial document is preserved in state
- If SSE connection drops: session state persists; user can reconnect
- If Claude API is unavailable: clear error message + recovery suggestion
- If tool input is malformed: handler returns descriptive error with retry_hint

---

## 5. Scalability Considerations

*Note: The current implementation is single-server, in-memory. The following
describes how this would scale in production.*

### Current Limitations
- Session state stored in `dict` — process-local, not shared across workers
- No authentication or rate limiting
- Single Flask instance with threading=True

### Production Scaling Path

**Horizontal Scaling:**
```
Sessions dict → Redis (with TTL for automatic cleanup)
  - Enables multiple Flask workers behind a load balancer
  - Session data JSON-serializable (no complex objects)
  - TTL of 2 hours covers typical document session

Flask → Gunicorn with async workers (gevent)
  - SSE connections hold for 5-30 minutes per session
  - Gevent handles many concurrent long-lived connections efficiently
```

**Load Balancing:**
```
Nginx → Multiple Gunicorn instances
  - SSE requires sticky sessions (route user to same backend)
  - Alternatively: session state in Redis makes any backend valid
```

**Rate Limiting:**
```
Per-IP: max 10 requests/minute (prevents API cost abuse)
Per-session: max 50 turns (documents rarely need more)
Anthropic API key rotation: pool of keys with per-key limits
```

**Monitoring:**
```
Key metrics to track:
  - SSE connection duration
  - Tool call success/failure rates per tool
  - Document completion rates by type
  - Average turns to completion
  - Token usage per session (cost tracking)
```

**Cost Optimization:**
```
Prompt caching: Layer 1 (meta-system) and Layer 2 (legal domain) are
  stable across sessions — eligible for Anthropic prompt caching
  (reduces cost by ~90% for cached tokens)

Session cleanup: Evict sessions older than 2 hours (documents done)
Context window pruning: Already implemented via trim_history()
```
