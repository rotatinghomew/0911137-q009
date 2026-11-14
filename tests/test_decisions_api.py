import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from usage_regimes.application import Application, ROOT, server


class DecisionApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state = Path(self.directory.name) / 'state.sqlite3'
        self.application = Application(ROOT / 'fixtures/data.json', self.state, ROOT / 'web')
        self.httpd = server(self.application)
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.worker.join()
        self.httpd.server_close()
        self.directory.cleanup()

    def request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.base + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
        return urlopen(request)

    def get(self, path):
        with urlopen(self.base + path) as response:
            return json.load(response)

    def test_decision_roundtrip_and_appears_in_view(self):
        with self.request('POST', '/api/decisions',
                          {'site': '厂区甲', 'boundary': 40, 'status': 'confirmed',
                           'note': '改造验收边界'}) as response:
            self.assertEqual(response.status, 201)
            decision = json.load(response)
        self.assertEqual(decision['boundary'], 40)
        decisions = self.get('/api/decisions')
        self.assertEqual(len(decisions), 1)
        view = self.get('/api/view?group=' + quote('厂区甲'))
        boundaries = {row['boundary']: row for row in view['result']['regimes']['boundaries']}
        self.assertIn(40, boundaries)
        self.assertEqual(boundaries[40]['source'], 'analyst')
        self.assertTrue(boundaries[40]['estimate'])

    def test_rejected_decision_is_stored_but_not_applied(self):
        self.request('POST', '/api/decisions',
                     {'site': '厂区乙', 'boundary': 44, 'status': 'rejected', 'note': '季节性波动'})
        view = self.get('/api/view?group=' + quote('厂区乙'))
        self.assertNotIn(44, [row['boundary'] for row in view['result']['regimes']['boundaries']])
        candidate = next(row for row in view['result']['regimes']['candidates']
                         if row['boundary'] == 44)
        self.assertEqual(candidate['status'], 'rejected')

    def test_annotation_boundary_is_protected(self):
        payload = {'site': '厂区甲', 'boundary': 55, 'status': 'rejected', 'note': '尝试覆盖'}
        with self.assertRaises(HTTPError) as caught:
            self.request('POST', '/api/decisions', payload)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.get('/api/decisions'), [])

    def test_invalid_decision_payloads_rejected(self):
        bad_payloads = [
            {'site': '未知厂区', 'boundary': 40, 'status': 'confirmed'},
            {'site': '厂区甲', 'boundary': 1.5, 'status': 'confirmed'},
            {'site': '厂区甲', 'boundary': 40, 'status': 'maybe'},
            {'site': '厂区甲', 'boundary': 40, 'status': 'confirmed', 'extra': 1},
            {'site': '厂区甲', 'boundary': 0, 'status': 'confirmed'},
        ]
        for payload in bad_payloads:
            with self.assertRaises(HTTPError) as caught:
                self.request('POST', '/api/decisions', payload)
            self.assertEqual(caught.exception.code, 400, payload)
        self.assertEqual(self.get('/api/decisions'), [])

    def test_decisions_survive_process_restart_and_saved_analysis_stays_frozen(self):
        self.request('POST', '/api/decisions',
                     {'site': '厂区甲', 'boundary': 40, 'status': 'confirmed', 'note': '固定边界'})
        view = self.get('/api/view')
        saved = json.load(self.request('POST', '/api/analyses',
                                       {'title': '冻结版本', 'options': view['options']}))
        # 重新打开应用（模拟换进程）：决策仍在，保存版本内容不被后续操作改变。
        reloaded = Application(self.application.dataset, self.state, ROOT / 'web')
        decisions = reloaded.store.list_decisions()
        self.assertEqual([(row['site'], row['boundary']) for row in decisions], [('厂区甲', 40)])
        restored = reloaded.store.get(saved['id'])
        self.assertEqual(restored['result'], view['result'])

    def test_adjusting_boundary_keeps_site_day_pin(self):
        # 分析师把候选 44 调整为 45：旧位置清除，新位置固定，证据快照随决策保存。
        self.request('POST', '/api/decisions',
                     {'site': '厂区乙', 'boundary': 44, 'status': 'rejected', 'note': '位置不准'})
        self.request('POST', '/api/decisions',
                     {'site': '厂区乙', 'boundary': 45, 'status': 'confirmed', 'note': '调整后确认'})
        decisions = self.get('/api/decisions')
        self.assertEqual(sorted((row['boundary'], row['status']) for row in decisions),
                         [(44, 'rejected'), (45, 'confirmed')])
        confirmed = next(row for row in decisions if row['boundary'] == 45)
        self.assertIn('evidence', confirmed)


if __name__ == '__main__':
    unittest.main()
