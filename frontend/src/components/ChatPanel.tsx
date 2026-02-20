import { useState, useRef, useEffect, type FormEvent, type KeyboardEvent } from "react";
import type { ChatMessage, SessionMetadata } from "../types";
import { MessageBubble } from "./MessageBubble";
import { PhaseIndicator } from "./PhaseIndicator";

interface ChatPanelProps {
  messages: ChatMessage[];
  metadata: SessionMetadata | null;
  isStreaming: boolean;
  isLoading: boolean;
  error: string | null;
  onSendMessage: (text: string) => void;
  onReset: () => void;
}

const STARTER_PROMPTS = [
  "I need a Non-Disclosure Agreement for sharing tech with a vendor",
  "Help me draft an employment contract for a senior engineer",
  "Create a consulting agreement for a freelance project",
  "I need a service agreement between my startup and a client",
];

export function ChatPanel({
  messages,
  metadata,
  isStreaming,
  isLoading,
  error,
  onSendMessage,
  onReset,
}: ChatPanelProps) {
  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text || isStreaming) return;
    setInputValue("");
    onSendMessage(text);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="chat-panel">
      {/* Header */}
      <div className="chat-header">
        <div className="chat-header-left">
          <div className="logo">
            <span className="logo-icon">⚖</span>
            <span className="logo-text">LexiDraft</span>
          </div>
          <PhaseIndicator metadata={metadata} />
        </div>
        <button
          className="btn btn--ghost btn--sm"
          onClick={onReset}
          title="Start over"
          disabled={isStreaming}
        >
          New Document
        </button>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {isEmpty ? (
          <div className="chat-empty">
            <div className="chat-empty-icon">⚖️</div>
            <h2 className="chat-empty-title">Draft Legal Documents with AI</h2>
            <p className="chat-empty-sub">
              Describe the document you need and I'll guide you through creating it.
            </p>
            <div className="starter-prompts">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  className="starter-prompt"
                  onClick={() => {
                    setInputValue(prompt);
                    inputRef.current?.focus();
                  }}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isLastMessage={idx === messages.length - 1}
                isStreaming={isStreaming}
              />
            ))}

            {isLoading && !isStreaming && (
              <div className="msg msg--assistant">
                <div className="msg-avatar">
                  <div className="avatar avatar--assistant">L</div>
                </div>
                <div className="msg-body">
                  <div className="msg-text msg-text--thinking">
                    <span className="thinking-dot" />
                    <span className="thinking-dot" />
                    <span className="thinking-dot" />
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div className="chat-error">
                <span>⚠ {error}</span>
                <button onClick={onReset} className="btn btn--sm btn--ghost">
                  Reset
                </button>
              </div>
            )}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form className="chat-input-area" onSubmit={handleSubmit}>
        <div className="chat-input-wrapper">
          <textarea
            ref={inputRef}
            className="chat-input"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isStreaming
                ? "Waiting for response..."
                : "Describe the document you need, or answer a question..."
            }
            disabled={isStreaming}
            rows={1}
          />
          <button
            type="submit"
            className="btn btn--primary chat-send"
            disabled={!inputValue.trim() || isStreaming}
            aria-label="Send message"
          >
            {isStreaming ? (
              <span className="spinner spinner--sm" />
            ) : (
              <span>↑</span>
            )}
          </button>
        </div>
        <div className="chat-input-hint">
          Press <kbd>Enter</kbd> to send · <kbd>Shift+Enter</kbd> for newline
        </div>
      </form>
    </div>
  );
}
