---
name: literature-pdf-parser
description: "面向科研 PDF 文献解析的 Agent Skill：内置可离线运行的 resources/pdf_parser.py，从真实 PDF 逐页提取正文、题注、脚注、表格、公式与章节结构，校正双栏/多栏阅读顺序并排除页眉页脚，为每段结论绑定页码与区块锚点，输出带计数自检与不确定性说明的 result.json 及 ARM v1.1 全套复核产物；当用户要求解析、结构化、翻译核对或逐字抽取科研文献时使用，支持中英文与扫描件。"
---

# 文献文档解析：提得全、排得对、拆得清、核得回

把真实 PDF 变成**可继续使用、可逐条回查原文**的结构化结果，而不是一段"看起来像全文"的文本。本 Skill 锁定题面四项要求：**提得全**（正文、图表题注、脚注、参考文献不漏行，页眉页脚不混入）、**排得对**（双栏、多栏、跨栏、跨页顺序正确）、**拆得清**（章节层级、表格行列归属、公式上下标与希腊字母保真）、**核得回**（每个结果指回页码与区块，读不出如实标注）。

## 何时使用

- 需要解析科研 PDF、抽取结构化正文/表格/公式/参考文献，并让关键结论回到原文证据。
- 需要处理双栏论文、跨页续表、题注与正文分离、扫描版文字层缺失等真实版式问题。
- 需要比较加载 Skill 与基础 Agent 的解析质量增益，并给出可复核的操作记录。

不适用：无原文材料、只要一句摘要、要求编造论文内容或评测成绩的场景。

## 运行环境与输出路径（重要）

- 平台把本 Skill 安装到 `/skills/weekly-skill`，用固定的 3 个案例运行。先读真实输入 `/input/case.json` 与 `/input/task.md`；`case.json` 可能含 `case_id`、`output_contract`、PDF/材料路径、目标字段与约束。**以实际字段为准，不从题目标签、文件名或示例推断材料内容**。PDF 案例提供真实 PDF，没有预抽取答案层。
- 中间文件（页面文本、坐标表、切图、OCR 临时文件）写在 `/app/work`，不污染输入目录；资源从 `/skills/weekly-skill/resources/` 读取，均为 UTF-8 文本。
- **本包自带可执行解析工具 `resources/pdf_parser.py`（无需联网、无强制第三方依赖）。优先直接运行它拿到真实解析骨架与全部交付产物，再按下面的规则逐页复核与回修；不要在 900 秒预算内从零手写解析器。**
- 最终结构化结果写到 `/app/output/result.json`（UTF-8 合法 JSON），**完整原样回填 `output_contract` 的全部字段与 `case_id`**，再补充本 Skill 的扩展字段；合同字段与本表同名时以合同为准。
- 同时写出可读的 `/app/output/parsed_text.md`（按正确阅读顺序的正文与题注）、`/app/output/structure_map.md`（逐页区块坐标表）、`/app/output/evidence_map.md`（逐条锚点回查表）、`/app/output/parse_log.txt`（使用的工具命令、页数、栏数、OCR 与失败记录）。若 `output_contract` 指定其他产物路径，以合同为准；有可编辑中间产物时保留在 `/app/output`。
- 预算内**尽早写入诚实的部分结果**再增量完善：64 次模型请求、900 秒、单次 16384 tokens；3 个案例由平台安排，参赛者不提供测试案例、白板或正式答案。
- 交付时 `/app/output` 必须同时具备 ARM v1.1 复核产物：`arm_manifest.json`、`README.md`、`src/reproduce.py`、`execution/run.log`、`execution/results/`、`characterization.json`、`trace/trace.jsonl`；内置脚本会自动生成，缺失时按 `resources/arm_contract.md` 补齐。这些是**运行时由真实材料生成的产物**，不是提交包里的预制答案。
- 让可核验操作轨迹覆盖逐页打开、坐标抽取、栏序判定、表格还原、公式核对、锚点抽查、回修等 **≥30 个真实动作**，不要只抛出一个最终结论；不得为凑数编造命令或日志。
- 禁止提交预制答案、正式案例答案或假造的解析结果；本 Skill 包内不应含任何 `result.json`。
- 资源限制：最多 50 个 UTF-8 文本文件、单文件 ≤500KB、总计 ≤2MB、无符号链接。

## 输入输出

输入：真实 PDF 路径与任务说明；可选约束：目标语言、关注字段、表格输出形态、必须覆盖的章节。

输出 `result.json` 字段如下（`output_contract` 优先）：

