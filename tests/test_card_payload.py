import itertools
import unittest

from main import _parse_card_payload


class CardPayloadTests(unittest.TestCase):
    def test_accepts_every_header_order(self):
        company = "ジーアールインベストメント株式会社"
        employee = "NGUYEN DANG THAI"
        branch = "麺亭 しま田"

        for header in itertools.permutations((company, employee, branch)):
            with self.subTest(header=header):
                payload = _parse_card_payload("\n".join((*header, "", "Bao cao")))
                self.assertEqual(payload["company_name"], company)
                self.assertEqual(payload["employee_name"], employee)
                self.assertEqual(payload["branch_name"], branch)
                self.assertEqual(payload["report_text"], "Bao cao")

    def test_ignores_blank_lines_and_non_breaking_spaces_in_header(self):
        payload = _parse_card_payload(
            "\nジーアールインベストメント株式会社\u00a0\n\n"
            "NGUYEN DANG THAI\u00a0\n\n麺亭 しま田\n\nDong 1\n\nDong 2"
        )
        self.assertEqual(payload["company_name"], "ジーアールインベストメント株式会社")
        self.assertEqual(payload["employee_name"], "NGUYEN DANG THAI")
        self.assertEqual(payload["branch_name"], "麺亭 しま田")
        self.assertEqual(payload["report_text"], "Dong 1\n\nDong 2")

    def test_legacy_unmarked_company_order_remains_supported(self):
        payload = _parse_card_payload("ラムラ\nNGUYEN ANH HAO\n新宿店\nNoi dung")
        self.assertEqual(payload["company_name"], "ラムラ")
        self.assertEqual(payload["branch_name"], "新宿店")

    def test_rejects_ambiguous_employee_names(self):
        with self.assertRaisesRegex(ValueError, "duy nhat ho ten"):
            _parse_card_payload("COMPANY NAME\nNGUYEN VAN A\nTRAN VAN B\nNoi dung")

    def test_uppercase_english_company_is_not_an_employee(self):
        payload = _parse_card_payload("ABC COMPANY LTD\nTOKYO STORE\nNGUYEN VAN A\nNoi dung")
        self.assertEqual(payload["company_name"], "ABC COMPANY LTD")
        self.assertEqual(payload["employee_name"], "NGUYEN VAN A")
        self.assertEqual(payload["branch_name"], "TOKYO STORE")


if __name__ == "__main__":
    unittest.main()
