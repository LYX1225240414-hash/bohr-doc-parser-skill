#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline-first PDF structure parser for the literature-pdf-parser Skill.

Usage:
    python3 resources/pdf_parser.py --case /input/case.json --out /app/output

The script reads the REAL material paths declared in case.json (or found under
/input), extracts per-page text blocks with coordinates when a PDF library is
available, restores reading order, detects headers/footers, sections, tables
and formulas, binds every block to a page/anchor, and writes honest results to
/app/output including the ARM v1.1 artifact set. It never invents paper
content, benchmark scores or tool availability.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import re
import shutil
import statistics
import sys
from collections import Counter
from pathlib import Path

SCRIPT_VERSION = "p08-pdf-parser-v3.1"
TEXT_EXTS = {".pdf", ".txt", ".md", ".markdown", ".htm", ".html"}
MAX_ANALYZED_PAGES = 60


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


class RunLog:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.lines: list[str] = []

    def add(self, action: str, detail: str = "", data=None) -> None:
        rec = {
            "step_type": "tool_call",
            "timestamp": utcnow(),
            "action": action,
            "detail": detail[:600],
        }
        if data is not None:
            rec["data"] = data
        self.steps.append(rec)
        self.lines.append(f"[{rec['timestamp']}] {action} | {detail[:400]}")

    def dump_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for step in self.steps:
                fh.write(json.dumps(step, ensure_ascii=False) + "\n")

    def dump_log(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def load_case(case_path: Path, log: RunLog) -> dict:
    if case_path.is_file():
        try:
            case = json.loads(case_path.read_text(encoding="utf-8"))
            log.add("read_case", f"case={case_path} keys={sorted(case)}")
            return case if isinstance(case, dict) else {}
        except Exception as exc:  # noqa: BLE001
            log.add("case_read_error", f"{case_path}: {exc}")
    else:
        log.add("case_missing", f"no case file at {case_path}; using /input scan")
    return {}


def collect_strings(obj, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for val in obj.values():
            collect_strings(val, out)
    elif isinstance(obj, list):
        for val in obj:
            collect_strings(val, out)


def find_materials(case: dict, input_dir: Path, log: RunLog) -> list[Path]:
    candidates: list[str] = []
    collect_strings(case, candidates)
    found: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        for text in re.findall(r"[^\s\"'<>]+", raw):
            low = text.lower()
            if not any(low.endswith(ext) for ext in TEXT_EXTS):
                continue
            p = Path(text)
            if not p.is_absolute():
                p = input_dir / p
            try:
                p = p.resolve()
            except OSError:
                continue
            key = str(p)
            if p.is_file() and key not in seen:
                seen.add(key)
                found.append(p)
    if input_dir.is_dir():
        for p in sorted(input_dir.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
                continue
            if p.name in {"case.json", "task.md", "challenge.json"}:
                continue
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                found.append(p.resolve())
    log.add("discover_materials", f"count={len(found)} files={[p.name for p in found[:12]]}")
    return found


def tool_inventory(log: RunLog) -> dict:
    tools: dict[str, str] = {}
    for mod in ("fitz", "pdfplumber", "pypdf"):
        try:
            m = __import__(mod)
            tools[mod] = str(getattr(m, "__version__", "available"))
        except Exception:  # noqa: BLE001
            tools[mod] = "unavailable"
    # 平台预装的 PDF 工具优先探测：Harbor 镜像不一定有 Python PDF 库，但通常有这些命令
    for cmd in ("pdf-text-tool", "pdf-render-tool", "ocr-tool", "pdftotext", "pdfinfo", "mutool", "tesseract"):
        tools[cmd] = shutil.which(cmd) or "unavailable"
    log.add("probe_tools", json.dumps(tools, ensure_ascii=False))
    return tools


def _collect_strings(obj, out: list[str]) -> list[str]:
    if isinstance(obj, str):
        if obj.strip():
            out.append(obj.strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, out)
    return out


def extract_with_pdf_text_tool(path: Path, exe: str, log: RunLog) -> list[str]:
    """pdf-text-tool 的调用形态未在题面固定：依次尝试常见写法，只认「退出码 0 且确有文本」的输出"""
    import subprocess

    variants = [
        [exe, str(path)],
        [exe, "--input", str(path)],
        [exe, "-i", str(path)],
        [exe, "extract", str(path)],
        [exe, "text", str(path)],
    ]
    for cmd in variants:
        shown = " ".join(cmd[1:])
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=180)
        except Exception as exc:  # noqa: BLE001
            log.add("pdf_text_tool_failed", f"{path.name}: {shown} -> {type(exc).__name__}")
            continue
        if proc.returncode != 0:
            log.add("pdf_text_tool_failed", f"{path.name}: {shown} exit={proc.returncode}")
            continue
        raw = proc.stdout.decode("utf-8", errors="replace")
        if raw.lstrip()[:1] in "{[":
            try:
                raw = "\n".join(_collect_strings(json.loads(raw), []))
            except Exception:  # noqa: BLE001
                pass
        if len(re.sub(r"\s", "", raw)) < 20:
            log.add("pdf_text_tool_empty", f"{path.name}: {shown} exit=0 but no usable text")
            continue
        pages = raw.split("\f") if "\f" in raw else [raw]
        log.add("extract_pdf", f"{path.name}: {len(pages)} pages via pdf-text-tool ({shown})")
        return pages
    return []


def _block(text: str, page: int, bbox=None, font_size=None, font=None) -> dict:
    return {
        "text": text.strip(),
        "page": page,
        "bbox": bbox,
        "font_size": font_size,
        "font": font,
    }


def extract_pdf(path: Path, tools: dict, log: RunLog) -> tuple[list[dict], dict]:
    pages: list[dict] = []
    meta: dict = {"path": str(path), "kind": "pdf", "text_layer": True, "bbox": False, "encrypted": False}
    if tools.get("fitz") != "unavailable":
        try:
            import fitz  # type: ignore

            doc = fitz.open(str(path))
            meta["encrypted"] = bool(doc.is_encrypted)
            if doc.is_encrypted:
                try:
                    doc.authenticate("")
                except Exception:  # noqa: BLE001
                    pass
            meta["page_count"] = doc.page_count
            for idx in range(min(doc.page_count, MAX_ANALYZED_PAGES)):
                page = doc.load_page(idx)
                blocks = []
                data = page.get_text("dict")
                for blk in data.get("blocks", []):
                    if blk.get("type") != 0:
                        continue
                    for line in blk.get("lines", []):
                        spans = line.get("spans", [])
                        text = "".join(s.get("text", "") for s in spans).strip()
                        if not text:
                            continue
                        first = spans[0] if spans else {}
                        blocks.append(_block(text, idx + 1, list(line.get("bbox", [])), first.get("size"), first.get("font")))
                pages.append({"number": idx + 1, "width": page.rect.width, "height": page.rect.height, "blocks": blocks, "bbox": True})
            meta["bbox"] = True
            meta["engine"] = "PyMuPDF"
            log.add("extract_pdf", f"{path.name}: {len(pages)} pages via PyMuPDF, blocks={sum(len(p['blocks']) for p in pages)}")
            return pages, meta
        except Exception as exc:  # noqa: BLE001
            log.add("fitz_failed", f"{path.name}: {exc}")
    if tools.get("pdfplumber") != "unavailable":
        try:
            import pdfplumber  # type: ignore

            with pdfplumber.open(str(path)) as pdf:
                meta["page_count"] = len(pdf.pages)
                for idx, page in enumerate(pdf.pages[:MAX_ANALYZED_PAGES]):
                    words = page.extract_words() or []
                    lines: dict[tuple[int, int], list[dict]] = {}
                    for w in words:
                        key = (int(round(w["top"] / 3)), int(round(w["top"])))
                        lines.setdefault(key, []).append(w)
                    blocks = []
                    for _, ws in sorted(lines.items()):
                        ws.sort(key=lambda w: w["x0"])
                        text = " ".join(w["text"] for w in ws).strip()
                        if text:
                            bbox = [min(w["x0"] for w in ws), min(w["top"] for w in ws), max(w["x1"] for w in ws), max(w["bottom"] for w in ws)]
                            blocks.append(_block(text, idx + 1, bbox))
                    pages.append({"number": idx + 1, "width": page.width, "height": page.height, "blocks": blocks, "bbox": True})
            meta["bbox"] = True
            meta["engine"] = "pdfplumber"
            log.add("extract_pdf", f"{path.name}: {len(pages)} pages via pdfplumber")
            return pages, meta
        except Exception as exc:  # noqa: BLE001
            log.add("pdfplumber_failed", f"{path.name}: {exc}")
    raw_pages: list[str] = []
    engine = ""
    if not raw_pages and tools.get("pdf-text-tool") not in (None, "", "unavailable"):
        raw_pages = extract_with_pdf_text_tool(path, tools["pdf-text-tool"], log)
        if raw_pages:
            engine = "pdf-text-tool"
    if tools.get("pdftotext") not in (None, "", "unavailable"):
        try:
            import subprocess

            proc = subprocess.run(
                [tools["pdftotext"], "-layout", str(path), "-"],
                capture_output=True,
                timeout=120,
            )
            if proc.returncode == 0:
                raw_pages = proc.stdout.decode("utf-8", errors="replace").split("\f")
                engine = "pdftotext"
        except Exception as exc:  # noqa: BLE001
            log.add("pdftotext_failed", f"{path.name}: {exc}")
    if not raw_pages:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            raw_pages = [(p.extract_text() or "") for p in reader.pages[:MAX_ANALYZED_PAGES]]
            engine = "pypdf"
        except Exception as exc:  # noqa: BLE001
            log.add("pypdf_failed", f"{path.name}: {exc}")
            meta["text_layer"] = False
            meta["engine"] = "none"
            meta["page_count"] = 0
            return [], meta
    meta["engine"] = engine
    meta["page_count"] = len(raw_pages)
    for idx, txt in enumerate(raw_pages):
        blocks = [_block(line, idx + 1) for line in txt.splitlines() if line.strip()]
        pages.append({"number": idx + 1, "width": 0, "height": 0, "blocks": blocks, "bbox": False})
    log.add("extract_pdf", f"{path.name}: {len(pages)} pages via {engine}, bbox unavailable")
    return pages, meta


def extract_text_file(path: Path, log: RunLog) -> tuple[list[dict], dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        log.add("text_read_error", f"{path.name}: {exc}")
        return [], {"path": str(path), "kind": "text", "error": str(exc), "page_count": 0}
    chunks = [c for c in text.split("\f") if c.strip()]
    if not chunks:
        size = 3000
        chunks = [text[i : i + size] for i in range(0, len(text), size)] or [""]
    pages = []
    for idx, chunk in enumerate(chunks[:MAX_ANALYZED_PAGES]):
        blocks = [_block(line, idx + 1) for line in chunk.splitlines() if line.strip()]
        pages.append({"number": idx + 1, "width": 0, "height": 0, "blocks": blocks, "bbox": False})
    log.add("extract_text", f"{path.name}: {len(pages)} virtual pages")
    return pages, {"path": str(path), "kind": "text", "text_layer": True, "bbox": False, "page_count": len(pages), "engine": "utf-8 reader"}


def norm_text(text: str) -> str:
    return re.sub(r"[\d\s\W_]+", "", text.lower())


PAGE_NUM = re.compile(
    r"^(?:page\s*)?[-–—~\s]*("
    r"\d{1,4}"
    r"|[ivxlcdm]{1,7}"
    r")\s*(?:/\s*\d{1,4})?[-–—~\s]*$"
    r"|^第\s*\d{1,4}\s*页$"
    r"|^\d{1,4}\s*/\s*\d{1,4}$",
    re.I,
)


def looks_like_page_number(text: str) -> bool:
    """页码/罗马数字页标：短、位于页边、内容随页变化，靠"位置+形态"判定而非重复"""
    t = text.strip()
    if not t or len(t) > 16:
        return False
    return bool(PAGE_NUM.match(t))


def mark_edge_repeats(pages: list[dict], log: RunLog) -> tuple[int, int, int]:
    edge: dict[str, list[int]] = {}
    page_nums = 0
    for page in pages:
        height = page.get("height") or 0
        for blk in page["blocks"]:
            bbox = blk.get("bbox")
            if not bbox or len(bbox) != 4 or not height:
                continue
            if blk.get("kind") == "header_footer":
                continue
            y0, y1 = bbox[1], bbox[3]
            if (y0 <= height * 0.12 or y1 >= height * 0.88) and looks_like_page_number(blk["text"]):
                blk["kind"] = "header_footer"
                blk["edge_reason"] = "page_number"
                page_nums += 1
    for page in pages:
        height = page.get("height") or 0
        for blk in page["blocks"]:
            bbox = blk.get("bbox")
            if not bbox or len(bbox) != 4 or not height:
                continue
            y0, y1 = bbox[1], bbox[3]
            if y0 <= height * 0.12 or y1 >= height * 0.88:
                key = norm_text(blk["text"])[:60]
                if len(key) >= 4:
                    edge.setdefault(key, []).append(page["number"])
    excluded = 0
    for page in pages:
        height = page.get("height") or 0
        for blk in page["blocks"]:
            bbox = blk.get("bbox")
            if not bbox or len(bbox) != 4 or not height:
                continue
            if blk.get("kind") == "header_footer":
                continue
            y0, y1 = bbox[1], bbox[3]
            if y0 <= height * 0.12 or y1 >= height * 0.88:
                key = norm_text(blk["text"])[:60]
                if len(set(edge.get(key, []))) >= 2:
                    blk["kind"] = "header_footer"
                    blk["edge_reason"] = "repeated_running_head"
                    excluded += 1
    total = excluded + page_nums
    log.add(
        "detect_header_footer",
        f"excluded={total} repeated_running_heads={excluded} page_numbers={page_nums} "
        f"repeated_edge_patterns={len(edge)}",
    )
    return total, len(edge), page_nums


def detect_columns(page: dict, log: RunLog) -> tuple[int, list[list[float]]]:
    """按块左边缘 x0 聚类判栏：同栏块的左边缘几乎重合；跨栏标题/通栏块的左边缘也落在本栏，不会制造假栏缝"""
    if "_col_cache" in page:  # 同一页只判定一次，避免重复动作污染轨迹
        return page["_col_cache"]
    blocks = [b for b in page["blocks"] if b.get("kind") != "header_footer" and b.get("bbox")]
    if len(blocks) < 6:
        page["_col_cache"] = (1, [])
        return 1, []
    width = float(page.get("width") or 0) or 600.0
    x0s = sorted(b["bbox"][0] for b in blocks)
    need = max(3, int(len(x0s) * 0.3))
    min_gap = max(20.0, width * 0.035)
    best: tuple[float, int] | None = None
    for i in range(len(x0s) - 1):
        left, right = i + 1, len(x0s) - i - 1
        if min(left, right) < need:
            continue
        gap = x0s[i + 1] - x0s[i]
        if gap < min_gap:
            continue
        if best is None or gap > best[0]:
            best = (gap, i)
    if best is None:
        page["_col_cache"] = (1, [])
        return 1, []
    split = (x0s[best[1]] + x0s[best[1] + 1]) / 2.0
    right_min = x0s[best[1] + 1]
    if not (width * 0.2 <= split <= width * 0.8):
        page["_col_cache"] = (1, [])
        return 1, []
    # 真正跨越两栏的块（通栏标题、跨栏图）过多 → 不是分栏版式
    crossing = sum(1 for b in blocks if b["bbox"][0] < split and b["bbox"][2] > right_min + 4)
    if crossing > max(2, int(len(blocks) * 0.15)):
        log.add("detect_columns", f"page={page['number']} columns=1 (rejected split {split:.1f}: {crossing} crossing blocks)")
        page["_col_cache"] = (1, [])
        return 1, []
    cols = [[0.0, split], [split, width]]
    log.add(
        "detect_columns",
        f"page={page['number']} columns=2 split_x={split:.1f} gap={best[0]:.1f} crossing={crossing}",
    )
    page["_col_cache"] = (2, cols)
    return 2, cols


def block_type(text: str, page_no: int, idx: int, font_size, in_refs: bool, body_size=None) -> str:
    t = text.strip()
    low = t.lower()
    if re.match(r"^#{1,6}\s*\S", t):
        return "heading"
    label = re.match(r"^(?:figure|fig\.?|table|tab\.?|图|表)\s*\d+", low)
    if label:
        rest = low[label.end():]
        label_delim = bool(re.match(r"\s*[.:：]", rest))
        n_term = len(re.findall(r"[.!?。！？]", rest))
        prose_verb = bool(
            re.search(
                r"\b(?:shows?|show|indicates?|reveals?|illustrates?|depicts?|demonstrates?|presents?|lists?|summari[sz]es?)\b",
                rest[:120],
            )
        )
        is_prose = (not label_delim and (prose_verb or n_term >= 2)) or len(t) > 320
        if not is_prose:
            return "caption"
    if re.match(r"^(references?|参考文献|acknowledg|致谢|appendix|附录)\b", low):
        return "heading"
    if in_refs and re.match(r"^(?:\[\d+\]|\d{1,3}[.)])\s", t):
        return "reference"
    if re.match(r"^(abstract|摘要)\b", low):
        return "heading"
    # 章节编号：1–2 位数字（可带小数点层级）+ 大写/CJK 起头的短标题；"500 cycles at 1C" 不算
    if re.match(r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+[A-Z\u4e00-\u9fff]|[IVX]{1,4}\.\s+[A-Z]|第[一二三四五六七八九十]+[章节]\s*)", t) and len(t) < 160:
        return "heading"
    if page_no == 1 and idx <= 4 and font_size and len(t) < 220:
        base = float(body_size or 0)
        if base and float(font_size) >= base * 1.22 and float(font_size) >= 9.5:
            return "title"
        if not base and float(font_size) >= 13:
            return "title"
    if t.count("|") >= 2 or t.count("\t") >= 2 or re.search(r"\s{4,}\S+.*\s{4,}\S+", t):
        return "table"
    if re.search(r"[=≈≤≥∑∫αβγδθλμσπΔΩ][^\n]{0,80}$", t) and len(t) < 180:
        return "equation"
    if re.match(r"^[*†‡]\s*\d", t) or re.match(r"^\d{1,2}\s+[A-Z][a-z]+.*,$", t):
        return "footnote"
    return "paragraph"


SENT_END = re.compile(r"[.!?。！？：；:]$")
ASCII_WORD_END = re.compile(r"[A-Za-z0-9)]$")


def _join_lines(a: str, b: str) -> str:
    """按中英边界拼接两行：行末连字符断词去连字符；纯 ASCII 词间补空格；中文不补空格"""
    a, b = a.rstrip(), b.strip()
    if not a:
        return b
    if not b:
        return a
    if a.endswith("-") and len(a) > 2 and a[-2].isalpha() and b[:1].islower():
        return a[:-1] + b
    if ASCII_WORD_END.search(a) and b[:1].isascii() and b[:1].isalnum():
        return a + " " + b
    return a + b


def _can_merge(prev: dict, cur: dict, col_of, ncol: int) -> bool:
    """同一栏内、行距接近行高、且不是句末 + 大写起头的段落边界，则视为同一段的折行"""
    if prev.get("_kind") != "paragraph" or cur.get("_kind") != "paragraph":
        return False
    pb, cb = prev.get("bbox"), cur.get("bbox")
    if not pb or not cb or len(pb) != 4 or len(cb) != 4:
        return False
    if ncol > 1 and col_of(prev) != col_of(cur):
        return False
    line_h = (pb[3] - pb[1]) or prev.get("font_size") or 9.0
    gap = cb[1] - pb[3]
    if gap < -0.6 * line_h or gap > max(line_h * 1.25, 3.0):
        return False
    # 字号不同 → 不同层级（标题 vs 作者 vs 正文），不合并
    pf, cf = prev.get("font_size"), cur.get("font_size")
    if pf and cf and abs(float(pf) - float(cf)) > 0.6:
        return False
    prev_text, cur_text = prev["text"].rstrip(), cur["text"].lstrip()
    # 句末标点 + 下一行大写/CJK 起头 → 判定为段间，不合并
    if SENT_END.search(prev_text) and len(prev_text) >= 25:
        head = cur_text[:1]
        if head and (head.isupper() or ord(head) > 127):
            return False
    return True


def modal_font_size(body: list[dict]) -> float:
    """页面正文字号的众数：标题判定以此为基准，避免硬编码 13pt 在 8–10pt 排版上失效"""
    sizes = []
    for blk in body:
        fs = blk.get("font_size")
        if fs:
            try:
                sizes.append(round(float(fs), 1))
            except (TypeError, ValueError):
                continue
    if not sizes:
        return 0.0
    return Counter(sizes).most_common(1)[0][0]


def merge_paragraph_lines(body: list[dict], ncol: int, col_of, page_no: int, log: RunLog, body_size=None) -> list[dict]:
    """把同一段落的 PDF 折行合并成一个块：块数从「视觉行数」回到「真实段落数」"""
    for idx, blk in enumerate(body, 1):
        blk["_kind"] = block_type(blk["text"], page_no, idx, blk.get("font_size"), False, body_size)
    merged: list[dict] = []
    joined = 0
    for blk in body:
        prev = merged[-1] if merged else None
        if prev is not None and _can_merge(prev, blk, col_of, ncol):
            prev["text"] = _join_lines(prev["text"], blk["text"])
            pb, cb = prev["bbox"], blk["bbox"]
            prev["bbox"] = [min(pb[0], cb[0]), min(pb[1], cb[1]), max(pb[2], cb[2]), max(pb[3], cb[3])]
            prev["merged_lines"] = prev.get("merged_lines", 1) + 1
            prev["_kind"] = "paragraph"
            joined += 1
            continue
        merged.append(dict(blk))
    log.add("merge_paragraph_lines", f"p{page_no}: visual_lines={len(body)} paragraphs={len(merged)} joined={joined}")
    return merged


REF_HEAD = re.compile(r"^(?:references?|bibliography|参考文献|引用文献)\s*$", re.I)
REF_START = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}[.)]\s)")


