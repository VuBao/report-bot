import base64
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from services.residence_card_service import (
    _address_needs_recheck,
    _build_address_crop_content,
    _merge_address_recheck,
    extract_residence_card,
    validate_card,
)


def _card(
    address="東京都北区中里2丁目22番10-301号 アンビハイツ",
    confidence=0.99,
    address_confidence=None,
):
    if address_confidence is None:
        address_confidence = confidence
    return {
        "document_type": "residence_card",
        "front_detected": True,
        "back_detected": False,
        "address_review_required": False,
        "front_image_index": 0,
        "back_image_index": None,
        "full_name": {"value": "NGUYEN VAN HUY", "confidence": confidence},
        "date_of_birth": {"value": "1995年01月02日", "confidence": confidence},
        "front_address": {"value": address, "confidence": address_confidence},
        "back_address_entries": [],
        "visa_expiry": {"value": "2027年12月31日", "confidence": confidence},
    }


def _address_check(
    address="東京都北区中里2丁目22番10-301号 アンビハイツ",
    confidence=0.99,
):
    return {
        "front_address": {"value": address, "confidence": confidence},
        "back_address_entries": [],
    }


def _jpeg_bytes(width=1600, height=1000):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="JPEG")
    return output.getvalue()


class ResidenceCardOcrTests(unittest.TestCase):
    def test_rejects_one_character_level_address_disagreement(self):
        first = _card("東京都北区中里2丁目22番10-301号 アンビハイツ")
        second = _address_check("東京都北区中里2丁目22番10-301号 アンビシャス")

        with self.assertRaisesRegex(ValueError, "dia chi mat truoc"):
            _merge_address_recheck(first, second)

    def test_confident_address_does_not_need_recheck(self):
        self.assertFalse(_address_needs_recheck(_card()))

    def test_model_doubt_or_low_confidence_needs_recheck(self):
        doubtful = _card()
        doubtful["address_review_required"] = True
        self.assertTrue(_address_needs_recheck(doubtful))
        self.assertTrue(_address_needs_recheck(_card(address_confidence=0.79)))

    def test_two_images_always_include_possible_back_address_crop(self):
        first = _card()
        first["back_detected"] = False

        content = _build_address_crop_content([_jpeg_bytes(), _jpeg_bytes()], first)

        self.assertEqual(content[0]["text"], "FRONT ADDRESS CROP")
        self.assertEqual(content[2]["text"], "BACK ADDRESS CROP")

    def test_uses_lower_confidence_from_two_matching_passes(self):
        verified = _merge_address_recheck(
            _card(confidence=0.98),
            _address_check(confidence=0.81),
        )

        self.assertEqual(verified["front_address"]["confidence"], 0.81)
        self.assertEqual(
            validate_card(verified, "NGUYEN VAN HUY")["address"],
            "東京都北区中里2丁目22番10-301号 アンビハイツ",
        )

    def test_rejects_low_address_confidence(self):
        verified = _merge_address_recheck(
            _card(confidence=0.99),
            _address_check(confidence=0.79),
        )

        with self.assertRaisesRegex(ValueError, "front_address"):
            validate_card(verified, "NGUYEN VAN HUY")

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_extract_confident_first_pass_skips_second_call(self, openai_client):
        first_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_card())))]
        )
        create = Mock(return_value=first_response)
        openai_client.return_value.chat.completions.create = create

        result = extract_residence_card([_jpeg_bytes()])

        self.assertEqual(result["front_address"]["value"], _card()["front_address"]["value"])
        self.assertEqual(create.call_count, 1)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_uncertain_first_pass_uses_enlarged_address_crop(self, openai_client):
        uncertain = _card(
            address="東京都北区中里2丁目22番10-301号 アンビシャス",
            address_confidence=0.60,
        )
        first_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(uncertain)))]
        )
        second_response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(_address_check()))
            )]
        )
        create = Mock(side_effect=[first_response, second_response])
        openai_client.return_value.chat.completions.create = create

        original = _jpeg_bytes()
        result = extract_residence_card([original])

        self.assertEqual(result["front_address"]["value"], _card()["front_address"]["value"])
        self.assertEqual(create.call_count, 2)
        first_prompt = create.call_args_list[0].kwargs["messages"][0]["content"]
        second_prompt = create.call_args_list[1].kwargs["messages"][0]["content"]
        self.assertNotEqual(first_prompt, second_prompt)

        second_content = create.call_args_list[1].kwargs["messages"][1]["content"]
        self.assertEqual(second_content[0]["text"], "FRONT ADDRESS CROP")
        crop_url = second_content[1]["image_url"]["url"]
        crop_bytes = base64.b64decode(crop_url.split(",", 1)[1])
        with Image.open(io.BytesIO(crop_bytes)) as crop:
            self.assertGreater(crop.width, crop.height)
            self.assertGreater(crop.width, 3000)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_explicit_model_doubt_triggers_recheck_and_uses_crop_result(
        self, openai_client
    ):
        doubtful = _card()
        doubtful["address_review_required"] = True
        first_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(doubtful)))]
        )
        second_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(
                _address_check("東京都北区中里2丁目22番10-301号 アンビシャス")
            )))]
        )
        create = Mock(side_effect=[first_response, second_response])
        openai_client.return_value.chat.completions.create = create

        result = extract_residence_card([_jpeg_bytes()])

        self.assertEqual(create.call_count, 2)
        self.assertEqual(
            result["front_address"]["value"],
            "東京都北区中里2丁目22番10-301号 アンビシャス",
        )
        self.assertFalse(result["address_review_required"])


if __name__ == "__main__":
    unittest.main()
