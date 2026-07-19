# 任务14 推荐算法说明（ALGORITHM v4.2.1 验收修正版）
## 1. 整体思路
对每款产品，先加载对应场景的基础权重，支持独立的动态权重调整（重视轻便/长续航）后重新归一化，再计算每个字段的加权分，求有效字段加权平均，最终得分归一化到 **0~100**。
排序采用固定三层规则，保证结果确定性。**默认返回评分最高的前3款产品**，需要全部结果可显式指定参数。

## 2. 接口定义（与代码100%对齐）
```python
def recommend_products(
    scenario: str,                          # 必选：使用场景 daily/commuting/sports/gaming
    min_score: float = 0.0,                 # 可选：最低分数门槛 0~100，默认0
    top_k: Optional[int] = 3,               # 可选：返回前k个结果，默认3（返回Top3），传None返回全部
    sort_by: str = "score",                 # 可选：平局排序键 score/price/weight，默认score
    prioritize_lightweight: bool = False,   # 可选：【评分调整】动态提权，重视轻便，默认False
    prioritize_long_battery: bool = False,  # 可选：【评分调整】动态提权，重视长续航，默认False
    preferences: Optional[dict] = None      # 可选：【硬筛选】过滤条件字典，默认无筛选
) -> dict
```
> 参数分类说明：
> - 前6个为函数独立参数，包含场景、分页、排序、评分权重调整
> - `preferences` 仅用于硬筛选过滤，不包含评分调整逻辑，和评分参数完全分离

---
## 3. 总分公式
$$
\text{total\_score} = \frac{\sum_{f \in \text{valid}}(w_f \cdot s_f)}{\sum_{f \in \text{valid}} w_f} \times 100
$$
- $w_f$：字段 $f$ 经过动态调整后的最终权重
- $s_f$：字段 $f$ 的归一化得分（0~1）
- 只有字段值非 None 的权重才计入归一化分母，缺失字段的权重不参与计算，不会因为数据缺失扣分。

## 4. 动态权重调整规则（v4.2新增，独立评分参数）
支持两种独立的权重偏好，开启后自动调整权重并重新归一化，保证所有权重和为1.0，不依赖场景在基础权重上叠加生效：
| 参数 | 调整规则 |
|------|----------|
| `prioritize_lightweight=True`（重视轻便） | `single_weight_g`（单耳重量）权重提升`weight_adjust_delta`（默认0.2，可在配置文件修改），其余字段权重按比例缩放，最终归一化到和为1.0 |
| `prioritize_long_battery=True`（重视长续航） | `total_battery_h`（总续航）权重提升`weight_adjust_delta`（默认0.2，可在配置文件修改），其余字段权重按比例缩放，最终归一化到和为1.0 |
- 两个偏好可同时开启，两个字段各提升对应delta后统一归一化
- 调整后不会出现负权重，所有字段权重≥0
- 权重调整幅度可通过配置文件修改，无需改代码

---
## 5. 单字段评分函数
### 5.1 数值字段（reference_price / single_weight_g / total_battery_h / ...）
使用**单调线性映射**，无跳变bug：
$$
\text{val}_{\text{clamp}} = \max(\text{min}, \min(\text{max}, v))
$$
$$
s_f =
\begin{cases}
(\text{val}_{\text{clamp}} - \text{min}) / (\text{max} - \text{min}) & \text{if higher\_is\_better = True} \\
(\text{max} - \text{val}_{\text{clamp}}) / (\text{max} - \text{min}) & \text{if higher\_is\_better = False}
\end{cases}
$$
- `higher_is_better=True`（续航、蓝牙版本等）：值越大分越高，严格单调递增
- `higher_is_better=False`（价格、重量等）：值越小分越高，严格单调递减
- 超出[min, max]范围的值截断到0.0或1.0，缺值标记为缺失字段跳过不参与评分

### 5.2 布尔字段（anc_supported / dual_device / low_latency）
$$
s_f = \begin{cases} 1 & \text{if 字段值为 True} \\ 0 & \text{if 字段值为 False 或 None} \end{cases}
$$
严格判断`value is True`，避免脏数据误判。

### 5.3 枚举字段（wearing_type / waterproof / codec）
查配置文件中的枚举分映射表，未匹配值返回0.5中性分，"待核验"返回0分。

---
## 6. 排序与平局规则
固定三层排序键，结果100%可复现，相同输入永远返回相同顺序：
| 层 | 键 | 方向 | 说明 |
|----|----|------|------|
| 主排序 | 总分 | 降序 | 分数高的排前面 |
| 第二层 | sort_by决定（默认price）<br>·score/price → reference_price<br>·weight → single_weight_g | 升序 | 同分时价格低/重量轻的排前面 |
| 第三层 | product_id | 升序（字典序） | 完全同分同价格时按产品ID排序 |

