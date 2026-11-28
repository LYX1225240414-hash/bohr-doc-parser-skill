# ARM v1.1 产物契约（运行时交付清单）

本题由 LLM 评审读取题面评分表，并对运行产物逐项核验。除题面要求的 `/app/output/result.json` 外，`/app/output` 必须包含下列七个可复核产物。`resources/pdf_parser.py` 会自动写入；若某个文件因异常缺失，按本表补齐真实内容，**不得写入预制答案或虚构日志**。

| 产物 | 必须包含 | 生成方式 |
|---|---|---|
| `arm_manifest.json` | `arm_version=1.1`；`entrypoint=src/reproduce.py`；`environment.dependencies=src/requirements.txt`；`execution.log_path=execution/run.log`；`execution.artifacts` 列出实际文件；`expected_outputs` 与 artifacts 一一对应，路径均相对 `/app/output`（如 `result.json`、`src/reproduce.py`、`execution/results/result.json`，**不要写成 `outputs/...`**）；`characterization`、`trace` 路径 | 脚本自动写入；手工补齐时只列真实存在的文件 |
| `README.md` | 调用命令、依赖（可选 PyMuPDF/pdfplumber/pdftotext/pypdf）、输入输出路径、每个产物用途、限制与失败处理；明确声明不含预制答案 | 脚本自动写入，复核后可按实际情况补充 |
| `src/reproduce.py` | 本次真实使用的解析脚本副本（即 `resources/pdf_parser.py`）；可独立重跑 | 脚本运行时复制自身 |
| `execution/run.log` | 带时间戳的真实动作记录：读取 case、发现材料、探测工具、逐页提取、栏序、表格、公式、锚点、自检、产物写入、失败与回退 | 脚本 `RunLog` 自动写入 |
| `execution/results/` | 至少包含 `result.json`、`parsed_text.md`、`structure_map.md`、`evidence_map.md`、`parse_log.txt` 的本次运行副本 | 脚本自动复制 |
| `characterization.json` | `case_id`、`script_version`、`tools`（实际探测到的版本或 unavailable）、每个输入文档的页数/文字层/bbox 能力、方法列表；trace_factor 注明由平台计算 | 脚本自动写入 |
| `trace/trace.jsonl` | 每行一个真实动作对象（`step_type`、`timestamp`、`action`、`detail`），与 run.log 同源；不得编造 | 脚本 `RunLog.dump_jsonl` 自动写入 |

## 合规红线

- 七个产物是**运行时结果**，只能由真实输入生成；Skill 包内不得预置这些产物的"正式案例版本"。
- `src/reproduce.py` 必须是实际执行的脚本，不能是一句 `pass` 或占位说明。
- `execution/run.log` 与 `trace/trace.jsonl` 中的工具版本必须是探测结果；不可用时如实写 `unavailable`，不要伪造命令或时间。
- `arm_manifest.json` 的 `expected_outputs` 不要写入不存在的路径；不要在输出清单中放 `result.json` 的预制答案副本以外的虚构文件。
- 输出仍须满足题面 `output_contract` 的全部字段与 `case_id`；合同字段优先于本 Skill 扩展字段。

## 自检命令（在 /app/output 下）

```bash
python3 - <<'PY'
import json, os
need = ["arm_manifest.json","README.md","src/reproduce.py","execution/run.log",
        "execution/results","characterization.json","trace/trace.jsonl","result.json"]
print([p for p in need if not os.path.exists(p)])
m = json.load(open("arm_manifest.json", encoding="utf-8"))
print(m["arm_version"], m["entrypoint"], len(m["expected_outputs"]))
PY
```

第一行应输出 `[]`；否则按表补齐并在 `change_log` 中记录。
