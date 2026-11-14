import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen([sys.executable, '-m', 'usage_regimes', '--port', str(port), '--state', str(Path(directory) / 'state.sqlite3')], cwd=ROOT)
        base = f'http://127.0.0.1:{port}'
        try:
            for attempt in range(100):
                try:
                    with urlopen(base + '/api/catalog', timeout=1) as response:
                        catalog = json.load(response)
                    break
                except OSError:
                    time.sleep(.05)
            else:
                raise RuntimeError('服务启动超时')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                page.wait_for_function("document.querySelector('#status').textContent === '分析已更新'")
                assert page.locator('#results tbody tr').count() > 0
                # 转折分析区块：曲线、图例与口径说明都已渲染。
                page.wait_for_selector('#chart svg path')
                assert page.locator('#legend .dot').count() >= 3
                assert page.locator('#regimeNotes li').count() >= 1

                # 筛选到单一厂区后仍能看到曲线，并在候选表中驳回一个候选（若存在）。
                page.locator('#filters select').select_option(catalog['groups'][1])
                page.get_by_role('button', name='更新分析', exact=True).click()
                page.wait_for_function("document.querySelector('#status').textContent === '分析已更新'")
                page.wait_for_selector('#chart svg path')
                candidate_rows = page.locator('#candidates tbody tr').count()
                if candidate_rows:
                    page.locator('#candidates tbody tr button', has_text='驳回').first.click()
                    page.wait_for_function(
                        "Array.from(document.querySelectorAll('#candidates tbody tr td')).some(td => td.textContent === 'rejected')")

                # 手工登记一条确认边界（回到全部范围，使卡片立即可见）。
                page.locator('#filters select').select_option('')
                page.get_by_role('button', name='更新分析', exact=True).click()
                page.wait_for_function("document.querySelector('#status').textContent === '分析已更新'")
                form = page.locator('#decisionForm')
                form.locator('select[name=site]').select_option(catalog['groups'][0])
                form.locator('input[name=boundary]').fill('30')
                form.locator('input[name=note]').fill('浏览器确认边界')
                form.get_by_role('button', name='提交决策').click()
                page.wait_for_selector('#boundaries .card')
                page.wait_for_function("document.querySelector('#decisionStatus').textContent.includes('固定')")
                assert page.locator('#boundaries .card').count() >= 1
                assert '累计节能量' in page.locator('#boundaries .card').first.inner_text()

                # 原有保存与回看流程仍然工作，且保存结果包含 regimes 视图。
                page.locator('#filters select').select_option(catalog['groups'][0])
                page.get_by_role('button', name='更新分析', exact=True).click()
                page.wait_for_function("document.querySelector('#status').textContent === '分析已更新'")
                page.locator('#save input').fill('浏览器业务核对')
                page.get_by_role('button', name='保存当前分析').click()
                page.wait_for_selector('#history button')
                page.reload()
                page.wait_for_selector('#history button')
                page.locator('#history button').click()
                page.wait_for_function("document.querySelector('#status').textContent.includes('浏览器业务核对')")
                assert page.locator('#filters select').input_value() == catalog['groups'][0]
                page.wait_for_selector('#chart svg path')
                page.get_by_role('button', name='查看资料').click()
                page.wait_for_selector('#raw tbody tr')
                assert not errors, errors
                print(json.dumps({'结果': '通过', '页面错误': errors, '候选行数': candidate_rows,
                                  '边界卡片': page.locator('#boundaries .card').count()}, ensure_ascii=False))
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    main()