| 字段 | 要求 |
|---|---|
| case_id | 从 case.json 原样回填；确实没有才填 `N/A` |
| status | `success` / `partial` / `unable` / `refused`；部分完成写明未完成页、区块与人工接管位置 |
| main_result | 按题目要求的解析产物：标题、作者与单位、摘要、章节树、正文块、图表题注、公式、参考文献、表格等；完整正文可放入合同字段，文件产物用路径引用 |
| blocks | 数组，每项 `type`（title/author/abstract/heading/paragraph/caption/table/equation/footnote/reference/header_footer）、`text`、`order`、`anchor`、`confidence`、`source_type` |
| section_tree | 数组，每项 `heading` / `level` / `number` / `anchor` / `children`，层级与编号忠实原文 |
| tables | 数组，每项 `caption` / `anchor` / `rows` / `cols` / `header` / `cells`（含 `row` / `col` / `rowspan` / `colspan` / `value`）/ `continued_from` |
| formulas | 数组，每项 `latex_or_unicode` / `number` / `anchor` / `symbols_preserved` / `uncertain_symbols` |
| reading_order | 对象，逐页记录 `page` / `columns` / `column_bboxes` / `header_footer_bboxes` / `order_rule` / `cross_page_links` |
| evidence_map | 数组，每项 `claim` / `value` / `evidence`（原文短引）/ `anchor` / `source_type` / `change_record`；**不得写推断或常识作为证据** |
| verification | 对象，每项含 `result`（pass/fail/na）与**带计数或抽查片段**的 `evidence`，项目见 `resources/checklist.md` |
| uncertainties | 数组，每项 `item` / `reason` / `anchor` / `question_for_author`；扫描页、乱码字体、无文字层、页码错乱分别写明 |
| sources | 使用的输入文件路径、页码范围、区块定位与工具版本，界定输入边界 |
| change_log | 按顺序记录问题 / 修正 / 位置 / 复核结果 |

**锚点格式**：`p<页>:<段>`、`p<页>:<栏>:<段>`、`p<页>:tab<号>`、`p<页>:fig<号>`、`p<页>:eq<号>`、`p<页>:footnote<号>`、`p<页>:ref<号>`。必须指向真实 PDF 页面上的真实位置；无法定位的条目写入 uncertainties，不填伪造锚点。

## 立即可用的解析工具（首选，不要从零写代码）

在确认输入路径后**第一件事**运行内置脚本，让真实 PDF 先变成带锚点的结构化骨架和全套产物：

```bash
python3 /skills/weekly-skill/resources/pdf_parser.py \
  --case /input/case.json \
  --out /app/output
```

脚本行为与边界：

- 从 `/input/case.json` 递归发现真实材料路径，也会扫描 `/input` 下的 PDF/TXT/MD；**不按题目标签猜内容**。
- 依次探测 PyMuPDF → pdfplumber → pdftotext → pypdf；有坐标时按「栏 → y → x」恢复阅读顺序，跨页重复边缘块标为 `header_footer`；无坐标时保留源顺序并在 `verification.reading_order_correct.result=na` 说明，不伪造 bbox。
- 自动识别标题/摘要/章节/题注/表格/公式/参考文献，生成 `blocks`、`section_tree`、`tables`、`formulas`、`reading_order`、`evidence_map`、`verification`、`uncertainties`、`sources`、`change_log`，并原样回填 `output_contract` 字段与 `case_id`。
- 写出 `result.json`、`parsed_text.md`、`structure_map.md`、`evidence_map.md`、`parse_log.txt`，以及 ARM v1.1 的 `arm_manifest.json`、`README.md`、`src/reproduce.py`、`execution/run.log`、`execution/results/`、`characterization.json`、`trace/trace.jsonl`。
- 脚本输出一行 JSON 摘要（`status` / `blocks` / `tables` / `uncertainties`）。若 `status: unable` 或 `blocks=0`，先检查 `parse_log.txt` 与 `sources`，再按异常处理决定 OCR 或如实报缺件。

脚本只是**保底与提速**，不能代替逐页复核：运行后按下面的第 2–6 步打开真实材料，抽查题注、跨栏、合并单元格、公式符号和锚点短引，发现错误就直接编辑 `/app/output/result.json` 与对应 Markdown 产物，并把每处修改写进 `change_log`。不得把示例或脚本占位文本当成正式案例答案。

## 工作流

### 第 0 步：落盘骨架并先跑内置解析器（先保底）
读 `/input/case.json` 与 `/input/task.md`，确认 `case_id`、`output_contract`、PDF 路径与任务边界；在 `/app/work` 建工作副本。立即运行上一节的 `resources/pdf_parser.py`：脚本先写 `status: partial` 骨架，再覆盖为真实解析结果，避免超时只留下空结果。若脚本因缺少输入无法运行，手工写骨架后继续。

### 第 1 步：确认输入边界与可用工具
打开真实 PDF（或材料），记录页数、语言、是否有文字层、是否扫描件、是否加密、是否含矢量表格与图片型表格。按 `resources/parsing_playbook.md` 探测镜像中实际可用的解析库/命令（如 PyMuPDF、pdfplumber、pdftotext、tesseract），记录版本与命令到 `parse_log.txt`；**不要假设某个包已安装，也不要伪造工具输出**。缺文件 → `status: unable` 并写明具体路径；加密/无文字层按异常处理。

