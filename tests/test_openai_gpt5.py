import unittest
from unittest.mock import Mock, patch

from services.ai_service import (
    AIResponseFormatError,
    _call_ai,
    _call_openai,
    generate_report,
)
from utils.openai_compat import build_chat_completion_kwargs


class OpenAiGpt5CompatibilityTests(unittest.TestCase):
    def test_gpt5_uses_reasoning_compatible_parameters(self):
        kwargs = build_chat_completion_kwargs(
            model="gpt-5",
            messages=[],
            max_tokens=2500,
            temperature=0.2,
            reasoning_effort="medium",
        )

        self.assertEqual(kwargs["max_completion_tokens"], 2500)
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertNotIn("max_tokens", kwargs)
        self.assertNotIn("temperature", kwargs)

    def test_gpt4o_keeps_legacy_parameters(self):
        kwargs = build_chat_completion_kwargs(
            model="gpt-4o",
            messages=[],
            max_tokens=1000,
            temperature=0.2,
            reasoning_effort="medium",
        )

        self.assertEqual(kwargs["max_tokens"], 1000)
        self.assertEqual(kwargs["temperature"], 0.2)
        self.assertNotIn("max_completion_tokens", kwargs)
        self.assertNotIn("reasoning_effort", kwargs)

    @patch("services.ai_service._call_openai", return_value="{}")
    @patch("services.ai_service._select_provider", return_value="openai")
    def test_extra_reasoning_budget_only_applies_to_gpt5(
        self, _select_provider, call_openai
    ):
        common = {
            "system_prompt": "system",
            "user_content": "user",
            "max_tokens": 1000,
            "anthropic_model": "fallback",
            "gpt5_max_completion_tokens": 2500,
        }

        _call_ai(openai_model="gpt-5", **common)
        self.assertEqual(call_openai.call_args.args[2], 2500)

        _call_ai(openai_model="gpt-4o", **common)
        self.assertEqual(call_openai.call_args.args[2], 1000)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_text_call_sends_gpt5_compatible_payload(self, openai_client):
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"ok": true}'))]
        create = Mock(return_value=response)
        openai_client.return_value.chat.completions.create = create

        result = _call_openai("system", "user", 2500, "gpt-5", 0.2, "medium")

        self.assertEqual(result, '{"ok": true}')
        sent = create.call_args.kwargs
        self.assertEqual(sent["max_completion_tokens"], 2500)
        self.assertEqual(sent["reasoning_effort"], "medium")
        self.assertNotIn("temperature", sent)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_empty_text_response_recovers_with_minimal_reasoning(self, openai_client):
        empty = Mock()
        empty.choices = [Mock(message=Mock(content=""), finish_reason="length")]
        empty.usage.completion_tokens = 2500
        empty.usage.completion_tokens_details.reasoning_tokens = 2500
        recovered = Mock()
        recovered.choices = [Mock(message=Mock(content='{"passed": true}'))]
        create = Mock(side_effect=[empty, recovered])
        openai_client.return_value.chat.completions.create = create

        result = _call_openai(
            "system",
            "user",
            2500,
            "gpt-5",
            reasoning_effort="low",
            recovery_max_tokens=4000,
            operation="report_review",
        )

        self.assertEqual(result, '{"passed": true}')
        self.assertEqual(create.call_count, 2)
        retry = create.call_args_list[1].kwargs
        self.assertEqual(retry["reasoning_effort"], "minimal")
        self.assertEqual(retry["max_completion_tokens"], 4000)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_invalid_text_response_stops_after_bounded_recovery(self, openai_client):
        invalid = Mock()
        invalid.choices = [Mock(message=Mock(content=""), finish_reason="length")]
        openai_client.return_value.chat.completions.create = Mock(
            side_effect=[invalid, invalid]
        )

        with self.assertRaisesRegex(AIResponseFormatError, "report_draft"):
            _call_openai(
                "system",
                "user",
                6000,
                "gpt-5",
                reasoning_effort="low",
                recovery_max_tokens=8000,
                operation="report_draft",
            )

        self.assertEqual(
            openai_client.return_value.chat.completions.create.call_count, 2
        )

    @patch.dict(
        "os.environ",
        {
            "OPENAI_MODEL": "gpt-5",
            "OPENAI_REPORT_MODEL": "gpt-5",
            "OPENAI_REVIEW_MODEL": "gpt-5",
        },
    )
    @patch("services.ai_service._call_ai")
    def test_report_and_review_use_separate_gpt5_reasoning_budgets(self, call_ai):
        call_ai.side_effect = [
            '{"current_situation":"現在は順調です。","future_plan":"継続予定です。"}',
            '{"passed":true,"issues":[],"summary":"一致"}',
        ]

        result = generate_report("仕事は順調。継続予定。", "NGUYEN VAN HUY")

        self.assertEqual(result["current_situation"], "現在は順調です。")
        draft = call_ai.call_args_list[0].kwargs
        review = call_ai.call_args_list[1].kwargs
        self.assertEqual(draft["openai_model"], "gpt-5")
        self.assertEqual(draft["max_tokens"], 4500)
        self.assertEqual(draft["gpt5_max_completion_tokens"], 6000)
        self.assertEqual(draft["openai_reasoning_effort"], "low")
        self.assertEqual(draft["gpt5_recovery_max_completion_tokens"], 8000)
        self.assertEqual(draft["operation"], "report_draft")
        self.assertEqual(review["openai_model"], "gpt-5")
        self.assertEqual(review["max_tokens"], 1000)
        self.assertEqual(review["gpt5_max_completion_tokens"], 2500)
        self.assertEqual(review["openai_reasoning_effort"], "low")
        self.assertEqual(review["gpt5_recovery_max_completion_tokens"], 4000)
        self.assertEqual(review["operation"], "report_review")


if __name__ == "__main__":
    unittest.main()
