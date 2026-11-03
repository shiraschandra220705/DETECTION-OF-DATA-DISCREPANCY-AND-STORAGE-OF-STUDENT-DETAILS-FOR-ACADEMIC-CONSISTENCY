"""Credential-free integration tests for Flask's internal reference matcher."""

import importlib
import json
import os
import unittest
from unittest.mock import patch

from google.cloud.firestore_v1.field_path import FieldPath


def selected_field_names(field_paths):
    """Interpret SDK field-path syntax as top-level dictionary keys."""
    return {FieldPath.from_api_repr(path).parts[0] for path in field_paths}


class Snapshot:
    def __init__(self, data):
        self.data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self.data) if self.data is not None else None


class DocumentReference:
    def __init__(self, records, document_id):
        self.records = records
        self.document_id = document_id

    def get(self, field_paths=None):
        data = self.records.get(self.document_id)
        if data is None:
            return Snapshot(None)
        if field_paths is not None:
            selected = selected_field_names(field_paths)
            data = {key: value for key, value in data.items() if key in selected}
        return Snapshot(data)


class Query:
    def __init__(self, records, fields=None, limit=None):
        self.records = records
        self.fields = fields
        self.max_rows = limit

    def select(self, fields):
        return Query(self.records, fields, self.max_rows)

    def limit(self, count):
        return Query(self.records, self.fields, count)

    def stream(self):
        rows = list(self.records.values())
        if self.max_rows is not None:
            rows = rows[:self.max_rows]
        for row in rows:
            if self.fields is not None:
                selected = selected_field_names(self.fields)
                row = {key: value for key, value in row.items() if key in selected}
            yield Snapshot(row)


class Collection:
    def __init__(self, records):
        self.records = records

    def document(self, document_id):
        return DocumentReference(self.records, document_id)

    def select(self, fields):
        return Query(self.records, fields)


class FakeFirestore:
    def __init__(self, collections):
        self.collections = collections

    def collection(self, name):
        return Collection(self.collections.get(name, {}))


def reference(usn="1AB21CS042", **extra):
    return {
        "USN": usn,
        "Name": "Synthetic Student",
        "DOB": "2005-01-01",
        "CGPA": "8.5",
        "Semester": "5",
        "10th Percentage": "92.5",
        "12th Percentage": "94.0",
        "College Name": "Example Institute",
        "Branch": "Computer Science and Engineering",
        "Parent's Name": "Must not be fetched",
        "Phone Number": "Must not be fetched",
        "Email": "Must not be fetched",
        "Semester 1 SGPA": "Must not be fetched",
        **extra,
    }


class InternalReferenceMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # app.py initializes Flask-Session and Firebase Admin at import time.
        # Replace only the Admin initialization/client construction so the
        # tests never need credentials or a live Firestore connection.
        with patch.dict(os.environ, {"FLASK_SECRET_KEY": "synthetic-test-secret"}), \
             patch("firebase_admin.initialize_app"), \
             patch("firebase_admin.firestore.client", return_value=None):
            cls.module = importlib.import_module("projectwork.app")

    def setUp(self):
        self.module.app.config.update(TESTING=True, SECRET_KEY="synthetic-test-secret")
        self.student = {
            "usn": "1AB21CS042",
            "dob": "2005-01-01",
            "cgpa": 8.5,
            "semester": 5,
            "tenthmarks": 92.5,
            "pucmarks": 94.0,
            "college": "Example Institute",
            "branch": "CSE",
            "uid": "must-not-be-trusted-from-record",
        }
        self.collections = {
            "student_records": {"uid-from-session": self.student},
            "users": {"uid-from-session": {"name": "Synthetic Student", "email": "private@example.test"}},
            "reference_students": {"1AB21CS042": reference()},
        }
        self.module.db = FakeFirestore(self.collections)

    def call_matcher(self, *, uid="uid-from-session", name="Synthetic Student"):
        with self.module.app.test_request_context("/"):
            from flask import session

            if uid:
                session["uid"] = uid
            if name:
                session["name"] = name
            return self.module.match_current_student_reference()

    def resolved_match_result(self, *, status="exact_match", method="exact_usn", score=100.0):
        return {
            "status": status,
            "registered_record": {
                "usn": "1AB21CS042",
                "name": "Synthetic Student",
                "dob": "2005-01-01",
                "cgpa": 8.5,
                "semester": 5,
                "tenthmarks": 92.5,
                "pucmarks": 94.0,
                "college": "Example Institute",
                "branch": "CSE",
            },
            "model_result": {
                "matched_candidate": reference(),
                "candidate": reference(),
                "possible_candidates": [{"candidate": reference(), "similarity_score": score}],
                "matching_method": method,
                "similarity_score": score,
                "ambiguity_status": {"status": "resolved", "is_ambiguous": False},
            },
        }

    def test_exact_usn_uses_direct_lookup_and_returns_internal_model_result(self):
        result = self.call_matcher()

        self.assertEqual(result["status"], "exact_match")
        self.assertEqual(result["retrieval_method"], "direct_usn_document")
        self.assertEqual(result["model_result"]["matching_method"], "exact_usn")
        self.assertNotIn("Email", result["model_result"]["candidate"])
        self.assertNotIn("Phone Number", result["model_result"]["candidate"])
        self.assertNotIn("Semester 1 SGPA", result["model_result"]["candidate"])
        self.assertIn("`10th Percentage`", self.module.REFERENCE_MATCH_FIELD_PATHS)
        self.assertIn("`12th Percentage`", self.module.REFERENCE_MATCH_FIELD_PATHS)
        self.assertIn("`College Name`", self.module.REFERENCE_MATCH_FIELD_PATHS)

    def test_inconsistent_direct_document_falls_back_to_projected_scan(self):
        self.collections["reference_students"]["1AB21CS042"] = reference(usn="WRONG-USN")
        self.collections["reference_students"]["legacy-document-id"] = reference(usn="1AB21CS042")

        result = self.call_matcher()

        self.assertEqual(result["retrieval_method"], "bounded_scan")
        self.assertEqual(result["status"], "exact_match")
        self.assertEqual(result["model_result"]["candidate"]["USN"], "1AB21CS042")

    def test_fuzzy_match_uses_scan_after_direct_document_missing(self):
        self.collections["student_records"]["uid-from-session"]["usn"] = "1AB21CS043"

        result = self.call_matcher()

        self.assertEqual(result["retrieval_method"], "bounded_scan")
        self.assertEqual(result["status"], "fuzzy_match")
        self.assertEqual(result["model_result"]["matching_method"], "fuzzy_multifield")

    def test_ambiguous_fuzzy_candidates_are_reported_internally(self):
        self.collections["student_records"]["uid-from-session"].update(
            usn="1AB21CS099", dob=None, cgpa=None, semester=None,
            tenthmarks=None, pucmarks=None, branch=None, college=None,
        )
        self.collections["reference_students"] = {
            "1AB21CS041": {"USN": "1AB21CS041", "Name": "Synthetic Student"},
            "1AB21CS042": {"USN": "1AB21CS042", "Name": "Synthetic Student"},
        }

        result = self.call_matcher()

        self.assertEqual(result["status"], "ambiguous_match")
        self.assertTrue(result["model_result"]["ambiguity_status"]["is_ambiguous"])

    def test_uncertain_match_is_not_reported_as_resolved(self):
        self.collections["student_records"]["uid-from-session"].update(
            usn="1AB21CS043", dob=None, cgpa=None, semester=None, tenthmarks=None,
            pucmarks=None, branch=None, college=None,
        )
        self.collections["users"]["uid-from-session"] = {"name": None}
        self.collections["reference_students"]["1AB21CS042"] = {
            "USN": "1AB21CS042", "Name": "Synthetic Student"
        }

        result = self.call_matcher(name=None)

        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["model_result"]["matched_candidate"])

    def test_truncated_candidate_scan_cannot_report_a_resolved_match(self):
        self.collections["student_records"]["uid-from-session"]["usn"] = "1AB21CS043"
        records = {"candidate-000": reference(usn="1AB21CS042")}
        for index in range(1, 101):
            records[f"candidate-{index:03}"] = {
                "USN": f"OTHER{index:03}",
                "Name": f"Unrelated Student {index}",
            }
        self.collections["reference_students"] = records

        result = self.call_matcher()

        self.assertTrue(result["candidate_set_truncated"])
        self.assertEqual(result["status"], "uncertain")

    def test_missing_student_usn_and_reference_data(self):
        self.assertEqual(self.call_matcher(uid=None)["status"], "unauthenticated")

        self.collections["student_records"].clear()
        self.assertEqual(self.call_matcher()["status"], "student_record_missing")

        self.collections["student_records"]["uid-from-session"] = {"usn": "  "}
        self.assertEqual(self.call_matcher()["status"], "registered_usn_missing")

        self.collections["student_records"]["uid-from-session"] = {"usn": "1AB21CS042"}
        self.collections["reference_students"].clear()
        self.assertEqual(self.call_matcher()["status"], "reference_record_missing")

    def test_uid_is_taken_from_session_and_user_email_is_not_passed_to_model(self):
        result = self.call_matcher(uid="uid-from-session")

        self.assertEqual(result["status"], "exact_match")
        self.assertEqual(result["model_result"]["candidate"]["USN"], "1AB21CS042")
        self.assertNotIn("email", result["model_result"].get("candidate", {}))

    def test_comparison_without_external_record_runs_only_registered_reference(self):
        match = self.resolved_match_result()
        with patch.object(self.module, "match_current_student_reference", return_value=match):
            result = self.module.compare_current_student_records()

        self.assertEqual(
            set(result), {"match_status", "matching_method", "similarity_score", "comparisons"}
        )
        self.assertEqual(result["match_status"], "exact_match")
        self.assertEqual(result["matching_method"], "exact_usn")
        self.assertEqual(result["similarity_score"], 100.0)
        self.assertEqual(set(result["comparisons"]), {"registered_vs_reference"})
        self.assertEqual(result["comparisons"]["registered_vs_reference"]["summary"]["matches"], 9)
        encoded = json.dumps(result)
        self.assertNotIn("possible_candidates", encoded)
        self.assertNotIn("Must not be fetched", encoded)
        self.assertNotIn("model_result", encoded)
        self.assertNotIn("registered_record", encoded)

    def test_external_record_runs_all_three_separate_comparisons(self):
        match = self.resolved_match_result(status="fuzzy_match", method="fuzzy_multifield", score=94.5)
        external = {
            "USN": "1AB21CS042",
            "Name": "Synthetic Student",
            "DOB": "2005-01-01",
            "CGPA": "8.5",
            "Semester": 5,
            "10th Percentage": "92.5",
            "12th Percentage": 94,
            "College Name": "Example Institute",
            "Branch": "Computer Science and Engineering",
        }
        with patch.object(self.module, "match_current_student_reference", return_value=match):
            result = self.module.compare_current_student_records(external)

        self.assertEqual(result["match_status"], "fuzzy_match")
        self.assertEqual(result["matching_method"], "fuzzy_multifield")
        self.assertEqual(result["similarity_score"], 94.5)
        self.assertEqual(
            set(result["comparisons"]),
            {"registered_vs_reference", "external_vs_reference", "registered_vs_external"},
        )
        self.assertEqual(result["comparisons"]["external_vs_reference"]["summary"]["matches"], 9)
        json.dumps(result)

    def test_external_record_must_be_mapping_with_only_supported_fields(self):
        with patch.object(self.module, "match_current_student_reference") as match:
            for invalid_external in ("not a mapping", ["1AB21CS042"], {"usn": "1AB21CS042", "email": "extra"}):
                with self.subTest(value=invalid_external):
                    result = self.module.compare_current_student_records(invalid_external)
                    self.assertEqual(result, {
                        "match_status": "invalid_external_record",
                        "matching_method": None,
                        "similarity_score": None,
                        "comparisons": {},
                    })
            match.assert_not_called()

    def test_unresolved_statuses_never_run_comparisons_or_expose_candidates(self):
        statuses = (
            "ambiguous_match",
            "uncertain",
            "unmatched",
            "student_record_missing",
            "registered_usn_missing",
            "reference_record_missing",
        )
        raw = {
            "matched_candidate": None,
            "candidate": reference(),
            "possible_candidates": [{"candidate": reference()}],
            "matching_method": "fuzzy_multifield",
            "similarity_score": 84.0,
        }
        for status in statuses:
            match = {"status": status, "model_result": raw}
            with self.subTest(status=status), patch.object(
                self.module, "match_current_student_reference", return_value=match
            ):
                result = self.module.compare_current_student_records({"usn": "1AB21CS042"})
                self.assertEqual(result["match_status"], status)
                self.assertEqual(result["comparisons"], {})
                self.assertEqual(set(result), {
                    "match_status", "matching_method", "similarity_score", "comparisons"
                })
                encoded = json.dumps(result)
                self.assertNotIn("possible_candidates", encoded)
                self.assertNotIn("Must not be fetched", encoded)

    def test_resolved_status_without_matched_candidate_fails_closed(self):
        match = self.resolved_match_result()
        match["model_result"]["matched_candidate"] = None
        with patch.object(self.module, "match_current_student_reference", return_value=match):
            result = self.module.compare_current_student_records()

        self.assertEqual(result["match_status"], "uncertain")
        self.assertEqual(result["comparisons"], {})


if __name__ == "__main__":
    unittest.main()
