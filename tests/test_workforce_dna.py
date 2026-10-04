import unittest

from tak_workforce import ContentDNA, MarketingDNA


class WorkforceDNATests(unittest.TestCase):
    def test_content_dna_round_trip_keeps_unmeasured_fields_null(self):
        record = ContentDNA.from_mapping(
            {
                "content_id": "content-1",
                "platform": "threads",
                "language": "ko",
                "format": "text_post",
                "hook_type": "curiosity",
                "storytelling": True,
                "cta_type": "question",
            }
        )
        data = record.to_dict()
        self.assertEqual(data["hook_type"], "curiosity")
        self.assertTrue(data["storytelling"])
        self.assertIsNone(data["controversy"])
        self.assertEqual(ContentDNA.from_mapping(data), record)

    def test_marketing_dna_separates_discovery_from_conversion(self):
        record = MarketingDNA.from_mapping(
            {
                "content_id": "content-2",
                "platform": "youtube",
                "language": "en",
                "discovery": True,
                "click": True,
                "conversion": False,
                "cta": "free trial",
                "funnel_stage": "consideration",
            }
        )
        data = record.to_dict()
        self.assertTrue(data["discovery"])
        self.assertFalse(data["conversion"])
        self.assertIsNone(data["share"])
        self.assertEqual(MarketingDNA.from_mapping(data), record)

    def test_dna_rejects_wrong_boolean_type_and_missing_content_reference(self):
        with self.assertRaises(ValueError):
            ContentDNA.from_mapping({"content_id": "content-1", "curiosity": "yes"})
        with self.assertRaises(ValueError):
            MarketingDNA.from_mapping({"click": True})


if __name__ == "__main__":
    unittest.main()