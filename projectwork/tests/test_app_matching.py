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
    def __init__(self, records, document_id, access_log=None, collection_name=None):
        self.records = records
        self.document_id = document_id
        self.access_log = access_log if access_log is not None else []
        self.collection_name = collection_name

    def get(self, field_paths=None):
        self.access_log.append((self.collection_name, self.document_id, field_paths))
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
    def __init__(self, records, access_log=None, collection_name=None):
        self.records = records
        self.access_log = access_log if access_log is not None else []
        self.collection_name = collection_name

    def document(self, document_id):
        return DocumentReference(self.records, document_id, self.access_log, self.collection_name)

    def select(self, fields):
        return Query(self.records, fields)


class FakeFirestore:
    def __init__(self, collections):
        self.collections = collections
        self.document_reads = []

    def collection(self, name):
        return Collection(self.collections.get(name, {}), self.document_reads, name)


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

    def call_comparison(self, external=None, *, uid="uid-from-session"):
        with self.module.app.test_request_context("/"):
            from flask import session
            if uid:
                session["uid"] = uid
            return self.module.compare_current_student_records(external)

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

    def test_direct_reference_hit_with_duplicate_normalized_usn_is_ambiguous(self):
        self.collections["reference_students"]["duplicate-doc"] = reference("1ab-21cs-042")
        result = self.call_matcher()

        self.assertEqual(result["retrieval_method"], "direct_usn_document")
        self.assertEqual(result["status"], "ambiguous_match")
        self.assertIsNone(result["model_result"]["matched_candidate"])

    def test_unique_direct_reference_hit_is_confirmed_by_bounded_scan(self):
        result = self.call_matcher()

        self.assertEqual(result["retrieval_method"], "direct_usn_document")
        self.assertEqual(result["status"], "exact_match")
        self.assertFalse(result["candidate_set_truncated"])
        self.assertEqual(result["model_result"]["matching_method"], "exact_usn")

    def test_direct_reference_hit_with_truncated_scan_is_uncertain_and_not_compared(self):
        for index in range(self.module.MAX_REFERENCE_CANDIDATES):
            self.collections["reference_students"][f"extra-{index}"] = reference(
                f"1ZZ99AA{index:03d}"
            )

        match_result = self.call_matcher()
        self.assertEqual(match_result["retrieval_method"], "direct_usn_document")
        self.assertEqual(match_result["status"], "uncertain")
        self.assertTrue(match_result["candidate_set_truncated"])

        comparison = self.call_comparison({"USN": "1AB21CS042"})
        self.assertNotIn("registered_vs_reference", comparison["comparisons"])
        self.assertNotIn("external_vs_reference", comparison["comparisons"])

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
        self.assertIn("registered_record", self.call_matcher())

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
            set(result), {"match_status", "matching_method", "similarity_score", "comparisons", "registered_record_exists", "reference_record_exists", "reference_identity_verified", "identity_verification_status", "external_comparisons_blocked", "discrepancies_detected", "message", "overall_result"}
        )
        self.assertEqual(result["match_status"], "exact_match")
        self.assertEqual(result["matching_method"], "exact_usn")
        self.assertEqual(result["similarity_score"], 100.0)
        self.assertEqual(set(result["comparisons"]), {"registered_vs_reference"})
        self.assertEqual(result["comparisons"]["registered_vs_reference"]["summary"]["matches"], 9)
        self.assertEqual(result["overall_result"], "No discrepancies detected in the available comparisons")
        self.assertEqual(result["identity_verification_status"], "verified")
        encoded = json.dumps(result)
        self.assertNotIn("possible_candidates", encoded)
        self.assertNotIn("Must not be fetched", encoded)

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
        self.assertFalse(result["discrepancies_detected"])
        self.assertEqual(result["overall_result"], "No discrepancies detected in the available comparisons")
        json.dumps(result)

    def test_external_record_must_be_mapping_with_only_supported_fields(self):
        with patch.object(self.module, "match_current_student_reference") as match:
            for invalid_external in ("not a mapping", ["1AB21CS042"], {"usn": "1AB21CS042", "email": "extra"}):
                with self.subTest(value=invalid_external):
                    result = self.module.compare_current_student_records(invalid_external)
                    self.assertEqual(result["match_status"], "invalid_external_record")
                    self.assertEqual(result["overall_result"], "No comparison could be performed")
                    self.assertEqual(result["comparisons"], {})
                    self.assertEqual(set(result), {
                        "match_status", "matching_method", "similarity_score",
                        "registered_record_exists", "reference_record_exists",
                        "reference_identity_verified", "identity_verification_status",
                        "external_comparisons_blocked", "comparisons",
                        "discrepancies_detected", "message", "overall_result",
                    })
                    self.assertEqual(result["identity_verification_status"], "incomplete")
                    self.assertFalse(result["external_comparisons_blocked"])
                    self.assertEqual(
                        result["message"],
                        "Invalid external student record; no comparison could be performed.",
                    )
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
                if status in {"student_record_missing", "registered_usn_missing"}:
                    self.assertEqual(set(result["comparisons"]), {"external_vs_reference"})
                else:
                    self.assertEqual(result["comparisons"], {})
                self.assertIn("registered_record_exists", result)
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

    def test_missing_registered_record_uses_external_usn_for_exact_reference(self):
        self.collections["student_records"].clear()
        result = self.call_comparison({"USN": "1ab21-cs-042", "Name": "Other Name"})
        self.assertFalse(result["registered_record_exists"])
        self.assertTrue(result["reference_record_exists"])
        self.assertEqual(set(result["comparisons"]), {"external_vs_reference"})
        self.assertTrue(result["discrepancies_detected"])
        self.assertEqual(result["overall_result"], "Discrepancies detected in available comparisons; identity could not be fully verified.")
        self.assertEqual(result["message"], "Student is not registered.")

    def test_missing_reference_still_compares_registered_and_external(self):
        self.collections["reference_students"].clear()
        result = self.call_comparison({"USN": "1AB21CS042", "CGPA": 8.5})
        self.assertTrue(result["registered_record_exists"])
        self.assertFalse(result["reference_record_exists"])
        self.assertEqual(set(result["comparisons"]), {"registered_vs_external"})
        self.assertEqual(result["message"], "Reference record is unavailable.")

    def test_both_firestore_records_missing_does_not_claim_comparison(self):
        self.collections["student_records"].clear()
        result = self.call_comparison()
        self.assertFalse(result["registered_record_exists"])
        self.assertFalse(result["reference_record_exists"])
        self.assertEqual(result["comparisons"], {})
        self.assertFalse(result["discrepancies_detected"])
        self.assertEqual(result["overall_result"], "No comparison could be performed")
        self.assertIn("No comparison could be performed", result["message"])

    def test_registered_usn_missing_keeps_registration_and_allows_external_reference_only(self):
        self.collections["student_records"]["uid-from-session"]["usn"] = "  "
        external = {"USN": "1AB21CS042", "Name": "Synthetic Student", "CGPA": 8.5}
        result = self.call_comparison(external)
        self.assertTrue(result["registered_record_exists"])
        self.assertTrue(result["reference_record_exists"])
        self.assertFalse(result["reference_identity_verified"])
        self.assertEqual(set(result["comparisons"]), {"external_vs_reference"})
        self.assertIn("could not be safely verified", result["message"])
        self.assertFalse(result["discrepancies_detected"])
        self.assertEqual(result["overall_result"], "Identity could not be safely verified; only partial comparisons were possible.")

    def test_registered_usn_invalid_is_not_reported_as_unregistered(self):
        self.collections["student_records"]["uid-from-session"]["usn"] = "!!!"
        result = self.call_comparison()
        self.assertTrue(result["registered_record_exists"])
        self.assertEqual(result["match_status"], "registered_usn_invalid")
        self.assertNotIn("not registered", result["message"].casefold())
        self.assertEqual(result["overall_result"], "No comparison could be performed")

    def test_missing_registered_usn_does_not_allow_registered_external_comparison(self):
        self.collections["student_records"]["uid-from-session"]["usn"] = None
        result = self.call_comparison({"USN": "1AB21CS042"})
        self.assertNotIn("registered_vs_external", result["comparisons"])
        self.assertFalse(result["reference_identity_verified"])

    def test_identity_mismatch_has_explicit_overall_result(self):
        result = self.call_comparison({"USN": "1AB21CS999"})
        self.assertIn("external comparisons were blocked", result["message"])
        self.assertEqual(set(result["comparisons"]), {"registered_vs_reference"})
        self.assertTrue(result["external_comparisons_blocked"])
        self.assertEqual(result["overall_result"], "Identity could not be safely verified; only partial comparisons were possible.")

    def test_external_identity_mismatch_and_registered_reference_discrepancy_report_both(self):
        self.collections["student_records"]["uid-from-session"]["cgpa"] = 7.5
        result = self.call_comparison({"USN": "1AB21CS999", "CGPA": 8.5})
        self.assertEqual(set(result["comparisons"]), {"registered_vs_reference"})
        self.assertTrue(result["discrepancies_detected"])
        self.assertTrue(result["external_comparisons_blocked"])
        self.assertEqual(result["overall_result"], "Discrepancies detected in available comparisons; identity could not be fully verified.")

    def test_registered_usn_invalid_and_external_reference_discrepancy_reports_both(self):
        self.collections["student_records"]["uid-from-session"]["usn"] = "!!!"
        result = self.call_comparison({"USN": "1AB21CS042", "CGPA": 7.5})
        self.assertEqual(set(result["comparisons"]), {"external_vs_reference"})
        self.assertTrue(result["discrepancies_detected"])
        self.assertEqual(result["overall_result"], "Discrepancies detected in available comparisons; identity could not be fully verified.")

    def test_successful_three_way_comparison_with_discrepancy(self):
        external = {"USN": "1AB21CS042", "Name": "Synthetic Student", "CGPA": 7.5}
        result = self.call_comparison(external)
        self.assertEqual(len(result["comparisons"]), 3)
        self.assertTrue(result["discrepancies_detected"])
        self.assertEqual(result["identity_verification_status"], "verified")
        self.assertEqual(result["overall_result"], "Discrepancies detected")

    def test_external_identity_mismatch_blocks_external_comparisons(self):
        result = self.call_comparison({"USN": "1AB21CS999"})
        self.assertNotIn("registered_vs_external", result["comparisons"])
        self.assertNotIn("external_vs_reference", result["comparisons"])
        self.assertIn("identity", result["message"])

    def test_authenticated_session_required_and_output_is_projected(self):
        with self.module.app.test_request_context("/"):
            result = self.module.compare_current_student_records({"USN": "1AB21CS042"})
        self.assertEqual(result["match_status"], "unauthenticated")
        encoded = json.dumps(result)
        self.assertNotIn("possible_candidates", encoded)
        self.assertNotIn("Must not be fetched", encoded)


class ExtensionComparisonAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"FLASK_SECRET_KEY": "synthetic-test-secret"}), \
             patch("firebase_admin.initialize_app"), \
             patch("firebase_admin.firestore.client", return_value=None):
            cls.module = importlib.import_module("projectwork.app")

    def setUp(self):
        self.module.app.config.update(TESTING=True, SECRET_KEY="synthetic-test-secret")
        self.student = {
            "usn": "1AB21CS042", "dob": "2005-01-01", "cgpa": 8.5,
            "semester": 5, "tenthmarks": 92.5, "pucmarks": 94.0,
            "college": "Example Institute", "branch": "CSE",
        }
        self.collections = {
            "student_records": {"verified-user": self.student},
            "users": {"verified-user": {"name": "Synthetic Student"}},
            "reference_students": {"1AB21CS042": reference()},
        }
        self.module.db = FakeFirestore(self.collections)
        self.client = self.module.app.test_client()
        self.url = "/api/extension/compare"
        self.auth_header = {"Authorization": "Bearer valid-token"}
        self.external = {
            "USN": "1AB21CS042",
            "Name": "Synthetic Student",
            "DOB": "2005-01-01",
            "CGPA": "8.5",
            "Semester": "5",
            "10th Grade": "92.5",
            "12th Grade": "94",
            "College Name": "Example Institute",
            "Branch": "CSE",
            "Academic Year": "2025-26",
        }

    def post(self, payload=None, headers=None):
        return self.client.post(self.url, json=payload, headers=headers or self.auth_header)

    def test_missing_authorization_header(self):
        response = self.post({"external_record": self.external}, headers={})
        self.assertEqual(response.status_code, 401)

    def test_oversized_request_is_rejected(self):
        response = self.client.post(
            self.url,
            data=b"{" + b" " * self.module.MAX_EXTENSION_REQUEST_BYTES,
            content_type="application/json",
            headers=self.auth_header,
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["message"], "Request body is too large.")

    def test_malformed_bearer_token(self):
        response = self.post({"external_record": self.external}, headers={"Authorization": "Basic token"})
        self.assertEqual(response.status_code, 401)

    def test_invalid_firebase_token(self):
        from firebase_admin import auth
        with patch.object(auth, "verify_id_token", side_effect=auth.InvalidIdTokenError("invalid")):
            response = self.post({"external_record": self.external})
        self.assertEqual(response.status_code, 401)

    def test_expired_firebase_token(self):
        from firebase_admin import auth
        error = auth.ExpiredIdTokenError("expired", Exception("expired"))
        with patch.object(auth, "verify_id_token", side_effect=error):
            response = self.post({"external_record": self.external})
        self.assertEqual(response.status_code, 401)

    def test_revoked_firebase_token(self):
        from firebase_admin import auth
        error = auth.RevokedIdTokenError("revoked token details must remain private")
        with patch.object(auth, "verify_id_token", side_effect=error) as verify:
            response = self.post({"external_record": self.external})
        self.assertEqual(response.status_code, 401)
        verify.assert_called_once_with("valid-token", check_revoked=True)
        self.assertEqual(response.get_json(), {
            "status": "error",
            "message": "Authentication failed. Please log in again.",
        })
        self.assertNotIn("revoked token details", response.get_data(as_text=True))

    def test_valid_token_completes_personal_comparison_without_session_cookie(self):
        from firebase_admin import auth
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}) as verify:
            response = self.post({"external_record": self.external})
        self.assertEqual(response.status_code, 200)
        verify.assert_called_once_with("valid-token", check_revoked=True)
        body = response.get_json()
        self.assertEqual(body["comparison"]["mode"], "personal")
        self.assertEqual(body["comparison"]["relationship_verification_status"], "verified")
        self.assertEqual(body["status"], "success")
        self.assertEqual(set(body["comparison"]["comparisons"]), {
            "registered_vs_reference", "external_vs_reference", "registered_vs_external"
        })
        self.assertEqual(len(body["comparison"]["comparisons"]["external_vs_reference"]["fields"]), 9)

    def test_authenticated_user_without_registered_record_gets_reference_only_result(self):
        from firebase_admin import auth
        self.collections["student_records"].clear()
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            response = self.post({"external_record": self.external})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["comparison"]
        self.assertEqual(result["mode"], "reference_only")
        self.assertEqual(result["relationship_verification_status"], "unverified")
        self.assertEqual(set(result["comparisons"]), {"external_vs_reference"})

    def test_missing_external_record_gets_400(self):
        from firebase_admin import auth
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            response = self.post({})
        self.assertEqual(response.status_code, 400)

    def test_malformed_external_record_gets_400(self):
        from firebase_admin import auth
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            response = self.post({"external_record": ["not", "an", "object"]})
            unsupported = self.post({"external_record": {"USN": "1AB21CS042", "Phone Number": "private"}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(unsupported.status_code, 400)

    def test_conflicting_aliases_for_same_field_get_400(self):
        from firebase_admin import auth
        supplied = dict(self.external, usn="1AB21CS042")
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            response = self.post({"external_record": supplied})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {
            "status": "error",
            "message": "external_record contains conflicting field aliases.",
        })

    def test_single_accepted_alias_per_field_still_compares_personally(self):
        from firebase_admin import auth
        supplied = {
            "usn": "1AB21CS042",
            "name": "Synthetic Student",
            "dob": "2005-01-01",
            "cgpa": "8.5",
            "semester": "5",
            "tenthmarks": "92.5",
            "pucmarks": "94",
            "college": "Example Institute",
            "branch": "CSE",
            "Academic Year": "2025-26",
        }
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            response = self.post({"external_record": supplied})
        self.assertEqual(response.status_code, 200)
        comparison = response.get_json()["comparison"]
        self.assertEqual(comparison["mode"], "personal")
        self.assertEqual(set(comparison["comparisons"]), {
            "registered_vs_reference", "external_vs_reference", "registered_vs_external"
        })

    def test_different_usn_selects_other_student_and_never_calls_personal_comparison(self):
        from firebase_admin import auth
        external = dict(self.external, USN="1AB21CS999")
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}), \
             patch.object(self.module, "compare_current_student_records") as personal_compare:
            response = self.post({"external_record": external})
        result = response.get_json()["comparison"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["mode"], "other_student")
        self.assertEqual(result["relationship_verification_status"], "different_student")
        self.assertEqual(result["reference_status"], "unavailable")
        self.assertEqual(result["comparisons"], {})
        personal_compare.assert_not_called()
        private_reads = [read for read in self.module.db.document_reads if read[0] == "student_records"]
        self.assertTrue(private_reads)
        self.assertEqual({read[1] for read in private_reads}, {"verified-user"})

    def test_other_student_exact_reference_returns_only_external_comparison(self):
        from firebase_admin import auth
        self.collections["reference_students"] = {"formatted-key": reference("1AB-21CS-999")}
        external = dict(self.external, USN="1ab 21cs999")
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}), \
             patch.object(self.module, "compare_current_student_records") as personal_compare:
            response = self.post({"external_record": external})
        result = response.get_json()["comparison"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["mode"], "other_student")
        self.assertEqual(set(result["comparisons"]), {"external_vs_reference"})
        self.assertEqual(len(result["comparisons"]["external_vs_reference"]["fields"]), 9)
        self.assertNotIn("registered_vs_reference", result["comparisons"])
        self.assertNotIn("registered_vs_external", result["comparisons"])
        personal_compare.assert_not_called()
        self.assertNotIn("Must not be fetched", response.get_data(as_text=True))

    def test_missing_and_invalid_extracted_usn_return_400(self):
        from firebase_admin import auth
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            missing = dict(self.external)
            del missing["USN"]
            missing_response = self.post({"external_record": missing})
            invalid_response = self.post({"external_record": dict(self.external, USN="!!!")})
        self.assertEqual(missing_response.status_code, 400)
        self.assertEqual(invalid_response.status_code, 400)

    def test_duplicate_normalized_reference_usns_are_ambiguous(self):
        from firebase_admin import auth
        self.collections["reference_students"] = {
            "one": reference("1AB21CS999"),
            "two": reference("1ab-21cs-999"),
        }
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            response = self.post({"external_record": dict(self.external, USN="1AB21CS999")})
        result = response.get_json()["comparison"]
        self.assertEqual(result["reference_status"], "ambiguous")
        self.assertEqual(result["comparisons"], {})

    def test_truncated_reference_scan_fails_closed(self):
        from firebase_admin import auth
        self.collections["reference_students"] = {
            "one": reference("1AB21CS999"),
            "two": reference("1AB21CS998"),
        }
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}), \
             patch.object(self.module, "MAX_REFERENCE_CANDIDATES", 1):
            response = self.post({"external_record": dict(self.external, USN="1AB21CS999")})
        result = response.get_json()["comparison"]
        self.assertEqual(result["reference_status"], "lookup_incomplete")
        self.assertEqual(result["comparisons"], {})

    def test_reference_only_missing_reference_is_clear_and_private_safe(self):
        from firebase_admin import auth
        self.collections["student_records"].clear()
        self.collections["reference_students"].clear()
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}), \
             patch.object(self.module, "compare_current_student_records") as personal_compare:
            response = self.post({"external_record": self.external})
        result = response.get_json()["comparison"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["mode"], "reference_only")
        self.assertEqual(result["relationship_verification_status"], "unverified")
        self.assertEqual(result["reference_status"], "unavailable")
        self.assertEqual(result["comparisons"], {})
        personal_compare.assert_not_called()

    def test_request_cannot_supply_uid(self):
        from firebase_admin import auth
        with patch.object(auth, "verify_id_token", return_value={"uid": "verified-user"}):
            response = self.post({"uid": "another-user", "external_record": self.external})
        self.assertEqual(response.status_code, 400)

    def test_existing_session_comparison_remains_available(self):
        # The pre-existing website path still takes identity from its session.
        with self.module.app.test_request_context("/"):
            from flask import session
            session["uid"] = "verified-user"
            result = self.module.compare_current_student_records({"USN": "1AB21CS042"})
        self.assertEqual(result["match_status"], "exact_match")
        self.assertIn("registered_vs_external", result["comparisons"])


if __name__ == "__main__":
    unittest.main()
