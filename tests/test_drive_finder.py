import unittest
from unittest.mock import patch

from utils import drive_finder


class _FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class _FakeFilesResource:
    def __init__(self, children_by_parent):
        self.children_by_parent = children_by_parent
        self.queries = []

    def list(self, **kwargs):
        query = kwargs["q"]
        parent_id = query.split("'", 2)[1]
        self.queries.append((parent_id, kwargs))
        return _FakeRequest({"files": self.children_by_parent.get(parent_id, [])})


class _FakeDriveService:
    def __init__(self, children_by_parent):
        self.files_resource = _FakeFilesResource(children_by_parent)

    def files(self):
        return self.files_resource


class DriveFinderTests(unittest.TestCase):
    def setUp(self):
        drive_finder.clear_cache()

    def tearDown(self):
        drive_finder.clear_cache()

    def test_finds_company_spreadsheet_in_nested_month_folder(self):
        service = _FakeDriveService({
            "root-folder": [
                {
                    "id": "month-folder",
                    "name": "Tháng 9-10/2026",
                    "mimeType": drive_finder._FOLDER_MIME_TYPE,
                },
                {
                    "id": "copy-template",
                    "name": "AAAAAAAAAAAAAAA",
                    "mimeType": drive_finder._SPREADSHEET_MIME_TYPE,
                },
            ],
            "month-folder": [
                {
                    "id": "company-sheet",
                    "name": "株式会社 ルフォア",
                    "mimeType": drive_finder._SPREADSHEET_MIME_TYPE,
                }
            ],
        })

        with (
            patch.object(drive_finder, "_get_drive_service", return_value=service),
            patch.dict("os.environ", {"GOOGLE_DRIVE_FOLDER_ID": "root-folder"}),
        ):
            spreadsheet_id, name = drive_finder.find_spreadsheet_id_strict(
                "株式会社ルフォア"
            )

        self.assertEqual(spreadsheet_id, "company-sheet")
        self.assertEqual(name, "株式会社 ルフォア")
        self.assertEqual(
            {parent_id for parent_id, _ in service.files_resource.queries},
            {"root-folder", "month-folder"},
        )
        for _, kwargs in service.files_resource.queries:
            self.assertTrue(kwargs["includeItemsFromAllDrives"])
            self.assertTrue(kwargs["supportsAllDrives"])


if __name__ == "__main__":
    unittest.main()
