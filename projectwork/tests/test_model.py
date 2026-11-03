"""Synthetic tests for the reusable student matching helpers."""

import json
import unittest
from datetime import date

from projectwork.model import (
    match_student,
    normalize_branch,
    normalize_date,
    normalize_number,
    normalize_usn,
)


class NormalizeTests(unittest.TestCase):
    def test_normalizes_common_input_formats(self):
        self.assertEqual(normalize_usn(" 1da23-is-0042 "), "1DA23IS0042")
        self.assertEqual(normalize_date("03/11/2004"), "2004-11-03")
        self.assertEqual(normalize_date(date(2004, 11, 3)), "2004-11-03")
        self.assertEqual(normalize_number(" 8,5 "), 8.5)
        self.assertEqual(
            normalize_branch("Information Science & Engineering"),
            "information science and engineering",
        )


class MatchStudentTests(unittest.TestCase):
    def test_exact_normalized_usn_is_authoritative_and_json_safe(self):
        student = {"usn": "1da23-is-0042", "name": "Synthetic Student"}
        reference = [{"USN": "1DA23IS0042", "Name": "Synthetic Student", "DOB": date(2004, 11, 3)}]

        result = match_student(student, reference)

        self.assertEqual(result["matching_method"], "exact_usn")
        self.assertEqual(result["similarity_score"], 100.0)
        self.assertEqual(result["ambiguity_status"]["status"], "resolved")
        self.assertEqual(result["matched_candidate"]["DOB"], "2004-11-03")
        json.dumps(result)

    def test_fuzzy_match_uses_multiple_fields_and_reports_candidate(self):
        student = {
            "usn": "1DA23IS0049",
            "name": "Avery Example",
            "dob": "03/11/2004",
            "branch": "ISE",
        }
        reference = [{
            "USN": "1DA23IS0042",
            "Name": "Avery Examples",
            "DOB": "2004-11-03",
            "Branch": "Information Science and Engineering",
        }]

        result = match_student(student, reference)

        self.assertEqual(result["matching_method"], "fuzzy_multifield")
        self.assertEqual(result["ambiguity_status"]["status"], "resolved")
        self.assertIsNotNone(result["matched_candidate"])
        self.assertGreater(result["similarity_score"], 72)

    def test_only_slightly_mistyped_usn_is_uncertain(self):
        result = match_student(
            {"usn": "1DA23IS0043"},
            [{"USN": "1DA23IS0042", "Name": "Synthetic Student"}],
        )

        self.assertEqual(result["ambiguity_status"]["status"], "uncertain")
        self.assertFalse(result["identity_evidence"]["sufficient"])
        self.assertIsNone(result["matched_candidate"])

    def test_fuzzy_usn_and_name_jointly_resolve(self):
        result = match_student(
            {"usn": "1DA23IS0043", "name": "Synthetic Student"},
            [{"USN": "1DA23IS0042", "Name": "Synthetic Student"}],
        )

        self.assertEqual(result["ambiguity_status"]["status"], "resolved")
        self.assertEqual(result["identity_evidence"]["reason"],
                         "Fuzzy USN is corroborated by an independent identity field.")

    def test_fuzzy_usn_and_dob_jointly_resolve(self):
        result = match_student(
            {"usn": "1DA23IS0043", "dob": "2004-11-03"},
            [{"USN": "1DA23IS0042", "DOB": "03/11/2004"}],
        )

        self.assertEqual(result["ambiguity_status"]["status"], "resolved")
        self.assertEqual(result["identity_evidence"]["scores"]["dob"], 100.0)

    def test_close_candidates_are_ambiguous(self):
        student = {"usn": "1DA23IS0099", "name": "Avery Example", "dob": "2004-11-03"}
        references = [
            {"USN": "1DA23IS0001", "Name": "Avery Example", "DOB": "2004-11-03"},
            {"USN": "1DA23IS0002", "Name": "Avery Example", "DOB": "2004-11-03"},
        ]

        result = match_student(student, references)

        self.assertEqual(result["ambiguity_status"]["status"], "ambiguous")
        self.assertTrue(result["ambiguity_status"]["is_ambiguous"])
        self.assertIsNone(result["matched_candidate"])
        self.assertEqual(len(result["possible_candidates"]), 2)

    def test_missing_usn_fallback_requires_name_and_dob(self):
        reference = [{"USN": "1DA23IS0001", "Name": "Avery Example", "DOB": "2004-11-03"}]
        result = match_student(
            {"name": "Avery Example", "dob": "03/11/2004"}, reference
        )
        name_only = match_student({"name": "Avery Example"}, reference)

        self.assertEqual(result["ambiguity_status"]["status"], "resolved")
        self.assertIn("USN is missing", result["identity_evidence"]["reason"])
        self.assertEqual(name_only["ambiguity_status"]["status"], "uncertain")
        self.assertIsNone(name_only["matched_candidate"])

    def test_calculated_cgpa_and_sgpa_history_do_not_affect_match_score(self):
        student = {"usn": "1DA23IS9999", "name": "Avery Example", "dob": "2004-11-03"}
        base = {"USN": "1DA23IS0001", "Name": "Avery Example", "DOB": "2004-11-03", "CGPA": "8.0"}
        first = dict(base, **{"Calculated CGPA": "8.1", "Semester 1 SGPA": "7.0"})
        second = dict(base, **{"Calculated CGPA": "2.0", "Semester 1 SGPA": "10.0"})

        first_result = match_student(student, [first])
        second_result = match_student(student, [second])

        self.assertEqual(first_result["similarity_score"], second_result["similarity_score"])


if __name__ == "__main__":
    unittest.main()
