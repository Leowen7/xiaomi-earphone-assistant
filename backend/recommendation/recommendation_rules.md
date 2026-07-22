# 小米智能穿戴选购推荐规则文档（P2-9最终版）

## 基础信息

1. 统一标准数据源：`data/wearables/processed/all_wearables.jsonl`。该文件为项目冻结数据，禁止修改产品ID、原生字段和官方参数。
2. 适用模块：P2-9推荐规则设计、客服导购问答、用户需求匹配和产品候选筛选；下游P2-10读取同一数据源实现评分与排序。
3. 执行顺序：

   `系统兼容性检查 → 硬过滤 → 人群匹配加分 → 场景匹配加分 → 综合排序`

4. 产品规格以冻结JSONL中的GLOBAL官方参数为准；价格仅沿用冻结文件中的`official_price`和`currency`，当前价格币种为AUD。
5. 所有判断只能使用JSONL中的原生字段，包括顶层字段、`wearable_specs`、`target_users`、`usage_scenarios`和`product_summary`。

## 全局约束

1. 字段值为`null`表示官方参数未知，不能解释为`false`，也不能作为产品优势。
2. `null`字段不满足`=true`、数值比较、文本包含等正向筛选条件。
3. 禁止将`official_price=null`描述为“低价”“免费”或“更便宜”。
4. NFC统一描述为：支持NFC，具体公交、门禁或支付服务视地区、版本、银行及服务可用性而定。
5. 蓝牙通话统一描述为：通过蓝牙连接手机，在手表端接听或拨打电话。没有蜂窝网络字段依据时，不得描述为完全脱离手机独立通话。
6. 游泳功能必须依据`sports_features`中的正向游泳词条。包含“不支持游泳”等否定词条时，不得判定为支持游泳记录。
7. `expected_candidates`表示满足全部硬过滤及系统兼容性要求的完整候选集合，不表示最终排名；P2-10再计算分数和Top排序。

# 一、测试条件与运算符规范

## 1. `user_device`枚举

- `iOS`：剔除明确不兼容iOS的设备W06、W07。
- `android_gms`：允许使用具备GMS要求的Wear OS设备。
- `android_no_gms`：剔除W06、W07。
- `android`：仅按Android兼容版本判断，不自动假设具备GMS。

系统兼容性属于全局硬过滤，即使未重复写入`hard_filter`，也必须执行。

## 2. `hard_filter`表达式

P2-10至少支持以下表达式：

- 等值：`product_category=smart_band`
- 布尔：`nfc_support=true`
- 数值：`battery_life_typical_days>=20`
- 集合：`product_id in [W06,W07]`
- 文本包含：`product_summary contains Wear OS`
- 数组包含：`sports_features contains 体成分测量`
- 数组正向游泳能力：`sports_features has_positive_swim_tracking=true`

其中`wearable_specs`中的字段可直接使用字段名；其他字段使用其顶层字段名。

# 二、一级硬过滤规则

## 1. 产品大类

- 手环：`product_category="smart_band"`，对应B01—B08。
- 手表：`product_category="smart_watch"`，对应W01—W08。

## 2. 手机系统兼容性

- `user_device=iOS`：剔除W06、W07。
- `user_device=android_no_gms`：剔除W06、W07。
- `user_device=android_gms`：W06、W07可以进入后续筛选。
- 其余设备根据`system_compatibility`判断。

## 3. 独立GNSS

准入条件：

`positioning_type="built_in_gnss"`

合格设备：

B01、B03、B06、W01、W02、W03、W04、W06、W07、W08。

已明确手机辅助定位：

W05，`positioning_type="connected_phone"`。

定位字段为`null`：

B02、B04、B05、B07、B08。以上设备不能描述为具备内置GNSS，也不能自动描述为手机辅助定位。

## 4. NFC

准入条件：

`nfc_support=true`

合格设备：

B01、W01、W02、W06、W07、W08。

`nfc_support=null`的设备不能进入NFC硬需求候选池。

## 5. 蓝牙通话

准入条件：

`bluetooth_call=true`

W01—W08均满足；B01—B08该字段为`null`，不能进入蓝牙通话硬需求候选池。

## 6. 尺寸与屏幕

- 细手腕明确要求41mm手表：W01。
- TFT屏幕：B05、B08。
- 大屏方形手表可通过`display_size_in`筛选；W03为2.07英寸、W04为1.96英寸、W05为2.0英寸。

