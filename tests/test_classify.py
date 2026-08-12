import unittest

from utah_permits.classify import classify_permit
from utah_permits.models import Permit


def permit(jurisdiction, permit_type, building_use=None, valuation=None, units=None, contractor=None):
    return Permit(
        state="UT",
        jurisdiction=jurisdiction,
        permit_number="TEST-1",
        issued_date="2026-08-01",
        permit_type=permit_type,
        building_use=building_use,
        valuation=valuation,
        units=units,
        contractor=contractor,
        address="1 Main St",
        source_name="test",
        source_url="https://example.com",
    )


class ClassificationTests(unittest.TestCase):
    def test_orem_single_family(self):
        p = classify_permit(permit("Orem", "Single Family Dwelling", valuation=800000, contractor="Builder LLC"))
        self.assertTrue(p.qualifies)
        self.assertEqual(p.classification, "SINGLE_FAMILY")
        self.assertGreaterEqual(p.score, 25)

    def test_orem_remodel_excluded(self):
        p = classify_permit(permit("Orem", "Remodel (C)", valuation=5000000))
        self.assertFalse(p.qualifies)
        self.assertEqual(p.score, 0)

    def test_summit_multifamily(self):
        p = classify_permit(permit("Summit County", "Residential: Multi-Family (Apartments or Condominiums) (IBC)"))
        self.assertTrue(p.qualifies)
        self.assertEqual(p.classification, "MULTIFAMILY")

    def test_summit_utility_excluded(self):
        p = classify_permit(permit("Summit County", "Residential: Utility Replacement/Upgrade"))
        self.assertFalse(p.qualifies)

    def test_provo_mfr_new(self):
        p = classify_permit(permit("Provo", "New Construction - Apartments", building_use="MFR", units=120, valuation=25000000, contractor="GC LLC"))
        self.assertTrue(p.qualifies)
        self.assertEqual(p.classification, "MULTIFAMILY")
        self.assertGreaterEqual(p.score, 80)

    def test_provo_mfr_remodel_excluded(self):
        p = classify_permit(permit("Provo", "Interior Remodel", building_use="MFR"))
        self.assertFalse(p.qualifies)


if __name__ == "__main__":
    unittest.main()
