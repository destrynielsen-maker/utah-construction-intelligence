from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.springville import SpringvilleCollector


class SpringvilleCollectorTests(unittest.TestCase):
    def test_parses_structured_development_inventory_and_units(self) -> None:
        features = [
            {
                "attributes": {
                    "OBJECTID": 10,
                    "Name": "Lakeside Landing Subdivision",
                    "Status": "Proposed Residential Subdivision",
                    "Description": "139 Units",
                }
            },
            {
                "attributes": {
                    "OBJECTID": 11,
                    "Name": "Springville Towns",
                    "Status": "Proposed Residential Subdivision",
                    "Description": "25 Units",
                }
            },
            {
                "attributes": {
                    "OBJECTID": 30,
                    "Name": "Powerhouse Industrial Park",
                    "Status": "Commercial Development",
                    "Description": "2 Lot, 550,819 Sq. Ft. Total Office/Warehouse",
                }
            },
        ]

        permits = SpringvilleCollector.parse_features(features)
        self.assertEqual(3, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertEqual(139, by_name["Lakeside Landing Subdivision"].units)
        self.assertEqual(25, by_name["Springville Towns"].units)
        self.assertEqual(2, by_name["Powerhouse Industrial Park"].units)
        self.assertEqual("", by_name["Powerhouse Industrial Park"].issued_date)
        self.assertEqual(
            "undated_source_inventory",
            by_name["Powerhouse Industrial Park"].raw["date_semantics"],
        )

    def test_springville_inventory_never_qualifies_as_issued_permits(self) -> None:
        permit = SpringvilleCollector.parse_features(
            [
                {
                    "attributes": {
                        "OBJECTID": 33,
                        "Name": "Spring Pointe Distribution Center",
                        "Status": "Commercial Development",
                        "Description": "186,872 Sq. Ft. Distribution Warehouse",
                    }
                }
            ]
        )[0]

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)


if __name__ == "__main__":
    unittest.main()
