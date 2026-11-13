"""Tests for counting only searches that actually reached a results page.

The failure these replay: a run logged "Round 1: 20 searches -> 0/60" while
Bing had recorded none of them. Typing and Enter succeed even when the search
box does not have the focus, so the batch counted attempts, the task reported
[OK], and nothing in the log said no search had happened (#59, #80).

The batch now clicks the box, clears it, types, and counts a query only when
the URL becomes a Bing results page for it. These tests use a driver that
remembers where it is and a keyboard that can be told not to navigate.

	python -m unittest discover -s tests
"""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import rewards_tasks

BING_HOME = "https://www.bing.com/"


class SearchDriver:
	def __init__(self, url=BING_HOME):
		self.current_url = url
		self.visited = []

	def get(self, url):
		self.visited.append(url)
		self.current_url = url


class TypingKeyboard:
	"""Records what was typed, and navigates unless the query is stuck.

	stuck is what a page that is not listening looks like: the characters and
	Enter go out, the browser stays where it was, and nothing raises.
	"""

	def __init__(self, driver, stuck=()):
		self.driver = driver
		self.typed = []
		self.clears = 0
		self.stuck = set(stuck)

	def clear(self):
		self.clears += 1

	def send_keys(self, keys):
		self.typed.append(keys)
		query = keys.split(" -noai", 1)[0]

		if query in self.stuck:
			return

		self.driver.current_url = "https://www.bing.com/search?q=" + query.replace(" ", "+")


def make_tasks(driver, keyboard):
	tasks = rewards_tasks.RewardsTaskUtils.__new__(rewards_tasks.RewardsTaskUtils)
	tasks.driver = driver
	tasks.tab_utils = types.SimpleNamespace(ensure_focus=lambda: None)
	tasks.elements = types.SimpleNamespace(get_bing_search_bar=lambda: "search bar")
	tasks.keyboard = keyboard
	tasks.mouse = types.SimpleNamespace(
		move_to_element=lambda element: None,
		human_like_click=lambda: None,
	)
	tasks.search_result_timeout = 0.05
	tasks.dismissals = 0

	def dismiss(timeout=3):
		tasks.dismissals += 1

		return False

	tasks.dismiss_cookie_consent = dismiss

	return tasks


class SearchBatchTests(unittest.TestCase):
	def setUp(self):
		# The batch pauses between searches to look human.
		sleep = mock.patch.object(rewards_tasks.time, "sleep", lambda seconds: None)
		sleep.start()
		self.addCleanup(sleep.stop)

	def _queries(self, queries):
		return mock.patch.object(rewards_tasks.queries, "related_queries", lambda count: list(queries))

	def test_a_query_that_reaches_a_results_page_is_counted(self):
		driver = SearchDriver()
		tasks = make_tasks(driver, TypingKeyboard(driver))

		with self._queries(["one", "two", "three"]):
			sent = tasks.run_search_batch(3)

		self.assertEqual(sent, 3)
		self.assertEqual(driver.visited, [BING_HOME, rewards_tasks.REWARDS_HOME_URL])
		self.assertEqual(tasks.progress, "sent 3 searches")

	def test_the_search_box_is_clicked_and_cleared_before_every_query(self):
		# Clicks are the fix for focus (#80); Ctrl+A+Delete is the fix for
		# concatenated queries (#59).
		driver = SearchDriver()
		keyboard = TypingKeyboard(driver)
		tasks = make_tasks(driver, keyboard)
		clicks = []
		tasks.mouse = types.SimpleNamespace(
			move_to_element=lambda element: clicks.append(element),
			human_like_click=lambda: None,
		)

		with self._queries(["one", "two"]):
			tasks.run_search_batch(2)

		self.assertEqual(clicks, ["search bar", "search bar"])
		self.assertEqual(keyboard.clears, 2)
		self.assertTrue(all(" -noai" in keys for keys in keyboard.typed))

	def test_a_query_that_lands_nowhere_is_retried_and_counted(self):
		driver = SearchDriver()
		keyboard = TypingKeyboard(driver)
		attempts = {"one": 0}
		normal = keyboard.send_keys

		def flaky(keys):
			query = keys.split(" -noai", 1)[0]

			if query != "one":
				normal(keys)

				return

			keyboard.typed.append(keys)
			attempts["one"] += 1

			if attempts["one"] == 2:
				driver.current_url = "https://www.bing.com/search?q=one"

		keyboard.send_keys = flaky
		tasks = make_tasks(driver, keyboard)

		with self._queries(["one", "two"]):
			sent = tasks.run_search_batch(2)

		self.assertEqual(sent, 2)
		self.assertEqual(attempts["one"], 2)
		# Once on arriving at bing.com, once before the retry.
		self.assertEqual(tasks.dismissals, 2)

	def test_a_later_query_that_never_navigates_is_skipped(self):
		driver = SearchDriver()
		keyboard = TypingKeyboard(driver, stuck={"two"})
		tasks = make_tasks(driver, keyboard)

		with self._queries(["one", "two", "three"]):
			with self.assertLogs(rewards_tasks.logger, level="WARNING") as logged:
				sent = tasks.run_search_batch(3)

		self.assertEqual(sent, 2)
		# one, two, two again for the retry, three.
		self.assertEqual(len(keyboard.typed), 4)
		self.assertIn("'two'", "\n".join(logged.output))

	def test_a_page_that_never_takes_input_fails_the_batch_at_once(self):
		driver = SearchDriver()
		keyboard = TypingKeyboard(driver, stuck={"one"})
		tasks = make_tasks(driver, keyboard)

		with self._queries(["one", "two"]):
			with self.assertRaises(rewards_tasks.SearchNeverSubmitted) as caught:
				tasks.run_search_batch(2)

		self.assertIn("'one'", str(caught.exception))
		self.assertIn(BING_HOME, str(caught.exception))
		# The retry, and nothing after it: nineteen more failures would only
		# spend minutes.
		self.assertEqual(len(keyboard.typed), 2)

	def test_a_source_with_no_queries_fails_instead_of_reporting_ok(self):
		driver = SearchDriver()
		tasks = make_tasks(driver, TypingKeyboard(driver))

		with self._queries([]):
			with self.assertRaises(rewards_tasks.SearchNeverSubmitted):
				tasks.run_search_batch(3)

	def test_an_unchanged_results_page_is_not_a_new_search(self):
		# On a results page the search box already holds the previous query, so
		# /search in the URL proves nothing unless the URL changed.
		previous = "https://www.bing.com/search?q=previous"
		tasks = make_tasks(SearchDriver(url=previous), TypingKeyboard(SearchDriver()))

		self.assertFalse(tasks._wait_for_search_results(previous, 0.05))


if __name__ == "__main__":
	unittest.main()
