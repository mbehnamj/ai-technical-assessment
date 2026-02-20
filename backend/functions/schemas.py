"""
Function / Tool JSON Schemas
=============================
Defines the complete JSON Schema for all 7 tool functions:
  Required: analyze_request, extract_structured_data, validate_completeness,
            generate_document_section, apply_revision
  Bonus:    suggest_clauses, detect_conflicts

Each schema includes:
  - Detailed property descriptions
  - Strict typing with enums where appropriate
  - Required vs. optional field designation
  - Validation constraints (minLength, maxLength, minimum, maximum, patterns)

Orchestration Strategy:
  intake       → analyze_request
  clarification → extract_structured_data (per field), validate_completeness,
                   suggest_clauses (optional)
  generation   → validate_completeness (confirm), generate_document_section (×N),
                  detect_conflicts (post-generation validation)
  revision     → apply_revision, detect_conflicts (post-revision)
  any phase    → detect_conflicts (on demand)
"""

TOOLS: list[dict] = [
    # ──────────────────────────────────────────────────────────────────
    # 1. analyze_request
    # ──────────────────────────────────────────────────────────────────
    {
        "name": "analyze_request",
        "description": (
            "Analyzes the user's message to identify the type of legal document needed, "
            "detect user expertise level, extract mentioned entities, classify intent, "
            "and identify missing critical information. "
            "WHEN TO CALL: At the start of every new user message during intake phase, "
            "and whenever the user appears to change their request or add new context. "
            "ORCHESTRATION: Always call this before extract_structured_data or "
            "validate_completeness in the intake phase. Returns state update recommendations "
            "that the system uses to route the conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_message": {
                    "type": "string",
                    "description": "The exact user message to analyze.",
                    "minLength": 1,
                    "maxLength": 10000,
                },
                "document_type": {
                    "type": "string",
                    "description": (
                        "The identified document type. Use 'unknown' if the type cannot be "
                        "determined with reasonable confidence."
                    ),
                    "enum": [
                        "nda",
                        "employment_agreement",
                        "service_agreement",
                        "consulting_agreement",
                        "partnership_agreement",
                        "llc_operating_agreement",
                        "terms_of_service",
                        "privacy_policy",
                        "licensing_agreement",
                        "purchase_agreement",
                        "unknown",
                    ],
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "Confidence score for document type identification. "
                        "0.0 = complete uncertainty; 1.0 = absolute certainty. "
                        "Scores below 0.6 should trigger a clarifying question rather "
                        "than proceeding with the identified type."
                    ),
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "detected_expertise": {
                    "type": "string",
                    "description": (
                        "User expertise level inferred from vocabulary, question style, "
                        "and specificity of their request. "
                        "'novice': unfamiliar with legal terms, asks basic questions. "
                        "'intermediate': understands basic concepts, comfortable with standard terms. "
                        "'expert': uses precise legal terminology, likely a professional."
                    ),
                    "enum": ["novice", "intermediate", "expert"],
                },
                "intent": {
                    "type": "string",
                    "description": (
                        "Classified user intent. "
                        "'create_new': wants a new document drafted from scratch. "
                        "'modify_existing': wants to change an already-generated document. "
                        "'ask_question': asking about a clause or concept without creating a document. "
                        "'out_of_scope': request is not related to legal document drafting. "
                        "'unclear': intent cannot be determined."
                    ),
                    "enum": ["create_new", "modify_existing", "ask_question", "out_of_scope", "unclear"],
                },
                "key_entities": {
                    "type": "array",
                    "description": (
                        "Entities explicitly mentioned in the user's message that should be "
                        "captured in the document data (party names, dates, amounts, etc.)."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "entity_type": {
                                "type": "string",
                                "enum": ["party_name", "date", "amount", "duration", "jurisdiction", "email", "role", "other"],
                            },
                            "value": {
                                "type": "string",
                                "description": "The extracted entity value as a string.",
                            },
                            "field_name": {
                                "type": "string",
                                "description": (
                                    "Suggested storage field name (e.g., 'party_1_name', "
                                    "'effective_date', 'payment_amount')."
                                ),
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                        "required": ["entity_type", "value"],
                    },
                    "maxItems": 20,
                },
                "missing_critical_info": {
                    "type": "array",
                    "description": (
                        "List of critical information fields required for this document type "
                        "that were NOT mentioned in the user's message. These will be asked "
                        "about in the clarification phase."
                    ),
                    "items": {"type": "string"},
                    "maxItems": 15,
                },
                "out_of_scope_reason": {
                    "type": "string",
                    "description": (
                        "If intent is 'out_of_scope', explain why and suggest a redirection. "
                        "Only required when intent == 'out_of_scope'."
                    ),
                    "maxLength": 300,
                },
            },
            "required": ["user_message", "document_type", "confidence", "detected_expertise", "intent"],
        },
    },

    # ──────────────────────────────────────────────────────────────────
    # 2. extract_structured_data
    # ──────────────────────────────────────────────────────────────────
    {
        "name": "extract_structured_data",
        "description": (
            "Extracts a single validated field from the conversation and stores it in "
            "the session's structured data schema. Call this once per field immediately "
            "after the user provides the relevant information. "
            "WHEN TO CALL: After every user message that contains factual information "
            "about the document (party names, dates, terms, etc.). "
            "ORCHESTRATION: Can be called multiple times per turn if the user provides "
            "multiple fields at once. Always validate before storing. "
            "Returns confirmation of what was stored and current data summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "field_name": {
                    "type": "string",
                    "description": (
                        "Standardized field identifier using snake_case. Examples: "
                        "'party_1_name', 'party_2_name', 'effective_date', 'term_duration', "
                        "'governing_law', 'payment_amount', 'confidentiality_term', "
                        "'party_1_state', 'arbitration_required', 'non_compete_duration'."
                    ),
                    "minLength": 1,
                    "maxLength": 100,
                    "pattern": "^[a-z][a-z0-9_]*$",
                },
                "field_value": {
                    "type": "string",
                    "description": "The raw value as provided by the user.",
                    "minLength": 1,
                    "maxLength": 2000,
                },
                "field_type": {
                    "type": "string",
                    "description": (
                        "The semantic data type of this field, used for validation and formatting."
                    ),
                    "enum": [
                        "text",
                        "date",
                        "duration",
                        "amount",
                        "party_name",
                        "jurisdiction",
                        "email",
                        "address",
                        "boolean",
                        "list",
                        "enum_value",
                    ],
                },
                "validation_status": {
                    "type": "string",
                    "description": (
                        "'valid': value is clear and usable. "
                        "'invalid': value has a detectable error (e.g., impossible date). "
                        "'needs_clarification': value is ambiguous. "
                        "'assumed': user didn't provide this; a reasonable default was applied."
                    ),
                    "enum": ["valid", "invalid", "needs_clarification", "assumed"],
                },
                "normalized_value": {
                    "type": "string",
                    "description": (
                        "The standardized form of the value if different from raw input. "
                        "Examples: dates normalized to ISO 8601 (YYYY-MM-DD), "
                        "booleans to 'true'/'false', amounts to '50000 USD'."
                    ),
                    "maxLength": 500,
                },
                "validation_notes": {
                    "type": "string",
                    "description": (
                        "Explanation of validation result, especially for 'invalid', "
                        "'needs_clarification', or 'assumed' statuses."
                    ),
                    "maxLength": 500,
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "Confidence that the extracted value accurately represents "
                        "what the user intended (0.0–1.0)."
                    ),
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
            },
            "required": ["field_name", "field_value", "field_type", "validation_status", "confidence"],
        },
    },

    # ──────────────────────────────────────────────────────────────────
    # 3. validate_completeness
    # ──────────────────────────────────────────────────────────────────
    {
        "name": "validate_completeness",
        "description": (
            "Checks whether sufficient information has been collected to generate the "
            "requested document. Returns a detailed completeness assessment. "
            "WHEN TO CALL: After gathering information in clarification phase, "
            "when you believe the user has provided enough detail to proceed, "
            "or when the user explicitly asks to generate the document. "
            "ORCHESTRATION: If ready_to_generate is true, the system will transition "
            "to the generation phase. If false, use the missing fields to guide "
            "the next clarification questions. "
            "RETRY LOGIC: If called and returns not-ready, ask about missing fields, "
            "then call again when they are provided."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "The document type being validated.",
                    "enum": [
                        "nda", "employment_agreement", "service_agreement",
                        "consulting_agreement", "partnership_agreement",
                        "llc_operating_agreement", "terms_of_service",
                        "privacy_policy", "licensing_agreement", "purchase_agreement",
                    ],
                },
                "is_complete": {
                    "type": "boolean",
                    "description": (
                        "True if ALL required fields for this document type are present "
                        "and validated. False if any critical field is missing."
                    ),
                },
                "completeness_score": {
                    "type": "number",
                    "description": (
                        "Percentage of required fields present (0.0–1.0). "
                        "1.0 = all required fields collected; 0.0 = none collected."
                    ),
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "required_missing": {
                    "type": "array",
                    "description": "Critical fields absent that BLOCK document generation.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {
                                "type": "string",
                                "description": "Field identifier (snake_case).",
                            },
                            "description": {
                                "type": "string",
                                "description": "Human-readable description of what is needed.",
                            },
                            "why_needed": {
                                "type": "string",
                                "description": "Why this field is critical for this document type.",
                            },
                            "example_values": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Example valid values to help the user.",
                                "maxItems": 3,
                            },
                        },
                        "required": ["field", "description"],
                    },
                    "maxItems": 10,
                },
                "optional_missing": {
                    "type": "array",
                    "description": (
                        "Optional fields not yet collected. Will NOT block generation; "
                        "defaults will be applied."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "description": {"type": "string"},
                            "default_if_omitted": {
                                "type": "string",
                                "description": "What value will be used if the user doesn't provide this.",
                            },
                        },
                        "required": ["field", "description"],
                    },
                    "maxItems": 10,
                },
                "ready_to_generate": {
                    "type": "boolean",
                    "description": (
                        "Whether the system should proceed to document generation. "
                        "Can be true even if optional fields are missing. "
                        "Should be false only if required_missing is non-empty."
                    ),
                },
                "recommendation": {
                    "type": "string",
                    "description": (
                        "Natural language recommendation for next steps. "
                        "E.g., 'Ready to generate. Proceeding to draft your NDA.' "
                        "or 'Still need party names before we can proceed.'"
                    ),
                    "maxLength": 500,
                },
            },
            "required": ["document_type", "is_complete", "completeness_score", "ready_to_generate"],
        },
    },

    # ──────────────────────────────────────────────────────────────────
    # 4. generate_document_section
    # ──────────────────────────────────────────────────────────────────
    {
        "name": "generate_document_section",
        "description": (
            "Generates a specific named section of the legal document with appropriate "
            "legal language. Implements prompt chaining — call this once per section, "
            "in the recommended order for the document type. "
            "WHEN TO CALL: During the generation phase, once for each required section. "
            "Always include chain-of-thought reasoning (why this language was chosen). "
            "ORCHESTRATION: Call sections in order (header → recitals → definitions → "
            "core → specialized clauses → general provisions → signature_block). "
            "After all sections are generated, call detect_conflicts() to validate. "
            "SELF-CONSISTENCY: Before calling, verify the content you will generate "
            "is consistent with already-generated sections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_name": {
                    "type": "string",
                    "description": "The standardized section identifier.",
                    "enum": [
                        "header",
                        "recitals",
                        "definitions",
                        "core_obligations",
                        "term_and_termination",
                        "confidentiality",
                        "intellectual_property",
                        "payment_terms",
                        "representations_warranties",
                        "indemnification",
                        "limitation_of_liability",
                        "dispute_resolution",
                        "general_provisions",
                        "signature_block",
                    ],
                },
                "section_content": {
                    "type": "string",
                    "description": (
                        "The complete text of the generated section in professional legal language. "
                        "Must be production-quality, not a placeholder or outline."
                    ),
                    "minLength": 50,
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "CHAIN-OF-THOUGHT: Explain your drafting decisions for this section. "
                        "Include: (1) what legal standards apply, (2) why this language was chosen, "
                        "(3) what risks or interests it protects, (4) alternatives considered. "
                        "This is used for transparency and quality assurance."
                    ),
                    "minLength": 50,
                    "maxLength": 1000,
                },
                "assumptions_made": {
                    "type": "array",
                    "description": (
                        "Any defaults or assumptions applied because the user didn't provide "
                        "specific information. Each should be flagged for user review."
                    ),
                    "items": {"type": "string"},
                    "maxItems": 10,
                },
                "flags": {
                    "type": "array",
                    "description": (
                        "Items in this section that require attorney review, "
                        "user clarification, or have jurisdiction-specific implications."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "flag_type": {
                                "type": "string",
                                "enum": [
                                    "attorney_review",
                                    "jurisdiction_specific",
                                    "user_clarification",
                                    "missing_info",
                                    "high_risk_clause",
                                ],
                            },
                            "description": {
                                "type": "string",
                                "maxLength": 300,
                            },
                            "section_reference": {
                                "type": "string",
                                "description": "Specific clause or paragraph within the section.",
                            },
                        },
                        "required": ["flag_type", "description"],
                    },
                    "maxItems": 8,
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "Self-assessed quality confidence for this section (0.0–1.0). "
                        "Sections with confidence < 0.7 should have explanatory flags."
                    ),
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "word_count": {
                    "type": "integer",
                    "description": "Approximate word count of the generated section.",
                    "minimum": 1,
                },
            },
            "required": ["section_name", "section_content", "reasoning", "confidence"],
        },
    },

    # ──────────────────────────────────────────────────────────────────
    # 5. apply_revision
    # ──────────────────────────────────────────────────────────────────
    {
        "name": "apply_revision",
        "description": (
            "Modifies a specific section or clause of the already-generated document "
            "based on user feedback. Supports targeted edits (clause-level) and "
            "broader section replacements. "
            "WHEN TO CALL: Whenever the user requests a change to the document. "
            "ORCHESTRATION: Always follow with detect_conflicts() to verify the "
            "revision didn't introduce contradictions. "
            "RETRY LOGIC: If a revision creates conflicts, present the conflict "
            "to the user and offer alternatives before applying."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_name": {
                    "type": "string",
                    "description": "The section being modified.",
                    "enum": [
                        "header", "recitals", "definitions", "core_obligations",
                        "term_and_termination", "confidentiality", "intellectual_property",
                        "payment_terms", "representations_warranties", "indemnification",
                        "limitation_of_liability", "dispute_resolution",
                        "general_provisions", "signature_block", "full_document",
                    ],
                },
                "revision_type": {
                    "type": "string",
                    "description": (
                        "'add_clause': inserting a new clause into an existing section. "
                        "'remove_clause': deleting a specific clause from a section. "
                        "'modify_clause': changing specific language within a clause. "
                        "'replace_section': replacing the entire section with new content. "
                        "'restructure': major reorganization of the section."
                    ),
                    "enum": [
                        "add_clause",
                        "remove_clause",
                        "modify_clause",
                        "replace_section",
                        "restructure",
                    ],
                },
                "original_content": {
                    "type": "string",
                    "description": (
                        "The original content being replaced (for reference and audit trail). "
                        "Include only the relevant clause or paragraph if modifying a clause."
                    ),
                    "maxLength": 5000,
                },
                "revised_content": {
                    "type": "string",
                    "description": "The new content replacing the original.",
                    "minLength": 1,
                    "maxLength": 10000,
                },
                "revision_rationale": {
                    "type": "string",
                    "description": (
                        "Clear explanation of what changed and why. Should reference the "
                        "user's specific request and the legal reasoning for the approach taken."
                    ),
                    "minLength": 20,
                    "maxLength": 1000,
                },
                "impact_assessment": {
                    "type": "array",
                    "description": (
                        "Potential impacts on other document sections. "
                        "List any sections that may need review or updating as a result."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "affected_section": {"type": "string"},
                            "potential_impact": {"type": "string"},
                            "action_needed": {
                                "type": "string",
                                "enum": ["review_recommended", "update_required", "no_action"],
                            },
                        },
                        "required": ["affected_section", "potential_impact"],
                    },
                    "maxItems": 5,
                },
                "user_feedback_reference": {
                    "type": "string",
                    "description": "Brief quote or summary of the user feedback that triggered this revision.",
                    "maxLength": 200,
                },
            },
            "required": ["section_name", "revision_type", "revised_content", "revision_rationale"],
        },
    },

    # ──────────────────────────────────────────────────────────────────
    # 6. suggest_clauses (BONUS)
    # ──────────────────────────────────────────────────────────────────
    {
        "name": "suggest_clauses",
        "description": (
            "Recommends relevant optional clauses based on the document type and "
            "collected context. Ranked by relevance and risk impact. "
            "WHEN TO CALL: After gathering critical information in clarification phase, "
            "before transitioning to generation. Also useful when the user asks "
            "'is there anything else I should include?' "
            "ORCHESTRATION: Present suggestions to the user; capture their preferences "
            "with extract_structured_data, then include chosen clauses in generation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Document type for which clauses are being suggested.",
                },
                "suggestions": {
                    "type": "array",
                    "description": "Recommended optional clauses, ordered by relevance.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "clause_name": {
                                "type": "string",
                                "description": "Human-readable name for the clause.",
                            },
                            "clause_type": {
                                "type": "string",
                                "enum": [
                                    "non_compete",
                                    "non_solicitation",
                                    "arbitration",
                                    "liquidated_damages",
                                    "force_majeure",
                                    "audit_rights",
                                    "assignment",
                                    "step_in_rights",
                                    "most_favored_nation",
                                    "exclusivity",
                                    "auto_renewal",
                                    "ip_ownership",
                                    "data_protection",
                                    "insurance_requirements",
                                    "change_of_control",
                                ],
                            },
                            "description": {
                                "type": "string",
                                "description": "Plain-language description of what this clause does.",
                                "maxLength": 400,
                            },
                            "why_relevant": {
                                "type": "string",
                                "description": "Why this clause is particularly relevant given the context.",
                                "maxLength": 300,
                            },
                            "risk_if_omitted": {
                                "type": "string",
                                "description": "The risk or gap that exists without this clause.",
                                "maxLength": 300,
                            },
                            "complexity": {
                                "type": "string",
                                "enum": ["simple", "moderate", "complex"],
                                "description": "Drafting complexity of this clause.",
                            },
                            "user_decision_needed": {
                                "type": "boolean",
                                "description": "Whether this clause requires a specific user decision before drafting.",
                            },
                        },
                        "required": ["clause_name", "clause_type", "description", "why_relevant"],
                    },
                    "minItems": 1,
                    "maxItems": 5,
                },
                "context_reasoning": {
                    "type": "string",
                    "description": "Why these specific suggestions are relevant to this document and context.",
                    "maxLength": 400,
                },
            },
            "required": ["document_type", "suggestions"],
        },
    },

    # ──────────────────────────────────────────────────────────────────
    # 7. detect_conflicts (BONUS)
    # ──────────────────────────────────────────────────────────────────
    {
        "name": "detect_conflicts",
        "description": (
            "Scans the current document for contradictions, inconsistencies, "
            "and internal conflicts. Implements output validation — verifying "
            "the primary generation output against quality requirements. "
            "WHEN TO CALL: (1) After all sections are generated, (2) after every "
            "apply_revision, (3) when the user explicitly asks to 'check' the document. "
            "ORCHESTRATION: If critical conflicts are found, surface them to the user "
            "immediately and block finalization until resolved. Minor conflicts "
            "can be noted and resolved in the next revision pass."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "conflicts_found": {
                    "type": "boolean",
                    "description": "Whether any conflicts or inconsistencies were detected.",
                },
                "conflicts": {
                    "type": "array",
                    "description": "Detailed list of identified conflicts.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "conflict_id": {
                                "type": "string",
                                "description": "Unique identifier for this conflict (e.g., 'C001').",
                            },
                            "conflict_type": {
                                "type": "string",
                                "enum": [
                                    "contradictory_terms",
                                    "inconsistent_definition",
                                    "conflicting_obligations",
                                    "date_inconsistency",
                                    "party_name_mismatch",
                                    "undefined_term",
                                    "logical_impossibility",
                                    "missing_cross_reference",
                                ],
                            },
                            "section_a": {
                                "type": "string",
                                "description": "First section involved in the conflict.",
                            },
                            "section_b": {
                                "type": "string",
                                "description": "Second section involved (if applicable).",
                            },
                            "description": {
                                "type": "string",
                                "description": "Plain-language description of the conflict.",
                                "maxLength": 500,
                            },
                            "severity": {
                                "type": "string",
                                "description": (
                                    "'critical': document is legally inconsistent and must be fixed. "
                                    "'major': significant issue that should be resolved. "
                                    "'minor': stylistic or preference-level inconsistency."
                                ),
                                "enum": ["critical", "major", "minor"],
                            },
                            "suggested_resolution": {
                                "type": "string",
                                "description": "Recommended way to resolve this conflict.",
                                "maxLength": 400,
                            },
                            "excerpt_a": {
                                "type": "string",
                                "description": "Relevant text excerpt from section_a.",
                                "maxLength": 300,
                            },
                            "excerpt_b": {
                                "type": "string",
                                "description": "Relevant text excerpt from section_b (if applicable).",
                                "maxLength": 300,
                            },
                        },
                        "required": ["conflict_type", "description", "severity"],
                    },
                    "maxItems": 15,
                },
                "consistency_checks_passed": {
                    "type": "array",
                    "description": "List of consistency checks that passed (for transparency).",
                    "items": {"type": "string"},
                    "maxItems": 10,
                },
                "validation_summary": {
                    "type": "string",
                    "description": (
                        "Overall document quality assessment. "
                        "E.g., 'Document is internally consistent and ready for review.' "
                        "or '2 critical issues found that must be resolved before execution.'"
                    ),
                    "maxLength": 500,
                },
                "can_finalize": {
                    "type": "boolean",
                    "description": (
                        "Whether the document can be presented as final to the user. "
                        "False if any 'critical' or 'major' conflicts exist."
                    ),
                },
            },
            "required": ["conflicts_found", "validation_summary", "can_finalize"],
        },
    },
]
