import copy
import json
import unittest

from usage_regimes.application import ROOT
from usage_regimes.regimes import (
    analyze_regimes, build_series, detect_candidates, estimate_impact,
)


def synthetic_dataset(shift_day=41, shift=-18.0, days=90, seed=7):
    """构造气温/停工混杂 + 已知持续水平偏移的合成资料。

    用量 = 110 + 2*温度 - 30*停工 + 噪声，shift_day 起叠加 shift。
    """
    rng = LinearRandom(seed)
    readings = []
    conditions = []
    for day in range(1, days + 1):
        temperature = 15 + 10 * (0.5 + 0.5 * ((day * 37) % 13) / 12)
        stop = 1 if day % 7 in (5, 6) else 0
        noise = (rng.next_value() - 0.5) * 12
        usage = 110 + 2 * temperature - 30 * stop + noise + (shift if day >= shift_day else 0.0)
        readings.append({
            'reading_id': f'甲-{day}', 'site': '厂区甲', 'meter': '甲表',
            'start': day - 1, 'end': day, 'mode': 'interval',
            'value': round(usage, 2), 'revision': 1, 'known_day': day,
        })
        conditions.append({
            'site': '厂区甲', 'day': day,
            'temperature': round(temperature, 1),
            'production': '停工' if stop else '运行', 'known_day': day,
        })
    return {
        'readings': readings,
        'conditions': conditions,
        'meters': [{'meter': '甲表', 'site': '厂区甲', 'installed_day': 1, 'start_value': 0}],
        'annotations': [],
    }


class LinearRandom:
    def __init__(self, seed):
        self.state = seed & 0xffffffff

    def next_value(self):
        # xorshift32：周期 2^32-1，避免短周期伪噪声制造出假转折。
        x = self.state
        x ^= (x << 13) & 0xffffffff
        x ^= x >> 17
        x ^= (x << 5) & 0xffffffff
        self.state = x & 0xffffffff
        return self.state / 0xffffffff


