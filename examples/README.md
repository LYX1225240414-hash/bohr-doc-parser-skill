# 最小调用示例（示意，非正式案例答案）

本目录只展示调用方式与字段结构；示例中的文字均为占位符，不代表任何真实科研材料或评测结果。

## 输入示意

```json
{
  "case_id": "[示例标识]",
  "output_contract": {
    "case_id": "string",
    "status": "string",
    "main_result": "按题目要求的结构"
  },
  "materials": [
    "/input/[示例论文.pdf]"
  ],
  "task": "按原文顺序提取正文、章节、图表题注与表格，并给出页码锚点"
}
```

## 调用步骤

1. 在 Agent 中加载本 Skill（安装后路径 `/skills/weekly-skill`）。
2. 读取真实 `/input/case.json` 与 `/input/task.md`，确认材料路径与输出合同。
3. **先运行内置解析脚本**：`python3 /skills/weekly-skill/resources/pdf_parser.py --case /input/case.json --out /app/output`。它先写骨架再写完整结果，并生成 ARM v1.1 七个产物与真实运行日志。
4. 按 `resources/parsing_playbook.md` 打开真实材料抽查栏序、页眉页脚、表格、公式与锚点短引；发现错误直接回修 `/app/output/result.json` 及相关产物，并记入 `change_log`。
5. 按 `resources/checklist.md` 与 `resources/arm_contract.md` 做带计数自检，确认 `parsed_text.md`、`structure_map.md`、`evidence_map.md`、`parse_log.txt` 与 ARM 产物齐全。
6. 最终答复只给简要说明，详细证据留在 `/app/output`。

## 输出说明

示意结构见 `../resources/output_example.json`。真实评测由平台用固定案例运行，参赛者不提交测试案例、白板或正式答案；提交包内不得含 `result.json`。
