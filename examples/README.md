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
2. 读取真实 `/input/case.json` 与 `/input/task.md`，按 SKILL.md 第 0 步先把骨架写到 `/app/output/result.json`。
3. 按 `resources/parsing_playbook.md` 探测工具、逐页抽取坐标、判栏序、还原表格与公式；中间文件写 `/app/work`。
4. 按 `resources/checklist.md` 做带计数自检，回修后增量写回 `/app/output/result.json`，并写 `parsed_text.md`、`structure_map.md`、`evidence_map.md`、`parse_log.txt`。
5. 最终答复只给简要说明，详细证据留在 `/app/output`。

## 输出说明

示意结构见 `../resources/output_example.json`。真实评测由平台用固定案例运行，参赛者不提交测试案例、白板或正式答案；提交包内不得含 `result.json`。