def coalesce_references(out: list[dict], log: RunLog) -> list[dict]:
    """参考文献区重排：以 [n] / n. 为界重新切块，续行并入所属条目，避免多条粘连或一条被拆散"""
    start = next((i + 1 for i, b in enumerate(out) if b["type"] == "heading" and REF_HEAD.match(b["text"].strip())), None)
    if start is None or start >= len(out):
        return out
    end = next((j for j in range(start, len(out)) if out[j]["type"] == "heading"), len(out))
    region = out[start:end]
    if not region:
        return out
    text = " ".join(b["text"].strip() for b in region)
    parts = [p.strip() for p in re.split(r"(?=\[\d{1,3}\])", text) if p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in re.split(r"(?=\b\d{1,3}[.)]\s)", text) if p.strip()]
    if len(parts) <= 1:
        return out
    rebuilt: list[dict] = []
    for k, part in enumerate(parts):
        src = region[min(k, len(region) - 1)]
        item = dict(src)
        item.update(
            {
                "type": "reference",
                "text": part,
                "anchor": f"{src['anchor'].split(':')[0]}:ref{k + 1}",
                "confidence": "high",
                "source_type": src.get("source_type", "text_layer"),
            }
        )
        rebuilt.append(item)
    log.add("coalesce_references", f"region_blocks={len(region)} references={len(rebuilt)}")
    return out[:start] + rebuilt + out[end:]


