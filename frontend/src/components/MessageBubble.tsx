import type { ChatMessage, FunctionCallEvent, FunctionResultEvent } from "../types";

// ── Function Call Badge ────────────────────────────────────────────────────

const TOOL_ICONS: Record<string, string> = {
  analyze_request: "🔍",
  extract_structured_data: "📋",
  validate_completeness: "✅",
  generate_document_section: "⚙️",
  apply_revision: "✏️",
  suggest_clauses: "💡",
  detect_conflicts: "⚠️",
};

const TOOL_LABELS: Record<string, string> = {
  analyze_request: "Analyzing request",
  extract_structured_data: "Capturing data",
  validate_completeness: "Checking completeness",
  generate_document_section: "Generating section",
  apply_revision: "Applying revision",
  suggest_clauses: "Suggesting clauses",
  detect_conflicts: "Checking for conflicts",
};

function FunctionBadge({ call, result }: {
  call: FunctionCallEvent;
  result?: FunctionResultEvent;
}) {
  const icon = TOOL_ICONS[call.name] || "🔧";
  const label = TOOL_LABELS[call.name] || call.name.replace(/_/g, " ");
  const success = result?.success ?? null;

  return (
    <div className="fn-badge">
      <span className="fn-icon">{icon}</span>
      <span className="fn-label">{label}</span>
      {success === null && (
        <span className="fn-status fn-status--running">
          <span className="spinner" />
        </span>
      )}
      {success === true && <span className="fn-status fn-status--ok">✓</span>}
      {success === false && <span className="fn-status fn-status--err">✗</span>}
    </div>
  );
}

// ── Message Bubble ─────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: ChatMessage;
  isLastMessage: boolean;
  isStreaming: boolean;
}

export function MessageBubble({ message, isLastMessage, isStreaming }: MessageBubbleProps) {
  const { role, content, functionCalls = [], functionResults = [] } = message;

  // Map result by function call id (or name as fallback)
  const resultByName = Object.fromEntries(
    functionResults.map((r) => [r.name, r])
  );

  if (role === "system") {
    return (
      <div className="msg msg--system">
        <span className="msg-system-icon">⚠</span>
        <span>{content}</span>
      </div>
    );
  }

  return (
    <div className={`msg msg--${role}`}>
      <div className="msg-avatar">
        {role === "user" ? (
          <div className="avatar avatar--user">U</div>
        ) : (
          <div className="avatar avatar--assistant">L</div>
        )}
      </div>

      <div className="msg-body">
        {/* Function call badges (assistant only) */}
        {role === "assistant" && functionCalls.length > 0 && (
          <div className="fn-badges">
            {functionCalls.map((call) => (
              <FunctionBadge
                key={call.id}
                call={call}
                result={resultByName[call.name]}
              />
            ))}
          </div>
        )}

        {/* Message text */}
        {content && (
          <div className="msg-text">
            {content}
            {isLastMessage && isStreaming && role === "assistant" && (
              <span className="cursor" />
            )}
          </div>
        )}

        {/* Streaming placeholder when no content yet */}
        {!content && isLastMessage && isStreaming && role === "assistant" && (
          <div className="msg-text msg-text--thinking">
            <span className="thinking-dot" />
            <span className="thinking-dot" />
            <span className="thinking-dot" />
          </div>
        )}
      </div>
    </div>
  );
}
