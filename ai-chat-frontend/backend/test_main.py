import os
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend import main


class ChatRequestTests(unittest.TestCase):
    def test_strips_message_and_history_content(self) -> None:
        request = main.ChatRequest(
            message="  hello  ",
            history=[{"role": "user", "content": "  earlier message  "}],
        )

        self.assertEqual(request.message, "hello")
        self.assertEqual(request.history[0].content, "earlier message")

    def test_rejects_blank_message(self) -> None:
        with self.assertRaises(ValidationError):
            main.ChatRequest(message="   ")


class ChatEndpointTests(unittest.TestCase):
    def tearDown(self) -> None:
        main._genai_client = None

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("backend.main.genai.Client")
    def test_sends_conversation_and_returns_reply(self, client_factory: Mock) -> None:
        client = client_factory.return_value
        client.models.generate_content.return_value.text = "A useful answer"
        request = main.ChatRequest(
            message="What next?",
            history=[
                {"role": "user", "content": "I finished the lab."},
                {"role": "model", "content": "Great work."},
            ],
        )

        result = main.chat(request)

        self.assertEqual(result, {"reply": "A useful answer"})
        client_factory.assert_called_once_with(api_key="test-key")
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], main.MODEL_NAME)
        self.assertEqual(
            [(item.role, item.parts[0].text) for item in call["contents"]],
            [
                ("user", "I finished the lab."),
                ("model", "Great work."),
                ("user", "What next?"),
            ],
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_reports_missing_api_key(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            main.get_genai_client()

        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
