import random
from typing import Iterable
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

FIRST_INTERVAL = (0.0, 0.1)
SECOND_INTERVAL = (0.1, 0.2)
THIRD_INTERVAL = (0.2, 0.4)

FIRST_INTERVAL_PROBABILITY = 0.377
SECOND_INTERVAL_PROBABILITY = 0.5492
THIRD_INTERVAL_PROBABILITY = 1 - (FIRST_INTERVAL_PROBABILITY + SECOND_INTERVAL_PROBABILITY)

class KeyboardUtils:
	def __init__(self, driver: webdriver.Edge):
		self.driver = driver

	def send_keys(self, keys: Iterable[str]):
		actions = ActionChains(self.driver, duration=0)

		for key in keys:
			actions.send_keys(key)

			interval = random.choices(
				[FIRST_INTERVAL, SECOND_INTERVAL, THIRD_INTERVAL],
				weights=[FIRST_INTERVAL_PROBABILITY, SECOND_INTERVAL_PROBABILITY, THIRD_INTERVAL_PROBABILITY]
			)[0]

			actions.pause(random.uniform(interval[0], interval[1]))

		actions.perform()

	def clear(self):
		"""Empty the focused field with Ctrl+A and Delete.

		The search box's own clear button was the old way, and the pointer
		click on it missed often enough to leave the previous query in the box
		and concatenate the next one onto it (#59). Select-all and delete does
		not care how large or where that button is.
		"""
		actions = ActionChains(self.driver, duration=0)
		actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE)
		actions.perform()