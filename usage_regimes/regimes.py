"""持续用量转折识别与改造前后基线比较。

口径要点（与 docs/data-contract.md 一致）：

- counter 是累计表底，只能在同一表内与相邻表底作差；换表日另起一段，不能跨表底作差。
- interval 直接作为区间用量。同一 reading_id 只取 cutoff 时可见的最高 revision。
- 基线只用当时（cutoff 前）可见、且工况可比的资料；未经历过的温度或生产组合标记为
  支撑域之外，不纳入节能量汇总。
- 识别在「气温 + 停工」调整后的残差上做持续偏移检验，避免把节假日、气温波动当成改造。
- 人工确认的边界来自 annotations 表或 decisions 存储，识别结果永远不会覆盖它们；
  资料修订只重算候选与估计，不会移动已经确认的边界。
"""

from collections import defaultdict
import math

from .domain import latest, number, selected

MIN_FIT_DAYS = 14          # 基线可拟合的最少可比天数
WINDOW_DAYS = 12           # 转折两侧的持续观察窗
CANDIDATE_ALPHA = 0.05     # 经 Bonferroni 多重检验校正后的族系显著性水平
CANDIDATE_PERSIST = 0.75   # 对侧窗中同向残差占比阈值
CANDIDATE_EFFECT = 0.5     # 残差偏移至少为残差标准差的倍数，避免小噪声虚高
WEAK_T = 2.5               # 弱观察门槛（未做多重检验校正，仅作人工线索）
MAX_PRIMARY = 3
MAX_WEAK = 2


def normal_quantile(probability):
    """标准正态分位数（Acklam 有理逼近），用于 Bonferroni 校正门槛。"""
    if not 0 < probability < 1:
        raise ValueError('概率必须在开区间 (0,1) 内')
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if probability < p_low:
        q = math.sqrt(-2 * math.log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) \
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if probability > p_high:
        q = math.sqrt(-2 * math.log(1 - probability))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) \
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = probability - 0.5
    r = q * q
    numerator = q * (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
    denominator = ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
    return numerator / denominator


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('统计结果必须为有限实数')
    return float(value)


def visible_rows(data, cutoff, group):
    """按 cutoff 取各 reading_id 的最高修订，并筛选业务范围。"""
    readings = latest(data['readings'], 'reading_id', 'revision', 'known_day', cutoff)
    readings = [row for row in readings
                if row['end'] <= cutoff and selected(row['site'], group)]
    conditions = {(row['site'], row['day']): row
                  for row in data['conditions']
                  if row['known_day'] <= cutoff and selected(row['site'], group)}
    return readings, conditions


def build_series(data, cutoff, group=''):
    """把原始读数归整为「站点 × 表计」分段的日用量序列。

    返回 series（每日归一行）、segments（分段元数据）、notes（口径提示）。
    """
    readings, conditions = visible_rows(data, cutoff, group)
    meter_info = {row['meter']: row for row in data['meters']}
    grouped = defaultdict(list)
    for row in readings:
        grouped[(row['site'], row['meter'])].append(row)

    series = []
    segments = []
    notes = []
    for (site, meter), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: (row['end'], row['revision']))
        info = meter_info.get(meter, {})
        start_value = info.get('start_value')
        previous = None
        segment_rows = []
        for row in rows:
            if row['end'] <= row['start']:
                raise ValueError('读数区间必须为正')
            value = number(row['value'])
            if row['mode'] == 'counter':
                if previous is None:
                    if start_value is None:
                        notes.append(f'{site} {meter} 第{row["end"]}天缺少表计起点，无法作差，已跳过。')
                        continue
                    usage = value - number(start_value)
                else:
                    usage = value - previous
                if usage < 0:
                    notes.append(f'{site} {meter} 第{row["end"]}天表底倒退，已按缺失处理，不参与作差。')
                    previous = value
                    continue
                previous = value
            elif row['mode'] == 'interval':
                usage = value
            else:
                raise ValueError('未知读数模式')
            condition = conditions.get((site, row['end']), {})
            point = {
                'site': site,
                'meter': meter,
                'day': row['end'],
                'usage': finite(usage),
                'temperature': condition.get('temperature'),
                'production': condition.get('production'),
                'mode': row['mode'],
                'revision': row['revision'],
                'reading_id': row['reading_id'],
            }
            segment_rows.append(point)
            series.append(point)
        if segment_rows:
            days = [point['day'] for point in segment_rows]
            complete = [point for point in segment_rows if point['temperature'] is not None
                        and point['production'] is not None]
            segments.append({
                'site': site,
                'meter': meter,
                'from_day': min(days),
                'to_day': max(days),
                'days': len(segment_rows),
                'complete_days': len(complete),
                'installed_day': info.get('installed_day'),
            })
    series.sort(key=lambda point: (point['site'], point['day']))
    return series, segments, notes