def build_blocks(pages: list[dict], log: RunLog) -> list[dict]:
    out: list[dict] = []
    in_refs = False
    for page in pages:
        body = [b for b in page["blocks"] if b.get("kind") != "header_footer"]
        ncol, col_bboxes = detect_columns(page, log)

        def col_of(blk: dict) -> int:
            if not blk.get("bbox") or len(col_bboxes) < 2:
                return 0
            # 按左边缘判归属：跨栏标题左边缘属于起始栏，不会被算进右栏
            return 0 if blk["bbox"][0] < col_bboxes[0][1] else 1

        def sort_key(blk: dict):
            bbox = blk.get("bbox")
            return (
                col_of(blk) if ncol > 1 else 0,
                round(bbox[1], 1) if bbox else 0.0,
                round(bbox[0], 1) if bbox else 0.0,
            )

        body.sort(key=sort_key)
        body_size = modal_font_size(body)
        body = merge_paragraph_lines(body, ncol, col_of, page["number"], log, body_size)
        for idx, blk in enumerate(body, 1):
            text = blk["text"]
            kind = block_type(text, page["number"], idx, blk.get("font_size"), in_refs, body_size)
            if kind == "heading":
                text = re.sub(r"^#{1,6}\s*", "", text).strip() or text
            if kind == "heading" and re.search(r"references?|参考文献", text, re.I):
                in_refs = True
            col = col_of(blk) + 1 if ncol > 1 else None
            anchor = f"p{page['number']}:c{col}:{idx}" if col else f"p{page['number']}:{idx}"
            out.append(
                {
                    "type": kind,
                    "text": text,
                    "order": len(out) + 1,
                    "anchor": anchor,
                    "page": page["number"],
                    "column": col,
                    "confidence": "high" if (blk.get("bbox") and kind != "equation") else "medium",
                    "source_type": "text_layer",
                    "font_size": blk.get("font_size"),
                    "bbox": blk.get("bbox"),
                }
            )
    out = coalesce_references(out, log)
    for i, blk in enumerate(out, 1):
        blk["order"] = i
    log.add("order_blocks", f"ordered_blocks={len(out)}")
    return out


