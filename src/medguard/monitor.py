from __future__ import annotations

from .chatbot import ChatbotPlanner
from .llm_classifier import LLMClassifierStatus, OpenAIThreatClassifier
from .models import MonitorResult, Principal, ToolCall


PROMPT_INJECTION_TERMS = [
    "ignore previous instructions",
    "ignore prior rules",
    "pretend you are",
    "act as admin",
    "developer mode",
    "system prompt",
    "override policy",
    "security audit",
]

ROLE_IMPERSONATION_TERMS = [
    "i'm dr.",
    "i am dr.",
    "i am the admin",
    "doctor asked me",
    "on behalf of",
    "i have approval",
]

SENSITIVE_INFERENCE_TERMS = [
    "pregnant",
    "pregnancy",
    "hiv",
    "oncology",
    "cancer",
    "antiretroviral",
]

SENSITIVE_FIELD_TERMS = [
    "ssn",
    "social security",
    "date of birth",
    "address",
    "phone",
    "email",
]

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ACTION_ORDER = {
    "allow": 0,
    "allow_with_logging": 1,
    "require_reauthentication": 2,
    "block_and_log": 3,
    "block_and_alert": 4,
}


class SecurityMonitor:
    def __init__(self, llm_classifier: OpenAIThreatClassifier | None = None) -> None:
        self.llm_classifier = llm_classifier or OpenAIThreatClassifier()

    def classifier_status(self) -> LLMClassifierStatus:
        return self.llm_classifier.status()

    def evaluate(
        self,
        principal: Principal,
        message: str,
        tool_call: ToolCall,
        history: list[dict],
    ) -> MonitorResult:
        return self.evaluate_hybrid(principal, message, tool_call, history)

    def evaluate_heuristic(
        self,
        principal: Principal,
        message: str,
        tool_call: ToolCall,
        history: list[dict],
    ) -> MonitorResult:
        return self._evaluate_heuristics(principal, message, tool_call, history)

    def evaluate_llm_only(
        self,
        principal: Principal,
        message: str,
        tool_call: ToolCall,
        history: list[dict],
    ) -> MonitorResult:
        llm_status = self.llm_classifier.status()
        if not llm_status.enabled:
            return self._llm_unavailable_result("LLM classifier is unavailable because no API key is configured.", llm_status.model)
        try:
            llm_result = self.llm_classifier.classify(principal, message, tool_call, history)
            if llm_result:
                return llm_result
        except RuntimeError as exc:
            return self._llm_unavailable_result(str(exc), llm_status.model)
        return self._llm_unavailable_result("LLM classifier returned no result.", llm_status.model)

    def evaluate_hybrid(
        self,
        principal: Principal,
        message: str,
        tool_call: ToolCall,
        history: list[dict],
    ) -> MonitorResult:
        heuristic = self._evaluate_heuristics(principal, message, tool_call, history)
        llm_result = self.evaluate_llm_only(principal, message, tool_call, history)
        if llm_result.source in {"llm_unavailable", "llm_error"}:
            heuristic.source = "heuristic"
            heuristic.llm_model = llm_result.llm_model
            heuristic.llm_error = llm_result.llm_error
            return heuristic
        return self._merge_results(heuristic, llm_result, llm_error=None)

    def compare_modes(
        self,
        principal: Principal,
        message: str,
        tool_call: ToolCall,
        history: list[dict],
    ) -> dict[str, MonitorResult]:
        heuristic = self.evaluate_heuristic(principal, message, tool_call, history)
        llm = self.evaluate_llm_only(principal, message, tool_call, history)
        hybrid = heuristic if llm.source in {"llm_unavailable", "llm_error"} else self._merge_results(heuristic, llm, llm_error=None)
        if hybrid is heuristic:
            hybrid = MonitorResult(
                risk_level=heuristic.risk_level,
                score=heuristic.score,
                attack_type=heuristic.attack_type,
                reasons=list(heuristic.reasons),
                recommended_action=heuristic.recommended_action,
                source="hybrid_fallback",
                heuristic_score=heuristic.heuristic_score,
                llm_score=None,
                llm_used=False,
                llm_model=llm.llm_model,
                llm_error=llm.llm_error,
            )
        return {
            "heuristic": heuristic,
            "llm": llm,
            "hybrid": hybrid,
        }

    def _evaluate_heuristics(
        self,
        principal: Principal,
        message: str,
        tool_call: ToolCall,
        history: list[dict],
    ) -> MonitorResult:
        lowered = message.lower()
        score = 0
        reasons: list[str] = []
        attack_type = "benign"

        if any(term in lowered for term in PROMPT_INJECTION_TERMS):
            score += 45
            reasons.append("Detected prompt-injection language that attempts to override system safeguards.")
            attack_type = "prompt_injection"

        if any(term in lowered for term in ROLE_IMPERSONATION_TERMS) and not self._is_identity_confirmation(principal, lowered):
            score += 20
            reasons.append("Detected social-engineering or role-impersonation language.")
            if attack_type == "benign":
                attack_type = "role_impersonation"

        if tool_call.scope == "bulk" or tool_call.tool == "export_records":
            score += 35
            reasons.append("Request targets multiple patient records or a broad export.")
            if attack_type == "benign":
                attack_type = "bulk_phi_exfiltration"

        if any(term in lowered for term in SENSITIVE_FIELD_TERMS) and not self._is_safe_self_service_contact_update(principal, tool_call):
            score += 25
            reasons.append("Request references sensitive patient identifiers or contact information.")
            if attack_type == "benign":
                attack_type = "sensitive_field_access"

        if any(term in lowered for term in SENSITIVE_INFERENCE_TERMS):
            score += 25
            reasons.append("Request appears to infer sensitive conditions or protected cohorts.")
            if attack_type == "benign":
                attack_type = "sensitive_inference"

        if tool_call.is_write:
            score += 10
            reasons.append("Request would modify medical or contact data.")
            if attack_type == "benign":
                attack_type = "record_modification"

        if tool_call.confidence < 0.45:
            score += 10
            reasons.append("Planner confidence is low, so intent ambiguity is elevated.")

        patient_access_risk, patient_access_reason, patient_attack_type = self._check_authorization(principal, tool_call)
        score += patient_access_risk
        if patient_access_reason:
            reasons.append(patient_access_reason)
        if patient_attack_type and self._should_override_attack_type(attack_type, patient_attack_type):
            attack_type = patient_attack_type

        if self._is_multi_turn_escalation(history, tool_call):
            score += 15
            reasons.append("Session behavior suggests escalation from normal queries toward broader access.")
            if attack_type == "benign":
                attack_type = "multi_turn_escalation"

        normalized_score = self._normalize_score(score)
        risk_level, recommended_action = self._map_score_to_decision(normalized_score, tool_call.is_write)
        if not reasons:
            reasons.append("No strong indicators of malicious or policy-violating behavior were detected.")

        return MonitorResult(
            risk_level=risk_level,
            score=normalized_score,
            attack_type=attack_type,
            reasons=reasons,
            recommended_action=recommended_action,
            source="heuristic",
            heuristic_score=normalized_score,
            llm_score=None,
            llm_used=False,
            llm_model=self.llm_classifier.model if self.llm_classifier.status().enabled else None,
            llm_error=None,
        )

    def _merge_results(self, heuristic: MonitorResult, llm_result: MonitorResult, llm_error: str | None) -> MonitorResult:
        risk_level = heuristic.risk_level if RISK_ORDER[heuristic.risk_level] >= RISK_ORDER[llm_result.risk_level] else llm_result.risk_level
        action = heuristic.recommended_action if ACTION_ORDER[heuristic.recommended_action] >= ACTION_ORDER[llm_result.recommended_action] else llm_result.recommended_action
        score = self._normalize_score(max(heuristic.score, llm_result.score))
        attack_type = llm_result.attack_type if RISK_ORDER[llm_result.risk_level] >= RISK_ORDER[heuristic.risk_level] else heuristic.attack_type

        reasons = list(dict.fromkeys(
            heuristic.reasons + [f"LLM classifier: {reason}" for reason in llm_result.reasons]
        ))

        return MonitorResult(
            risk_level=risk_level,
            score=score,
            attack_type=attack_type,
            reasons=reasons,
            recommended_action=action,
            source="hybrid",
            heuristic_score=heuristic.score,
            llm_score=self._normalize_score(llm_result.score),
            llm_used=True,
            llm_model=llm_result.llm_model,
            llm_error=llm_error,
        )

    @staticmethod
    def _llm_unavailable_result(error_message: str, model: str | None) -> MonitorResult:
        return MonitorResult(
            risk_level="high",
            score=100,
            attack_type="classifier_unavailable",
            reasons=["LLM classifier could not evaluate the prompt.", error_message],
            recommended_action="block_and_log",
            source="llm_unavailable",
            heuristic_score=None,
            llm_score=None,
            llm_used=False,
            llm_model=model,
            llm_error=error_message,
        )

    @staticmethod
    def _map_score_to_decision(score: int, is_write: bool) -> tuple[str, str]:
        if score >= 70:
            return "critical", "block_and_alert"
        if score >= 40:
            return "high", "block_and_log" if not is_write else "require_reauthentication"
        if score >= 20:
            return "medium", "allow_with_logging"
        return "low", "allow"

    @staticmethod
    def _normalize_score(score: int | float) -> int:
        return max(0, min(100, int(round(score))))

    @staticmethod
    def _check_authorization(principal: Principal, tool_call: ToolCall) -> tuple[int, str, str | None]:
        patient_id = tool_call.target_patient_id
        if tool_call.tool == "conversation":
            return 0, "", None

        if principal.role == "admin":
            return 0, "", None

        if tool_call.tool == "export_records":
            if principal.role != "admin":
                return 40, "Only administrative users can export records, and broad export remains highly sensitive.", "bulk_phi_exfiltration"
            return 0, "", None

        if tool_call.scope == "bulk" and principal.role not in {"admin", "physician"}:
            return 35, "Bulk cohort queries are not authorized for this role.", "bulk_phi_exfiltration"

        if principal.role == "anonymous":
            return 55, "Anonymous users are not permitted to access or modify patient records.", "unauthorized_access"

        if principal.role == "patient":
            if patient_id and patient_id != principal.linked_patient_id:
                return 55, "Patient users may only access their own record.", "unauthorized_access"
            if tool_call.is_write and tool_call.tool != "update_contact_info":
                return 35, "Patient users cannot directly modify clinical data.", "unauthorized_modification"
            return 0, "", None

        if principal.role == "nurse":
            if patient_id and principal.authorized_patients and patient_id not in principal.authorized_patients:
                return 40, "Requested patient is outside the nurse's assigned panel.", "unauthorized_access"
            if tool_call.tool == "update_allergy":
                return 45, "Nurses are not authorized to modify allergy lists in this prototype.", "unauthorized_modification"
            return 0, "", None

        if principal.role == "physician":
            if patient_id and principal.authorized_patients and patient_id not in principal.authorized_patients:
                return 20, "Requested patient falls outside the physician's assigned panel.", "unauthorized_access"
            return 0, "", None

        return 20, "Role policy could not be matched confidently.", "unauthorized_access"

    @staticmethod
    def _is_multi_turn_escalation(history: list[dict], tool_call: ToolCall) -> bool:
        if len(history) < 2:
            return False
        previous_single_record_requests = sum(1 for event in history[-3:] if event.get("tool") in {"get_patient_summary", "get_lab_results", "get_medications"})
        return previous_single_record_requests >= 2 and tool_call.scope == "bulk"

    @staticmethod
    def _should_override_attack_type(current: str, proposed: str) -> bool:
        if current == "benign":
            return True
        if current == "record_modification" and proposed == "unauthorized_modification":
            return True
        if current == "sensitive_field_access" and proposed == "unauthorized_access":
            return True
        return False

    @staticmethod
    def _is_safe_self_service_contact_update(principal: Principal, tool_call: ToolCall) -> bool:
        return (
            principal.role == "patient"
            and tool_call.tool == "update_contact_info"
            and tool_call.target_patient_id == principal.linked_patient_id
        )

    @staticmethod
    def _is_identity_confirmation(principal: Principal, lowered_message: str) -> bool:
        return ChatbotPlanner._matches_selected_identity(lowered_message, principal)
