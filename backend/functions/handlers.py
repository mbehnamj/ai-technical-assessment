"""
Tool Handler Execution Logic
=============================
Implements the execution logic for all 7 tool functions.

Design principles:
  - Handle partial/malformed tool calls gracefully
  - Return structured responses the LLM can interpret
  - Include error states and recovery paths
  - Mutate session state as the source of truth
  - Never raise exceptions — always return error dicts
"""

import json
import time
from typing import Any


class ToolHandler:
    """
    Executes tool calls and updates session state.

    Orchestration Strategy:
      - analyze_request    → updates phase, document_type, user_expertise
      - extract_*          → populates extracted_data, removes from missing_fields
      - validate_complete. → sets completeness_score, transitions to generation
      - generate_section   → populates document_sections, triggers _rebuild_document
      - apply_revision     → updates specific section, triggers _rebuild_document
      - suggest_clauses    → stores suggestions for user presentation
      - detect_conflicts   → sets conflicts, can_finalize flag

    Retry Logic:
      - Failed tool calls return {'success': False, 'error': '...', 'retry_hint': '...'}
      - The orchestrator (app.py) surfaces errors to the LLM for recovery
    """

    # Section rendering order for document assembly
    SECTION_ORDER = [
        "header",
        "recitals",
        "definitions",
        "core_obligations",
        "confidentiality",
        "intellectual_property",
        "payment_terms",
        "representations_warranties",
        "indemnification",
        "limitation_of_liability",
        "term_and_termination",
        "dispute_resolution",
        "general_provisions",
        "signature_block",
    ]

    def __init__(self, state: dict):
        self.state = state

    # ──────────────────────────────────────────────────────────────────
    # Dispatch
    # ──────────────────────────────────────────────────────────────────

    def execute(self, tool_name: str, tool_input: dict) -> dict[str, Any]:
        """
        Route a tool call to the appropriate handler.

        Returns a dict with at minimum:
          {'success': bool, ...result fields...}
        """
        dispatch = {
            "analyze_request": self._analyze_request,
            "extract_structured_data": self._extract_structured_data,
            "validate_completeness": self._validate_completeness,
            "generate_document_section": self._generate_document_section,
            "apply_revision": self._apply_revision,
            "suggest_clauses": self._suggest_clauses,
            "detect_conflicts": self._detect_conflicts,
        }

        handler = dispatch.get(tool_name)
        if not handler:
            return {
                "success": False,
                "error": f"Unknown tool: '{tool_name}'",
                "retry_hint": "Use one of: " + ", ".join(dispatch.keys()),
            }

        try:
            return handler(tool_input or {})
        except Exception as exc:
            return {
                "success": False,
                "tool": tool_name,
                "error": str(exc),
                "retry_hint": "Tool execution failed. Review input schema and retry.",
            }

    # ──────────────────────────────────────────────────────────────────
    # 1. analyze_request
    # ──────────────────────────────────────────────────────────────────

    def _analyze_request(self, inp: dict) -> dict:
        """Update session state from request analysis."""

        # Update document type if high confidence
        doc_type = inp.get("document_type", "unknown")
        confidence = inp.get("confidence", 0.0)
        if doc_type and doc_type != "unknown" and confidence >= 0.6:
            self.state["document_type"] = doc_type

        # Update user expertise
        expertise = inp.get("detected_expertise")
        if expertise and self.state.get("user_expertise", "unknown") == "unknown":
            self.state["user_expertise"] = expertise

        # Update phase based on intent
        intent = inp.get("intent", "unclear")
        current_phase = self.state.get("phase", "intake")

        if intent == "create_new" and current_phase == "intake":
            self.state["phase"] = "clarification"
        elif intent == "modify_existing" and current_phase not in ("intake",):
            self.state["phase"] = "revision"
        elif intent == "out_of_scope":
            self.state["out_of_scope_flag"] = True

        # Extract entities into data store
        for entity in inp.get("key_entities", []):
            field_name = entity.get("field_name")
            value = entity.get("value")
            entity_confidence = entity.get("confidence", 0.5)
            if field_name and value and entity_confidence >= 0.7:
                if field_name not in self.state["extracted_data"]:
                    self.state["extracted_data"][field_name] = value

        # Update missing fields list
        missing = inp.get("missing_critical_info", [])
        if missing:
            existing_missing = self.state.get("missing_fields", [])
            # Merge without duplicates
            combined = list(dict.fromkeys(existing_missing + missing))
            # Remove fields already collected
            combined = [f for f in combined if f not in self.state["extracted_data"]]
            self.state["missing_fields"] = combined

        return {
            "success": True,
            "state_updated": {
                "phase": self.state["phase"],
                "document_type": self.state.get("document_type"),
                "user_expertise": self.state.get("user_expertise"),
                "out_of_scope": self.state.get("out_of_scope_flag", False),
            },
            "entities_captured": len(inp.get("key_entities", [])),
            "missing_fields_identified": len(inp.get("missing_critical_info", [])),
            "message": f"Request analyzed. Phase: {self.state['phase']}. "
                       f"Document type: {self.state.get('document_type', 'undetermined')} "
                       f"(confidence: {confidence:.0%}).",
        }

    # ──────────────────────────────────────────────────────────────────
    # 2. extract_structured_data
    # ──────────────────────────────────────────────────────────────────

    def _extract_structured_data(self, inp: dict) -> dict:
        """Store a validated field in extracted_data."""
        field_name = inp.get("field_name", "").strip()
        if not field_name:
            return {
                "success": False,
                "error": "field_name is required and must be non-empty.",
                "retry_hint": "Provide a valid snake_case field_name.",
            }

        field_value = inp.get("field_value", "")
        validation_status = inp.get("validation_status", "valid")
        normalized = inp.get("normalized_value") or field_value
        confidence = inp.get("confidence", 1.0)

        if validation_status == "invalid":
            return {
                "success": False,
                "field_name": field_name,
                "validation_status": "invalid",
                "validation_notes": inp.get("validation_notes", "Value failed validation."),
                "retry_hint": "Ask the user to clarify this field before storing.",
            }

        if validation_status == "needs_clarification":
            return {
                "success": False,
                "field_name": field_name,
                "validation_status": "needs_clarification",
                "validation_notes": inp.get("validation_notes", "Ambiguous value."),
                "retry_hint": "Ask the user to clarify, then call this tool again.",
            }

        # Store the value (use normalized form when available)
        stored_value = normalized if normalized != field_value else field_value
        self.state["extracted_data"][field_name] = stored_value

        # Track confidence for each field
        if "field_confidence" not in self.state:
            self.state["field_confidence"] = {}
        self.state["field_confidence"][field_name] = confidence

        # Remove from missing fields
        missing = self.state.get("missing_fields", [])
        self.state["missing_fields"] = [f for f in missing if f != field_name]

        # Track assumptions
        if validation_status == "assumed":
            if "assumed_fields" not in self.state:
                self.state["assumed_fields"] = []
            self.state["assumed_fields"].append(
                {"field": field_name, "assumed_value": stored_value,
                 "notes": inp.get("validation_notes", "")}
            )

        return {
            "success": True,
            "field_stored": field_name,
            "stored_value": stored_value,
            "validation_status": validation_status,
            "was_normalized": normalized != field_value,
            "fields_remaining": len(self.state.get("missing_fields", [])),
            "total_fields_collected": len(self.state["extracted_data"]),
        }

    # ──────────────────────────────────────────────────────────────────
    # 3. validate_completeness
    # ──────────────────────────────────────────────────────────────────

    def _validate_completeness(self, inp: dict) -> dict:
        """Update completeness assessment and potentially trigger phase transition."""
        ready = inp.get("ready_to_generate", False)
        completeness_score = inp.get("completeness_score", 0.0)
        required_missing = inp.get("required_missing", [])
        optional_missing = inp.get("optional_missing", [])
        recommendation = inp.get("recommendation", "")

        # Update state
        self.state["completeness_score"] = completeness_score
        self.state["missing_fields"] = [f["field"] for f in required_missing]

        # Transition to generation if ready
        if ready and self.state["phase"] == "clarification":
            self.state["phase"] = "generation"

        # Store validation result
        self.state["last_validation"] = {
            "timestamp": time.time(),
            "ready": ready,
            "score": completeness_score,
            "required_missing": required_missing,
            "optional_missing": optional_missing,
        }

        return {
            "success": True,
            "ready_to_generate": ready,
            "completeness_score": completeness_score,
            "phase_transitioned_to": self.state["phase"] if ready else None,
            "required_missing_count": len(required_missing),
            "optional_missing_count": len(optional_missing),
            "required_missing": required_missing,
            "optional_missing": optional_missing,
            "recommendation": recommendation,
            "next_action": (
                "Proceed to document generation." if ready
                else f"Ask about: {', '.join(f['field'] for f in required_missing[:3])}"
            ),
        }

    # ──────────────────────────────────────────────────────────────────
    # 4. generate_document_section
    # ──────────────────────────────────────────────────────────────────

    def _generate_document_section(self, inp: dict) -> dict:
        """Store a generated section and rebuild the full document."""
        section_name = inp.get("section_name", "").strip()
        section_content = inp.get("section_content", "").strip()

        if not section_name:
            return {
                "success": False,
                "error": "section_name is required.",
                "retry_hint": "Provide a valid section_name from the allowed enum.",
            }
        if not section_content or len(section_content) < 20:
            return {
                "success": False,
                "error": "section_content is too short or empty.",
                "retry_hint": "Generate complete, production-quality section content.",
            }

        confidence = inp.get("confidence", 1.0)
        reasoning = inp.get("reasoning", "")
        flags = inp.get("flags", [])
        assumptions = inp.get("assumptions_made", [])

        # Store section
        self.state["document_sections"][section_name] = {
            "content": section_content,
            "reasoning": reasoning,
            "confidence": confidence,
            "flags": flags,
            "assumptions": assumptions,
            "generated_at": time.time(),
            "word_count": len(section_content.split()),
        }

        # Rebuild assembled document
        self._rebuild_document()
        self.state["document_updated"] = True

        # Accumulate flags for user summary
        if "all_flags" not in self.state:
            self.state["all_flags"] = []
        for flag in flags:
            flag["section"] = section_name
            self.state["all_flags"].append(flag)

        # Determine what comes next
        next_section = self._get_next_section()

        return {
            "success": True,
            "section_stored": section_name,
            "word_count": len(section_content.split()),
            "confidence": confidence,
            "flags_raised": len(flags),
            "assumptions_made": len(assumptions),
            "sections_complete": list(self.state["document_sections"].keys()),
            "next_section_needed": next_section,
            "all_sections_done": next_section is None,
            "message": (
                f"Section '{section_name}' generated ({len(section_content.split())} words). "
                + (f"Next: '{next_section}'" if next_section else "All sections complete!")
            ),
        }

    def _rebuild_document(self) -> None:
        """Assemble all sections into the complete document in canonical order."""
        sections = self.state.get("document_sections", {})
        parts = []

        # Add sections in canonical order
        for name in self.SECTION_ORDER:
            if name in sections:
                parts.append(sections[name]["content"])

        # Add any non-standard sections not in the canonical order
        for name, data in sections.items():
            if name not in self.SECTION_ORDER:
                parts.append(data["content"])

        self.state["current_document"] = "\n\n" + "\n\n".join(parts) if parts else ""

    def _get_next_section(self) -> str | None:
        """Determine the next section needed based on document type and what's done."""
        from prompts.tasks import SECTION_ORDERS, DOCUMENT_TYPE_DISPLAY  # local import

        doc_type = self.state.get("document_type", "default")
        order = SECTION_ORDERS.get(doc_type, SECTION_ORDERS["default"])
        done = set(self.state.get("document_sections", {}).keys())

        for section in order:
            if section not in done:
                return section
        return None

    # ──────────────────────────────────────────────────────────────────
    # 5. apply_revision
    # ──────────────────────────────────────────────────────────────────

    def _apply_revision(self, inp: dict) -> dict:
        """Apply a targeted revision to the document."""
        section_name = inp.get("section_name", "").strip()
        revised_content = inp.get("revised_content", "").strip()
        revision_type = inp.get("revision_type", "modify_clause")
        rationale = inp.get("revision_rationale", "")
        impact = inp.get("impact_assessment", [])
        user_feedback = inp.get("user_feedback_reference", "")

        if not section_name:
            return {
                "success": False,
                "error": "section_name is required.",
                "retry_hint": "Specify which section to revise.",
            }
        if not revised_content:
            return {
                "success": False,
                "error": "revised_content cannot be empty.",
                "retry_hint": "Provide the complete revised section content.",
            }

        original_content = ""

        if section_name == "full_document":
            original_content = self.state.get("current_document", "")
            self.state["current_document"] = revised_content
        elif section_name in self.state.get("document_sections", {}):
            original_content = self.state["document_sections"][section_name]["content"]
            self.state["document_sections"][section_name]["content"] = revised_content
            self.state["document_sections"][section_name]["last_revised"] = time.time()
            self._rebuild_document()
        else:
            # New section being added
            self.state["document_sections"][section_name] = {
                "content": revised_content,
                "reasoning": rationale,
                "confidence": 0.9,
                "flags": [],
                "assumptions": [],
                "generated_at": time.time(),
                "word_count": len(revised_content.split()),
            }
            self._rebuild_document()

        self.state["document_updated"] = True
        self.state["phase"] = "revision"

        # Track revision history
        if "revision_history" not in self.state:
            self.state["revision_history"] = []
        self.state["revision_history"].append({
            "section": section_name,
            "revision_type": revision_type,
            "rationale": rationale,
            "user_feedback": user_feedback,
            "timestamp": time.time(),
            "char_delta": len(revised_content) - len(original_content),
        })

        return {
            "success": True,
            "section_revised": section_name,
            "revision_type": revision_type,
            "char_delta": len(revised_content) - len(original_content),
            "rationale": rationale,
            "impact_assessment": impact,
            "revision_count": len(self.state.get("revision_history", [])),
            "message": f"Revision applied to '{section_name}'. {rationale[:100]}",
            "next_action": "Call detect_conflicts() to verify document integrity.",
        }

    # ──────────────────────────────────────────────────────────────────
    # 6. suggest_clauses
    # ──────────────────────────────────────────────────────────────────

    def _suggest_clauses(self, inp: dict) -> dict:
        """Store clause suggestions for user presentation."""
        suggestions = inp.get("suggestions", [])
        doc_type = inp.get("document_type", "")
        reasoning = inp.get("context_reasoning", "")

        if not suggestions:
            return {
                "success": False,
                "error": "At least one suggestion is required.",
                "retry_hint": "Provide relevant optional clauses for this document type.",
            }

        self.state["clause_suggestions"] = suggestions
        self.state["clause_suggestions_context"] = reasoning

        # Identify which suggestions require user decisions
        decision_needed = [s["clause_name"] for s in suggestions if s.get("user_decision_needed")]

        return {
            "success": True,
            "suggestions_count": len(suggestions),
            "suggestions": suggestions,
            "decision_needed_for": decision_needed,
            "context_reasoning": reasoning,
            "message": (
                f"{len(suggestions)} optional clause(s) suggested for this {doc_type}. "
                "Present these to the user and capture their preferences."
            ),
        }

    # ──────────────────────────────────────────────────────────────────
    # 7. detect_conflicts
    # ──────────────────────────────────────────────────────────────────

    def _detect_conflicts(self, inp: dict) -> dict:
        """Update conflict state and determine if document can be finalized."""
        conflicts_found = inp.get("conflicts_found", False)
        conflicts = inp.get("conflicts", [])
        validation_summary = inp.get("validation_summary", "")
        can_finalize = inp.get("can_finalize", not conflicts_found)
        passed_checks = inp.get("consistency_checks_passed", [])

        self.state["conflicts"] = conflicts
        self.state["has_conflicts"] = conflicts_found
        self.state["can_finalize"] = can_finalize
        self.state["last_validation_summary"] = validation_summary

        # Categorize by severity
        critical = [c for c in conflicts if c.get("severity") == "critical"]
        major = [c for c in conflicts if c.get("severity") == "major"]
        minor = [c for c in conflicts if c.get("severity") == "minor"]

        # Override can_finalize if critical issues exist
        if critical:
            self.state["can_finalize"] = False
            can_finalize = False

        # If document is clean, transition to complete phase
        if not conflicts_found and self.state.get("phase") == "generation":
            self.state["phase"] = "complete"

        return {
            "success": True,
            "conflicts_found": conflicts_found,
            "total_conflicts": len(conflicts),
            "critical_count": len(critical),
            "major_count": len(major),
            "minor_count": len(minor),
            "critical_conflicts": critical,
            "can_finalize": can_finalize,
            "consistency_checks_passed": passed_checks,
            "validation_summary": validation_summary,
            "phase_after_validation": self.state.get("phase"),
            "message": (
                validation_summary or (
                    "No conflicts detected. Document is ready for review."
                    if not conflicts_found
                    else f"{len(critical)} critical, {len(major)} major, {len(minor)} minor issues found."
                )
            ),
        }
