# 字段字典（文献 PDF 解析）

`output_contract` 中的字段优先：同名时以合同为准，不得改名或遗漏；本表扩展字段补充在合同字段之后。

| 字段 | 类型 | 含义 |
|---|---|---|
| case_id | string | 从 case.json 原样回填；确实没有才填 `N/A` |
| status | string | `success` / `partial` / `unable` / `refused` |
| main_result | object/array | 按题目要求的解析产物；完整正文可写入合同字段或指向产物文件 |
| blocks | array | `type` / `text` / `order` / `anchor` / `confidence` / `source_type` |
| section_tree | array | `heading` / `level` / `number` / `anchor` / `children` |
| tables | array | `caption` / `anchor` / `rows` / `cols` / `header` / `cells` / `continued_from` |
| formulas | array | `latex_or_unicode` / `number` / `anchor` / `symbols_preserved` / `uncertain_symbols` |
| reading_order | object | 逐页 `page` / `columns` / `column_bboxes` / `header_footer_bboxes` / `order_rule` / `cross_page_links` |
| evidence_map | array | `claim` / `value` / `evidence` / `anchor` / `source_type` / `change_record` |
| verification | object | 每项 `result` + 带计数/片段的 `evidence` |
| uncertainties | array | `item` / `reason` / `anchor` / `question_for_author` |
| sources | array | 输入文件路径、页码范围、区块定位与工具版本 |
| change_log | array | 问题 / 修正 / 位置 / 复核结果 |

## block.type 允许值
`title` / `author` / `affiliation` / `abstract` / `heading` / `paragraph` / `caption` / `table` / `equation` / `footnote` / `reference` / `header_footer`。

## source_type 允许值
`material` / `text_layer` / `ocr` / `table_region` / `figure_region` / `author_confirmation`；不写"推断""常识"。

## 锚点格式
`p<页>:<段>` / `p<页>:<栏>:<段>` / `p<页>:tab<号>` / `p<页>:fig<号>` / `p<页>:eq<号>` / `p<页>:footnote<号>` / `p<页>:ref<号>`。
锚点必须指向真实 PDF 页面上的真实位置；无法定位的写入 uncertainties，不填伪造锚点。

## verification 计数项
- `text_completeness`：逐页提取块数 / 可见块数，漏行数单列
- `reading_order_correct`：锚点抽查通过页数 / 抽查页数
- `header_footer_excluded`：识别并排除块数 / 边缘重复块数
- `table_structure`：单元格归属正确表格数 / 检查表格数
- `formula_fidelity`：符号保真项 / 检查项
- `anchor_spotcheck`：回查成功数 / 抽查数（附短引）
- `no_new_facts`：材料外新增事实数（必须为 0）
- `uncertainty_disclosure`：已披露项 / 发现的不可读或冲突项
