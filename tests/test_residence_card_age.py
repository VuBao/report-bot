import unittest
from datetime import date
from unittest.mock import Mock, patch

from config.sheet_config import FORM_AGE_CELL, FORM_DATE_CELL, FORM_DOB_CELL
from services.residence_card_service import (
    _calculate_age,
    _write_residence_card_form_once,
)


class ResidenceCardAgeTests(unittest.TestCase):
    def test_age_increments_on_birthday_not_at_start_of_year(self):
        birthday = "2001年09月17日"

        self.assertEqual(_calculate_age(birthday, date(2026, 9, 16)), 24)
        self.assertEqual(_calculate_age(birthday, date(2026, 9, 17)), 25)
        self.assertEqual(_calculate_age(birthday, date(2026, 9, 18)), 25)

    def test_february_29_birthday_increments_on_march_1_in_non_leap_year(self):
        birthday = "2004年02月29日"

        self.assertEqual(_calculate_age(birthday, date(2026, 2, 28)), 21)
        self.assertEqual(_calculate_age(birthday, date(2026, 3, 1)), 22)

    def test_future_birth_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "tuong lai"):
            _calculate_age("2027年01月01日", date(2026, 9, 16))

    @patch("services.residence_card_service._japan_today")
    @patch("services.residence_card_service._verify_form_layout")
    @patch("services.residence_card_service._find_worksheet_exact")
    @patch("services.residence_card_service._get_client")
    def test_form_writes_age_to_c4_using_same_date_as_report(
        self,
        get_client,
        find_worksheet,
        verify_form_layout,
        japan_today,
    ):
        japan_today.return_value = date(2026, 9, 16)
        worksheet = Mock(id=123, title="LUONG THI THUY NHI")
        spreadsheet = Mock()
        get_client.return_value.open_by_key.return_value = spreadsheet
        find_worksheet.return_value = worksheet

        written = {}

        def capture_updates(updates, **_kwargs):
            written.update({item["range"]: item["values"][0][0] for item in updates})

        def read_back(ranges):
            return [
                {"range": f"FORMAT!{cell}", "values": [[written[cell]]]}
                for cell in ranges
            ]

        worksheet.batch_update.side_effect = capture_updates
        worksheet.batch_get.side_effect = read_back

        _write_residence_card_form_once(
            "spreadsheet-id",
            "株式会社standorm",
            "にぼし香早稲田店",
            {
                "full_name": "LUONG THI THUY NHI",
                "date_of_birth": "2001年07月18日",
                "address": "東京都豊島区",
                "visa_expiry": "2026年12月21日",
            },
            "current",
            "future",
        )

        self.assertEqual(written[FORM_DOB_CELL], "2001年07月18日")
        self.assertEqual(written[FORM_AGE_CELL], "25")
        self.assertEqual(written[FORM_DATE_CELL], "作成日：2026年09月16日")
        verify_form_layout.assert_called_once_with(spreadsheet, worksheet)


if __name__ == "__main__":
    unittest.main()
