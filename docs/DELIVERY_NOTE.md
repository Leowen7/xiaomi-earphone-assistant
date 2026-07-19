# DELIVERY_NOTE

## 任务基本信息

| 项目 | 内容 |
|------|------|
| **Jira编号** | AJ15XIAOMI-14 |
| **任务名称** | 耳机个性化推荐规则设计 |
| **负责人** | 组员B（数据清洗、对比和推荐） |
| **交付日期** | 2026-07-19 |
| **版本号** | **v4.2 最终验收版**（动态权重/排除筛选/不足生成/默认规则） |
| **依赖任务** | AJ15XIAOMI-12（数据清洗）、AJ15XIAOMI-13（产品对比） |
| **关联文档** | `ALGORITHM.md`（算法说明，已同步 v4.2） |

---

## 版本迭代历史（v1 → v2 → v3 → v4 → v4.1 → v4.2）

| 版本 | 日期 | 主要修复内容 |
|------|------|--------------|
| v1 | 2026-07-18 | 首版交付：4场景权重配置 + 加权评分 + 基础排序 |
| v2 | 2026-07-18 | 动态平局规则、推荐理由过滤、apply_preferences筛选接口、命令行参数支持 |
| v3 | 2026-07-18 | 数值评分改为单调线性映射修复跳变bug、固定三层排序、推荐理由改为客观描述 |
| v4 | 2026-07-18 | 缺失字段自动跳过归一化、补全product返回字段、空结果提示、过滤缺失字段推荐理由 |
| v4.1 | 2026-07-18 | 修正文档参数名错误、配置描述改为客观、top_k正整数校验、补全命令行说明 |
| **v4.2** | 2026-07-19 | 响应最终验收要求：<br>1. 新增"重视轻便/重视长续航"动态权重调整，调整后自动归一化<br>2. 新增excluded_wearing_types排除佩戴方式硬筛选<br>3. 新增每款产品不足/限制生成规则<br>4. 明确默认返回前3款规则，补全文档，约定任务15对接规则 |

---

## v4.2 验收修复清单（对应组长最终反馈）

| 验收要求 | 实现方案 | 代码位置 |
|---------|----------|---------|
| 定义"重视轻便"和"重视长续航"动态调整权重，调整后重新归一化 | 两个偏好各提升对应字段权重0.2，其余字段按比例缩放，最终归一化到权重和为1.0，支持同时开启 | `_adjust_weights()` L157-175 |
| 增加"排除入耳式"通用excluded_wearing_types硬筛选 | 新增列表类型参数，支持排除多个佩戴方式，和原有wearing_type参数兼容 | `apply_preferences()` L278-286 |
| 定义每款推荐产品的不足或限制生成规则 | 基于评分明细，取得分最低的1-2个有效字段，映射为客观不足描述，无不足时返回"无明显短板" | `format_limitations()` L323-352 |
| 补全文档，明确默认返回前3款以及与任务15的规则约定 | 文档补全所有规则，top_k默认值改为3，明确任务15对接约定，参数和代码100%对齐 | 本文档 + ALGORITHM.md §8-9 |
| 不处理任务15范围内的sort_by、Flask接口等内容 | 仅实现任务14范围内的规则，未修改任务15相关逻辑 | 主接口仅返回结构化dict |

---

## 完成功能清单

### 1. 核心评分能力
- ✅ 4个基础场景权重配置，每个场景权重和=1.0
- ✅ 三种字段评分算法：布尔字段/数值字段（单调线性无跳变）/枚举字段
- ✅ 缺失字段自动跳过，有效权重归一化，不会因为数据缺失扣分
- ✅ 固定三层排序规则，结果稳定可复现
- ✅ 动态权重调整：支持重视轻便/重视长续航，调整后自动归一化
- ✅ 客观优势推荐理由生成，无主观评价
- ✅ 客观不足/限制生成，无主观评价
- ✅ 配置文件驱动，无需改代码即可调权重