### 第 2 步：逐页坐标抽取与版式判定
逐页提取文字块及坐标（bbox），写入 `/app/work/page_blocks.jsonl`。识别页眉页脚：跨页重复出现且位于页面上下边缘的块单独标为 `header_footer`，不计入正文。判定每页栏数（单栏/双栏/多栏/跨栏），记录栏边界 x 坐标与跨栏标题。按 `reading_order` 规则排序：先按栏、再按 y、再按 x；跨栏标题与图表题注按实际版面插入正确位置，不把相邻两段拼成一句。逐页把坐标表写入 `structure_map.md`。

### 第 3 步：结构拆分与逐字保真
按章节编号还原多级标题树；正文逐段保留原文词序、数字、单位、限定词、否定关系、引用编号，不改写、不翻译、不补造。图表题注与正文分离但保留相邻锚点。公式与希腊字母、上下标按 Unicode/LaTeX 原样保留，逐条填 `formulas` 并标注无法确认的符号。脚注与参考文献按编号单独成块，不并入正文。

### 第 4 步：表格结构还原与跨页续接
按 `resources/parsing_playbook.md` 的判据处理表格：先定位表格线或文本对齐网格，确定行列数、表头层级、合并单元格与跨页续表；为每格写 `row`/`col`/`rowspan`/`colspan`/`value` 与锚点。图片型表格若无法可靠重建，保留占位与锚点并在 `uncertainties` 说明，不猜数值。跨页续表在 `continued_from` 中指向上一页表格锚点。

### 第 5 步：扫描件与异常回退
无文字层或 OCR 错字时，按 playbook 做图像预处理（灰度、二值化、分辨率提升）、OCR 与后处理校验；把 OCR 原文与置信度、页码写入 `parse_log.txt`，并用 `source_type: ocr` 标记。加密 PDF 记录无法解密的具体页与原因；乱码字体记录编码与替换字符位置。任何回退都写 `status: partial` 与人工接管位置，不把 OCR 猜测写成事实。

### 第 6 步：带计数的自检与回修
逐项核对 `resources/checklist.md`，把**计数**写进 `verification`：
- `text_completeness`：逐页提取块数 / 目视或文本层可见块数，漏行数为 0 才算通过；
- `reading_order_correct`：按锚点抽查通过页数 / 抽查页数，附抽查片段；
- `header_footer_excluded`：识别并排除的页眉页脚块数 / 边缘重复块数；
- `table_structure`：单元格归属正确的表格数 / 检查表格数，含合并单元格与跨页续表；
- `formula_fidelity`：符号保真项 / 检查项，列出不确定符号；
- `anchor_spotcheck`：按锚点回查成功数 / 抽查数，附短引片段；
- `no_new_facts`：材料外新增事实数（必须为 0）；
- `uncertainty_disclosure`：已披露的不可读/冲突项数 / 发现的不可读/冲突项数。
失败项回到第 2–4 步修正并记入 `change_log`；仍无法解决则保留 `partial`，不得写成通过。

### 第 7 步：交付与复核
写出 `/app/output/result.json` 与全部产物，按 `resources/arm_contract.md` 逐项确认：`case_id` 已回填、`output_contract` 字段齐全、`evidence_map` 每条有原文短引和真实锚点、`verification` 每项有计数、`uncertainties` 与 `change_log` 如实填写；ARM v1.1 七个产物齐全且指向本次真实运行。最终答复只做简要说明，详细证据留在产物中。

## 异常处理

| 情况 | 处理 |
|---|---|
| 加密/损坏 PDF | 记录文件路径与报错，写 `status: unable` 或 partial，不猜内容 |
| 无文字层扫描件 | OCR 回退并标 `source_type: ocr`；保留低置信片段与人工接管位置 |
| 双栏串栏/错行 | 用坐标重排并重读上下文，记录栏边界与修正前后顺序 |
| 页眉页脚混入正文 | 按跨页重复与边缘位置识别，移入 `header_footer` 块并计数 |
| 跨页续表/合并单元格 | 补 `continued_from` 与 rowspan/colspan，无法确认标 uncertainties |
| 公式符号失真/乱码字体 | 保留 Unicode 原文与位置，列出不确定符号，不静默替换 |
| 工具缺失/权限不足/超时 | 尽早落盘 partial，写明失败命令与已完成范围，不伪造解析日志 |

## 资源

- `resources/pdf_parser.py`：**可离线运行的主解析脚本**，产出真实结构化结果与 ARM v1.1 全套产物（首选调用）。
- `resources/arm_contract.md`：ARM v1.1 产物清单、字段含义与缺失补齐规则。
- `resources/parsing_playbook.md`：工具探测、栏序判据、页眉页脚识别、表格与公式还原规则、OCR 回退流程。
- `resources/checklist.md`：带计数的自检清单。
- `resources/field_dict.md`：字段字典、锚点格式与 verification 计数项。
- `resources/output_example.json`：输出结构示意（占位示例，非答案）。
- `examples/README.md`：最小调用示例（示意）。
- `environment/resources.yaml`：**资源入口**。声明脚本运行时、输入输出路径、平台预装工具用途（`pdf-text-tool` / `pdf-render-tool` / `ocr-tool`）与产物说明。

## 最小示例

见 `examples/README.md`。示意输出仅展示字段结构，不代表任何真实科研案例的解析结果或评测成绩。
