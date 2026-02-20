import { useState, useRef, useCallback } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import type {
  ChatMessage,
  DocumentState,
  SessionMetadata,
  FunctionCallEvent,
  FunctionResultEvent,
  ConversationPhase,
  DocumentUpdatePayload,
  MetadataPayload,
  ErrorPayload,
} from "../types";

const API_BASE = "/api";

// ─────────────────────────────────────────────────────────────────────────────

function generateId(): string {
  return Math.random().toString(36).slice(2, 11);
}

function generateSessionId(): string {
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// ─────────────────────────────────────────────────────────────────────────────

interface UseChatReturn {
  messages: ChatMessage[];
  document: DocumentState | null;
  metadata: SessionMetadata | null;
  isStreaming: boolean;
  isLoading: boolean;
  error: string | null;
  sessionId: string;
  sendMessage: (text: string) => Promise<void>;
  resetConversation: () => Promise<void>;
}

// ─────────────────────────────────────────────────────────────────────────────

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [document, setDocument] = useState<DocumentState | null>(null);
  const [metadata, setMetadata] = useState<SessionMetadata | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionIdRef = useRef<string>(generateSessionId());
  const abortControllerRef = useRef<AbortController | null>(null);

  // Current assistant message being built during streaming
  const currentAssistantMsgRef = useRef<ChatMessage | null>(null);

  // ── Helper: append/update messages ──────────────────────────────────────

  const appendUserMessage = useCallback((text: string) => {
    const msg: ChatMessage = {
      id: generateId(),
      role: "user",
      content: text,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, []);

  const startAssistantMessage = useCallback((): ChatMessage => {
    const msg: ChatMessage = {
      id: generateId(),
      role: "assistant",
      content: "",
      timestamp: Date.now(),
      functionCalls: [],
      functionResults: [],
    };
    currentAssistantMsgRef.current = msg;
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, []);

  const appendToCurrentAssistant = useCallback((token: string) => {
    if (!currentAssistantMsgRef.current) {
      startAssistantMessage();
    }
    const msgId = currentAssistantMsgRef.current!.id;
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, content: m.content + token } : m))
    );
  }, [startAssistantMessage]);

  const addFunctionCallToAssistant = useCallback((evt: FunctionCallEvent) => {
    if (!currentAssistantMsgRef.current) return;
    const msgId = currentAssistantMsgRef.current.id;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? { ...m, functionCalls: [...(m.functionCalls ?? []), evt] }
          : m
      )
    );
  }, []);

  const addFunctionResultToAssistant = useCallback((evt: FunctionResultEvent) => {
    if (!currentAssistantMsgRef.current) return;
    const msgId = currentAssistantMsgRef.current.id;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? { ...m, functionResults: [...(m.functionResults ?? []), evt] }
          : m
      )
    );
  }, []);

  // ── sendMessage ──────────────────────────────────────────────────────────

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isStreaming) return;

      setError(null);
      setIsLoading(true);
      setIsStreaming(true);

      appendUserMessage(text);
      startAssistantMessage();

      // Cancel previous request if any
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        await fetchEventSource(`${API_BASE}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({
            session_id: sessionIdRef.current,
            message: text,
          }),
          signal: controller.signal,

          onopen: async (response) => {
            if (!response.ok) {
              throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            setIsLoading(false);
          },

          onmessage: (evt) => {
            try {
              const payload = JSON.parse(evt.data);

              switch (evt.event) {
                case "message":
                  appendToCurrentAssistant(payload.content ?? "");
                  break;

                case "function_call":
                  addFunctionCallToAssistant({
                    name: payload.name,
                    id: payload.id,
                    timestamp: Date.now(),
                  });
                  break;

                case "function_result":
                  addFunctionResultToAssistant({
                    name: payload.name,
                    success: payload.success,
                    result: payload.result ?? {},
                    timestamp: Date.now(),
                  });
                  break;

                case "document_update": {
                  const docPayload = payload as DocumentUpdatePayload;
                  setDocument({
                    content: docPayload.document,
                    sections: docPayload.sections,
                    documentType: docPayload.document_type,
                    charCount: docPayload.char_count,
                    flags: [],
                  });
                  break;
                }

                case "metadata": {
                  const meta = payload as MetadataPayload;
                  setMetadata({
                    phase: meta.phase as ConversationPhase,
                    documentType: meta.document_type,
                    userExpertise: meta.user_expertise as SessionMetadata["userExpertise"],
                    missingFields: meta.missing_fields,
                    completenessScore: meta.completeness_score,
                    sectionsGenerated: meta.sections_generated,
                    iteration: meta.iteration,
                    timestamp: meta.timestamp,
                  });
                  break;
                }

                case "error": {
                  const errPayload = payload as ErrorPayload;
                  if (!errPayload.recoverable) {
                    setError(errPayload.message);
                  }
                  // Add error to chat as system message
                  setMessages((prev) => [
                    ...prev,
                    {
                      id: generateId(),
                      role: "system",
                      content: `Error: ${errPayload.message}`,
                      timestamp: Date.now(),
                    },
                  ]);
                  break;
                }

                case "done":
                  currentAssistantMsgRef.current = null;
                  setIsStreaming(false);
                  setIsLoading(false);
                  break;
              }
            } catch {
              // Malformed JSON in event data — ignore silently
            }
          },

          onerror: (err) => {
            if ((err as Error).name === "AbortError") return;
            setError("Connection error. Please try again.");
            setIsStreaming(false);
            setIsLoading(false);
            throw err; // Tell fetchEventSource to stop retrying
          },

          onclose: () => {
            currentAssistantMsgRef.current = null;
            setIsStreaming(false);
            setIsLoading(false);
          },
        });
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError(`Failed to send message: ${(err as Error).message}`);
        }
        setIsStreaming(false);
        setIsLoading(false);
      }
    },
    [isStreaming, appendUserMessage, startAssistantMessage, appendToCurrentAssistant,
     addFunctionCallToAssistant, addFunctionResultToAssistant]
  );

  // ── resetConversation ────────────────────────────────────────────────────

  const resetConversation = useCallback(async () => {
    // Abort any in-progress stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const oldSessionId = sessionIdRef.current;
    sessionIdRef.current = generateSessionId();

    // Reset local state
    setMessages([]);
    setDocument(null);
    setMetadata(null);
    setError(null);
    setIsStreaming(false);
    setIsLoading(false);
    currentAssistantMsgRef.current = null;

    // Notify backend
    try {
      await fetch(`${API_BASE}/conversation/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: oldSessionId }),
      });
    } catch {
      // Ignore reset errors — local state is already clean
    }
  }, []);

  return {
    messages,
    document,
    metadata,
    isStreaming,
    isLoading,
    error,
    sessionId: sessionIdRef.current,
    sendMessage,
    resetConversation,
  };
}