---
## 7. 硬筛选规则（全部通过preferences字典传入，评分前执行）
### 7.1 基础硬筛选
| 参数key | 类型 | 说明 |
|---------|------|------|
| `reference_price_min` | float | 最低价格，低于该价格的产品排除 |
| `reference_price_max` | float | 最高价格，高于该价格的产品排除 |
| `anc_supported` | bool | 必须支持主动降噪，值为True时不支持的产品排除 |
| `low_latency` | bool | 必须支持低延迟，值为True时不支持的产品排除 |
| `dual_device` | bool | 必须支持双设备连接，值为True时不支持的产品排除 |
| `wearing_type` | string | 必须匹配指定佩戴方式（入耳式/半入耳式等），不匹配的排除 |
| `waterproof_min` | string | 最低防水等级（IPX4 < IP54 < IPX5 < IP55 < IPX8 < IP68），等级不足的排除 |

### 7.2 排除佩戴方式筛选（v4.2新增）
| 参数key | 类型 | 说明 |
|---------|------|------|
| `excluded_wearing_types` | list[string] | 排除指定佩戴方式，如`["入耳式"]`则排除所有入耳式产品，支持同时排除多个 |
- 和`wearing_type`参数兼容：同时传时先匹配必须的佩戴方式，再排除列表中的类型
- 不传或传空列表不生效
- 参数名拼写：`excluded_wearing_types`（注意excluded拼写，无笔误）

---
## 8. 推荐理由与不足生成规则
### 8.1 推荐理由（产品优势）
1. 过滤缺失字段、无贡献字段（权重为0/得分为null）
2. 按加权贡献度`weighted_score`降序取前3个字段
3. 映射为客观中文短语，无主观评价：
| 字段 | 推荐文案 |
|------|----------|
| reference_price | 参考价格较低 |
| single_weight_g | 单耳重量较轻 |
| total_battery_h | 续航时间较长 |
| anc_supported | 支持主动降噪 |
| low_latency | 支持低延迟模式 |
| dual_device | 支持双设备连接 |
| bluetooth_version | 蓝牙版本较新 |
| wearing_type | 佩戴方式匹配 |
| waterproof | 防水等级匹配 |
| codec | 音频编码支持 |
- 无有效优势字段时返回"综合表现均衡"

### 8.2 不足/限制（v4.2新增，客观描述）
1. 过滤缺失字段
2. 布尔字段得0分（不支持该功能）直接判定为不足
3. 数值/枚举字段得分**<0.3**判定为不足（阈值0.3，避免将中等水平误判为短板）
4. 按得分升序（最差的在前）取前2个最明显的不足
5. 映射为客观中文短语，无主观评价：
| 字段 | 不足文案 |
|------|----------|
| reference_price | 参考价格较高 |
| single_weight_g | 单耳重量较重 |
| total_battery_h | 续航时间较短 |
| anc_supported | 不支持主动降噪 |
| low_latency | 不支持低延迟模式 |
| dual_device | 不支持双设备连接 |
| bluetooth_version | 蓝牙版本较低 |
| wearing_type | 佩戴方式匹配度一般 |
| waterproof | 防水等级较低 |
| codec | 音频编码支持一般 |
- 无明显不足时返回"无明显短板"

---
## 9. 通用规则
- 空结果返回友好提示，包含具体放宽建议
- 所有入参都有合法性校验，非法输入返回`{success: false, error: "明确错误信息"}`
- 返回结构中每个产品同时包含`recommendation_reason`（优势）和`limitations`（不足），前端可直接渲染，无需二次加工
- 配置文件缺失时自动使用默认配置兜底，不会崩溃
- 严格基于8款冻结产品数据，无增减

---
## 10. 与任务15的对接约定
1. 任务15直接import本模块的`recommend_products`和`apply_preferences`函数即可，不需要修改任何评分逻辑
2. 任务15基础对接时**不需要传动态权重参数**，使用默认`False`即可，动态权重为前端用户可选的高级功能
3. 所有硬筛选参数通过`preferences`字典传入，动态权重参数作为函数独立参数传入，不要混在preferences中
4. 所有参数名以本文档为准，和代码100%对齐，不要自行修改参数名
5. 权重、阈值、枚举得分调整直接修改`configs/earphone_rules.json`即可，不需要修改代码
6. 后续补充codec等字段数据后，评分会自动生效，不需要改代码

---
## 11. 返回数据结构示例
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
      "product": {
        "product_id": "EAR008",
        "product_name": "Redmi Buds 4",
        "model": "M2137E1",
        "brand": "REDMI",
        "reference_price": 199.0,
        "single_weight_g": 4.0,
        "source_url": "https://www.mi.com/redmi-buds-4",
        "update_date": "2026-07-16",
        "remarks": "续航条件说明"
      },
      "score": 77.2,
      "breakdown": [
        {"field": "reference_price", "weight": 0.25, "original_weight": 0.25, "field_score": 0.92, "weighted_score": 0.230, "is_missing": false}
      ],
      "top_factors": ["single_weight_g", "reference_price", "wearing_type"],
      "recommendation_reason": "单耳重量较轻、参考价格较低、佩戴方式匹配",
      "limitations": "不支持主动降噪、防水等级较低"
    }
  ]
}
```