def design_row(point):
    return [1.0, float(point['temperature']), 1.0 if point['production'] == '停工' else 0.0]


def invert(matrix):
    """高斯-若尔当求逆，矩阵为对称正定的法方程矩阵。"""
    n = len(matrix)
    augmented = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
                 for i, row in enumerate(matrix)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda row: abs(augmented[row][i]))
        if abs(augmented[pivot][i]) < 1e-12:
            raise ValueError('设计矩阵共线，无法拟合基线')
        augmented[i], augmented[pivot] = augmented[pivot], augmented[i]
        divisor = augmented[i][i]
        augmented[i] = [value / divisor for value in augmented[i]]
        for row in range(n):
            if row == i:
                continue
            factor = augmented[row][i]
            augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[i])]
    return [row[n:] for row in augmented]


def ols(points):
    """y = b0 + b1*temperature + b2*stop，返回系数、(X'X)^-1 与残差方差。"""
    n = len(points)
    p = 3
    if n < MIN_FIT_DAYS:
        raise ValueError('可比资料不足，无法可靠拟合基线')
    design = [design_row(point) for point in points]
    targets = [point['usage'] for point in points]
    xtx = [[sum(design[k][i] * design[k][j] for k in range(n)) for j in range(p)]
           for i in range(p)]
    xty = [sum(design[k][i] * targets[k] for k in range(n)) for i in range(p)]
    inverse = invert(xtx)
    beta = [sum(inverse[i][j] * xty[j] for j in range(p)) for i in range(p)]
    residuals = [targets[k] - sum(beta[j] * design[k][j] for j in range(p))
                 for k in range(n)]
    variance = sum(e * e for e in residuals) / (n - p)
    return beta, inverse, variance, residuals


def welch_t(left, right):
    """两段残差均值差异的 Welch t 统计量。"""
    n_l, n_r = len(left), len(right)
    mean_l, mean_r = sum(left) / n_l, sum(right) / n_r
    var_l = sum((value - mean_l) ** 2 for value in left) / (n_l - 1)
    var_r = sum((value - mean_r) ** 2 for value in right) / (n_r - 1)
    standard_error = math.sqrt(var_l / n_l + var_r / n_r)
    if standard_error < 1e-12:
        return 0.0, standard_error
    return (mean_r - mean_l) / standard_error, standard_error


def detect_candidates(series, segments):
    """在气温/停工调整后的残差上扫描持续水平偏移。

    每段先做整段调整模型，再用等长两侧窗比较残差均值；显著且同向持续的偏移
    才作为主要候选，其余仅作弱观察供分析师参考。
    """
    grouped = defaultdict(list)
    for point in series:
        grouped[(point['site'], point['meter'])].append(point)

    candidates = []
    for segment in segments:
        key = (segment['site'], segment['meter'])
        points = sorted(grouped[key], key=lambda point: point['day'])
        complete = [point for point in points
                    if point['temperature'] is not None and point['production'] is not None]
        if len(complete) < MIN_FIT_DAYS + 2 * WINDOW_DAYS:
            continue
        try:
            beta, _inverse, variance, residuals = ols(complete)
        except ValueError:
            continue
        sigma = math.sqrt(variance)
        for point, residual in zip(complete, residuals):
            point['_residual'] = residual
        scored = []
        for index in range(WINDOW_DAYS, len(complete) - WINDOW_DAYS):
            boundary = complete[index]['day']
            left = [point['_residual'] for point in complete if point['day'] < boundary][-WINDOW_DAYS:]
            right = [point['_residual'] for point in complete if point['day'] >= boundary][:WINDOW_DAYS]
            if len(left) < WINDOW_DAYS or len(right) < WINDOW_DAYS:
                continue
            statistic, _se = welch_t(left, right)
            shift = sum(right) / len(right) - sum(left) / len(left)
            persistence = sum(1 for value in right
                              if (value < 0) == (shift < 0) or value == 0) / len(right)
            effect_size = abs(shift) / sigma if sigma > 1e-12 else 0.0
            scored.append({
                'site': segment['site'],
                'meter': segment['meter'],
                'boundary': boundary,
                't_statistic': finite(statistic),
                'shift_per_day': finite(shift),
                'persistence': finite(persistence),
                'effect_size': finite(effect_size),
                'residual_sigma': finite(sigma),
                'temperature_slope': finite(beta[1]),
                'stop_effect': finite(beta[2]),
            })
        # 扫描位置数决定多重检验校正强度：同一批窗口检验共用一个 Bonferroni 门槛。
        positions = max(1, len(complete) - 2 * WINDOW_DAYS)
        threshold = normal_quantile(1 - CANDIDATE_ALPHA / (2 * positions))
        strong = [row for row in scored
                  if abs(row['t_statistic']) >= threshold
                  and row['persistence'] >= CANDIDATE_PERSIST
                  and row['effect_size'] >= CANDIDATE_EFFECT]
        weak = [row for row in scored
                if abs(row['t_statistic']) >= WEAK_T and row['persistence'] >= 0.6
                and row['effect_size'] >= CANDIDATE_EFFECT]
        strong.sort(key=lambda row: abs(row['t_statistic']), reverse=True)
        weak.sort(key=lambda row: abs(row['t_statistic']), reverse=True)

        def pick(rows, limit, strength):
            chosen = []
            for row in rows:
                if all(abs(row['boundary'] - other['boundary']) >= WINDOW_DAYS for other in chosen):
                    row = {**row, 'strength': strength}
                    chosen.append(row)
                if len(chosen) >= limit:
                    break
            return chosen

        primary = pick(strong, MAX_PRIMARY, 'primary')
        occupied = [row['boundary'] for row in primary]
        weak = [row for row in weak if all(abs(row['boundary'] - day) >= WINDOW_DAYS for day in occupied)]
        candidates.extend(primary)
        candidates.extend(pick(weak, MAX_WEAK, 'weak'))
        for point in complete:
            point.pop('_residual', None)
    candidates.sort(key=lambda row: (row['site'], row['boundary']))
    return candidates


