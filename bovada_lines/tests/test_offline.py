import unittest

from gambling.cli import audit, chicago_date, replay, research_parlays


class FrozenNov11Regression(unittest.TestCase):
    def test_sqlite_integrity(self):
        meta = audit()
        self.assertEqual(meta['integrity'], 'ok')
        self.assertEqual(meta['foreign_key_errors'], 0)

    def test_batch_and_record_counts(self):
        meta = audit()
        self.assertEqual(meta['counts']['capture_batches'], 28)
        self.assertEqual(meta['counts']['events'], 1156)
        self.assertEqual(meta['counts']['market_quotes'], 6936)
        self.assertEqual(meta['counts']['model_scores'], 10173)
        self.assertEqual(meta['counts']['settlements'], 148)

    def test_original_quote_cohort(self):
        snapshot = replay('2026-11-11')
        self.assertEqual(snapshot['games'], 41)
        self.assertEqual(snapshot['status_counts']['PRODUCTION_QUALIFIED'], 11)

    def test_parlay_pricing_not_verified(self):
        observations = research_parlays('2026-11-11', limit=500)
        self.assertEqual(observations['total'], 88)
        for entry in observations['rows']:
            self.assertEqual(entry['authorization'], 'RESEARCH_ONLY')
            self.assertEqual(entry['quote_status'], 'MULTILEG_OFFER_NOT_VERIFIED')
            self.assertEqual(entry['adjusted_kelly_status'], 'SIZING_BLOCKED')
            self.assertEqual(len(set(entry['leg_event_keys'].split('|'))), int(entry['legs']))

    def test_central_date_conversion(self):
        self.assertEqual(chicago_date('2026-11-12T01:00:00Z'), '2026-11-11')


if __name__ == '__main__':
    unittest.main()
