from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class FakeEHRStore:
    def __init__(self, database_path: str | Path = ":memory:", data_path: Path | None = None) -> None:
        base_path = Path(__file__).resolve().parent
        self._data_path = data_path or (base_path / "data" / "patients.json")
        self._database_path = str(database_path)
        self._connection = sqlite3.connect(self._database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()
        self._seed_if_empty()

    @property
    def database_path(self) -> str:
        return self._database_path

    def close(self) -> None:
        if getattr(self, "_connection", None) is not None:
            self._connection.close()
            self._connection = None

    def __del__(self) -> None:
        self.close()

    def reset(self) -> None:
        cursor = self._connection.cursor()
        for table in [
            "session_events",
            "incidents",
            "notes",
            "appointments",
            "labs",
            "allergies",
            "medications",
            "diagnoses",
            "patients",
        ]:
            cursor.execute(f"DELETE FROM {table}")
        self._connection.commit()
        self._seed_if_empty()

    def list_patients(self) -> list[dict]:
        cursor = self._connection.execute("SELECT id FROM patients ORDER BY id")
        return [self.get_patient(row["id"]) for row in cursor.fetchall()]

    def get_patient(self, patient_id: str) -> dict | None:
        row = self._connection.execute(
            """
            SELECT id, name, dob, gender, contact_phone, contact_email, contact_address
            FROM patients
            WHERE LOWER(id) = LOWER(?)
            """,
            (patient_id,),
        ).fetchone()
        if not row:
            return None
        return self._assemble_patient(row["id"], row)

    def find_patient_by_name(self, text: str) -> dict | None:
        lowered = text.lower()
        cursor = self._connection.execute("SELECT id, name FROM patients")
        for row in cursor.fetchall():
            if row["name"].lower() in lowered:
                return self.get_patient(row["id"])
        return None

    def get_patient_summary(self, patient_id: str) -> dict | None:
        patient = self.get_patient(patient_id)
        if not patient:
            return None
        return {
            "id": patient["id"],
            "name": patient["name"],
            "dob": patient["dob"],
            "diagnoses": list(patient["diagnoses"]),
            "medications": list(patient["medications"]),
            "allergies": list(patient["allergies"]),
            "upcoming_appointments": list(patient["appointments"]),
            "latest_note": patient["notes"][-1] if patient["notes"] else "",
        }

    def get_lab_results(self, patient_id: str, lab_name: str | None = None) -> list[dict]:
        query = "SELECT name, value, unit, date FROM labs WHERE patient_id = ?"
        params: list[str] = [patient_id]
        if lab_name:
            query += " AND LOWER(name) LIKE ?"
            params.append(f"%{lab_name.lower()}%")
        query += " ORDER BY date DESC, id DESC"
        rows = self._connection.execute(query, tuple(params)).fetchall()
        if rows:
            return [dict(row) for row in rows]
        if lab_name:
            fallback_rows = self._connection.execute(
                "SELECT name, value, unit, date FROM labs WHERE patient_id = ? ORDER BY date DESC, id DESC",
                (patient_id,),
            ).fetchall()
            return [dict(row) for row in fallback_rows]
        return []

    def get_medications(self, patient_id: str) -> list[str]:
        rows = self._connection.execute(
            "SELECT medication FROM medications WHERE patient_id = ? ORDER BY id",
            (patient_id,),
        ).fetchall()
        return [row["medication"] for row in rows]

    def update_contact(self, patient_id: str, updates: dict[str, str]) -> dict | None:
        patient = self.get_patient(patient_id)
        if not patient:
            return None
        merged = dict(patient["contact"])
        merged.update(updates)
        self._connection.execute(
            """
            UPDATE patients
            SET contact_phone = ?, contact_email = ?, contact_address = ?
            WHERE id = ?
            """,
            (
                merged.get("phone", patient["contact"]["phone"]),
                merged.get("email", patient["contact"]["email"]),
                merged.get("address", patient["contact"]["address"]),
                patient_id,
            ),
        )
        self._connection.commit()
        return self.get_patient(patient_id)["contact"]

    def update_allergy(self, patient_id: str, action: str, allergy: str) -> list[str] | None:
        patient = self.get_patient(patient_id)
        if not patient:
            return None
        normalized = allergy.strip()
        if not normalized:
            return list(patient["allergies"])

        if action == "remove":
            self._connection.execute(
                "DELETE FROM allergies WHERE patient_id = ? AND LOWER(allergy) = LOWER(?)",
                (patient_id, normalized),
            )
        elif action == "add":
            exists = self._connection.execute(
                "SELECT 1 FROM allergies WHERE patient_id = ? AND LOWER(allergy) = LOWER(?)",
                (patient_id, normalized),
            ).fetchone()
            if not exists:
                self._connection.execute(
                    "INSERT INTO allergies(patient_id, allergy) VALUES(?, ?)",
                    (patient_id, normalized),
                )
        self._connection.commit()
        return self._fetch_simple_list("allergies", "allergy", patient_id)

    def schedule_followup(self, patient_id: str, date: str, visit_type: str = "Follow-up visit") -> dict | None:
        if not self.get_patient(patient_id):
            return None
        self._connection.execute(
            "INSERT INTO appointments(patient_id, date, type, clinician) VALUES(?, ?, ?, ?)",
            (patient_id, date, visit_type, "Assigned clinician"),
        )
        self._connection.commit()
        row = self._connection.execute(
            """
            SELECT date, type, clinician
            FROM appointments
            WHERE patient_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (patient_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_patients_by_condition(self, condition: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT DISTINCT p.id, p.name
            FROM patients p
            JOIN diagnoses d ON d.patient_id = p.id
            WHERE LOWER(d.diagnosis) LIKE ?
            ORDER BY p.id
            """,
            (f"%{condition.lower()}%",),
        ).fetchall()
        return [{"id": row["id"], "name": row["name"], "diagnoses": self._fetch_simple_list("diagnoses", "diagnosis", row["id"])} for row in rows]

    def list_patients_by_medication(self, medication: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT DISTINCT p.id, p.name
            FROM patients p
            JOIN medications m ON m.patient_id = p.id
            WHERE LOWER(m.medication) LIKE ?
            ORDER BY p.id
            """,
            (f"%{medication.lower()}%",),
        ).fetchall()
        return [{"id": row["id"], "name": row["name"], "medications": self._fetch_simple_list("medications", "medication", row["id"])} for row in rows]

    def summarize_condition_cohort(self, condition: str) -> dict:
        matches = self.list_patients_by_condition(condition)
        appointments = []
        for patient in matches:
            next_visit = self._connection.execute(
                """
                SELECT date, type, clinician
                FROM appointments
                WHERE patient_id = ?
                ORDER BY date ASC, id ASC
                LIMIT 1
                """,
                (patient["id"],),
            ).fetchone()
            appointments.append(
                {
                    "patient_id": patient["id"],
                    "name": patient["name"],
                    "next_appointment": dict(next_visit) if next_visit else None,
                }
            )
        return {
            "condition": condition,
            "count": len(matches),
            "patients": matches,
            "appointments": appointments,
        }

    def list_patients_by_condition_and_lab(
        self,
        condition: str,
        lab_name: str,
        comparator: str,
        threshold: float,
    ) -> list[dict]:
        allowed_comparators = {">", ">=", "<", "<=", "="}
        normalized_comparator = comparator if comparator in allowed_comparators else ">="
        rows = self._connection.execute(
            f"""
            SELECT p.id, p.name, l.name AS lab_name, l.value, l.unit, l.date
            FROM patients p
            JOIN diagnoses d ON d.patient_id = p.id
            JOIN labs l ON l.patient_id = p.id
            WHERE LOWER(d.diagnosis) LIKE ?
              AND LOWER(l.name) LIKE ?
              AND CAST(l.value AS REAL) {normalized_comparator} ?
            ORDER BY p.id ASC, l.date DESC, l.id DESC
            """,
            (f"%{condition.lower()}%", f"%{lab_name.lower()}%", threshold),
        ).fetchall()
        matches_by_patient: dict[str, dict] = {}
        for row in rows:
            if row["id"] in matches_by_patient:
                continue
            matches_by_patient[row["id"]] = {
                "id": row["id"],
                "name": row["name"],
                "diagnoses": self._fetch_simple_list("diagnoses", "diagnosis", row["id"]),
                "matched_lab": {
                    "name": row["lab_name"],
                    "value": row["value"],
                    "unit": row["unit"],
                    "date": row["date"],
                    "comparator": normalized_comparator,
                    "threshold": threshold,
                },
            }
        return list(matches_by_patient.values())

    def export_records(self) -> list[dict]:
        return self.list_patients()

    def append_session_event(self, session_id: str, actor: str, message: str, tool: str, decision: str, outcome: str) -> None:
        self._connection.execute(
            """
            INSERT INTO session_events(session_id, actor, message, tool, decision, outcome)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (session_id, actor, message, tool, decision, outcome),
        )
        self._connection.commit()

    def list_session_history(self, session_id: str, descending: bool = False) -> list[dict]:
        order = "DESC" if descending else "ASC"
        rows = self._connection.execute(
            f"""
            SELECT actor, message, tool, decision, outcome
            FROM session_events
            WHERE session_id = ?
            ORDER BY id {order}
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def log_incident(self, incident: dict) -> None:
        self._connection.execute(
            """
            INSERT INTO incidents(timestamp, session_id, principal_json, message, tool_call_json, monitor_result_json, policy_decision_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident["timestamp"],
                incident["session_id"],
                json.dumps(incident["principal"]),
                incident["message"],
                json.dumps(incident["tool_call"]),
                json.dumps(incident["monitor_result"]),
                json.dumps(incident["policy_decision"]),
            ),
        )
        self._connection.commit()

    def list_incidents(self, limit: int = 20) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT timestamp, session_id, principal_json, message, tool_call_json, monitor_result_json, policy_decision_json
            FROM incidents
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        incidents = []
        for row in rows:
            incidents.append(
                {
                    "timestamp": row["timestamp"],
                    "session_id": row["session_id"],
                    "principal": json.loads(row["principal_json"]),
                    "message": row["message"],
                    "tool_call": json.loads(row["tool_call_json"]),
                    "monitor_result": json.loads(row["monitor_result_json"]),
                    "policy_decision": json.loads(row["policy_decision_json"]),
                }
            )
        return incidents

    def incident_stats(self) -> dict:
        rows = self._connection.execute(
            """
            SELECT monitor_result_json, policy_decision_json
            FROM incidents
            ORDER BY id DESC
            """
        ).fetchall()
        counts_by_risk: dict[str, int] = {}
        counts_by_action: dict[str, int] = {}
        for row in rows:
            monitor = json.loads(row["monitor_result_json"])
            policy = json.loads(row["policy_decision_json"])
            counts_by_risk[monitor["risk_level"]] = counts_by_risk.get(monitor["risk_level"], 0) + 1
            counts_by_action[policy["action"]] = counts_by_action.get(policy["action"], 0) + 1
        return {
            "total": len(rows),
            "counts_by_risk": counts_by_risk,
            "counts_by_action": counts_by_action,
        }

    def _initialize_schema(self) -> None:
        cursor = self._connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dob TEXT NOT NULL,
                gender TEXT NOT NULL,
                contact_phone TEXT,
                contact_email TEXT,
                contact_address TEXT
            );

            CREATE TABLE IF NOT EXISTS diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                diagnosis TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                medication TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS allergies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                allergy TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS labs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                unit TEXT NOT NULL,
                date TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                clinician TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                note TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS session_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                message TEXT NOT NULL,
                tool TEXT NOT NULL,
                decision TEXT NOT NULL,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                principal_json TEXT NOT NULL,
                message TEXT NOT NULL,
                tool_call_json TEXT NOT NULL,
                monitor_result_json TEXT NOT NULL,
                policy_decision_json TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    def _seed_if_empty(self) -> None:
        existing = self._connection.execute("SELECT COUNT(*) AS count FROM patients").fetchone()["count"]
        if existing:
            return
        dataset = json.loads(self._data_path.read_text(encoding="utf-8"))
        for patient in dataset:
            self._connection.execute(
                """
                INSERT INTO patients(id, name, dob, gender, contact_phone, contact_email, contact_address)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patient["id"],
                    patient["name"],
                    patient["dob"],
                    patient["gender"],
                    patient["contact"]["phone"],
                    patient["contact"]["email"],
                    patient["contact"]["address"],
                ),
            )
            for diagnosis in patient["diagnoses"]:
                self._connection.execute("INSERT INTO diagnoses(patient_id, diagnosis) VALUES(?, ?)", (patient["id"], diagnosis))
            for medication in patient["medications"]:
                self._connection.execute("INSERT INTO medications(patient_id, medication) VALUES(?, ?)", (patient["id"], medication))
            for allergy in patient["allergies"]:
                self._connection.execute("INSERT INTO allergies(patient_id, allergy) VALUES(?, ?)", (patient["id"], allergy))
            for lab in patient["labs"]:
                self._connection.execute(
                    "INSERT INTO labs(patient_id, name, value, unit, date) VALUES(?, ?, ?, ?, ?)",
                    (patient["id"], lab["name"], lab["value"], lab["unit"], lab["date"]),
                )
            for appointment in patient["appointments"]:
                self._connection.execute(
                    "INSERT INTO appointments(patient_id, date, type, clinician) VALUES(?, ?, ?, ?)",
                    (patient["id"], appointment["date"], appointment["type"], appointment["clinician"]),
                )
            for note in patient["notes"]:
                self._connection.execute("INSERT INTO notes(patient_id, note) VALUES(?, ?)", (patient["id"], note))
        self._connection.commit()

    def _assemble_patient(self, patient_id: str, row: sqlite3.Row | None = None) -> dict:
        base = row or self._connection.execute(
            """
            SELECT id, name, dob, gender, contact_phone, contact_email, contact_address
            FROM patients
            WHERE id = ?
            """,
            (patient_id,),
        ).fetchone()
        if not base:
            return {}
        return {
            "id": base["id"],
            "name": base["name"],
            "dob": base["dob"],
            "gender": base["gender"],
            "contact": {
                "phone": base["contact_phone"],
                "email": base["contact_email"],
                "address": base["contact_address"],
            },
            "diagnoses": self._fetch_simple_list("diagnoses", "diagnosis", patient_id),
            "medications": self._fetch_simple_list("medications", "medication", patient_id),
            "allergies": self._fetch_simple_list("allergies", "allergy", patient_id),
            "labs": [dict(item) for item in self._connection.execute("SELECT name, value, unit, date FROM labs WHERE patient_id = ? ORDER BY date DESC, id DESC", (patient_id,)).fetchall()],
            "appointments": [dict(item) for item in self._connection.execute("SELECT date, type, clinician FROM appointments WHERE patient_id = ? ORDER BY date ASC, id ASC", (patient_id,)).fetchall()],
            "notes": [item["note"] for item in self._connection.execute("SELECT note FROM notes WHERE patient_id = ? ORDER BY id ASC", (patient_id,)).fetchall()],
        }

    def _fetch_simple_list(self, table: str, column: str, patient_id: str) -> list[str]:
        rows = self._connection.execute(
            f"SELECT {column} FROM {table} WHERE patient_id = ? ORDER BY id ASC",
            (patient_id,),
        ).fetchall()
        return [row[column] for row in rows]
