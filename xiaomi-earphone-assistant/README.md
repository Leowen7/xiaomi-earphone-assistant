# xiaomi-earphone-assistant

基于结构化产品数据与 RAG 的小米/REDMI 耳机智能对比、选购推荐与使用问答系统。

## 第一阶段目标

1. 完成 8 款小米/REDMI 耳机的数据采集、清洗和标准化。
2. 支持两款耳机参数对比。
3. 根据预算、场景和偏好返回前 3 款推荐结果。
4. 基于说明书、FAISS 和大模型完成产品使用问答，并展示来源。
5. 跑通前端、Flask 后端、产品数据、推荐服务和知识库的完整链路。

## 协作约定

- `main` 分支只保存已检查、可以运行的版本。
- 成员在自己的分支开发，完成后再合并。
- 不提交 `.venv`、`.idea`、`.env`、缓存和 API Key。
- 不修改已经确定的公共字段名和接口格式。
- 代码统一使用相对路径，不写个人电脑的绝对路径。
- 每次提交说明本次完成的具体内容。

## 建议分支

- `data-collection`
- `data-recommendation`
- `frontend-rag`
- `integration`

## 本地运行

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python backend/app.py
```
