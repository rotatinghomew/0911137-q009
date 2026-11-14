const statusNode = document.querySelector('#status');
const filters = document.querySelector('#filters');
let current = null;
let requestGeneration = 0;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function text(tag, value) {
  const node = document.createElement(tag);
  node.textContent = typeof value === 'object' ? JSON.stringify(value) : String(value ?? '未知');
  return node;
}

function table(container, rows) {
  container.replaceChildren();
  if (!rows.length) {
    container.append(text('p', '当前范围没有记录'));
    return;
  }
  const columns = Array.from(new Set(rows.flatMap(row => Object.keys(row))));
  const grid = document.createElement('table');
  const head = document.createElement('tr');
  for (const column of columns) head.append(text('th', column));
  const thead = document.createElement('thead');
  thead.append(head);
  grid.append(thead);
  const body = document.createElement('tbody');
  for (const row of rows) {
    const line = document.createElement('tr');
    for (const column of columns) line.append(text('td', row[column]));
    body.append(line);
  }
  grid.append(body);
  container.append(grid);
}

function fmt(value, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

const SITE_COLORS = {'厂区甲': '#1f6f8b', '厂区乙': '#c2693a'};

function renderChart(regimes) {
  const host = document.querySelector('#chart');
  host.replaceChildren();
  const points = regimes.series;
  if (!points.length) {
    host.append(text('p', '当前范围没有可绘制的用量记录'));
    return;
  }
  const width = 1080;
  const height = 340;
  const margin = {top: 18, right: 18, bottom: 34, left: 56};
  const days = points.map(p => p.day);
  const values = points.map(p => p.usage);
  const minDay = Math.min(...days);
  const maxDay = Math.max(...days);
  const minValue = Math.min(...values, 0);
  const maxValue = Math.max(...values);
  const x = day => margin.left + (day - minDay) / Math.max(1, maxDay - minDay) * (width - margin.left - margin.right);
  const y = value => height - margin.bottom - (value - minValue) / Math.max(1e-9, maxValue - minValue) * (height - margin.top - margin.bottom);

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', '每日用量曲线与转折边界');

  for (let i = 0; i <= 4; i++) {
    const value = minValue + (maxValue - minValue) * i / 4;
    const gy = y(value);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', margin.left);
    line.setAttribute('x2', width - margin.right);
    line.setAttribute('y1', gy);
    line.setAttribute('y2', gy);
    line.setAttribute('stroke', '#d6e3e9');
    svg.append(line);
    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', margin.left - 6);
    label.setAttribute('y', gy + 4);
    label.setAttribute('text-anchor', 'end');
    label.setAttribute('font-size', '11');
    label.textContent = value.toFixed(0);
    svg.append(label);
  }
  for (const tick of [minDay, ...Array.from({length: 4}, (_, i) => Math.round(minDay + (maxDay - minDay) * (i + 1) / 5)), maxDay]) {
    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', x(tick));
    label.setAttribute('y', height - 10);
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('font-size', '11');
    label.textContent = `第${tick}天`;
    svg.append(label);
  }

  // 换表日：灰色虚线分段提示
  for (const swap of regimes.meter_swaps) {
    if (swap.day < minDay || swap.day > maxDay) continue;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x(swap.day));
    line.setAttribute('x2', x(swap.day));
    line.setAttribute('y1', margin.top);
    line.setAttribute('y2', height - margin.bottom);
    line.setAttribute('stroke', '#8a9aa4');
    line.setAttribute('stroke-dasharray', '4 4');
    svg.append(line);
    const tag = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    tag.setAttribute('x', x(swap.day) + 3);
    tag.setAttribute('y', margin.top + 10);
    tag.setAttribute('font-size', '10');
    tag.setAttribute('fill', '#567');
    tag.textContent = `${swap.site}换表`;
    svg.append(tag);
  }

  // 已确认边界：实线
  for (const boundary of regimes.boundaries) {
    if (boundary.boundary < minDay || boundary.boundary > maxDay) continue;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x(boundary.boundary));
    line.setAttribute('x2', x(boundary.boundary));
    line.setAttribute('y1', margin.top);
    line.setAttribute('y2', height - margin.bottom);
    line.setAttribute('stroke', boundary.is_meter_swap ? '#8a9aa4' : '#b32d2e');
    line.setAttribute('stroke-width', '2');
    svg.append(line);
    const tag = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    tag.setAttribute('x', x(boundary.boundary) + 3);
    tag.setAttribute('y', height - margin.bottom - 4);
    tag.setAttribute('font-size', '10');
    tag.setAttribute('fill', '#b32d2e');
    tag.textContent = `${boundary.site} 已确认`;
    svg.append(tag);
  }

  const sites = Array.from(new Set(points.map(p => p.site)));
  for (const site of sites) {
    const sitePoints = points.filter(p => p.site === site);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const d = sitePoints.map((p, i) => `${i ? 'L' : 'M'}${x(p.day).toFixed(1)},${y(p.usage).toFixed(1)}`).join('');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', SITE_COLORS[site] || '#333');
    path.setAttribute('stroke-width', '1.6');
    svg.append(path);
    for (const candidate of regimes.candidates.filter(c => c.site === site)) {
      const marker = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      marker.setAttribute('cx', x(candidate.boundary));
      marker.setAttribute('cy', y(sitePoints.find(p => p.day === candidate.boundary)?.usage ?? 0));
      marker.setAttribute('r', candidate.strength === 'primary' ? 5 : 4);
      marker.setAttribute('fill', candidate.strength === 'primary' ? '#b32d2e' : '#e0a13a');
      marker.setAttribute('stroke', 'white');
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = `${site} 候选边界 第${candidate.boundary}天：t=${candidate.t_statistic.toFixed(2)}，持续度=${(candidate.persistence * 100).toFixed(0)}%`;
      marker.append(title);
      svg.append(marker);
    }
  }
  host.append(svg);

  const legend = document.querySelector('#legend');
  legend.replaceChildren();
  for (const site of sites) {
    const item = document.createElement('span');
    const dot = document.createElement('i');
    dot.className = 'dot';
    dot.style.background = SITE_COLORS[site] || '#333';
    item.append(dot, text('span', site));
    legend.append(item);
  }
  for (const [color, label] of [['#b32d2e', '主要候选 / 已确认边界'], ['#e0a13a', '弱观察候选'], ['#8a9aa4', '换表分段']]) {
    const item = document.createElement('span');
    const dot = document.createElement('i');
    dot.className = 'dot';
    dot.style.background = color;
    item.append(dot, text('span', label));
    legend.append(item);
  }
}

