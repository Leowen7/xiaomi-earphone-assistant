# 小米智能穿戴设备字段填写规范

## 1. 适用范围

本规范适用于第二阶段新增的两类产品：

- `smart_band`：智能手环
- `smart_watch`：智能手表

原有耳机数据与字段不删除、不覆盖。穿戴设备专用参数统一放入 `wearable_specs`，从而使耳机、手环和手表能够在同一项目中共存。

## 2. 交付文件

P2-2需提交：

```text
data/schemas/wearable_data_dictionary.xlsx
data/templates/wearable_product_template.json
docs/wearable_field_specification.md
```

## 3. 数据目录建议

```text
data/
├─ phase2_wearable_product_list.xlsx
├─ schemas/
│  └─ wearable_data_dictionary.xlsx
├─ templates/
│  └─ wearable_product_template.json
└─ wearables/
   ├─ raw/
   ├─ processed/
   └─ sources/
```

## 4. 填写原则

1. 产品必须来自已经冻结的16款名单。
2. 产品名称必须与官方页面一致。
3. 每个产品只能使用一个明确的 `source_region`。
4. 不得把不同地区版本的参数混合填写。
5. 数据来源只能使用小米、Xiaomi或REDMI官方产品页、规格页、说明书和支持页。
6. 未找到官方数据时使用 `null`，不得依据第三方资料猜测。
7. 缺失数组统一使用 `[]`。
8. 布尔字段只允许 `true`、`false` 或 `null`。
9. 成员不得自行新增、删除或改名字段；确需新增字段，应由组长统一修改字段字典。
10. 颜色和表带版本不作为独立产品；NFC、41mm、Lite等差异写入 `variant`。

## 5. 单位规则

| 字段 | 统一单位 | JSON示例 |
|---|---|---|
| `display_size_in` | 英寸 | `1.74` |
| `max_brightness_nits` | nit | `1200` |
| `battery_life_typical_days` | 天 | `21` |
| `battery_life_heavy_days` | 天 | `9` |
| `charging_time_minutes` | 分钟 | `60` |
| `weight_g` | 克 | `15.8` |
| `dimensions_mm` | 毫米，长×宽×厚 | `"46.5×20.7×10.9"` |

数值字段只保存数字，不附加单位。约值、是否含表带等情况写入 `data_quality.notes`。

## 6. 定位字段规则

`positioning_type`只允许：

- `built_in_gnss`：设备内置卫星定位
- `connected_phone`：依赖手机定位
- `none`：明确不支持定位
- `null`：官方资料无法确认

不要再使用含义模糊的 `gps_support=true/false`。

## 7. 来源追溯

每款产品至少需要一条 `source_records`：

```json
{
  "field_scope": ["basic_info", "wearable_specs"],
  "source_url": "https://www.mi.com/...",
  "source_type": "product_page",
  "source_region": "GLOBAL",
  "accessed_at": "2026-07-21"
}
```

`source_type`只允许：

- `product_page`
- `specs_page`
- `manual`
- `support_page`

## 8. 数据状态

`data_quality.status`流程：

```text
draft → submitted → approved
                  ↘ rejected
```

只有 `approved` 数据才能进入 `processed` 目录和FAISS知识库。

## 9. 成员填写流程

1. 从 `wearable_product_template.json` 复制一份新文件。
2. 文件名建议使用产品ID，例如 `B01.json`、`W03.json`。
3. 按照官方页面填写基础信息和 `wearable_specs`。
4. 为所用官方页面增加 `source_records`。
5. 运行JSON格式检查。
6. 自检后将 `data_quality.status` 改为 `submitted`。
7. 组长核验来源、字段和单位。
8. 通过后由组长改为 `approved` 并放入 `data/wearables/processed/`。

## 10. JSON格式检查

在项目根目录执行：

```bash
python -m json.tool data/wearables/raw/B01.json
```

无报错即表示JSON语法正确。

也可以批量检查：

```python
import json
from pathlib import Path

for path in Path("data/wearables/raw").glob("*.json"):
    with path.open("r", encoding="utf-8") as file:
        json.load(file)
    print(f"OK: {path}")
```

## 11. 与现有耳机数据的关系

第二阶段不要求推翻耳机数据库。建议后端按 `product_category` 判断应读取的专用字段：

```text
earphone    → earphone_specs
smart_band  → wearable_specs
smart_watch → wearable_specs
```

通用字段如 `product_id`、`product_name`、`official_url` 和 `usage_scenarios` 可由三类产品共同使用。

## 12. P2-2验收条件

- 字段字典包含字段名、中文含义、类型、必填性、单位/枚举和缺失规则。
- JSON模板可以正常解析。
- 布尔值、数组、日期和单位规则明确。
- 来源记录能够追溯到官方页面。
- 手环和手表共用核心字段。
- 原有耳机数据无需删除。
- 三个交付文件已提交GitHub并经组长审核。
