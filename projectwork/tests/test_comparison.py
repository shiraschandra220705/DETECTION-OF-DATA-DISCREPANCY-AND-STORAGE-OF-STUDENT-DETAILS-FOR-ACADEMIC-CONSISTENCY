"""Synthetic unit tests for the independent discrepancy comparison engine."""

import json
import math
import unittest
from datetime import date
from decimal import Decimal

from projectwork.comparison import (
    compare_external_to_reference,
    compare_records,
    compare_registered_to_external,
    compare_registered_to_reference,
    compare_three_sources,
)


def registered_record(**overrides):
    record = {
        "usn": " 1ab21-cs-042 ",
        "name": "Synthetic Student",
        "dob": "01/02/2005",
        "cgpa": 8.5,
        "semester": 5,
        "tenthmarks": "92.50",
        "pucmarks": 94,
        "college": " Example Institute ",
        "branch": "CSE",
    }
    record.update(overrides)
    return record


def reference_record(**overrides):
    record = {
        "USN": "1AB21CS042",
        "Name": "synthetic student",
        "DOB": "2005-02-01",
        "CGPA": "8.50",
        "Semester": "5.0",
        "10th Percentage": 92.5,
        "12th Percentage": "94.00",
        "College Name": "example institute",
        "Branch": "Computer Science and Engineering",
    }
    record.update(overrides)
    return record


def external_record(**overrides):
    # External records are permitted to use either the app or reference schema.
    record = {
        "USN": "1ab21cs042",
        "Name": "Synthetic Student",
        "DOB": date(2005, 2, 1),
        "CGPA": "8.5",
        "Semester": 5,
        "10th Percentage": "92.5",
        "12th Percentage": 94.0,
        "College Name": "Example Institute",
        "Branch": "Computer Science Engineering",
    }
    record.update(overrides)
    return record


class CompareRecordsTests(unittest.TestCase):
    def test_equivalent_registered_and_reference_schemas_match(self):
        result = compare_registered_to_reference(registered_record(), reference_record())

        self.assertEqual(result["left_source"], "registered")
        self.assertEqual(result["right_source"], "reference")
        self.assertEqual(len(result["fields"]), 9)
        self.assertEqual(result["summary"], {"matches": 9, "mismatches": 0, "missing": 0})
        self.assertTrue(all(field["status"] == "match" for field in result["fields"]))
        json.dumps(result)

    def test_mismatches_are_reported_per_field_with_normalized_values(self):
        result = compare_records(
            registered_record(name="Other Student", cgpa=8.6, branch="ISE"),
            reference_record(Name="Synthetic Student", CGPA="8.5", Branch="ISE"),
            left_source="registered",
            right_source="reference",
        )
        fields = {entry["field"]: entry for entry in result["fields"]}

        self.assertEqual(fields["Name"]["status"], "mismatch")
        self.assertEqual(fields["CGPA"]["status"], "mismatch")
        self.assertEqual(fields["Branch"]["status"], "match")
        self.assertEqual(fields["CGPA"]["left_value"], 8.6)
        self.assertEqual(fields["CGPA"]["left_normalized"], 8.6)
        self.assertEqual(result["summary"], {"matches": 7, "mismatches": 2, "missing": 0})

    def test_missing_values_include_null_markers_and_nan(self):
        result = compare_records(
            registered_record(name=None, dob="", cgpa=math.nan, semester="N/A"),
            reference_record(Name="Synthetic Student", DOB="null", CGPA="8.5", Semester="5"),
        )
        fields = {entry["field"]: entry for entry in result["fields"]}

        self.assertEqual(fields["Name"]["status"], "missing")
        self.assertEqual(fields["DOB"]["status"], "missing")
        self.assertEqual(fields["CGPA"]["status"], "missing")
        self.assertEqual(fields["Semester"]["status"], "missing")
        self.assertEqual(fields["Name"]["left_value"], None)

    def test_numeric_strings_and_numbers_compare_by_value(self):
        result = compare_records(
            {"cgpa": "8.50", "semester": "5.0", "tenthmarks": "92.500", "pucmarks": 94},
            {"CGPA": 8.5, "Semester": 5, "10th Percentage": 92.5, "12th Percentage": "94.0"},
        )
        fields = {entry["field"]: entry for entry in result["fields"]}

        for name in ("CGPA", "Semester", "10th Percentage", "12th Percentage"):
            self.assertEqual(fields[name]["status"], "match")

    def test_supported_date_formats_normalize_to_iso(self):
        result = compare_records(
            {"dob": "01/02/2005"},
            {"DOB": "2005-02-01"},
        )
        dob = next(field for field in result["fields"] if field["field"] == "DOB")

        self.assertEqual(dob["status"], "match")
        self.assertEqual(dob["left_value"], "01/02/2005")
        self.assertEqual(dob["right_value"], "2005-02-01")
        self.assertEqual(dob["left_normalized"], "2005-02-01")
        self.assertEqual(dob["right_normalized"], "2005-02-01")

    def test_branch_abbreviations_normalize(self):
        pairs = (
            ("ISE", "Information Science & Engineering"),
            ("CSE", "Computer Science and Engineering"),
            ("ECE", "Electronics and Communication Engineering"),
            ("ME", "Mechanical Engineering"),
        )
        for short, full in pairs:
            with self.subTest(branch=short):
                result = compare_records({"branch": short}, {"Branch": full})
                branch = next(field for field in result["fields"] if field["field"] == "Branch")
                self.assertEqual(branch["status"], "match")