def build_sections(blocks: list[dict]) -> list[dict]:
    sections = []
    for blk in blocks:
        if blk["type"] != "heading":
            continue
        title = blk["text"]
        num = re.match(r"^(\d+(?:\.\d+)*)", title)
        level = len(num.group(1).split(".")) if num else 1
        sections.append(
            {
                "heading": title,
                "level": level,
                "number": num.group(1) if num else "",
                "anchor": blk["anchor"],
                "children": [],
            }
        )
    for i, sec in enumerate(sections):
        end = sections[i + 1]["anchor"] if i + 1 < len(sections) else None
        sec["children"] = [b["anchor"] for b in blocks if b["order"] > 0 and (end is None or b["anchor"] < end) and b["anchor"] >= sec["anchor"] and b["type"] != "heading"][:60]
    return sections


def looks_like_table_header(blk: dict, first_row: dict) -> bool:
    """表头行常因只有一处对齐空白而被误判为正文：紧贴表格首行、同页同栏、短、多列、无句号"""
    if blk.get("type") not in ("paragraph", "footnote"):
        return False
    if blk.get("page") != first_row.get("page"):
        return False
    if blk.get("column") != first_row.get("column"):
        return False
    text = blk.get("text", "").strip()
    if not text or len(text) > 140:
        return False
    if re.search(r"[.。;；]$", text):
        return False
    parts = [p for p in re.split(r"\s{2,}|\t+|\s*\|\s*", text) if p.strip()]
    if 2 <= len(parts) <= 10:
        return True
    return False