function fillDecisionForm(site, boundary) {
  const form = document.querySelector('#decisionForm');
  form.elements.site.value = site;
  form.elements.boundary.value = boundary;
  form.elements.note.focus();
}

function renderCandidates(regimes) {
  const host = document.querySelector('#candidates');
  host.replaceChildren();
  if (!regimes.candidates.length) {
    host.append(text('p', '调整气温与停工后未发现达到阈值的持续水平偏移；请结合曲线与工况备注人工判断。'));
    return;
  }
  const grid = document.createElement('table');
  const head = document.createElement('tr');
  for (const column of ['站点', '边界', '证据强度', 'Welch t', '残差偏移/天', '持续度', '调整模型（气温斜率/停工效应）', '状态', '操作']) {
    head.append(text('th', column));
  }
  const thead = document.createElement('thead');
  thead.append(head);
  grid.append(thead);
  const body = document.createElement('tbody');
  for (const candidate of regimes.candidates) {
    const line = document.createElement('tr');
    const values = [
      candidate.site,
      `第${candidate.boundary}天`,
      candidate.strength === 'primary' ? '主要候选' : '弱观察',
      candidate.t_statistic.toFixed(2),
      candidate.shift_per_day.toFixed(2),
      `${(candidate.persistence * 100).toFixed(0)}%`,
      `${candidate.temperature_slope.toFixed(2)} / ${candidate.stop_effect.toFixed(2)}`,
      candidate.covered_by_annotation ? '资料已确认（受保护）' : candidate.status,
    ];
    for (const value of values) line.append(text('td', value));
    const action = document.createElement('td');
    if (!candidate.covered_by_annotation) {
      const confirm = text('button', '确认');
      confirm.type = 'button';
      confirm.addEventListener('click', () => fillDecisionForm(candidate.site, candidate.boundary));
      const reject = text('button', '驳回');
      reject.type = 'button';
      reject.addEventListener('click', () => submitDecision({site: candidate.site, boundary: candidate.boundary, status: 'rejected', note: '识别证据不足，分析师驳回'}));
      action.append(confirm, reject);
    } else {
      action.append(text('span', '不可覆盖'));
    }
    line.append(action);
    body.append(line);
  }
  grid.append(body);
  host.append(grid);
}

