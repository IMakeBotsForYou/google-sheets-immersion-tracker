import unittest

from immersion_tracker.durations import parse_card_count, parse_duration


class ParseDurationTests(unittest.TestCase):
    def test_understood(self):
        cases = {
            "10 דקות": 10, "1 שעה": 60, "1 שעה ו-20 דקות": 80, "1.5 שעות": 90, "1:35": 95, "90": 90, "0": 0,
            "שעה": 60, "רבע": 15, "חצי": 30, "שעה ורבע": 75, "שעה וחצי": 90, "2 שעות וחצי": 150,
            "חצי שעה": 30, "רבע שעה": 15, "אין": 0, "45 (בערך)": 45,
        }
        for text, minutes in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), minutes)

    def test_not_understood(self):
        for text in ["", "כמה שיכולתי", "1 שעה 35"]:      # the last one: unit missing, we refuse to guess
            with self.subTest(text=text):
                self.assertIsNone(parse_duration(text))


class ParseCardCountTests(unittest.TestCase):
    def test_understood(self):
        cases = {"120": 120, "20 קלפים": 20, "400+ קלפים": 400, "קלפים 20": 20, "20 קלפים (=20 חדשים)": 20,
                 "1,200 cards": 1200, "0": 0, "אין": 0}
        for text, cards in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_card_count(text), cards)

    def test_not_understood(self):
        self.assertIsNone(parse_card_count("הרבה"))


if __name__ == "__main__":
    unittest.main()