def support_domain(points):
    """基线资料实际经历过的温度与生产组合范围。"""
    temperatures = [point['temperature'] for point in points
                    if point['temperature'] is not None]
    productions = sorted({point['production'] for point in points
                          if point['production'] is not None})
    if not temperatures:
        return None
    return {
        'temperature_min': finite(min(temperatures)),
        'temperature_max': finite(max(temperatures)),
        'productions': productions,
    }


def estimate_impact(series, segments, site, boundary):
    """以边界前资料拟合基线，预测边界后反事实用量并估计节能量。

    只在同一表计分段内比较；落在基线支撑域外（未经历的温度/生产组合）的日期
    单独列出，不计入节能量，并给出不确定度。
    """
    segment = next((row for row in segments
                    if row['site'] == site and row['from_day'] <= boundary <= row['to_day']), None)
    if segment is None:
        return {'site': site, 'boundary': boundary, 'estimable': False,
                'reason': '边界落在没有观测资料的区间', 'unsupported_days': []}
    if boundary == segment['from_day'] and segment['installed_day'] == boundary:
        return {'site': site, 'boundary': boundary, 'estimable': False,
                'reason': '换表日不能跨表底作差，无法估计改造前后差异',
                'meter': segment['meter'], 'unsupported_days': []}

    points = sorted((point for point in series
                     if point['site'] == site and point['meter'] == segment['meter']),
                    key=lambda point: point['day'])
    before = [point for point in points if point['day'] < boundary
              and point['temperature'] is not None and point['production'] is not None]
    after = [point for point in points if point['day'] >= boundary]
    if len(before) < MIN_FIT_DAYS:
        return {'site': site, 'boundary': boundary, 'estimable': False,
                'reason': f'边界前仅有 {len(before)} 个可比观测，少于 {MIN_FIT_DAYS} 天，无法可靠估计',
                'meter': segment['meter'], 'unsupported_days': []}
    try:
        beta, inverse, variance, _residuals = ols(before)
    except ValueError as error:
        return {'site': site, 'boundary': boundary, 'estimable': False, 'reason': str(error),
                'meter': segment['meter'], 'unsupported_days': []}

    domain = support_domain(before)
    unsupported = []
    saved_total = 0.0
    predicted_total = 0.0
    actual_total = 0.0
    variance_total = 0.0
    supported = 0
    for point in after:
        if point['temperature'] is None or point['production'] is None:
            unsupported.append({'day': point['day'], 'reason': '缺少气温或工况资料'})
            continue
        design = design_row(point)
        outside = (point['temperature'] < domain['temperature_min']
                   or point['temperature'] > domain['temperature_max']
                   or point['production'] not in domain['productions'])
        if outside:
            reasons = []
            if point['temperature'] < domain['temperature_min'] or point['temperature'] > domain['temperature_max']:
                reasons.append(f"温度 {point['temperature']}°C 超出基线范围 "
                               f"{domain['temperature_min']}–{domain['temperature_max']}°C")
            if point['production'] not in domain['productions']:
                reasons.append(f"工况 {point['production']} 未在基线期出现过")
            unsupported.append({'day': point['day'], 'reason': '；'.join(reasons)})
            continue
        predicted = sum(beta[j] * design[j] for j in range(3))
        # Var(x'b) = x' (X'X)^-1 x * sigma^2；累加再加上日间残差噪声。
        coefficient_variance = sum(design[i] * inverse[i][j] * design[j]
                                   for i in range(3) for j in range(3)) * variance
        saved = predicted - point['usage']
        saved_total += saved
        predicted_total += predicted
        actual_total += point['usage']
        variance_total += coefficient_variance + variance
        supported += 1

    if supported == 0:
        return {'site': site, 'boundary': boundary, 'estimable': False,
                'reason': '边界后没有处于基线支撑域内的观测，不能可靠估计',
                'meter': segment['meter'], 'support_domain': domain,
                'unsupported_days': unsupported}

    standard_error = math.sqrt(variance_total)
    saved_per_day = saved_total / supported
    relative = saved_total / predicted_total if predicted_total else None
    result = {
        'site': site,
        'boundary': boundary,
        'estimable': True,
        'meter': segment['meter'],
        'baseline_days': len(before),
        'evaluated_days': supported,
        'saved_total': finite(saved_total),
        'saved_per_day': finite(saved_per_day),
        'predicted_total': finite(predicted_total),
        'actual_total': finite(actual_total),
        'relative_saving': finite(relative) if relative is not None else None,
        'standard_error': finite(standard_error),
        'confidence_interval_95': [finite(saved_total - 1.96 * standard_error),
                                   finite(saved_total + 1.96 * standard_error)],
        'support_domain': domain,
        'unsupported_days': unsupported,
        'reliable': not unsupported,
        'baseline_coefficients': {
            'intercept': finite(beta[0]),
            'temperature_slope': finite(beta[1]),
            'stop_effect': finite(beta[2]),
        },
    }
    return result


