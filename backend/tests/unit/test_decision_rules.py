import unittest
from datetime import date
from app.domain.decision import next_review, advance_streaks, decision_status, evidence_current

class DecisionRulesTest(unittest.TestCase):
    def test_same_class_and_direction(self):
        state = advance_streaks({}, {'a': 1}, True, '2026-10-01')
        state = advance_streaks(state, {'b': 1}, True, '2026-10-02')
        self.assertEqual(state['b']['count'], 1)
        self.assertEqual(state.get('a', {}).get('count', 0), 0)
        state = advance_streaks(state, {'b': -1}, True, '2026-10-03')
        self.assertEqual(state['b']['count'], 1)
    def test_invalid_breaks_streak(self):
        self.assertEqual(advance_streaks({'a': {'count': 2, 'direction': 1}}, {}, False, '2026-10-03'), {})
    def test_month_clamps_and_ack_moves_forward(self):
        self.assertEqual(next_review(date(2026, 2, 28), 31, None), (date(2026, 2, 28), True))
        self.assertEqual(next_review(date(2026, 2, 28), 31, '2026-02'), (date(2026, 3, 31), False))
    def test_data_precedence(self):
        self.assertEqual(decision_status(False, False, True, True, True), 'data_issue')
        self.assertEqual(decision_status(True, False, True, True, True), 'setup')

    def test_old_evidence_expires_after_one_day(self):
        self.assertFalse(evidence_current(date(2026, 10, 4), date(2026, 10, 1)))
        self.assertTrue(evidence_current(date(2026, 10, 2), date(2026, 10, 1)))
