import copy
import json
import unittest

from usage_regimes.application import ROOT
from usage_regimes.domain import run


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / 'fixtures/data.json').read_text())
        self.data = {key: [] for key in self.fixture['tables']}

    def test_fixture_is_deterministic_and_not_mutated(self):
        original = copy.deepcopy(self.fixture['tables'])
        options = {'cutoff': self.fixture['meta']['default_cutoff'], 'group': ''}
        first = run(self.fixture['tables'], options)
        second = run(self.fixture['tables'], options)
        self.assertEqual(first, second)
        self.assertEqual(original, self.fixture['tables'])
        self.assertTrue(first['rows'])
        json.dumps(first, allow_nan=False)

    def sample(self):
        first = dict(reading_id='r', site='甲', meter='m', start=0, end=1, mode='counter', value=10, revision=1, known_day=1)
        self.data['readings'] = [first, {**first, 'revision': 2, 'value': 12, 'known_day': 5}]
        self.data['conditions'] = [dict(site='甲', day=1, temperature=20, production='运行', known_day=1)]
        self.data['annotations'] = [dict(site='甲', boundary=1, status='confirmed', note='人工边界', known_day=2)]

    def test_revision_visibility(self):
        self.sample()
        early = run(self.data, {'cutoff': 2, 'group': ''})['rows'][0]
        later = run(self.data, {'cutoff': 5, 'group': ''})['rows'][0]
        self.assertEqual((early['value'], early['revision']), (10, 1))
        self.assertEqual((later['value'], later['revision']), (12, 2))

    def test_manual_annotation_survives_revision(self):
        self.sample()
        result = run(self.data, {'cutoff': 5, 'group': ''})
        self.assertEqual(result['summary']['人工备注'], 1)
        self.assertIn('人工边界', result['notes'][-1])

    def test_unknown_conditions_and_bad_interval(self):
        self.sample()
        self.data['conditions'] = []
        self.assertIsNone(run(self.data, {'cutoff': 2, 'group': ''})['rows'][0]['temperature'])
        self.data['readings'][0]['end'] = 0
        with self.assertRaises(ValueError):
            run(self.data, {'cutoff': 2, 'group': ''})
