# PDF 解析操作手册（方法与判据）

本文件只给方法与判据，不含任何案例答案。运行时所有原文与结论必须来自 `/input` 下的真实材料。

## 1. 工具探测（第 1 步）
1. 读取 `/input/case.json` 与 `/input/task.md`，记录 `case_id`、`output_contract`、材料路径。
2. 逐项探测并记录到 `parse_log.txt`：Python 解释器、`import fitz`（PyMuPDF）、`import pdfplumber`、`pdftotext -v`、`tesseract --version`、`ocrmypdf --version`。用实际命令的 stdout/stderr 记录可用版本；不可用就写 `unavailable`，不假装可用。
3. 选择优先级：有文字层 → PyMuPDF/pdfplumber 坐标抽取；无文字层 → 图像预处理 + OCR；混合页逐页分别处理。
4. 把实际调用的命令（含参数）逐条写入 `parse_log.txt`，便于复现。

## 2. 逐页坐标抽取（第 2 步）
- 每页导出文本块：bbox (x0,y0,x1,y1)、文本、字号、字体名、块序号，存入 `/app/work/page_blocks.jsonl`。
- 页眉页脚判据：同一 bbox 区域在 ≥2 页重复出现、位于页面上/下 12% 区域、内容相似（页码、期刊名、DOI 行）→ `header_footer`，不进正文但保留锚点。
- 栏数判据：统计正文块 x 中心分布，若出现两个稳定峰且峰间空隙明显 → 双栏；三个及以上 → 多栏；跨栏标题的 bbox 跨越两峰 → 单独插到栏序之前。
- 排序规则：先跨栏标题（按 y），再按栏（左→右或按实际版面），栏内按 y 再按 x；跨页续接块用文本首尾重合度判断并写 `cross_page_links`。
- 判断困难时保留两种候选顺序、附锚点进 uncertainties，不随意选一种写成事实。

## 3. 逐字保真（第 3 步）
- 提取文本不做改写、不做同义替换；数字、单位、正负号、上下标、希腊字母按原文 Unicode 保留。
- 断行合并仅在确认是同一段落折行时进行；合并前记录前后块 ID 到 `change_log`。
- 题注（Figure/Table caption）单独成块，与图表主体相邻但顺序按版面。
- 脚注与参考文献按编号单独成块，引用编号原样保留，不把脚注内容并入正文句子。

## 4. 表格还原（第 4 步）
1. 先找表格线（pdfplumber lines/rects 或 PyMuPDF drawings）；无表格线时用文字 x/y 对齐聚类推断网格。
2. 确定行列数、表头层级（多层表头逐层记录）、合并单元格范围（rowspan/colspan）。
3. 每格写 `row`/`col`/`value` 与锚点；跨页续表填 `continued_from` 指向上一页表格锚点，表头只在首表出现但续表仍需引用。
4. 图片型表格：若无法从文本层还原，保留 `table` 占位块与图号锚点，写 uncertainties 说明缺什么，不猜数值。

## 5. 公式与特殊字符（第 3/4 步）
- 优先保留原文 Unicode；能可靠转 LaTeX 时另存 `latex_or_unicode` 并在 `symbols_preserved` 记录。
- 上下标、希腊字母、求和/积分限、矩阵括号逐项核对；不能确认的符号写入 `uncertain_symbols` 与 uncertainties。
- 公式编号按原文记录到 `number` 与锚点，不重新编号。

## 6. 扫描件与 OCR 回退（第 5 步）
- 判据：页面文字层字符数接近 0 且渲染页含显著非白像素 → 扫描页。
- 流程：300 dpi 渲染 → 灰度/二值化 → OCR（记录语言参数）→ 用词典/上下文做后处理校验；不覆盖原文图像，OCR 文本单独保存。
- 每条 OCR 结果标 `source_type: ocr` 与置信度；关键数字与结论需二次回看图像，无法确认进 uncertainties。

## 7. 异常处置
| 情况 | 判据与动作 |
|---|---|
| 加密 PDF | 打开报错或需要密码 → 记录路径与报错，`status: unable/partial` |
| 页码错乱 | 印刷页码与 PDF 页序不一致 → 两者都记录，锚点以 PDF 物理页为准并注明印刷页码 |
| 乱码字体 | 出现替换字符或 ToUnicode 缺失 → 保留原始编码片段，标 uncertainties |
| 工具/权限失败 | 写清命令、退出码与已完成范围，尽早落盘 partial，不伪造日志 |

## 8. 轨迹与预算
- 64 次模型请求、900 秒、单次 16384 tokens；先保底落盘再增量完善。
- 目标 ≥30 个真实可核验动作：逐页打开、坐标抽取、栏序判定、题注分离、表格还原、公式核对、OCR、锚点抽查、回修各步都留痕；不编造操作。