class ThreeSourceTests(unittest.TestCase):
    def test_all_three_pairwise_comparisons_are_independent_and_labeled(self):
        registered = registered_record(cgpa=8.0)
        reference = reference_record(CGPA="8.5")
        external = external_record(CGPA="8.0")

        results = compare_three_sources(registered, reference, external)

        self.assertEqual(
            set(results),
            {"registered_vs_reference", "external_vs_reference", "registered_vs_external"},
        )
        self.assertEqual(results["registered_vs_reference"]["left_source"], "registered")
        self.assertEqual(results["registered_vs_reference"]["right_source"], "reference")
        self.assertEqual(results["external_vs_reference"]["left_source"], "external")
        self.assertEqual(results["external_vs_reference"]["right_source"], "reference")
        self.assertEqual(results["registered_vs_external"]["left_source"], "registered")
        self.assertEqual(results["registered_vs_external"]["right_source"], "external")

        self.assertEqual(_field_status(results["registered_vs_reference"], "CGPA"), "mismatch")
        self.assertEqual(_field_status(results["external_vs_reference"], "CGPA"), "mismatch")
        self.assertEqual(_field_status(results["registered_vs_external"], "CGPA"), "match")
        self.assertNotIn("overall_status", results)
        json.dumps(results)

    def test_each_directional_comparison_function(self):
        registered = registered_record()
        reference = reference_record()
        external = external_record()

        self.assertEqual(
            compare_registered_to_reference(registered, reference)["summary"]["matches"], 9
        )
        self.assertEqual(
            compare_external_to_reference(external, reference)["summary"]["matches"], 9
        )
        self.assertEqual(
            compare_registered_to_external(registered, external)["summary"]["matches"], 9
        )