class RegimeTests(unittest.TestCase):
    def test_persistent_shift_is_detected_after_covariate_adjustment(self):
        data = synthetic_dataset()
        series, segments, notes = build_series(data, 90)
        candidates = detect_candidates(series, segments)
        self.assertTrue(candidates, '应识别出持续水平偏移')
        nearest = min(candidates, key=lambda row: abs(row['boundary'] - 41))
        self.assertLessEqual(abs(nearest['boundary'] - 41), 4)
        self.assertLess(nearest['shift_per_day'], -8)
        self.assertEqual(nearest['strength'], 'primary')

    def test_temperature_and_shutdown_alone_do_not_raise_primary_candidate(self):
        # 没有任何水平偏移：气温与停工波动不得通过多重检验门槛成为主要候选；
        # 弱观察只是人工线索，分析师可以驳回。
        data = synthetic_dataset(shift_day=10**6, shift=0.0)
        series, segments, _ = build_series(data, 90)
        candidates = detect_candidates(series, segments)
        self.assertEqual([row for row in candidates if row['strength'] == 'primary'], [])

    def test_baseline_uses_only_prior_comparable_data_and_flags_domain(self):
        data = synthetic_dataset()
        series, segments, _ = build_series(data, 90)
        impact = estimate_impact(series, segments, '厂区甲', 41)
        self.assertTrue(impact['estimable'])
        self.assertEqual(impact['baseline_days'], 40)
        # 注入的 -18/天应被恢复，置信区间覆盖真值且不跨零。
        self.assertAlmostEqual(impact['saved_per_day'], 18.0, delta=4.0)
        self.assertGreater(impact['confidence_interval_95'][0], 0)
        self.assertTrue(impact['reliable'])

    def test_unseen_temperature_is_excluded_and_marked_unreliable(self):
        data = synthetic_dataset(days=70)
        # 基线期温度全部落在 15–25；边界后一半日子制造未经历的低温，另一半仍在域内。
        for row in data['conditions']:
            if row['day'] >= 56:
                row['temperature'] = 4.0
        series, segments, _ = build_series(data, 70)
        impact = estimate_impact(series, segments, '厂区甲', 41)
        self.assertTrue(impact['estimable'])
        self.assertFalse(impact['reliable'])
        self.assertTrue(impact['unsupported_days'])
        self.assertEqual(impact['evaluated_days'], 15)
        self.assertEqual(len(impact['unsupported_days']), 15)

    def test_meter_swap_is_segmented_not_treated_as_retrofit(self):
        data = synthetic_dataset(days=80)
        for row in data['readings']:
            if row['end'] >= 51:
                row['meter'] = '甲表-new'
                row['reading_id'] = f'甲new-{row["end"]}'
        data['meters'].append({'meter': '甲表-new', 'site': '厂区甲', 'installed_day': 51, 'start_value': 0})
        view = analyze_regimes(data, 80)
        self.assertEqual([swap['day'] for swap in view['meter_swaps']], [51])
        impact = estimate_impact(view['series'], view['segments'], '厂区甲', 51)
        self.assertFalse(impact['estimable'])
        self.assertIn('换表', impact['reason'])

    def test_counter_usage_only_differenced_within_meter(self):
        data = synthetic_dataset(days=40)
        cumulative = 0.0
        for row in data['readings']:
            cumulative += row['value']
            row['mode'] = 'counter'
            row['value'] = round(cumulative, 2)
        series, segments, _ = build_series(data, 40)
        self.assertEqual(len(series), 40)
        self.assertTrue(all(point['usage'] > 0 for point in series))

    def test_confirmed_annotation_is_presented_and_never_overwritten(self):
        data = synthetic_dataset(days=90)
        data['annotations'] = [{'site': '厂区甲', 'boundary': 41, 'status': 'confirmed',
                                 'note': '班次调整', 'known_day': 42}]
        view = analyze_regimes(data, 90, decisions=[])
        boundaries = [row for row in view['boundaries'] if row['boundary'] == 41]
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0]['source'], 'annotation')
        for candidate in view['candidates']:
            if candidate['boundary'] == 41:
                self.assertTrue(candidate['covered_by_annotation'])

    def test_analyst_decision_survives_later_revision(self):
        data = synthetic_dataset(days=90)
        view = analyze_regimes(data, 90, decisions=[
            {'site': '厂区甲', 'boundary': 45, 'status': 'confirmed', 'source': 'analyst', 'note': '验收边界'}])
        boundary = next(row for row in view['boundaries'] if row['boundary'] == 45)
        self.assertEqual(boundary['status'], 'confirmed')
        first_estimate = boundary['estimate']['saved_total']
        # 修订早期读数（补抄回改）：决策边界仍是第 45 天，只有估计值随资料重算。
        revised = copy.deepcopy(data)
        revised['readings'][9]['value'] += 12
        revised['readings'][9]['revision'] = 2
        revised['readings'][9]['known_day'] = 60
        view2 = analyze_regimes(revised, 90, decisions=[
            {'site': '厂区甲', 'boundary': 45, 'status': 'confirmed', 'source': 'analyst', 'note': '验收边界'}])
        same = next(row for row in view2['boundaries'] if row['boundary'] == 45)
        self.assertEqual(same['boundary'], 45)
        self.assertNotEqual(same['estimate']['saved_total'], first_estimate)

    def test_cutoff_hides_late_revisions_from_baseline(self):
        data = synthetic_dataset(days=60)
        target = next(row for row in data['readings'] if row['end'] == 30)
        original_value = target['value']
        # 修订版在第 55 天才可见；cutoff=50 时分析只能看到原始值。
        target['revision'] = 2
        target['known_day'] = 55
        target['value'] = 9999.0
        # 补一条始终可见的原始修订，保证该读数在 cutoff=50 仍存在（模拟补抄前已入库）。
        data['readings'].append({**target, 'revision': 1, 'known_day': 30, 'value': original_value})
        early_series, _, _ = build_series(data, 50)
        self.assertNotAlmostEqual(
            next(point['usage'] for point in early_series if point['day'] == 30), 9999.0)
        late_series, _, _ = build_series(data, 60)
        self.assertAlmostEqual(
            next(point['usage'] for point in late_series if point['day'] == 30), 9999.0)

    def test_result_is_json_safe_and_deterministic(self):
        data = synthetic_dataset()
        first = analyze_regimes(data, 90)
        second = analyze_regimes(data, 90)
        json.dumps(first, allow_nan=False)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_future_decisions_are_hidden_at_earlier_cutoff(self):
        data = synthetic_dataset()
        decisions = [{'site': '厂区甲', 'boundary': 60, 'status': 'confirmed',
                      'source': 'analyst', 'note': '未来才确认'}]
        early = analyze_regimes(data, 50, decisions=decisions)
        self.assertEqual(early['boundaries'], [])
        self.assertTrue(all(row['status'] == 'candidate' for row in early['candidates']))
        late = analyze_regimes(data, 90, decisions=decisions)
        self.assertEqual([row['boundary'] for row in late['boundaries']], [60])


if __name__ == '__main__':
    unittest.main()
