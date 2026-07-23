# P2-6 穿戴设备 RAG 文本块生成

## 仓库目录

```text
data/wearables/
├── manuals/
│   └── raw/
│       └── P2-14_Wearable_FAQ_Compatible.docx
└── processed/
    ├── all_wearables.jsonl
    └── chunks/
        ├── wearable_parameter_chunks.jsonl
        ├── wearable_manualfaq_chunks.jsonl
        └── wearable_all_chunks.jsonl

scripts/p2_6/
├── json_to_chunks.py
├── word_faq_to_chunks.py
└── run_pipeline.py

docs/p2_6/
├── README.md
├── validation_report.md
└── run_log.txt
```

## 数据关系

| 数据源 | 文本块类型 | 数量 |
|---|---|---:|
| `data/wearables/processed/all_wearables.jsonl` | 9种参数主题 | 144 |
| `data/wearables/manuals/raw/P2-14_Wearable_FAQ_Compatible.docx` | `manual_faq` | 96 |
| 合并结果 | 全部文本块 | 240 |

## 使用方法

在仓库根目录执行：

```bash
python -m pip install python-docx
python scripts/p2_6/run_pipeline.py
```

还应在仓库根目录现有的 `requirements.txt` 中新增：

```text
python-docx>=1.1,<2.0
```

不要用本任务的依赖说明覆盖项目原有 `requirements.txt`。

## 预期结果

- 参数文本块：144条
- FAQ文本块：96条
- 合并文本块：240条
- 产品覆盖：16款
- errors：0
- warnings：0
- 进程退出码：0

## 输出字段说明

FAQ文本块中的：

- `source_domain_verified=true`：来源链接属于小米官方域名；
- `source_content_verified=false`：程序未逐条人工核对网页正文与中文答案；
- `data_status=approved`：结构、数量、唯一性和官方域名校验通过。

## 合并要求

把本包中的 `data`、`scripts`、`docs` 三个目录复制到仓库根目录并选择合并，不要把外层“P2-6_仓库合并版_最终”文件夹整体放进仓库。
