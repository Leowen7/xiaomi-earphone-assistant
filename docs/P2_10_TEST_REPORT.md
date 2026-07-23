# P2-10 穿戴设备推荐引擎测试报告

> 日期：2026-07-23  
> 测试环境：Python 3.13.5、pytest 9.0.2  
> 测试命令：`python -m pytest -q tests/test_wearable_recommendation.py`

## 最终测试结果

```text
52 passed in 0.08s
```

本结果仅代表P2-10穿戴设备推荐专项测试通过，不代表仓库其他模块的全部测试均已运行。

## 本轮最终修正

1. `expected_candidates`始终返回全部满足系统兼容性和硬过滤条件的完整候选集合。
2. `recommendations`单独按`top_k`返回最终推荐，默认最多3款。
3. 每款推荐均包含：
   - `rank`
   - `product_id`
   - `product_name`
   - `score`
   - `official_price`
   - `currency`
   - 恰好3条`match_reasons`
4. 综合排序顺序统一为：
   - `total_score`降序；
   - `preference_hits`降序；
   - 已知价格优先；
   - 已知价格从低到高；
   - `product_id`升序。
5. 仅有5ATM防水、但没有正向游泳词条的产品，不再描述为“支持游泳记录”或“可用于游泳”，只描述为浅水环境佩戴。
6. 测试直接读取P2-9正式文件：
   `backend/recommendation/recommendation_test_cases.json`
7. P2-10扩展用例T013—T015保存在测试代码的内联fixture中，不修改P2-9冻结测试文件。
8. 推荐理由删除“佩戴轻便”“大屏”“防护无忧”等主观措辞，改为重量、屏幕尺寸、防水等级等客观参数。

## 测试覆盖

| 测试内容 | 数量 |
|---|---:|
| P2-9冻结用例T001—T012 | 12 |
| P2-10扩展用例T013—T015 | 3 |
| 系统兼容性 | 3 |
| 硬过滤表达式 | 11 |
| 游泳正向/否定判定 | 2 |
| 分阶段筛选、近似匹配与候选构建 | 9 |
| 评分与排序 | 6 |
| Top3及输出结构 | 3 |
| 无候选处理与数据完整性 | 3 |
| **合计** | **52** |

## 关键验收结果

- T001—T012实际候选集合与P2-9正式`expected_candidates`一致。
- T003返回5个完整候选，同时`recommendations`仅返回Top3。
- T010返回4个完整候选，同时`recommendations`仅返回Top3。
- B05、B08没有正向游泳词条，不会被描述为支持游泳记录。
- 普通`android`不放行W06、W07，只有`android_gms`允许。
- `null`不等于`false`，价格未知不按0处理。
- 总分相同时，`preference_hits`优先于价格决定排序。
- 每款正式候选和推荐结果均生成恰好3条可验证理由。

## 正式依赖

本提交不包含也不修改以下冻结文件：

```text
data/wearables/processed/all_wearables.jsonl
backend/recommendation/recommendation_rules.md
backend/recommendation/recommendation_test_cases.json
```

运行测试前，以上文件应已存在于仓库正式路径。

## 本次允许提交的文件

```text
backend/recommendation/recommend_wearables.py
tests/test_wearable_recommendation.py
docs/P2_10_TEST_REPORT.md
```
