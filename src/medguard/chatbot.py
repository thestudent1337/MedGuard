from __future__ import annotations

import re
from datetime import date, timedelta

from .models import Principal, ToolCall
from .store import FakeEHRStore


ALLERGY_TERMS = [
    "penicillin",
    "latex",
    "sulfa",
    "peanuts",
    "shellfish",
    "none known",
]

LAB_TERMS = [
    "a1c",
    "cholesterol",
    "ldl",
    "triglycerides",
    "creatinine",
    "egfr",
    "potassium",
    "hemoglobin",
    "ferritin",
    "tsh",
]

CONDITION_TERMS = [
    "diabetes",
    "hypertension",
    "asthma",
    "cancer",
    "hiv",
    "pregnant",
    "pregnancy",
    "anxiety",
    "kidney",
    "oncology",
]

MEDICATION_TERMS = [
    "metformin",
    "lisinopril",
    "atorvastatin",
    "albuterol",
    "sertraline",
    "sumatriptan",
    "losartan",
    "ferrous",
    "antiretroviral",
]

CONTACT_FIELD_TERMS = ["phone", "address", "email", "contact", "number"]
CONTACT_UPDATE_TERMS = ["update", "change", "set", "replace", "correct", "fix", "edit", "new"]
ALLERGY_UPDATE_TERMS = ["remove", "delete", "clear", "add", "update", "set"]
SCHEDULE_TERMS = ["schedule", "appointment", "follow-up", "follow up", "book", "arrange"]
LAB_REQUEST_TERMS = ["lab", "labs", "bloodwork", "blood work", "results", "test result", "panel"]
MEDICATION_REQUEST_TERMS = ["medication", "medications", "taking", "prescribed", "meds", "drugs", "prescriptions"]
SUMMARY_REQUEST_TERMS = ["summary", "record", "diagnosis", "diagnoses", "note", "history", "allergies", "chart", "overview"]
COHORT_SUMMARY_TERMS = ["cohort summary", "panel summary", "population summary", "overview", "panel", "count", "how many", "roster"]
GREETING_TERMS = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]
HELP_TERMS = ["help", "what can you do", "how can you help", "what can i ask", "capabilities"]
IDENTITY_PATTERNS = [
    r"\bi am dr\.?\s+([a-z]+(?:\s+[a-z]+)?)\b",
    r"\bi'm dr\.?\s+([a-z]+(?:\s+[a-z]+)?)\b",
    r"\bi am nurse\s+([a-z]+(?:\s+[a-z]+)?)\b",
    r"\bi'm nurse\s+([a-z]+(?:\s+[a-z]+)?)\b",
    r"\bthis is dr\.?\s+([a-z]+(?:\s+[a-z]+)?)\b",
]
FOLLOWUP_REFERENCE_TERMS = ["she", "her", "he", "him", "they", "them", "that patient", "this patient"]