### 2. 硬筛选能力
- ✅ 价格区间筛选（reference_price_min / reference_price_max）
- ✅ ANC/低延迟/双设备布尔筛选（anc_supported / low_latency / dual_device）
- ✅ 指定佩戴方式筛选（wearing_type）
- ✅ 防水等级筛选（waterproof_min）
- ✅ 排除佩戴方式筛选（excluded_wearing_types，支持排除多个，如排除入耳式）

### 3. 接口与规范
- ✅ `recommend_products()` 对外主接口，默认返回前3款
- ✅ `apply_preferences()` 硬筛选函数，参数和文档100%对齐
- ✅ 完整参数校验，非法输入返回明确错误
- ✅ 空结果友好提示，包含具体放宽建议
- ✅ 错误统一返回 `{success: false, error: "..."}`，前端友好
- ✅ 全部相对路径，无本地绝对路径
- ✅ 字段100%对齐数据字典，无自造字段
- ✅ 8款冻结产品，无增减
- ✅ 命令行测试支持，覆盖所有筛选和权重调整参数

---

## 接口说明

### 主接口 `recommend_products()`

```python
def recommend_products(
    scenario: str,                         # 场景：daily / commuting / sports / gaming
    min_score: float = 0.0,               # 最低分数门槛（0~100）
    top_k: Optional[int] = 3,              # 返回前 k 个结果，默认 3（返回前3款），None 返回全部
    sort_by: str = "score",                # 平局排序键：score / price / weight
    prioritize_lightweight: bool = False,  # 【评分调整】动态提权：重视轻便，权重 +0.2 后归一化
    prioritize_long_battery: bool = False,  # 【评分调整】动态提权：重视长续航，权重 +0.2 后归一化
    preferences: Optional[dict] = None,    # 【硬筛选】过滤条件字典，默认无筛选
) -> dict
```

> **参数分类说明**：前 6 个为函数独立参数（包含场景、分页、排序、评分权重调整），`preferences` **仅用于硬筛选过滤**，和评分参数完全分离。

**preferences 参数支持的 key（全部为可选硬筛选参数）**：

| key | 类型 | 说明 |
|-----|------|------|
| `reference_price_min` | float | 最低价格 |
| `reference_price_max` | float | 最高价格 |
| `anc_supported` | bool | 必须支持主动降噪 |
| `low_latency` | bool | 必须支持低延迟模式 |
| `dual_device` | bool | 必须支持双设备连接 |
| `wearing_type` | str | 必须匹配的佩戴方式（如"入耳式"） |
| `waterproof_min` | str | 最低防水等级（IPX4 < IP54 < IPX5 < IP55 < IPX8 < IP68） |
| `excluded_wearing_types` | list[str] | 排除的佩戴方式列表（如 `["入耳式", "骨传导"]`），支持排除多个 |

> 注意：`prioritize_lightweight` 和 `prioritize_long_battery` **不是** preferences 的 key，而是函数独立参数，用于动态调整评分权重。

**返回结构**：

```json
{
  "success": true,
  "scenario": "daily",
  "scenario_label": "日常使用",
  "total_count": 3,
  "message": null,
  "weight_adjusted": false,
  "products": [
    {
      "product": { "product_id": "...", "product_name": "...", ... },
      "score": 77.2,
      "breakdown": [...],
      "top_factors": ["single_weight_g", "reference_price"],
      "recommendation_reason": "单耳重量较轻、参考价格较低",
      "limitations": "不支持主动降噪"
    }
  ]
}
```

### 硬筛选函数 `apply_preferences()`

```python
def apply_preferences(products: list[dict], preferences: dict) -> list[dict]
```

在评分之前对产品列表进行过滤，返回满足所有硬筛选条件的产品列表。

### 动态权重调整函数 `_adjust_weights()`

```python
def _adjust_weights(
    base_weights: dict,
    prioritize_lightweight: bool = False,
    prioritize_long_battery: bool = False
) -> dict
```

基于基础权重，按偏好动态调整后重新归一化（权重和=1.0）。

---

## 验证方式

### 命令行测试

