from collections import Counter, defaultdict
import math
from statistics import mean, median


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('数值必须为有限实数')
    return value


def selected(value, group):
    return not group or value == group


def latest(rows, key, revision, visible, cutoff):
    result = {}
    for row in rows:
        if row[visible] > cutoff:
            continue
        previous = result.get(row[key])
        if previous is None or row[revision] > previous[revision]:
            result[row[key]] = row
    return list(result.values())


def output(rows, summary, notes):
    return {'rows': rows, 'summary': summary, 'notes': notes}


def run(data, options):
    cutoff, group = options['cutoff'], options['group']
    readings = latest(data['readings'], 'reading_id', 'revision', 'known_day', cutoff)
    conditions = {(row['site'], row['day']): row for row in data['conditions'] if row['known_day'] <= cutoff}
    rows = []
    for reading in sorted(readings, key=lambda row: (row['site'], row['end'])):
        if reading['end'] > cutoff or not selected(reading['site'], group):
            continue
        if reading['end'] <= reading['start']:
            raise ValueError('读数区间必须为正')
        condition = conditions.get((reading['site'], reading['end']), {})
        rows.append(dict(reading=reading['reading_id'], site=reading['site'], meter=reading['meter'], time=reading['end'], mode=reading['mode'], value=number(reading['value']), revision=reading['revision'], temperature=condition.get('temperature'), production=condition.get('production')))
    annotations = [row for row in data['annotations'] if row['known_day'] <= cutoff and selected(row['site'], group)]
    return output(rows, {'读数条数': len(rows), '累计表底条数': sum(row['mode'] == 'counter' for row in rows), '人工备注': len(annotations)}, ['累计表底与区间用量不能直接相加。'] + [f"{row['site']} 第{row['boundary']}天：{row['note']}" for row in annotations])