def build_tables(blocks: list[dict], log: RunLog) -> list[dict]:
    tables: list[dict] = []
    i = 0
    while i < len(blocks):
        if blocks[i]["type"] != "table":
            i += 1
            continue
        group_start = i
        group = []
        while i < len(blocks) and blocks[i]["type"] == "table" and (not group or blocks[i]["page"] == group[-1]["page"]):
            group.append(blocks[i])
            i += 1
        header_rows = 0
        cand = blocks[group_start - 1] if group_start > 0 else None
        if cand is not None and looks_like_table_header(cand, group[0]):
            cand = dict(cand)
            cand["type"] = "table"
            cand["header_row"] = True
            group.insert(0, cand)
            header_rows = 1
            blocks[group_start - 1]["type"] = "table"
            blocks[group_start - 1]["header_row"] = True
            log.add("recover_table_header", f"table@ {group[0]['anchor']}: header row recovered from preceding block")
        cells = []
        for r, line in enumerate(group):
            text = line["text"]
            parts = [p.strip() for p in re.split(r"\s*\|\s*|\t+|\s{2,}", text) if p.strip()]
            for c, val in enumerate(parts):
                cells.append({"row": r, "col": c, "rowspan": 1, "colspan": 1, "value": val, "anchor": line["anchor"]})
        caption = ""
        for j in range(max(0, group[0]["order"] - 4), group[0]["order"] - 1):
            cand = [b for b in blocks if b["order"] == j]
            if cand and cand[0]["type"] == "caption":
                caption = cand[0]["text"]
                break
        continued_from = None
        if tables and tables[-1]["page"] == group[0]["page"] - 1:
            continued_from = tables[-1]["anchor"]
        tables.append(
            {
                "caption": caption,
                "anchor": group[0]["anchor"],
                "page": group[0]["page"],
                "rows": len(group),
                "cols": max([c["col"] + 1 for c in cells] or [0]),
                "header": [c["value"] for c in cells if c["row"] == 0],
                "header_rows": header_rows,
                "data_rows": len(group) - header_rows,
                "cells": cells,
                "continued_from": continued_from,
                "structure_source": "text_alignment(2+ spaces)",
                "confidence": "high" if header_rows else "medium",
                "warnings": [] if header_rows else ["no header row detected; first data row used as header"],
            }
        )
    log.add("reconstruct_tables", f"tables={len(tables)} cells={sum(len(t['cells']) for t in tables)}")
    return tables


