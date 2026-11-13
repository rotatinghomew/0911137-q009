# 记录样式

以下为当前业务文件中的实际记录，字段口径见 `data-contract.md`；字段标识保持业务接口写法。

### `readings`

字段：`end`、`known_day`、`meter`、`mode`、`reading_id`、`revision`、`site`、`start`、`value`。

```json
{
  "reading_id": "厂区甲-1",
  "site": "厂区甲",
  "meter": "厂区甲-old",
  "start": 0,
  "end": 1,
  "mode": "counter",
  "value": 1152.95,
  "revision": 1,
  "known_day": 1
}
```

### `conditions`

字段：`day`、`known_day`、`production`、`site`、`temperature`。

```json
{
  "site": "厂区甲",
  "day": 1,
  "temperature": 20.7,
  "production": "运行",
  "known_day": 1
}
```

### `meters`

字段：`installed_day`、`meter`、`site`、`start_value`。

```json
{
  "meter": "厂区甲-old",
  "site": "厂区甲",
  "installed_day": 1,
  "start_value": 1000
}
```

### `annotations`

字段：`boundary`、`known_day`、`note`、`site`、`status`。

```json
{
  "boundary": 55,
  "site": "厂区甲",
  "status": "confirmed",
  "note": "生产班次调整",
  "known_day": 57
}
```
