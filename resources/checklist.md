# 自检清单（必须带计数写入 verification）

## 第 0/1 步：输入与工具
- [ ] 已读取 `/input/case.json` 与 `/input/task.md`，`case_id` 与 `output_contract` 已记录
- [ ] 骨架 `result.json` 已早期落盘并增量更新（含 `status: partial` 保底）
- [ ] 已打开真实 PDF，`sources` 覆盖文件路径、页数与版本信息
- [ ] 已探测并记录实际可用的解析工具与版本到 `parse_log.txt`，未假设包已安装
- [ ] 规则表（语言、关注字段、版式方向、禁止改动、输出字段）已建立并每步重读
- [ ] 未用题目标签、文件名或示例推断材料内容

## 第 2 步：栏序与页眉页脚
- [ ] 逐页提取了文字块与 bbox，写入 `/app/work/page_blocks.jsonl`
- [ ] 每页栏数与栏边界 x 坐标已记录，`reading_order` 有 `order_rule`
- [ ] 跨页重复且位于页面边缘的块已标为 `header_footer`，不混入正文
- [ ] 双栏/多栏按栏 → y → x 排序，跨栏标题与题注位置正确
- [ ] 计数：按锚点抽查通过页数 / 抽查页数；识别排除的页眉页脚块数 / 边缘重复块数

## 第 3/4 步：结构与逐字保真
- [ ] 章节层级与编号忠实原文，`section_tree` 无跳级或合并
- [ ] 正文、题注、脚注、参考文献逐字保留数字、单位、限定词、否定与引用编号
- [ ] 表格行列、表头层级、合并单元格、跨页续表逐格核对，`continued_from` 已填
- [ ] 公式、上下标、希腊字母与特殊符号保真；不确定符号列出而非静默替换
- [ ] 未新增材料外事实；图片型表格无法还原时保留占位并写 uncertainties
- [ ] 计数：表格归属正确数 / 检查数；公式符号保真项 / 检查项；材料外新增事实数 = 0

## 第 5 步：异常与回退
- [ ] 扫描页/无文字层已 OCR 回退并标 `source_type: ocr`，附置信度与日志
- [ ] 加密、乱码字体、页码错乱均写明具体位置与人工接管位置
- [ ] `status` 与实际完成度一致，未把失败写成 success

## 第 6/7 步：带计数的证据与诚实性
- [ ] `verification` 八项均有 `result` 与带计数/片段的 `evidence`
- [ ] `text_completeness`：逐页提取块数 / 可见块数，漏行数写明
- [ ] `anchor_spotcheck`：按锚点回查成功数 / 抽查数，附原文短引
- [ ] `uncertainty_disclosure`：已披露不可读/冲突项 / 发现的不可读/冲突项
- [ ] `evidence_map` 每条有原文短引与真实锚点，`source_type` 不用"推断"
- [ ] 缺口、冲突、权限不足写入 uncertainties；回修记入 `change_log`

## 提交前检查
- [ ] `result.json` 原样回填 `case_id` 与全部 `output_contract` 字段
- [ ] `parsed_text.md` / `structure_map.md` / `evidence_map.md` / `parse_log.txt` 已写盘
- [ ] 包内不含 `result.json`、正式案例答案或预制输出
- [ ] 资源为 UTF-8 文本、相对路径、无符号链接，单文件 ≤500KB、总量 ≤2MB