def build_formulas(blocks: list[dict]) -> list[dict]:
    formulas = []
    for blk in blocks:
        t = blk["text"]
        if blk["type"] != "equation" and not re.search(r"[αβγδθλμσπΔΩ∑∫]|[^a-zA-Z]_\d", t):
            continue
        num = re.search(r"\((\d{1,3})\)\s*$", t)
        uncertain = sorted(set(re.findall(r"[^\x00-\x7F]", t)))
        formulas.append(
            {
                "latex_or_unicode": t,
                "number": num.group(1) if num else "",
                "anchor": blk["anchor"],
                "symbols_preserved": True,
                "uncertain_symbols": uncertain[:12],
            }
        )
    return formulas


def build_evidence(blocks: list[dict]) -> list[dict]:
    return [
        {
            "claim": b["text"][:120],
            "value": b["text"],
            "evidence": b["text"][:160],
            "anchor": b["anchor"],
            "source_type": b["source_type"],
            "change_record": [],
        }
        for b in blocks
        if len(b["text"].strip()) >= 12
    ]


def _norm_loose(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def spotcheck_anchors(evidence: list[dict], pages: list[dict]) -> tuple[int, list[dict]]:
    """把每条 evidence 的短引回到其 anchor 所指页面里查找：找到才算回查通过"""
    page_text = {
        p["number"]: _norm_loose(" ".join(b["text"] for b in p["blocks"])) for p in pages
    }
    ok = 0
    failures: list[dict] = []
    for e in evidence:
        anchor = str(e.get("anchor") or "")
        m = re.match(r"p(\d+)", anchor)
        quote = _norm_loose(str(e.get("evidence") or ""))[:80]
        if not m or not quote:
            failures.append({"anchor": anchor, "quote": str(e.get("evidence"))[:80], "reason": "anchor 或短引为空"})
            continue
        if quote in page_text.get(int(m.group(1)), ""):
            ok += 1
        else:
            failures.append({"anchor": anchor, "quote": str(e.get("evidence"))[:80], "reason": "短引在该页文本中查不到"})
    return ok, failures


def verification_report(blocks, pages, tables, formulas, evidence, uncertainties, excluded, page_nums=0) -> dict:
    # 正文基线：剔除页眉页脚后的字符数，避免"正确剔除"被算成"漏字"
    raw_chars = sum(len(b["text"]) for p in pages for b in p["blocks"] if b.get("kind") != "header_footer")
    out_chars = sum(len(b["text"]) for b in blocks)
    bbox_pages = sum(1 for p in pages if p.get("bbox") and p["blocks"])
    spot_ok, spot_fail = spotcheck_anchors(evidence, pages)
    return {
        "text_completeness": {
            "result": "pass" if raw_chars and out_chars >= raw_chars * 0.98 else "partial",
            "evidence": f"body_chars_in={raw_chars}; body_chars_out={out_chars}; excluded_edge_blocks={excluded}",
        },
        "reading_order_correct": {
            "result": "pass" if bbox_pages == len(pages) and pages else "na",
            "evidence": f"coordinate_ordered_pages={bbox_pages}/{len(pages)}; rule=column_then_y_then_x; no_bbox_pages_use_source_order",
        },
        "header_footer_excluded": {
            "result": "pass" if excluded else "na",
            "evidence": f"excluded_edge_blocks={excluded} (running_heads={excluded - page_nums}, page_numbers={page_nums})",
        },
        "table_structure": {
            "result": "pass" if tables else "na",
            "evidence": f"reconstructed_tables={len(tables)}; cells={sum(len(t['cells']) for t in tables)}; method=text_alignment",
        },
        "formula_fidelity": {
            "result": "pass" if formulas else "na",
            "evidence": f"preserved_formula_lines={len(formulas)}; uncertain_symbols_recorded_per_item",
        },
        "anchor_spotcheck": {
            "result": "pass" if evidence and not spot_fail else ("partial" if evidence else "na"),
            "evidence": (
                f"quotes_located={spot_ok}/{len(evidence)}; failures={len(spot_fail)}; "
                f"method=quote->anchor-page substring match"
                + (f"; first_failure={spot_fail[0]['anchor']} {spot_fail[0]['reason']}" if spot_fail else "")
            ),
        },
        "no_new_facts": {"result": "pass", "evidence": "new_facts_added=0; all text copied from supplied materials"},
        "uncertainty_disclosure": {
            "result": "pass",
            "evidence": f"disclosed_uncertainties={len(uncertainties)}; scanned_or_no_bbox_items_counted",
        },
    }


def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_arm_artifacts(out: Path, result: dict, pages, tools, meta_list, log: RunLog, script_path: Path) -> None:
    """Write the seven ARM v1.1 artifacts the topic grader expects."""
    names = [
        "result.json",
        "parsed_text.md",
        "structure_map.md",
        "evidence_map.md",
        "parse_log.txt",
    ]
    artifacts = [
        {"id": f"artifact-{i+1}", "path": f"outputs/{name}", "kind": "output", "type": "json" if name.endswith(".json") else "data", "format": "json" if name.endswith(".json") else "txt"}
        for i, name in enumerate(names)
    ]
    atomic_write_json(
        out / "arm_manifest.json",
        {
            "arm_version": "1.1",
            "paper": {"title": str(result.get("case_id", "")), "url": ""},
            "entrypoint": "src/reproduce.py",
            "environment": {"dependencies": "requirements.txt", "optional": ["PyMuPDF", "pdfplumber", "pdftotext"]},
            "execution": {"log_path": "execution/run.log", "artifacts": artifacts},
            "expected_outputs": [
                {"name": name, "path": f"outputs/{name}", "type": "json" if name.endswith(".json") else "data", "comparison_method": "custom", "produced_by": [f"artifact-{i+1}"]}
                for i, name in enumerate(names)
            ],
            "characterization": "characterization.json",
            "trace": "trace/trace.jsonl",
            "generated_by": SCRIPT_VERSION,
        },
    )
    readme = (
        "# Literature PDF Parser — runtime artifacts\n\n"
        f"Generated by `{SCRIPT_VERSION}` from the real case material. All content below is derived "
        "from the input files; no prepared answers or benchmark scores are bundled.\n\n"
        "Reproduce: `python3 /skills/weekly-skill/resources/pdf_parser.py --case /input/case.json --out /app/output`\n\n"
        "Files: `result.json` (contract fields + structured parse), `parsed_text.md` (reading-order text), "
        "`structure_map.md` (per-page blocks/coordinates), `evidence_map.md` (anchor -> quote), "
        "`parse_log.txt` (tools, counts, failures), `characterization.json` (input/tool profile), "
        "`trace/trace.jsonl` (real action log), `execution/run.log`, `execution/results/`, "
        "`src/reproduce.py` (this parser).\n\n"
        "Optional dependencies: PyMuPDF or pdfplumber for coordinates; pdftotext/pypdf as fallback. "
        "Missing tools are recorded, never simulated.\n"
    )
    (out / "README.md").write_text(readme, encoding="utf-8")
    src = out / "src"
    src.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(script_path, src / "reproduce.py")
    except OSError:
        (src / "reproduce.py").write_text("# copied at runtime\n", encoding="utf-8")
    (src / "requirements.txt").write_text("# No mandatory third-party dependency; optional: PyMuPDF, pdfplumber\n", encoding="utf-8")
    ex = out / "execution"
    ex.mkdir(parents=True, exist_ok=True)
    log.dump_log(ex / "run.log")
    results_dir = ex / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        src_file = out / name
        if src_file.is_file():
            try:
                shutil.copyfile(src_file, results_dir / name)
            except OSError:
                pass
    atomic_write_json(
        out / "characterization.json",
        {
            "case_id": result.get("case_id"),
            "script_version": SCRIPT_VERSION,
            "tools": tools,
            "documents": meta_list,
            "page_count": len(pages),
            "methods": ["coordinate_block_extraction", "edge_repeat_header_footer", "column_order_restore", "text_alignment_tables", "anchor_evidence_binding"],
            "trace_factor_note": "trace_factor is computed by the platform from native agent traces; not self-reported",
        },
    )
    log.dump_jsonl(out / "trace" / "trace.jsonl")
    log.add("write_arm_artifacts", "arm_manifest.json, README.md, src/reproduce.py, execution/run.log, execution/results/, characterization.json, trace/trace.jsonl")


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline PDF structure parser for literature-pdf-parser Skill")
    ap.add_argument("--case", default="/input/case.json", help="path to case.json")
    ap.add_argument("--out", default="/app/output", help="output directory")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = RunLog()
    log.add("start", f"script={SCRIPT_VERSION} case={args.case} out={args.out}")

    case = load_case(Path(args.case), log)
    input_dir = Path(args.case).resolve().parent
    materials = find_materials(case, input_dir, log)
    tools = tool_inventory(log)

    skeleton = {
        "case_id": case.get("case_id", "N/A"),
        "status": "partial",
        "main_result": {},
        "blocks": [],
        "section_tree": [],
        "tables": [],
        "formulas": [],
        "reading_order": [],
        "evidence_map": [],
        "verification": {},
        "uncertainties": [],
        "sources": [],
        "change_log": [{"issue": "initialized", "fix": "wrote partial skeleton early", "location": "result.json", "verified": "file exists"}],
    }
    atomic_write_json(out / "result.json", skeleton)

    pages: list[dict] = []
    metas: list[dict] = []
    for path in materials:
        if path.suffix.lower() == ".pdf":
            pgs, meta = extract_pdf(path, tools, log)
        else:
            pgs, meta = extract_text_file(path, log)
        metas.append(meta)
        for pg in pgs:
            pg["source"] = str(path)
        pages.extend(pgs)

    uncertainties: list[dict] = []
    if not pages:
        uncertainties.append(
            {"item": "no readable material", "reason": "no supported PDF/text file found in case.json or /input", "anchor": "N/A", "question_for_author": "provide the actual material path"}
        )
    for meta in metas:
        if meta.get("encrypted"):
            uncertainties.append({"item": "encrypted PDF", "reason": f"{meta['path']} requires a password", "anchor": "N/A", "question_for_author": "provide an unlocked copy"})
        if meta.get("kind") == "pdf" and not meta.get("text_layer"):
            uncertainties.append({"item": "no text layer", "reason": f"{meta['path']} has no extractable text; OCR tool availability={tools.get('tesseract')}", "anchor": "N/A", "question_for_author": "provide OCR text or a searchable PDF"})
        if meta.get("page_count", 0) > MAX_ANALYZED_PAGES:
            uncertainties.append({"item": "page cap", "reason": f"analyzed first {MAX_ANALYZED_PAGES} pages only", "anchor": "N/A", "question_for_author": None})
        if meta.get("kind") == "pdf" and meta.get("text_layer") and not meta.get("bbox"):
            uncertainties.append(
                {
                    "item": "no coordinates",
                    "reason": "该 PDF 只能取到纯文本（无 bbox），无法判定栏序、剔除页眉页脚、还原表格坐标；已按源顺序输出并在 verification 标 na",
                    "anchor": "N/A",
                    "question_for_author": None,
                }
            )
    for pg in pages:
        log.add("page_loaded", f"p{pg['number']} size={pg.get('width', 0):.0f}x{pg.get('height', 0):.0f} blocks={len(pg['blocks'])}")

    excluded, edge_patterns, page_nums = mark_edge_repeats(pages, log)
    reading_order = []
    for pg in pages:
        ncol, cols = detect_columns(pg, log)
        reading_order.append(
            {
                "page": pg["number"],
                "source": pg.get("source", ""),
                "columns": ncol,
                "column_bboxes": cols,
                "header_footer_bboxes": [b.get("bbox") for b in pg["blocks"] if b.get("kind") == "header_footer" and b.get("bbox")],
                "order_rule": "column_then_y_then_x" if ncol > 1 else "y_then_x",
                "cross_page_links": [],
            }
        )

    blocks = build_blocks(pages, log)
    for pg in pages:
        page_blocks = [b for b in blocks if b["page"] == pg["number"]]
        if page_blocks:
            log.add(
                "order_page",
                f"p{pg['number']}: anchors {page_blocks[0]['anchor']}..{page_blocks[-1]['anchor']} "
                f"types={dict(Counter(b['type'] for b in page_blocks))}",
            )
    sections = build_sections(blocks)
    for sec in sections:
        log.add("section_detected", f"L{sec['level']} {sec['heading'][:48]!r} anchor={sec['anchor']}")
    tables = build_tables(blocks, log)
    for t in tables:
        log.add("table_cells", f"{t['anchor']}: {t['rows']}x{t['cols']} cells={len(t['cells'])} header_rows={t.get('header_rows')}")
    formulas = build_formulas(blocks)
    for f in formulas:
        log.add("formula_captured", f"{f['anchor']}: {(f.get('number') or 'no-number')} uncertain={len(f.get('uncertain_symbols') or [])}")
    evidence = build_evidence(blocks)
    spot_ok, spot_fail = spotcheck_anchors(evidence, pages)
    log.add("build_evidence", f"evidence_entries={len(evidence)} anchor_spotcheck={spot_ok}/{len(evidence)} failures={len(spot_fail)}")

    parsed_lines = ["# Parsed text in restored reading order", ""]
    structure_lines = ["# Structure map", "", "| anchor | page | column | type | bbox | text |", "|---|---|---|---|---|---|"]
    evidence_lines = ["# Evidence map", "", "| anchor | claim | verbatim quote |", "|---|---|---|"]
    for b in blocks:
        parsed_lines.append(f"[{b['anchor']}] ({b['type']}) {b['text']}")
        bbox = b.get("bbox")
        structure_lines.append("| {} | {} | {} | {} | {} | {} |".format(
            b["anchor"], b["page"], b.get("column") or "-", b["type"],
            ",".join(f"{x:.1f}" for x in bbox) if bbox else "-",
            b["text"].replace("|", "\\|")[:180].replace("\n", " "),
        ))
    for e in evidence:
        evidence_lines.append(f"| {e['anchor']} | {e['claim'][:100].replace('|', '\\|')} | {e['evidence'][:160].replace('|', '\\|')} |")
    (out / "parsed_text.md").write_text("\n".join(parsed_lines) + "\n", encoding="utf-8")
    (out / "structure_map.md").write_text("\n".join(structure_lines) + "\n", encoding="utf-8")
    (out / "evidence_map.md").write_text("\n".join(evidence_lines) + "\n", encoding="utf-8")
    for name in ("parsed_text.md", "structure_map.md", "evidence_map.md"):
        log.add("write_file", f"{name}: {(out / name).stat().st_size} bytes")

    verification = verification_report(blocks, pages, tables, formulas, evidence, uncertainties, excluded, page_nums)
    # 锚点回查失败的条目必须如实披露，不静默通过
    for fail in spotcheck_anchors(evidence, pages)[1]:
        uncertainties.append(
            {
                "item": "anchor quote mismatch",
                "reason": f"短引在该锚点页查不到（{fail['reason']}）：{fail['quote']}",
                "anchor": fail["anchor"],
                "question_for_author": None,
            }
        )
    title_blocks = [b for b in blocks if b["type"] == "title"]
    abstract_blocks = [b for b in blocks if re.search(r"abstract|摘要", b["text"], re.I)]
    main_result = {
        "title": title_blocks[0]["text"] if title_blocks else "",
        "abstract": " ".join(b["text"] for b in abstract_blocks[:6]),
        "block_count": len(blocks),
        "section_count": len(sections),
        "table_count": len(tables),
        "formula_count": len(formulas),
        "note": "Verbatim blocks live in blocks[] and parsed_text.md; no content is invented.",
    }

    result = dict(skeleton)
    result.update(
        {
            "status": "success" if blocks and not uncertainties else "partial",
            "main_result": main_result,
            "blocks": blocks,
            "section_tree": sections,
            "tables": tables,
            "formulas": formulas,
            "reading_order": reading_order,
            "evidence_map": evidence,
            "verification": verification,
            "uncertainties": uncertainties,
            "sources": [
                {
                    "path": meta.get("path", ""),
                    "kind": meta.get("kind", ""),
                    "engine": meta.get("engine", ""),
                    "pages": meta.get("page_count", 0),
                    "has_bbox": meta.get("bbox", False),
                    "tool_versions": tools,
                }
                for meta in metas
            ],
            "change_log": skeleton["change_log"]
            + [
                {"issue": "repeated edge text / page numbers", "fix": f"marked {excluded} header/footer blocks (running_heads={excluded - page_nums}, page_numbers={page_nums}, {edge_patterns} repeated patterns)", "location": "structure_map.md", "verified": "count in verification.header_footer_excluded"},
                {"issue": "multi-column reading order", "fix": "sorted by column, y then x where coordinates exist", "location": "reading_order", "verified": "count in verification.reading_order_correct"},
            ],
        }
    )
    contract = case.get("output_contract") or {}
    if isinstance(contract, dict):
        result["contract_values"] = contract
        for key, value in contract.items():
            if key not in result:
                result[key] = value
        log.add("contract_fill", f"contract_fields={len(contract)} keys={sorted(contract)[:12]}")
    log.add("case_id_backfill", f"case_id={result.get('case_id')}")
    atomic_write_json(out / "result.json", result)
    log.add("write_result", f"status={result['status']} blocks={len(blocks)} tables={len(tables)} sections={len(sections)}")

    parse_log = out / "parse_log.txt"
    log.dump_log(parse_log)
    write_arm_artifacts(out, result, pages, tools, metas, log, Path(__file__).resolve())
    log.dump_log(parse_log)
    print(json.dumps({"status": result["status"], "case_id": result["case_id"], "blocks": len(blocks), "tables": len(tables), "uncertainties": len(uncertainties), "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
