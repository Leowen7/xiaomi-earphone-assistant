# P2-7 FAISS知识库构建校验报告

## 构建结果

- 输入文本块：240
- 产品数量：16
- 参数文本块：144
- FAQ文本块：96
- FAISS向量数量：240
- Metadata数量：240
- Embedding模型：`BAAI/bge-small-zh-v1.5`
- Embedding维度：512
- 索引类型：`IndexFlatIP`
- 构建耗时：11.74秒

## 一致性校验

- 向量数量与输入一致：通过
- Metadata数量与输入一致：通过
- 产品覆盖16款：通过
- errors：0
- warnings：0

## 警告

- 无

## 输出文件

- `vector_store\wearables\wearable.faiss`
- `vector_store\wearables\wearable_metadata.jsonl`
- `vector_store\wearables\manifest.json`