class OriginalAndInvalidValueTests(unittest.TestCase):
    def test_numeric_original_format_is_preserved_alongside_normalized_value(self):
        result = compare_records({"cgpa": " 08.500 "}, {"CGPA": 8.5})
        cgpa = next(field for field in result["fields"] if field["field"] == "CGPA")

        self.assertEqual(cgpa["status"], "match")
        self.assertEqual(cgpa["left_value"], " 08.500 ")
        self.assertEqual(cgpa["right_value"], 8.5)
        self.assertEqual(cgpa["left_normalized"], 8.5)
        self.assertEqual(cgpa["right_normalized"], 8.5)
        json.dumps(result)

        decimal_result = compare_records({"cgpa": Decimal("8.500")}, {"CGPA": 8.5})
        decimal_cgpa = next(
            field for field in decimal_result["fields"] if field["field"] == "CGPA"
        )
        self.assertEqual(decimal_cgpa["left_value"], "8.500")
        self.assertEqual(decimal_cgpa["left_normalized"], 8.5)
        json.dumps(decimal_result)

    def test_identical_invalid_numeric_values_are_mismatch(self):
        result = compare_records({"cgpa": "eight"}, {"CGPA": "eight"})
        cgpa = next(field for field in result["fields"] if field["field"] == "CGPA")

        self.assertEqual(cgpa["status"], "mismatch")
        self.assertEqual(cgpa["left_value"], "eight")
        self.assertIsNone(cgpa["left_normalized"])
        self.assertEqual(cgpa["validation"], {"left_invalid": True, "right_invalid": True})

    def test_identical_malformed_usns_are_mismatch_and_preserved(self):
        result = compare_records({"usn": "!!!"}, {"USN": "!!!"})
        usn = next(field for field in result["fields"] if field["field"] == "USN")

        self.assertEqual(usn["status"], "mismatch")
        self.assertEqual(usn["left_value"], "!!!")
        self.assertEqual(usn["right_value"], "!!!")
        self.assertIsNone(usn["left_normalized"])
        self.assertIsNone(usn["right_normalized"])
        self.assertEqual(usn["validation"], {"left_invalid": True, "right_invalid": True})

    def test_malformed_usn_against_valid_usn_is_mismatch(self):
        result = compare_records({"usn": "!!!"}, {"USN": "1AB21CS042"})
        usn = next(field for field in result["fields"] if field["field"] == "USN")

        self.assertEqual(usn["status"], "mismatch")
        self.assertEqual(usn["left_value"], "!!!")
        self.assertIsNone(usn["left_normalized"])
        self.assertEqual(usn["right_normalized"], "1AB21CS042")
        self.assertEqual(usn["validation"], {"left_invalid": True, "right_invalid": False})

    def test_genuinely_missing_usn_remains_missing(self):
        for missing_value in (None, "", "N/A"):
            with self.subTest(value=missing_value):
                result = compare_records({"usn": missing_value}, {"USN": "1AB21CS042"})
                usn = next(field for field in result["fields"] if field["field"] == "USN")
                self.assertEqual(usn["status"], "missing")
                self.assertFalse(usn["validation"]["left_invalid"])

    def test_invalid_numeric_against_valid_number_is_mismatch(self):
        result = compare_records({"CGPA": "8.point5"}, {"cgpa": 8.5})
        cgpa = next(field for field in result["fields"] if field["field"] == "CGPA")

        self.assertEqual(cgpa["status"], "mismatch")
        self.assertEqual(cgpa["validation"], {"left_invalid": True, "right_invalid": False})

    def test_identical_unsupported_dates_are_mismatch(self):
        result = compare_records({"dob": "sometime in spring"}, {"DOB": "sometime in spring"})
        dob = next(field for field in result["fields"] if field["field"] == "DOB")

        self.assertEqual(dob["status"], "mismatch")
        self.assertEqual(dob["left_value"], "sometime in spring")
        self.assertIsNone(dob["left_normalized"])
        self.assertEqual(dob["validation"], {"left_invalid": True, "right_invalid": True})

    def test_genuinely_missing_values_remain_missing(self):
        result = compare_records(
            {"cgpa": None, "dob": "", "semester": float("nan")},
            {"CGPA": "null", "DOB": "2005-02-01", "Semester": 5},
        )
        fields = {entry["field"]: entry for entry in result["fields"]}

        self.assertEqual(fields["CGPA"]["status"], "missing")
        self.assertEqual(fields["DOB"]["status"], "missing")
        self.assertEqual(fields["Semester"]["status"], "missing")
        self.assertEqual(fields["CGPA"]["validation"], {"left_invalid": False, "right_invalid": False})

    def test_original_dates_and_invalid_outputs_are_json_serializable(self):
        result = compare_records(
            {"dob": date(2005, 2, 1), "cgpa": float("nan")},
            {"DOB": "01/02/2005", "CGPA": "invalid"},
        )
        fields = {entry["field"]: entry for entry in result["fields"]}

        self.assertEqual(fields["DOB"]["left_value"], "2005-02-01")
        self.assertEqual(fields["DOB"]["left_normalized"], "2005-02-01")
        self.assertIsNone(fields["CGPA"]["left_value"])
        json.dumps(result)


def _field_status(comparison, field_name):
    return next(item["status"] for item in comparison["fields"] if item["field"] == field_name)


if __name__ == "__main__":
    unittest.main()
