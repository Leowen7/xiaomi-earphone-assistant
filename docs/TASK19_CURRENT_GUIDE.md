# AJ15XIAOMI-19 当前阶段后端集成说明

## 1. 当前已经完成

本代码包完成了任务17交付前，任务19可以独立完成的部分：

- `GET /api/health`
- `GET /api/products`
- `POST /api/compare`
- `POST /api/recommend`
- 统一成功/失败 JSON 格式
- 参数校验与错误码
- 相对路径读取产品数据
- 调用已有 `compare_products.py`
- 调用已有 `filter_recommend.py` 和 `recommend_products.py`
- `POST /api/chat` 占位接口
- 一键冒烟测试脚本

`/api/chat` 当前返回 HTTP 503 是预期行为，因为 AJ15XIAOMI-17 尚未交付。

---

## 2. 合并方法

把压缩包解压后，将其中的 `backend` 和 `docs` 文件夹复制到：

```text
xiaomi-earphone-assistant/
```

也就是仓库根目录。

允许覆盖：

```text
backend/app.py
```

不要删除或覆盖现有文件：

```text
backend/scripts/compare_products.py
backend/scripts/filter_recommend.py
backend/scripts/recommend_products.py
data/processed/product_data_clean.json
configs/earphone_rules.json
```

本代码包会直接调用这些已有成果。

---

## 3. 运行

在仓库根目录打开终端：

```bash
pip install -r requirements.txt
python backend/app.py
```

浏览器打开：

```text
http://127.0.0.1:5000
```

健康检查：

```text
http://127.0.0.1:5000/api/health
```

---

## 4. 一键检查当前接口

保持后端文件已经复制到仓库后，在仓库根目录执行：

```bash
python backend/scripts/smoke_test_task19.py
```

预期输出：

```text
✅ 健康检查
✅ 产品列表接口
✅ 产品对比接口
✅ 相同产品校验
✅ 个性化推荐接口
✅ 问答占位接口（等待任务17）
```

最后出现：

```text
当前阶段可完成的任务19后端检查全部通过。
```

---

## 5. 给赵阳的接口

### 5.1 获取8款耳机

```http
GET /api/products?category=earphone
```

返回：

```json
{
  "success": true,
  "products": [
    {
      "product_id": "EAR001",
      "product_name": "产品名称",
      "model": "产品型号",
      "brand": "Xiaomi",
      "category": "earphone",
      "product_level": "入门",
      "wearing_type": "半入耳式",
      "reference_price": 199
    }
  ]
}
```

### 5.2 产品对比

```http
POST /api/compare
Content-Type: application/json
```

请求：

```json
{
  "product_ids": ["EAR001", "EAR006"]
}
```

成功返回包含：

```text
products
comparison
advantages
missing_fields
```

### 5.3 智能推荐

```http
POST /api/recommend
Content-Type: application/json
```

请求：

```json
{
  "budget_max": 300,
  "scenario": "sports",
  "preferences": ["lightweight", "long_battery"],
  "must_have": ["waterproof"],
  "excluded_wearing_types": ["入耳式"],
  "top_k": 3
}
```

可选值：

```text
scenario:
daily
commuting
sports
gaming

preferences:
lightweight
long_battery

must_have:
anc
waterproof
low_latency
dual_device
```

成功返回包含：

```text
request_summary
recommendations
```

每条推荐包括：

```text
rank
product_id
product_name
score
score_details
reasons
limitations
missing_fields
```

### 5.4 问答占位接口

```http
POST /api/chat
Content-Type: application/json
```

请求：

```json
{
  "product_id": "EAR006",
  "question": "如何恢复出厂设置？",
  "top_k": 3
}
```

当前预期返回：

```json
{
  "success": false,
  "message": "说明书知识库尚未完成，待AJ15XIAOMI-17合并后开放问答服务",
  "error_code": "NO_KNOWLEDGE_FOUND",
  "sources": [],
  "knowledge_ready": false
}
```

赵阳前端可以据此显示“知识库建设中”，而不是继续返回手机等模拟回答。

---

## 6. 任务17完成后如何继续

旦同学交付任务17后，只修改：

```text
backend/services/chat_service.py
```

把当前占位逻辑替换成：

```text
校验产品与问题
→ 调用检索函数
→ 获取3—5条说明书片段
→ 调用大模型生成回答
→ 返回answer和sources
```

前端仍然调用 `/api/chat`，不需要再次修改接口地址。

旦同学提供的检索函数建议统一为：

```python
def search_manuals(product_id: str, query: str, top_k: int = 3) -> list[dict]:
    ...
```

每条结果至少包含：

```text
product_id
product_name
chunk_id
source_file
page
section
content
score
```

---

## 7. 当前验收结论

完成本代码包的本地运行与冒烟测试后，可以确认：

- AJ15XIAOMI-19 已进入“处理中”；
- 产品接口已完成；
- 对比接口已完成；
- 推荐接口已完成；
- 问答接口框架已完成；
- 完整问答功能仍等待 AJ15XIAOMI-17；
- 暂时不能把 AJ15XIAOMI-19 移动到“完成”。
