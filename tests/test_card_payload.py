import unittest

from main import _parse_card_payload


class CardPayloadTests(unittest.TestCase):
    def test_reads_header_in_company_branch_employee_order(self):
        payload = _parse_card_payload(
            "株式会社ルフォア\nLe Coquillage\nNGUYEN VAN HUY\n\nBao cao"
        )
        self.assertEqual(payload["company_name"], "株式会社ルフォア")
        self.assertEqual(payload["employee_name"], "NGUYEN VAN HUY")
        self.assertEqual(payload["branch_name"], "Le Coquillage")
        self.assertEqual(payload["report_text"], "Bao cao")

    def test_ignores_blank_lines_and_non_breaking_spaces_in_header(self):
        payload = _parse_card_payload(
            "\nジーアールインベストメント株式会社\u00a0\n\n"
            "麺亭 しま田\u00a0\n\nNGUYEN DANG THAI\n\nDong 1\n\nDong 2"
        )
        self.assertEqual(payload["company_name"], "ジーアールインベストメント株式会社")
        self.assertEqual(payload["employee_name"], "NGUYEN DANG THAI")
        self.assertEqual(payload["branch_name"], "麺亭 しま田")
        self.assertEqual(payload["report_text"], "Dong 1\n\nDong 2")

    def test_unmarked_company_uses_fixed_order(self):
        payload = _parse_card_payload("ラムラ\n新宿店\nNGUYEN ANH HAO\nNoi dung")
        self.assertEqual(payload["company_name"], "ラムラ")
        self.assertEqual(payload["employee_name"], "NGUYEN ANH HAO")
        self.assertEqual(payload["branch_name"], "新宿店")

    def test_rejects_employee_name_outside_third_line(self):
        with self.assertRaisesRegex(ValueError, "Dong thu ba"):
            _parse_card_payload("株式会社ルフォア\nNGUYEN VAN HUY\nLe Coquillage\nNoi dung")

    def test_accepts_uppercase_english_company_and_branch_in_fixed_order(self):
        payload = _parse_card_payload("ABC COMPANY LTD\nTOKYO STORE\nNGUYEN VAN A\nNoi dung")
        self.assertEqual(payload["company_name"], "ABC COMPANY LTD")
        self.assertEqual(payload["employee_name"], "NGUYEN VAN A")
        self.assertEqual(payload["branch_name"], "TOKYO STORE")


if __name__ == "__main__":
    unittest.main()
