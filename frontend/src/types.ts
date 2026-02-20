// ─────────────────────────────────────────────────────────────────────────────
// Types for LexiDraft frontend
// ─────────────────────────────────────────────────────────────────────────────

export type ConversationPhase =
  | "intake"
  | "clarification"
  | "generation"
  | "revision"
  | "complete"
  | "error_recovery";

export type MessageRole = "user" | "assistant" | "system";

export type EventType =
  | "message"
  | "function_call"
  | "function_result"
  | "document_update"
  | "error"
  | "metadata"
  | "done";

// ── Chat Messages ──────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  // Function call events embedded in messages
  functionCalls?: FunctionCallEvent[];
  functionResults?: FunctionResultEvent[];
}

export interface FunctionCallEvent {
  name: string;
  id: string;
  timestamp: number;
}

export interface FunctionResultEvent {
  name: string;
  success: boolean;
  result: Record<string, unknown>;
  timestamp: number;
}

// ── Document State ─────────────────────────────────────────────────────────

export interface DocumentSection {
  name: string;
  content: string;
  wordCount?: number;
  confidence?: number;
  flags?: DocumentFlag[];
}

export interface DocumentFlag {
  flag_type: "attorney_review" | "jurisdiction_specific" | "user_clarification" | "missing_info" | "high_risk_clause";
  description: string;
  section?: string;
}

export interface DocumentState {
  content: string;
  sections: string[];
  documentType: string | null;
  charCount: number;
  flags: DocumentFlag[];
}

// ── Session Metadata ───────────────────────────────────────────────────────

export interface SessionMetadata {
  phase: ConversationPhase;
  documentType: string | null;
  userExpertise: "novice" | "intermediate" | "expert" | "unknown";
  missingFields: string[];
  completenessScore: number;
  sectionsGenerated: string[];
  iteration: number;
  timestamp: number;
}

// ── SSE Event Payloads ─────────────────────────────────────────────────────

export interface MessagePayload {
  content: string;
}

export interface FunctionCallPayload {
  name: string;
  id: string;
}

export interface FunctionResultPayload {
  name: string;
  success: boolean;
  result: Record<string, unknown>;
}

export interface DocumentUpdatePayload {
  document: string;
  sections: string[];
  document_type: string | null;
  char_count: number;
}

export interface ErrorPayload {
  message: string;
  phase: string;
  recoverable: boolean;
  details?: string;
}

export interface MetadataPayload {
  phase: ConversationPhase;
  document_type: string | null;
  user_expertise: string;
  missing_fields: string[];
  completeness_score: number;
  sections_generated: string[];
  iteration: number;
  timestamp: number;
}

export interface DonePayload {
  status: string;
  timestamp: number;
}