## 7. 续航

- `battery_life_typical_days>=18`：B02、B03、B04、B05、W03、W04、W05。
- `battery_life_typical_days>=20`：B02、B03、B04。

## 8. Wear OS与Google Wallet

Wear OS准入条件：

`product_summary contains Wear OS`

Google Wallet需求可增加：

`usage_scenarios contains Google Wallet银行卡支付`

冻结数据中满足Wear OS要求的设备为W06、W07。

## 9. 体成分监测

准入条件：

`sports_features contains 体成分测量`

冻结数据中仅W07满足。

## 10. 游泳记录

准入条件：

`sports_features has_positive_swim_tracking=true`

判断方法：

- `sports_features`中存在“游泳”“水上运动”“泳池游泳”或“浅水运动记录”等正向词条；
- 同一词条不得包含“不支持”“无”等否定表达。

仅有`water_resistance="5ATM"`但没有正向游泳词条时，只能描述为浅水环境佩戴，不能描述为游泳记录。

## 11. 预算

用户传入`max_budget`和`currency`时：

1. `currency`必须一致；
2. `official_price`必须为数值；
3. `official_price<=max_budget`才进入正式候选。

`official_price=null`时：

- 无法确认是否满足预算；
- 不进入正式预算候选；
- 可以作为`near_match_product_id`，并在`unmet_conditions`中注明价格未知。

用户没有预算条件时，不因价格为`null`淘汰产品。

# 三、二级人群匹配加分

人群分仅根据`target_users`与用户人群关键词匹配，避免与具体功能重复计分。

1. 每命中一个`target_users`标签：+1分。
2. 人群匹配总分上限为4分。
3. 可进行同义词归一化，例如：
   - 学生、预算有限 → 预算敏感用户/学生群体；
   - 细手腕、女生小表盘 → 细手腕用户；
   - 长辈、健康关注 → 日常健康管理用户/健康关注者；
   - 户外跑步、徒步 → 户外运动用户/户外出行人群；
   - Wear OS、谷歌生态 → Wear OS应用需求用户/Google生态服务用户。
4. 人群分不再直接依据NFC、蓝牙通话或GNSS字段加分。

# 四、三级场景匹配加分

仅当用户明确提出相应需求时加分：

1. NFC通勤需求且`nfc_support=true`：+2。
2. 蓝牙通话需求且`bluetooth_call=true`：+2。
3. 脱离手机户外定位需求且`positioning_type="built_in_gnss"`：+1。
4. 游泳记录需求且满足正向游泳能力判断：+1。
5. 高运动模式需求且`sports_modes_count>=140`：+1。
6. 健康管理需求且心率、血氧、睡眠、压力四项均为`true`：+1。
7. 长续航偏好且`battery_life_typical_days>=15`：+1。

场景分最高9分。硬过滤只负责准入，不直接产生额外分数。

# 五、综合排序

P2-10计算：

`总分 = 人群匹配分（0—4） + 场景匹配分（0—9）`

总分相同时依次比较：

1. 用户偏好命中数量；
2. 在币种相同且价格均已知时，`official_price`较低者优先；
3. 已知价格优先于未知价格；
4. 按`product_id`字典序升序。

P2-9测试文件只验证完整候选集合，不强制验证候选数组中的排列顺序。

# 六、候选数量、近似匹配与兜底

1. 满足硬条件的产品少于3款时，按实际数量返回，不得用不符合条件的产品补足。
2. 无产品满足全部硬条件时，`expected_candidates`返回空数组。
3. `near_match_product_id`只能放置未满足少量硬条件的接近产品。
4. `unmet_conditions`必须明确写出其未满足条件。
5. 近似产品不得混入正式候选。
6. B02、W02仅作为无明确需求时的均衡参考机型，不参与强制补足。

# 七、推荐理由规范

每个正式候选包含：

- `product_id`
- `match_reasons`：3条可由冻结JSONL验证的理由

理由可使用：

- 明确数值，如`battery_life_typical_days=21`
- 明确布尔值，如`nfc_support=true`
- 明确数组内容，如`sports_features包含游泳追踪`
- 顶层字段内容，如`target_users`、`usage_scenarios`和`product_summary`

禁止使用无法由数据验证的主观表述，例如“性价比最高”“佩戴无负担”“最商务”“视觉效果最好”。
