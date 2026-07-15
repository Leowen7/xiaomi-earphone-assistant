# 小米耳机智能选购与客服助手 API 规范（v1）

## 1. 通用约定

- 基础路径：`/api`
- 请求和返回编码：UTF-8
- 数据格式：JSON
- 成功字段：`success: true`
- 失败字段：`success: false`
- 产品唯一标识：`product_id`
- 未知或缺失字段：`null`
- 前端不得保存或调用大模型 API Key

### 通用失败返回

```json
{
  "success": false,
  "message": "错误说明",
  "error_code": "INVALID_REQUEST"
}
```

建议错误码：

- `INVALID_REQUEST`
- `PRODUCT_NOT_FOUND`
- `NO_MATCHED_PRODUCT`
- `NO_KNOWLEDGE_FOUND`
- `LLM_SERVICE_ERROR`
- `INTERNAL_ERROR`

---

## 2. 健康检查

### GET `/api/health`

成功返回：

```json
{
  "success": true,
  "message": "service is running"
}
```

---

## 3. 获取产品列表

### GET `/api/products`

可选查询参数：

- `category`：第一阶段固定为 `earphone`

成功返回：

```json
{
  "success": true,
  "products": [
    {
      "product_id": "EAR001",
      "product_name": "REDMI Buds 8 青春版",
      "brand": "REDMI",
      "product_level": "入门",
      "wearing_type": "入耳式",
      "reference_price": null
    }
  ]
}
```

---

## 4. 产品参数对比

### POST `/api/compare`

请求：

```json
{
  "product_ids": ["EAR001", "EAR006"]
}
```

校验规则：

- `product_ids` 必须存在；
- 第一阶段必须恰好包含 2 个不同的产品 ID；
- 产品 ID 必须存在于产品数据库中。

成功返回：

```json
{
  "success": true,
  "products": [
    {
      "product_id": "EAR001",
      "product_name": "REDMI Buds 8 青春版"
    },
    {
      "product_id": "EAR006",
      "product_name": "REDMI Buds 8 Pro"
    }
  ],
  "comparison": [
    {
      "field": "reference_price",
      "label": "参考价格",
      "unit": "元",
      "values": {
        "EAR001": 199,
        "EAR006": 599
      },
      "conclusion": "EAR001 价格更低 400 元"
    },
    {
      "field": "anc_supported",
      "label": "主动降噪",
      "unit": null,
      "values": {
        "EAR001": true,
        "EAR006": true
      },
      "conclusion": "两款产品均支持主动降噪"
    }
  ],
  "advantages": {
    "EAR001": ["价格较低"],
    "EAR006": ["降噪能力更强", "功能更完整"]
  },
  "missing_fields": []
}
```

失败示例：

```json
{
  "success": false,
  "message": "请选择两款不同的耳机进行对比",
  "error_code": "INVALID_REQUEST"
}
```

---

## 5. 个性化选购推荐

### POST `/api/recommend`

请求：

```json
{
  "budget_max": 300,
  "scenario": "sports",
  "preferences": [
    "lightweight",
    "long_battery"
  ],
  "must_have": [
    "waterproof"
  ],
  "excluded_wearing_types": [
    "入耳式"
  ],
  "top_k": 3
}
```

字段说明：

- `budget_max`：预算上限，单位为元，可为 `null`；
- `scenario`：`daily`、`commuting`、`sports`、`gaming`；
- `preferences`：软偏好，可以为空数组；
- `must_have`：硬条件，不满足的产品直接排除；
- `excluded_wearing_types`：用户不能接受的佩戴方式；
- `top_k`：返回数量，第一阶段最大为 3。

成功返回：

```json
{
  "success": true,
  "request_summary": {
    "budget_max": 300,
    "scenario": "sports",
    "preferences": ["lightweight", "long_battery"],
    "must_have": ["waterproof"]
  },
  "recommendations": [
    {
      "rank": 1,
      "product_id": "EAR002",
      "product_name": "REDMI Buds 8 活力版",
      "score": 88.4,
      "score_details": {
        "budget": 100,
        "weight": 92,
        "battery": 85,
        "waterproof": 100
      },
      "reasons": [
        "价格符合预算",
        "重量较轻",
        "具备防水能力"
      ],
      "limitations": [
        "不支持主动降噪"
      ],
      "missing_fields": []
    }
  ]
}
```

没有符合产品：

```json
{
  "success": false,
  "message": "当前产品库中没有同时满足全部必须条件的产品",
  "error_code": "NO_MATCHED_PRODUCT",
  "suggestions": [
    "提高预算上限",
    "减少必须条件",
    "允许更多佩戴方式"
  ]
}
```

---

## 6. 说明书 RAG 问答

### POST `/api/chat`

请求：

```json
{
  "product_id": "EAR006",
  "question": "这款耳机怎么恢复出厂设置？",
  "top_k": 3
}
```

成功返回：

```json
{
  "success": true,
  "answer": "请将耳机放入充电盒，并按照说明书中的复位步骤操作。",
  "sources": [
    {
      "product_id": "EAR006",
      "product_name": "REDMI Buds 8 Pro",
      "source_file": "REDMI_Buds_8_Pro_用户手册.pdf",
      "page": 8,
      "content": "说明书相关原文片段",
      "score": 0.86
    }
  ]
}
```

无知识依据：

```json
{
  "success": false,
  "message": "当前说明书知识库中没有找到足够依据，请确认产品型号或换一种提问方式。",
  "error_code": "NO_KNOWLEDGE_FOUND",
  "sources": []
}
```

## 7. 接口变更规则

公共字段和接口格式合并到 `main` 后不得由个人直接修改。需要变更时：

1. 在 Jira 记录变更原因；
2. 更新本文件；
3. 通知前端、后端和数据负责人；
4. 使用独立 Pull Request 合并。
