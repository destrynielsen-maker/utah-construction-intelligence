import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from utah_permits.feeds import write_feed
from utah_permits.models import Permit


class FeedTests(unittest.TestCase):
    def test_feed_is_valid_xml(self):
        p = Permit(
            state="UT",
            jurisdiction="Orem",
            permit_number="26-1234",
            issued_date="2026-08-01",
            permit_type="Single Family Dwelling",
            address="100 Main St",
            source_name="test",
            source_url="https://example.com/source",
            classification="SINGLE_FAMILY",
            qualifies=True,
            score=25,
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "feed.xml"
            write_feed(path, [p], "Test", "Test feed", "https://example.com/")
            tree = ET.parse(path)
            self.assertEqual(tree.getroot().tag, "rss")
            self.assertEqual(tree.findtext("./channel/item/guid"), p.key)


if __name__ == "__main__":
    unittest.main()