def meter_swaps(segments):
    """每个站点除最早一段外的起点都是换表日，单独标记而非改造转折。"""
    seen = defaultdict(list)
    for segment in segments:
        seen[segment['site']].append(segment)
    swaps = []
    for site, rows in seen.items():
        rows.sort(key=lambda row: row['from_day'])
        for row in rows[1:]:
            swaps.append({'site': site, 'day': row['from_day'], 'meter': row['meter']})
    return swaps


def analyze_regimes(data, cutoff, group='', decisions=None):
    """生成曲线页面所需的完整转折分析视图。"""
    decisions = decisions or []
    series, segments, notes = build_series(data, cutoff, group)
    candidates = detect_candidates(series, segments)
    swaps = meter_swaps(segments)
    swap_keys = {(row['site'], row['day']) for row in swaps}

    annotation_keys = {(row['site'], row['boundary']): row
                       for row in data.get('annotations', [])
                       if row['known_day'] <= cutoff and selected(row['site'], group)}

    effective = []
    for decision in decisions:
        if not selected(decision['site'], group):
            continue
        # 历史时点视图只呈现当时已经确认的边界：边界天本身必须已在 cutoff 之前。
        if decision['boundary'] > cutoff:
            continue
        if decision['status'] == 'rejected':
            continue
        key = (decision['site'], decision['boundary'])
        if key in annotation_keys:
            continue  # annotations 表中的确认边界单独呈现，避免重复
        effective.append(decision)
    for annotation in annotation_keys.values():
        effective.append({
            'site': annotation['site'],
            'boundary': annotation['boundary'],
            'status': 'confirmed',
            'source': 'annotation',
            'note': annotation.get('note', ''),
        })

    estimates = []
    boundary_views = []
    for decision in effective:
        impact = estimate_impact(series, segments, decision['site'], decision['boundary'])
        estimates.append(impact)
        boundary_views.append({
            'site': decision['site'],
            'boundary': decision['boundary'],
            'status': decision['status'],
            'source': decision.get('source', 'analyst'),
            'note': decision.get('note', ''),
            'is_meter_swap': (decision['site'], decision['boundary']) in swap_keys,
            'estimate': impact,
        })

    for candidate in candidates:
        key = (candidate['site'], candidate['boundary'])
        matched = next((decision for decision in decisions
                        if decision['site'] == key[0] and decision['boundary'] == key[1]
                        and decision['boundary'] <= cutoff), None)
        candidate['status'] = matched['status'] if matched else 'candidate'
        candidate['covered_by_annotation'] = key in annotation_keys

    notes = list(notes)
    if not candidates:
        notes.append('当前资料在调整气温与停工后没有发现持续水平偏移，短期下降不构成改造证据。')
    for swap in swaps:
        notes.append(f"{swap['site']} 第{swap['day']}天换表（{swap['meter']}），新表分段单独建模，不能跨表底作差。")

    return {
        'series': series,
        'segments': segments,
        'candidates': candidates,
        'meter_swaps': swaps,
        'boundaries': boundary_views,
        'estimates': estimates,
        'notes': notes,
        'parameters': {
            'min_fit_days': MIN_FIT_DAYS,
            'window_days': WINDOW_DAYS,
            'candidate_alpha': CANDIDATE_ALPHA,
            'candidate_persistence': CANDIDATE_PERSIST,
            'candidate_effect': CANDIDATE_EFFECT,
            'weak_t': WEAK_T,
        },
    }