```bash
# 默认 daily 场景（返回前3款）
python recommend_products.py daily

# 指定场景
python recommend_products.py commuting
python recommend_products.py sports
python recommend_products.py gaming

# 打印评分明细
python recommend_products.py daily -v

# 指定 top_k（默认3，None返回全部）
python recommend_products.py daily --top-k 5

# 硬筛选示例
python recommend_products.py commuting --anc --price-max 500
python recommend_products.py sports --exclude-wearing 入耳式
python recommend_products.py daily --waterproof-min IPX5

# 动态权重调整
python recommend_products.py daily --prioritize-lightweight
python recommend_products.py commuting --prioritize-long-battery
python recommend_products.py daily --prioritize-lightweight --prioritize-long-battery

# 组合使用
python recommend_products.py commuting --anc --price-max 500 --prioritize-lightweight
```

### v4.2 验证点

- ✅ 动态权重调整：prioritize_lightweight / prioritize_long_battery 叠加后权重和仍=1.0
- ✅ 排除筛选：excluded_wearing_types 正确排除指定佩戴方式
- ✅ 不足生成：每款产品均有 limitations 字段，无明显短板时返回"无明显短板"
- ✅ 默认返回前3款：top_k=3 生效
- ✅ 4场景全跑通：daily / commuting / sports / gaming 均正常输出
- ✅ 空结果提示：包含具体放宽建议
- ✅ 数值公式单调性：价格从50元到2000元严格单调递减，无跳变

---

## 依赖说明

- **数据依赖**：依赖任务12生成的 `data/processed/product_data_clean.json`（必须先运行任务12）
- **配置依赖**：依赖 `configs/earphone_rules.json`（可选，缺失时使用代码内默认值）
- **Python依赖**：仅使用标准库（json / os / sys / typing），无需额外依赖

---

## 与任务15的规则约定

1. 任务15直接 `import recommend_products` 的 `recommend_products` 和 `apply_preferences` 函数即可，不需要修改评分逻辑
2. **动态权重参数**（`prioritize_lightweight` / `prioritize_long_battery`）作为 `recommend_products` 的**独立参数**传入，不需要放在 preferences 里
3. **硬筛选参数**全部通过 `preferences` 字典传入，支持的 key 参见上方接口说明
4. 所有参数名以 ALGORITHM.md 为准，和代码 100% 对齐
5. 权重调整幅度可通过修改 `configs/earphone_rules.json` 中的 `weight_adjust_delta` 调整，不需要修改代码
6. 后续补充字段数据后评分自动生效，不需要改代码
7. `recommend_products` 默认返回前 3 款（`top_k=3`），需要全部结果时传 `top_k=None`
8. 每款产品同时包含 `recommendation_reason`（优势）和 `limitations`（不足），前端可直接渲染，无需二次加工

---

## 验收检查清单

- [x] 动态权重调整：prioritize_lightweight / prioritize_long_battery 逻辑正确，归一化后权重和=1.0
- [x] 排除筛选：excluded_wearing_types 正确排除指定佩戴方式，支持排除多个
- [x] 不足生成：每款产品均有 limitations 字段，无明显短板时返回"无明显短板"
- [x] 默认返回前3款：top_k=3 作为默认值在代码和文档中一致
- [x] 文档补全：ALGORITHM.md 和 DELIVERY_NOTE.md 均为完整版，无截断
- [x] 任务15约定：接口参数、返回结构、约定条款全部在文档中明确
- [x] 数值公式单调性：4场景全跑通，无跳变bug
- [x] 排序确定性：固定三层排序，结果可复现
- [x] 硬筛选完整：6种筛选类型全部覆盖
- [x] 空结果友好提示：包含具体放宽建议
- [x] 错误处理：非法输入返回明确错误信息
- [x] 字段对齐：所有字段100%复用任务12标准字段
- [x] 布尔字段严格判断：`value is True`，避免脏数据误判
- [x] 缺失字段不扣分：null字段权重不计入归一化分母
- [x] 配置驱动：earphone_rules.json 驱动场景权重和阈值，无需改代码
- [x] 相对路径：全部使用 `__file__` 推导路径，无本地绝对路径