function estimateBlock(estimate) {
  const block = document.createElement('div');
  block.className = 'estimate';
  if (!estimate.estimable) {
    block.append(text('p', `无法估计：${estimate.reason}`));
    if (estimate.unsupported_days?.length) {
      block.append(text('p', `支撑域外日期 ${estimate.unsupported_days.length} 天（见明细）`));
    }
    return block;
  }
  const items = [
    ['基线可比天数', String(estimate.baseline_days)],
    ['评估天数', `${estimate.evaluated_days} 天`],
    ['累计节能量', `${fmt(estimate.saved_total)}（95% 区间 ${fmt(estimate.confidence_interval_95[0])} 至 ${fmt(estimate.confidence_interval_95[1])}）`],
    ['日均节能', fmt(estimate.saved_per_day)],
    ['相对节能率', estimate.relative_saving === null ? '—' : `${(estimate.relative_saving * 100).toFixed(1)}%`],
    ['标准误', fmt(estimate.standard_error)],
  ];
  for (const [key, value] of items) {
    block.append(text('dt', key), text('dd', value));
  }
  const domain = estimate.support_domain;
  block.append(text('p', `基线支撑域：气温 ${domain.temperature_min.toFixed(1)}–${domain.temperature_max.toFixed(1)}°C，工况 ${domain.productions.join('、')}`));
  if (estimate.unsupported_days.length) {
    const warning = document.createElement('p');
    warning.className = 'warning';
    warning.textContent = `有 ${estimate.unsupported_days.length} 天超出基线支撑域，已排除在节能量之外，不能可靠外推：`;
    const detail = document.createElement('ul');
    for (const row of estimate.unsupported_days) {
      detail.append(text('li', `第${row.day}天：${row.reason}`));
    }
    block.append(warning, detail);
  }
  return block;
}

function renderBoundaries(regimes) {
  const host = document.querySelector('#boundaries');
  host.replaceChildren();
  if (!regimes.boundaries.length) {
    host.append(text('p', '还没有已确认边界。可在候选转折中确认，或在下方手工登记边界。'));
    return;
  }
  for (const boundary of regimes.boundaries) {
    const card = document.createElement('article');
    card.className = 'card';
    const title = document.createElement('h4');
    title.textContent = `${boundary.site} 第${boundary.boundary}天 · ${boundary.status === 'confirmed' ? '已确认' : boundary.status}（来源：${boundary.source === 'annotation' ? '资料 annotation' : '分析师决策'}）${boundary.note ? ' · ' + boundary.note : ''}${boundary.is_meter_swap ? ' · 换表日' : ''}`;
    card.append(title, estimateBlock(boundary.estimate));
    host.append(card);
  }
}

function renderRegimes(regimes) {
  renderChart(regimes);
  renderCandidates(regimes);
  renderBoundaries(regimes);
  document.querySelector('#regimeNotes').replaceChildren(...regimes.notes.map(note => text('li', note)));
  const siteSelect = document.querySelector('#decisionForm').elements.site;
  if (!siteSelect.dataset.filled) {
    for (const site of Array.from(new Set(regimes.series.map(p => p.site)))) {
      siteSelect.append(text('option', site));
    }
    siteSelect.dataset.filled = '1';
  }
}

