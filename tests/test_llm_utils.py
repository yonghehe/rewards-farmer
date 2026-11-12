"""Tests for where and how the LLM request is sent.

The interesting case is the local/Ollama one. qwen3.5 and other thinking
models reason before answering, and the thinking budget is wasted here: the
model only has to produce a short search query. Setting LLM_THINK=false has to
reach Ollama's native /api/chat, because that is the endpoint that honours
think=false; /v1/chat/completions does not reliably do so.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import llm_utils


class FakeResponse:
	def __init__(self, payload):
		self.payload = payload

	def raise_for_status(self):
		return None

	def json(self):
		return self.payload


def chat_completion(content: str) -> FakeResponse:
	return FakeResponse({"choices": [{"message": {"content": content}}]})


def ollama_chat(content: str, thinking: str = "") -> FakeResponse:
	return FakeResponse({"message": {"role": "assistant", "content": content, "thinking": thinking}})


@mock.patch.object(llm_utils, "DEFAULT_LLM_PROVIDER", "local")
class LocalThinkingTests(unittest.TestCase):
	def environment(self, **values):
		values.setdefault("LOCAL_LLM_BASE_URL", "http://192.168.10.58:11434/v1")
		values.setdefault("LOCAL_LLM_MODEL", "qwen3.5:0.8b")
		return mock.patch.dict(os.environ, values, clear=False)

	def test_without_llm_think_the_openai_endpoint_is_unchanged(self):
		with self.environment(LLM_THINK=""), mock.patch(
			"llm_utils.requests.post", return_value=chat_completion("cats")
		) as post:
			answer = llm_utils.get_llm_response([{"role": "user", "content": "hi"}])

		self.assertEqual(answer, "cats")

		url = post.call_args.args[0]
		self.assertTrue(url.endswith("/v1/chat/completions"), url)
		self.assertNotIn("think", post.call_args.kwargs["json"])

	def test_llm_think_false_uses_the_native_chat_endpoint(self):
		with self.environment(LLM_THINK="false"), mock.patch(
			"llm_utils.requests.post", return_value=ollama_chat("cats", thinking="thinking...")
		) as post:
			answer = llm_utils.get_llm_response([{"role": "user", "content": "hi"}])

		self.assertEqual(answer, "cats")

		url = post.call_args.args[0]
		self.assertEqual(url, "http://192.168.10.58:11434/api/chat")

		body = post.call_args.kwargs["json"]
		self.assertIs(body["think"], False)
		self.assertEqual(body["model"], "qwen3.5:0.8b")
		self.assertIs(body["stream"], False)

	def test_a_named_level_is_passed_through_untouched(self):
		with self.environment(LLM_THINK="low"), mock.patch(
			"llm_utils.requests.post", return_value=ollama_chat("cats")
		) as post:
			llm_utils.get_llm_response([{"role": "user", "content": "hi"}])

		self.assertEqual(post.call_args.kwargs["json"]["think"], "low")

	def test_an_ollama_error_is_raised_rather_than_read_as_an_answer(self):
		refused = FakeResponse({"error": "model 'qwen3.5:0.8b' not found"})

		with self.environment(LLM_THINK="false"), mock.patch(
			"llm_utils.requests.post", return_value=refused
		):
			with self.assertRaises(RuntimeError) as raised:
				llm_utils.get_llm_response([{"role": "user", "content": "hi"}])

		self.assertIn("not found", str(raised.exception))


@mock.patch.object(llm_utils, "DEFAULT_LLM_PROVIDER", "openrouter")
class RemoteProviderTests(unittest.TestCase):
	def test_llm_think_does_not_reroute_a_remote_provider(self):
		with mock.patch.dict(
			os.environ,
			{"LLM_THINK": "false", "OPENROUTER_API_KEY": "key"},
			clear=False,
		), mock.patch(
			"llm_utils.requests.post", return_value=chat_completion("cats")
		) as post:
			answer = llm_utils.get_llm_response([{"role": "user", "content": "hi"}])

		self.assertEqual(answer, "cats")
		self.assertTrue(post.call_args.args[0].endswith("/v1/chat/completions"))


if __name__ == "__main__":
	unittest.main()
