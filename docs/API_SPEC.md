# 接口约定（第一版）

## GET /api/products?category=earphone

## POST /api/compare
```json
{"product_ids": ["EAR001", "EAR002"]}
```

## POST /api/recommend
```json
{
  "budget_max": 300,
  "scenario": "sports",
  "preferences": ["lightweight", "long_battery"],
  "must_have": ["waterproof"]
}
```

## POST /api/chat
```json
{
  "product_id": "EAR001",
  "question": "这款耳机怎么恢复出厂设置？"
}
```
