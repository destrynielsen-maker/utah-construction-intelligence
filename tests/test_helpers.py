import unittest

from utah_permits.collectors.orem import OremCollector
from utah_permits.collectors.provo import ProvoCollector
from utah_permits.collectors.summit_county import SummitCountyCollector


class HelperTests(unittest.TestCase):
    def test_orem_money(self):
        self.assertEqual(OremCollector._money("$905,128.61"), 905128.61)

    def test_orem_date(self):
        self.assertEqual(OremCollector._iso_date("7/31/2026"), "2026-07-31")

    def test_summit_date(self):
        self.assertEqual(SummitCountyCollector._iso_date("1/2/2026"), "2026-01-02")

    def test_provo_epoch(self):
        self.assertEqual(ProvoCollector._epoch_date(0), "1970-01-01")


if __name__ == "__main__":
    unittest.main()