async function submitDecision(payload) {
  const decisionStatus = document.querySelector('#decisionStatus');
  decisionStatus.textContent = '正在提交决策';
  try {
    await api('/api/decisions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    decisionStatus.textContent = '决策已固定；后续资料修订不会移动该边界。';
    await refresh();
  } catch (error) {
    decisionStatus.textContent = error.message;
  }
}

function render(value, savedTitle = '') {
  current = value;
  const summary = document.querySelector('#summary');
  summary.replaceChildren();
  for (const [key, amount] of Object.entries(value.result.summary)) {
    summary.append(text('dt', key), text('dd', amount));
  }
  document.querySelector('#notes').replaceChildren(...value.result.notes.map(note => text('li', note)));
  document.querySelector('#digest').textContent = `资料指纹：${value.digest}`;
  table(document.querySelector('#results'), value.result.rows);
  renderRegimes(value.result.regimes);
  statusNode.textContent = savedTitle ? `正在查看保存的分析：${savedTitle}` : '分析已更新';
  filters.elements.cutoff.value = value.options.cutoff;
  filters.elements.group.value = value.options.group;
}

async function refresh() {
  const generation = ++requestGeneration;
  const query = new URLSearchParams(new FormData(filters));
  statusNode.textContent = '正在分析';
  try {
    const result = await api(`/api/view?${query}`);
    if (generation === requestGeneration) render(result);
  } catch (error) {
    if (generation === requestGeneration) {
      current = null;
      statusNode.textContent = error.message;
    }
  }
}

async function history() {
  const entries = await api('/api/analyses');
  const list = document.querySelector('#history');
  list.replaceChildren();
  for (const entry of entries) {
    const item = document.createElement('li');
    const button = text('button', entry.title);
    button.type = 'button';
    button.addEventListener('click', async () => {
      const generation = ++requestGeneration;
      try {
        const saved = await api(`/api/analyses/${entry.id}`);
        if (generation === requestGeneration) render(saved, saved.title);
      } catch (error) {
        statusNode.textContent = error.message;
      }
    });
    item.append(button, text('small', entry.created_at));
    list.append(item);
  }
}

filters.addEventListener('submit', event => {
  event.preventDefault();
  refresh();
});

document.querySelector('#decisionForm').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.target;
  submitDecision({
    site: form.elements.site.value,
    boundary: Number(form.elements.boundary.value),
    status: form.elements.status.value,
    note: form.elements.note.value,
  });
  form.elements.note.value = '';
});

document.querySelector('#save').addEventListener('submit', async event => {
  event.preventDefault();
  if (!current) return;
  try {
    const saved = await api('/api/analyses', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: event.target.elements.title.value, options: current.options})});
    render(saved, saved.title);
    await history();
  } catch (error) {
    statusNode.textContent = error.message;
  }
});

document.querySelector('#source').addEventListener('click', async () => {
  try {
    const data = await api(`/api/source?table=${encodeURIComponent(document.querySelector('#tables').value)}`);
    table(document.querySelector('#raw'), data.rows);
  } catch (error) {
    statusNode.textContent = error.message;
  }
});

async function start() {
  const catalog = await api('/api/catalog');
  document.querySelector('#description').textContent = catalog.description;
  filters.elements.cutoff.min = catalog.min_cutoff;
  filters.elements.cutoff.max = catalog.max_cutoff;
  filters.elements.cutoff.value = catalog.default_cutoff;
  const groups = [['', '全部'], ...catalog.groups.map(group => [group, group])];
  for (const [key, label] of groups) {
    const option = text('option', label);
    option.value = key;
    filters.elements.group.append(option);
  }
  for (const name of Object.keys(catalog.tables)) {
    const option = text('option', `${name}（${catalog.tables[name]}）`);
    option.value = name;
    document.querySelector('#tables').append(option);
  }
  await refresh();
  await history();
}

start().catch(error => { statusNode.textContent = error.message; });