class ChatbotPlanner:
    def __init__(self, store: FakeEHRStore) -> None:
        self.store = store

    def plan(self, message: str, principal: Principal, history: list[dict]) -> ToolCall:
        lowered = message.lower()
        patient = self._resolve_patient(message, principal, history)

        if any(term in lowered for term in ["dump", "export", "entire database", "all records", "every patient record", "reveal all records", "download all patient data"]):
            return ToolCall(
                tool="export_records",
                raw_message=message,
                scope="bulk",
                requested_fields=["full_record"],
                confidence=0.98,
                planner_notes=["Matched broad export language.", "This is a bulk data access pattern."],
            )

        if self._looks_like_bulk_request(lowered):
            medication = self._extract_known_term(lowered, MEDICATION_TERMS)
            condition = self._extract_known_term(lowered, CONDITION_TERMS)
            comparator, threshold = self._extract_numeric_filter(lowered)
            lab_name = self._extract_known_term(lowered, LAB_TERMS)
            if condition and lab_name and threshold is not None:
                return ToolCall(
                    tool="list_patients_by_condition_and_lab",
                    raw_message=message,
                    scope="bulk",
                    filters={
                        "condition": condition,
                        "lab_name": lab_name,
                        "comparator": comparator,
                        "threshold": threshold,
                    },
                    requested_fields=["patient_name", "diagnoses", "labs"],
                    confidence=0.9,
                    planner_notes=[f"Matched cohort query for {condition} plus {lab_name} {comparator} {threshold}."],
                )
            if condition and any(term in lowered for term in COHORT_SUMMARY_TERMS):
                return ToolCall(
                    tool="summarize_condition_cohort",
                    raw_message=message,
                    scope="bulk",
                    filters={"condition": condition},
                    requested_fields=["patient_name", "diagnoses", "appointments"],
                    confidence=0.86,
                    planner_notes=[f"Matched cohort summary request for condition: {condition}."],
                )
            if medication:
                return ToolCall(
                    tool="list_patients_by_medication",
                    raw_message=message,
                    scope="bulk",
                    filters={"medication": medication},
                    requested_fields=["patient_name", "medications"],
                    confidence=0.88,
                    planner_notes=[f"Matched bulk cohort query by medication: {medication}."],
                )
            if condition:
                return ToolCall(
                    tool="list_patients_by_condition",
                    raw_message=message,
                    scope="bulk",
                    filters={"condition": condition},
                    requested_fields=["patient_name", "diagnoses"],
                    confidence=0.88,
                    planner_notes=[f"Matched bulk cohort query by condition: {condition}."],
                )
            cohort_phrase = self._extract_phrase_after_patterns(lowered, ["patients with", "who has", "who have", "everyone with", "all patients with", "find patients with"])
            if cohort_phrase:
                return ToolCall(
                    tool="list_patients_by_condition",
                    raw_message=message,
                    scope="bulk",
                    filters={"condition": cohort_phrase},
                    requested_fields=["patient_name", "diagnoses"],
                    confidence=0.7,
                    planner_notes=[f"Matched generalized cohort query phrase: {cohort_phrase}."],
                )

        if any(term in lowered for term in CONTACT_FIELD_TERMS) and any(term in lowered for term in CONTACT_UPDATE_TERMS):
            updates = self._extract_contact_updates(message)
            return ToolCall(
                tool="update_contact_info",
                raw_message=message,
                target_patient_id=patient["id"] if patient else None,
                requested_fields=list(updates.keys()),
                updates=updates,
                is_write=True,
                confidence=0.82,
                planner_notes=["Detected contact-field update request.", f"Resolved target patient: {patient['id'] if patient else 'none'}."],
            )

        if ("allergy" in lowered or "allergies" in lowered) and any(term in lowered for term in ALLERGY_UPDATE_TERMS):
            allergy_name = self._extract_known_term(lowered, ALLERGY_TERMS) or self._extract_allergy_phrase(lowered)
            action = "remove" if any(term in lowered for term in ["remove", "delete", "clear"]) else "add"
            return ToolCall(
                tool="update_allergy",
                raw_message=message,
                target_patient_id=patient["id"] if patient else None,
                requested_fields=["allergies"],
                updates={"action": action, "allergy": allergy_name or "unspecified allergy"},
                is_write=True,
                confidence=0.86,
                planner_notes=[f"Detected allergy {action} request.", f"Resolved target patient: {patient['id'] if patient else 'none'}."],
            )

        if any(term in lowered for term in SCHEDULE_TERMS):
            appointment_date = self._extract_date(lowered) or str(date.today() + timedelta(days=14))
            visit_type = "Follow-up visit"
            if "nephrology" in lowered:
                visit_type = "Nephrology follow-up"
            elif "primary care" in lowered:
                visit_type = "Primary care follow-up"
            elif "neurology" in lowered:
                visit_type = "Neurology follow-up"
            return ToolCall(
                tool="schedule_followup",
                raw_message=message,
                target_patient_id=patient["id"] if patient else None,
                requested_fields=["appointments"],
                updates={"date": appointment_date, "type": visit_type},
                is_write=True,
                confidence=0.8,
                planner_notes=[f"Detected scheduling request for {appointment_date}.", f"Resolved target patient: {patient['id'] if patient else 'none'}."],
            )

        if any(term in lowered for term in LAB_REQUEST_TERMS) or any(term in lowered for term in LAB_TERMS):
            lab_name = self._extract_known_term(lowered, LAB_TERMS)
            return ToolCall(
                tool="get_lab_results",
                raw_message=message,
                target_patient_id=patient["id"] if patient else None,
                requested_fields=["labs"],
                filters={"lab_name": lab_name},
                confidence=0.84,
                planner_notes=[f"Detected lab retrieval request{f' for {lab_name}' if lab_name else ''}.", f"Resolved target patient: {patient['id'] if patient else 'none'}."],
            )

        if any(term in lowered for term in MEDICATION_REQUEST_TERMS):
            return ToolCall(
                tool="get_medications",
                raw_message=message,
                target_patient_id=patient["id"] if patient else None,
                requested_fields=["medications"],
                confidence=0.78,
                planner_notes=["Detected medication lookup request.", f"Resolved target patient: {patient['id'] if patient else 'none'}."],
            )

        if patient or any(term in lowered for term in SUMMARY_REQUEST_TERMS):
            return ToolCall(
                tool="get_patient_summary",
                raw_message=message,
                target_patient_id=patient["id"] if patient else None,
                requested_fields=["summary"],
                confidence=0.75,
                planner_notes=["Using summary fallback.", f"Resolved target patient: {patient['id'] if patient else 'none'}."],
            )

        if self._is_conversational_turn(lowered, patient, principal):
            return ToolCall(
                tool="conversation",
                raw_message=message,
                scope="conversation",
                confidence=0.92,
                filters={"conversation_type": self._classify_conversation_type(lowered, principal)},
                planner_notes=["Detected a conversational turn that does not require protected data access."],
            )

        return ToolCall(
            tool="unknown",
            raw_message=message,
            requested_fields=[],
            confidence=0.25,
            planner_notes=["No supported intent pattern matched."],
        )

    def execute(self, tool_call: ToolCall, redact: bool = False) -> str:
        tool = tool_call.tool

        if tool == "conversation":
            conversation_type = tool_call.filters.get("conversation_type", "general")
            if conversation_type == "identity_confirmation":
                return (
                    "The user is confirming the identity already selected for this session. "
                    "Acknowledge them briefly, note that no patient data has been accessed yet, and invite the next healthcare task."
                )
            if conversation_type == "capability":
                return (
                    "No protected data access was requested. Briefly describe the supported tasks: patient summaries, lab lookups, medication lookups, scheduling, contact updates, and physician cohort queries."
                )
            return "No protected data access was requested. Reply conversationally, briefly, and invite the user's next healthcare task."

        if tool == "unknown":
            return "I could not map that request to a supported healthcare task. Try asking for a patient summary, labs, medications, scheduling, or a contact update."

        if tool_call.target_patient_id is None and tool not in {
            "export_records",
            "list_patients_by_condition",
            "list_patients_by_medication",
            "summarize_condition_cohort",
            "list_patients_by_condition_and_lab",
        }:
            return "I need a valid patient reference before I can act on that request."

        if tool == "get_patient_summary":
            summary = self.store.get_patient_summary(tool_call.target_patient_id)
            if not summary:
                return "I could not find that patient record."
            if redact:
                return f"{summary['name']}: diagnoses {', '.join(summary['diagnoses'])}. Sensitive details were redacted pending authorization."
            return (
                f"{summary['name']} ({summary['id']}) has diagnoses of {', '.join(summary['diagnoses'])}. "
                f"Current medications: {', '.join(summary['medications'])}. Allergies: {', '.join(summary['allergies'])}. "
                f"Next appointment: {summary['upcoming_appointments'][-1]['date']}."
            )

        if tool == "get_lab_results":
            lab_name = tool_call.filters.get("lab_name")
            labs = self.store.get_lab_results(tool_call.target_patient_id, lab_name)
            if not labs:
                return "No lab results were found for that patient."
            if redact:
                return f"I found {len(labs)} lab result entries, but exact values were redacted pending authorization."
            lab_lines = [f"{lab['name']}: {lab['value']} {lab['unit']} on {lab['date']}" for lab in labs]
            return "Latest lab results:\n- " + "\n- ".join(lab_lines)

        if tool == "get_medications":
            medications = self.store.get_medications(tool_call.target_patient_id)
            if not medications:
                return "No medications were found for that patient."
            return "Current medications: " + ", ".join(medications)

        if tool == "update_contact_info":
            updated_contact = self.store.update_contact(tool_call.target_patient_id, tool_call.updates)
            if not updated_contact:
                return "I could not update contact information because the patient was not found."
            return "Updated contact information for the patient."

        if tool == "update_allergy":
            allergies = self.store.update_allergy(
                tool_call.target_patient_id,
                tool_call.updates.get("action", "add"),
                tool_call.updates.get("allergy", ""),
            )
            if allergies is None:
                return "I could not update the allergy list because the patient was not found."
            return "Updated allergy list: " + ", ".join(allergies)

        if tool == "schedule_followup":
            appointment = self.store.schedule_followup(
                tool_call.target_patient_id,
                tool_call.updates.get("date", str(date.today() + timedelta(days=14))),
                tool_call.updates.get("type", "Follow-up visit"),
            )
            if not appointment:
                return "I could not schedule the appointment because the patient was not found."
            return f"Scheduled {appointment['type']} on {appointment['date']}."

        if tool == "list_patients_by_condition":
            matches = self.store.list_patients_by_condition(tool_call.filters.get("condition", ""))
            if not matches:
                return "No patients matched that condition filter."
            if redact:
                return f"{len(matches)} patient records matched the filter, but identities were redacted."
            return "Matching patients:\n- " + "\n- ".join(f"{item['name']} ({item['id']})" for item in matches)

        if tool == "list_patients_by_medication":
            matches = self.store.list_patients_by_medication(tool_call.filters.get("medication", ""))
            if not matches:
                return "No patients matched that medication filter."
            if redact:
                return f"{len(matches)} patient records matched the medication filter, but identities were redacted."
            return "Matching patients:\n- " + "\n- ".join(f"{item['name']} ({item['id']})" for item in matches)

        if tool == "summarize_condition_cohort":
            summary = self.store.summarize_condition_cohort(tool_call.filters.get("condition", ""))
            if not summary["count"]:
                return "No patients matched that condition summary request."
            if redact:
                return f"{summary['count']} patient records matched the cohort summary request, but identities were redacted."
            patient_names = ", ".join(patient["name"] for patient in summary["patients"])
            next_visits = [
                f"{item['name']}: {item['next_appointment']['date']} ({item['next_appointment']['type']})"
                for item in summary["appointments"]
                if item["next_appointment"]
            ]
            response = f"Cohort summary for {summary['condition']}: {summary['count']} matched patients. Patients: {patient_names}."
            if next_visits:
                response += " Upcoming visits: " + "; ".join(next_visits)
            return response

        if tool == "list_patients_by_condition_and_lab":
            matches = self.store.list_patients_by_condition_and_lab(
                tool_call.filters.get("condition", ""),
                tool_call.filters.get("lab_name", ""),
                tool_call.filters.get("comparator", ">="),
                float(tool_call.filters.get("threshold", 0)),
            )
            if not matches:
                return "No patients matched that combined condition and lab filter."
            if redact:
                return f"{len(matches)} patient records matched the combined cohort filter, but identities were redacted."
            return "Matching patients:\n- " + "\n- ".join(
                f"{item['name']} ({item['id']}): {item['matched_lab']['name']} {item['matched_lab']['value']} {item['matched_lab']['unit']} on {item['matched_lab']['date']}"
                for item in matches
            )

        if tool == "export_records":
            records = self.store.export_records()
            if redact:
                return f"{len(records)} records were identified, but full export was redacted pending authorization."
            return f"Exported {len(records)} full patient records."

        return "The request was recognized, but no execution path is implemented."

    def _resolve_patient(self, message: str, principal: Principal, history: list[dict]) -> dict | None:
        direct = self._resolve_patient_without_history(message, principal)
        if direct:
            return direct
        if self._contains_followup_reference(message):
            prior_patient = self._resolve_patient_from_history(history, principal)
            if prior_patient:
                return prior_patient

        return None

    def _resolve_patient_from_history(self, history: list[dict], principal: Principal) -> dict | None:
        for event in reversed(history):
            resolved = self._resolve_patient_without_history(event.get("message", ""), principal)
            if resolved:
                return resolved
        return None

    def _resolve_patient_without_history(self, message: str, principal: Principal) -> dict | None:
        by_name = self.store.find_patient_by_name(message)
        if by_name:
            return by_name

        partial = self._resolve_patient_by_partial_name(message)
        if partial:
            return partial

        id_match = re.search(r"\bpatient\s+(P?\d{4})\b|\b(P\d{4})\b", message, re.IGNORECASE)
        if id_match:
            patient_id = (id_match.group(1) or id_match.group(2)).upper()
            if not patient_id.startswith("P"):
                patient_id = f"P{patient_id}"
            return self.store.get_patient(patient_id)

        if principal.role == "patient" and principal.linked_patient_id and re.search(r"\bmy\b", message, re.IGNORECASE):
            return self.store.get_patient(principal.linked_patient_id)

        return None

    def _resolve_patient_by_partial_name(self, message: str) -> dict | None:
        lowered = message.lower()
        best_match = None
        best_score = 0
        for patient in self.store.list_patients():
            parts = [part for part in patient["name"].lower().split() if len(part) >= 3]
            score = sum(1 for part in parts if re.search(rf"\b{re.escape(part)}\b", lowered))
            if score > best_score:
                best_score = score
                best_match = patient
        return best_match if best_score >= 1 else None

    def _is_conversational_turn(self, lowered: str, patient: dict | None, principal: Principal) -> bool:
        if self._matches_selected_identity(lowered, principal):
            return True
        if patient:
            return False
        if self._contains_phrase(lowered, GREETING_TERMS):
            return True
        if self._contains_phrase(lowered, HELP_TERMS):
            return True
        if any(re.search(pattern, lowered) for pattern in IDENTITY_PATTERNS):
            return True
        if len(lowered.split()) <= 8 and not any(char.isdigit() for char in lowered):
            if not self._looks_like_bulk_request(lowered) and not any(term in lowered for term in CONTACT_UPDATE_TERMS + ALLERGY_UPDATE_TERMS + SCHEDULE_TERMS + LAB_REQUEST_TERMS + MEDICATION_REQUEST_TERMS + SUMMARY_REQUEST_TERMS):
                return True
        return False

    @staticmethod
    def _classify_conversation_type(lowered: str, principal: Principal) -> str:
        if ChatbotPlanner._contains_phrase(lowered, HELP_TERMS):
            return "capability"
        if ChatbotPlanner._matches_selected_identity(lowered, principal):
            return "identity_confirmation"
        if ChatbotPlanner._contains_phrase(lowered, GREETING_TERMS):
            return "greeting"
        return "general"

    @staticmethod
    def _matches_selected_identity(text: str, principal: Principal) -> bool:
        normalized_text = re.sub(r"[^a-z\s]", " ", text.lower())
        normalized_name = re.sub(r"[^a-z\s]", " ", principal.name.lower())
        tokens = [token for token in normalized_name.split() if len(token) >= 3]
        return bool(tokens) and all(token in normalized_text for token in tokens)

    @staticmethod
    def _contains_followup_reference(text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in FOLLOWUP_REFERENCE_TERMS)

    @staticmethod
    def _contains_phrase(text: str, phrases: list[str]) -> bool:
        return any(re.search(rf"\b{re.escape(phrase)}\b", text) for phrase in phrases)

    @staticmethod
    def _extract_known_term(text: str, terms: list[str]) -> str | None:
        for term in terms:
            if term in text:
                return term
        return None

    @staticmethod
    def _extract_date(text: str) -> str | None:
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        return match.group(1) if match else None

    @staticmethod
    def _extract_contact_updates(message: str) -> dict[str, str]:
        updates: dict[str, str] = {}

        phone_match = re.search(r"(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})", message)
        if phone_match:
            updates["phone"] = phone_match.group(1)

        email_match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", message)
        if email_match:
            updates["email"] = email_match.group(1)

        address_match = re.search(r"address(?:\s+to|\s+as)?\s+(.+)$", message, re.IGNORECASE)
        if address_match and "@" not in address_match.group(1):
            updates["address"] = address_match.group(1).strip(" .")

        return updates or {"contact_note": "Requested contact change"}

    @staticmethod
    def _extract_allergy_phrase(text: str) -> str | None:
        match = re.search(r"(?:remove|delete|clear|add|set|update)\s+the\s+(.+?)\s+allergy", text)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _looks_like_bulk_request(text: str) -> bool:
        bulk_patterns = [
            "all patients",
            "patients with",
            "patients have",
            "how many patients",
            "everyone with",
            "which patients",
            "who has",
            "who have",
            "list patients",
            "show patients",
            "find patients",
            "cohort",
            "panel",
        ]
        return any(pattern in text for pattern in bulk_patterns)

    @staticmethod
    def _extract_phrase_after_patterns(text: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            if pattern in text:
                phrase = text.split(pattern, 1)[1].strip(" ?.!,")
                if phrase:
                    return phrase
        return None

    @staticmethod
    def _extract_numeric_filter(text: str) -> tuple[str, float | None]:
        patterns = [
            (r"(?:above|over|greater than)\s+(\d+(?:\.\d+)?)", ">"),
            (r"(?:at least|>=)\s+(\d+(?:\.\d+)?)", ">="),
            (r"(?:below|under|less than)\s+(\d+(?:\.\d+)?)", "<"),
            (r"(?:at most|<=)\s+(\d+(?:\.\d+)?)", "<="),
            (r"=\s*(\d+(?:\.\d+)?)", "="),
        ]
        for pattern, comparator in patterns:
            match = re.search(pattern, text)
            if match:
                return comparator, float(match.group(1))
        return ">=", None
