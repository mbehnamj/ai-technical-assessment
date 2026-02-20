import type { ConversationPhase, SessionMetadata } from "../types";

const PHASE_CONFIG: Record<ConversationPhase, { label: string; color: string; desc: string }> = {
  intake: {
    label: "Intake",
    color: "#6366f1",
    desc: "Understanding your needs",
  },
  clarification: {
    label: "Gathering Info",
    color: "#f59e0b",
    desc: "Collecting document details",
  },
  generation: {
    label: "Drafting",
    color: "#10b981",
    desc: "Generating your document",
  },
  revision: {
    label: "Revising",
    color: "#3b82f6",
    desc: "Applying your changes",
  },
  complete: {
    label: "Complete",
    color: "#22c55e",
    desc: "Document ready for review",
  },
  error_recovery: {
    label: "Recovery",
    color: "#ef4444",
    desc: "Resolving an issue",
  },
};

const DOC_TYPE_LABELS: Record<string, string> = {
  nda: "NDA",
  employment_agreement: "Employment Agreement",
  service_agreement: "Service Agreement",
  consulting_agreement: "Consulting Agreement",
  partnership_agreement: "Partnership Agreement",
  llc_operating_agreement: "LLC Operating Agreement",
  terms_of_service: "Terms of Service",
  privacy_policy: "Privacy Policy",
  licensing_agreement: "Licensing Agreement",
  purchase_agreement: "Purchase Agreement",
};

interface PhaseIndicatorProps {
  metadata: SessionMetadata | null;
}

export function PhaseIndicator({ metadata }: PhaseIndicatorProps) {
  const phase = metadata?.phase ?? "intake";
  const config = PHASE_CONFIG[phase] ?? PHASE_CONFIG.intake;
  const docType = metadata?.documentType
    ? DOC_TYPE_LABELS[metadata.documentType] ?? metadata.documentType
    : null;
  const completeness = metadata?.completenessScore ?? 0;

  return (
    <div className="phase-bar">
      <div className="phase-pill" style={{ borderColor: config.color }}>
        <span className="phase-dot" style={{ background: config.color }} />
        <span className="phase-label">{config.label}</span>
        {docType && <span className="phase-doctype">· {docType}</span>}
      </div>

      {phase === "clarification" && completeness > 0 && (
        <div className="phase-progress">
          <div
            className="phase-progress-fill"
            style={{ width: `${Math.round(completeness * 100)}%`, background: config.color }}
          />
          <span className="phase-progress-label">
            {Math.round(completeness * 100)}%
          </span>
        </div>
      )}

      {phase === "generation" && metadata && metadata.sectionsGenerated.length > 0 && (
        <div className="phase-sections">
          {metadata.sectionsGenerated.map((s) => (
            <span key={s} className="section-chip">{s.replace(/_/g, " ")}</span>
          ))}
        </div>
      )}
    </div>
  );
}
