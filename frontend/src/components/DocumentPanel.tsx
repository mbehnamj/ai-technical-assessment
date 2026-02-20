import { useState } from "react";
import type { DocumentState, SessionMetadata } from "../types";

interface DocumentPanelProps {
  document: DocumentState | null;
  metadata: SessionMetadata | null;
  isStreaming: boolean;
}

const SECTION_LABELS: Record<string, string> = {
  header: "Header",
  recitals: "Recitals",
  definitions: "Definitions",
  core_obligations: "Core Obligations",
  confidentiality: "Confidentiality",
  intellectual_property: "Intellectual Property",
  payment_terms: "Payment Terms",
  representations_warranties: "Representations & Warranties",
  indemnification: "Indemnification",
  limitation_of_liability: "Limitation of Liability",
  term_and_termination: "Term & Termination",
  dispute_resolution: "Dispute Resolution",
  general_provisions: "General Provisions",
  signature_block: "Signature Block",
};

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {
    const ta = window.document.createElement("textarea");
    ta.value = text;
    window.document.body.appendChild(ta);
    ta.select();
    window.document.execCommand("copy");
    window.document.body.removeChild(ta);
  });
}

function downloadDocument(content: string, docType: string | null) {
  const filename = `${docType ?? "legal_document"}_${Date.now()}.txt`;
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = window.document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function DocumentPanel({ document, metadata, isStreaming }: DocumentPanelProps) {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<"full" | "sections">("full");

  const isEmpty = !document || !document.content;
  const isGenerating = metadata?.phase === "generation" && isStreaming;

  const handleCopy = () => {
    if (!document?.content) return;
    copyToClipboard(document.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!document?.content) return;
    downloadDocument(document.content, document.documentType);
  };

  return (
    <div className="doc-panel">
      {/* Header */}
      <div className="doc-header">
        <div className="doc-header-left">
          <h2 className="doc-title">
            {document?.documentType
              ? formatDocType(document.documentType)
              : "Document Preview"}
          </h2>
          {document && (
            <span className="doc-stats">
              {document.charCount.toLocaleString()} chars ·{" "}
              {document.sections.length} sections
            </span>
          )}
        </div>

        {document && (
          <div className="doc-actions">
            <div className="tab-group">
              <button
                className={`tab ${activeTab === "full" ? "tab--active" : ""}`}
                onClick={() => setActiveTab("full")}
              >
                Full Doc
              </button>
              <button
                className={`tab ${activeTab === "sections" ? "tab--active" : ""}`}
                onClick={() => setActiveTab("sections")}
              >
                Sections ({document.sections.length})
              </button>
            </div>
            <button className="btn btn--ghost btn--sm" onClick={handleCopy} disabled={!document.content}>
              {copied ? "✓ Copied" : "Copy"}
            </button>
            <button className="btn btn--ghost btn--sm" onClick={handleDownload} disabled={!document.content}>
              Download
            </button>
          </div>
        )}
      </div>

      {/* Flags */}
      {document?.flags && document.flags.length > 0 && (
        <div className="doc-flags">
          <div className="doc-flags-title">⚠ Requires Attention</div>
          {document.flags.map((flag, i) => (
            <div key={i} className={`doc-flag doc-flag--${flag.flag_type.replace("_", "-")}`}>
              <span className="flag-icon">{getFlagIcon(flag.flag_type)}</span>
              <span className="flag-desc">{flag.description}</span>
            </div>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="doc-content">
        {isEmpty && !isGenerating && (
          <div className="doc-empty">
            <div className="doc-empty-icon">📄</div>
            <p className="doc-empty-title">Your document will appear here</p>
            <p className="doc-empty-sub">
              Chat with LexiDraft to start generating your legal document.
            </p>
          </div>
        )}

        {isGenerating && isEmpty && (
          <div className="doc-generating">
            <div className="generating-animation">
              <div className="generating-bar" />
              <div className="generating-bar" />
              <div className="generating-bar generating-bar--short" />
              <div className="generating-bar" />
              <div className="generating-bar generating-bar--short" />
            </div>
            <p className="generating-label">Drafting your document…</p>
            {metadata?.sectionsGenerated && metadata.sectionsGenerated.length > 0 && (
              <div className="generating-sections">
                {metadata.sectionsGenerated.map((s) => (
                  <span key={s} className="section-chip section-chip--done">
                    ✓ {SECTION_LABELS[s] ?? s}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {document && activeTab === "full" && (
          <pre className="doc-text">{document.content}</pre>
        )}

        {document && activeTab === "sections" && (
          <div className="doc-sections">
            {document.sections.map((sectionName) => (
              <div key={sectionName} className="doc-section-item">
                <div className="doc-section-name">
                  {SECTION_LABELS[sectionName] ?? sectionName.replace(/_/g, " ")}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer disclaimer */}
      {document && (
        <div className="doc-disclaimer">
          ⚖ AI-generated draft only. Have this reviewed by a qualified attorney before execution.
        </div>
      )}
    </div>
  );
}

function formatDocType(type: string): string {
  const labels: Record<string, string> = {
    nda: "Non-Disclosure Agreement",
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
  return labels[type] ?? type.replace(/_/g, " ");
}

function getFlagIcon(flagType: string): string {
  const icons: Record<string, string> = {
    attorney_review: "⚖",
    jurisdiction_specific: "🌍",
    user_clarification: "❓",
    missing_info: "📝",
    high_risk_clause: "🔴",
  };
  return icons[flagType] ?? "⚠";
}
