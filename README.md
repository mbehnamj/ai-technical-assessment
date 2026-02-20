# LexiDraft — AI Legal Document Generation System

A conversational AI system for generating professional legal documents, built with Python/Flask, React/TypeScript, Anthropic Claude, and Server-Sent Events streaming.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Anthropic API key

### Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Start the server
python app.py
# Server runs at http://localhost:5001
```

**.env file:**
```
ANTHROPIC_API_KEY=sk-ant-...
FLASK_ENV=development
PORT=5001
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
# App runs at http://localhost:5173
```

Open http://localhost:5173 in your browser.

---

## System Overview

LexiDraft guides users through a conversational flow to draft professional legal documents:

```
intake → clarification → generation → revision → complete
```

**Supported Document Types:**
- Non-Disclosure Agreements (NDA)
- Employment Agreements
- Service / Consulting Agreements
- Partnership Agreements
- LLC Operating Agreements
- Terms of Service
- Privacy Policies
- Licensing Agreements
- Purchase Agreements

---

## Architecture

### Backend (`backend/`)

| File | Purpose |
|------|---------|
| `app.py` | Flask routes, SSE streaming orchestration loop |
| `prompts/base.py` | 4-layer prompt composition engine |
| `prompts/legal_domain.py` | Legal expertise, terminology, expertise adaptation |
| `prompts/tasks.py` | Phase-specific task instructions |
| `functions/schemas.py` | JSON schemas for all 7 tools |
| `functions/handlers.py` | Tool execution logic and state mutation |
| `streaming/sse.py` | SSE event formatting utilities |

### Frontend (`frontend/src/`)

| File | Purpose |
|------|---------|
| `hooks/useChat.ts` | SSE connection, state management, event parsing |
| `components/ChatPanel.tsx` | Conversation UI with streaming display |
| `components/DocumentPanel.tsx` | Live document preview, copy/download |
| `components/MessageBubble.tsx` | Message rendering with function call badges |
| `components/PhaseIndicator.tsx` | Phase and progress display |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | SSE stream for chat messages |
| `/api/conversation/reset` | POST | Reset a session |
| `/api/conversation/state` | GET | Current session state |
| `/api/conversation/document` | GET | Current generated document |
| `/api/health` | GET | Health check |

---

## Design Decisions & Assumptions

1. **LLM Provider**: Anthropic Claude (claude-sonnet-4-6) — matches the "Anthropic Claude" requirement and allows use of the Anthropic Python SDK's streaming + tool_use API.

2. **Temperature: 0.3** — Legal documents require precision and consistency. Higher temperatures (tested at 0.7) produced party name mismatches across sections.

3. **Session storage: in-memory** — No database required per spec. Sessions are stored in a Python dict with threading.Lock. See ARCHITECTURE.md for production scaling path using Redis.

4. **POST + SSE**: The frontend uses `@microsoft/fetch-event-source` instead of native `EventSource` because native EventSource doesn't support POST bodies. This allows sending the session_id and message in the request body.

5. **Section-by-section generation (Prompt Chaining)**: Rather than generating the whole document at once, each section is generated via a separate tool call. This improves consistency, allows progress indication, and makes revision more targeted.

6. **Document type scope**: The system handles 10 common document types. Adding a new type requires adding it to the enum in schemas.py and section order in tasks.py.

---

## Testing the System

### Scenario 1: Successful NDA Generation
1. Type: "I need an NDA for sharing trade secrets with a potential investor"
2. Provide party names when asked
3. Specify mutual vs. one-way, jurisdiction, term
4. Observe live document generation in the right panel
5. See detect_conflicts() validation pass

### Scenario 2: Handling Ambiguous Information
1. Type: "I need a contract for working with someone"
2. Observe the system asking clarifying questions
3. Try providing contradictory information (e.g., "1 year term" then "2 years")
4. See the conflict surfaced and resolved

### Scenario 3: Document Revision
1. Complete a document generation
2. Type: "Change the governing law to New York"
3. Type: "Add a non-solicitation clause"
4. Observe apply_revision() + detect_conflicts() in action

### Scenario 4: Failure Mode — Out of Scope
1. Type: "What stocks should I invest in?"
2. Observe redirection to legal document drafting

---

## Documentation

- **[PROMPT_ENGINEERING.md](./PROMPT_ENGINEERING.md)** — Detailed prompt architecture, 5 iteration logs, 5 failure mode analyses, design rationale, token budget analysis
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — System diagrams, data flow, error handling strategy, scalability considerations
