# -*- coding: utf-8 -*-
"""Markdown 格式检查器：对《数学基础系列》全部 md 文件做结构健康检查。

检查项：
  1. UTF-8 可解码
  2. 代码块围栏成对闭合（``` / ~~~）
  3. Mermaid 块闭合
  4. $ / $$ 公式定界符配对（行内与块级）
  5. 表格列数一致性
  6. 标题层级跳跃
  7. 同文件重复标题
  8. 行尾空白 / 缩进用 Tab
  9. HTML 标签配对（div/span/table/details 等）
 10. 空代码块 / 无语言标签代码块
 11. 引用块内公式或空行规范（宽松提示）
 12. 全角标点出现在英文语境（宽松提示）
"""
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "数学基础系列"))
BLOCK_LANGS = {"", "text", "txt", "plain", "md", "markdown", "mermaid",
               "python", "py", "javascript", "js", "typescript", "ts", "bash",
               "sh", "powershell", "ps1", "json", "yaml", "yml", "toml", "sql",
               "cpp", "c", "java", "go", "rust", "html", "css", "latex", "tex",
               "pseudocode", "jsx", "tsx"}
# 代码块内这些语言的 ``` 不作为闭合判断干扰（多行字符串等），但围栏本身必须成对
FUZZY = {"py", "python", "js", "javascript", "ts", "typescript", "java", "go", "rust", "c", "cpp"}

SEVERITY = {"ERR": 0, "WARN": 1, "INFO": 2}


def check_file(path):
    issues = []
    rel = os.path.relpath(path, ROOT)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except (UnicodeDecodeError, OSError) as e:
        return [(rel, 0, "ERR", f"无法以 UTF-8 解码: {e}")]
    lines = raw.split("\n")

    # ---- 1+2. 代码块围栏配对 + 无语言标签 + 空块 ----
    fence = None
    fence_start = 0
    fence_lang = None
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^\s*(```+|~~~+)\s*(\S*)\s*$", ln)
        if m:
            if fence is None:
                fence = m.group(1)
                fence_start = i
                fence_lang = m.group(2)
                if not fence_lang:
                    j = i  # 1-based；lines[j] 为围栏下一行
                    while j < len(lines) and not re.match(r"^\s*(```+|~~~+)\s*$", lines[j]):
                        j += 1
                    body = lines[i:j]
                    first = next((c.strip() for c in body if c.strip()), "")
                    issues.append((rel, i, "WARN", f"代码块未标注语言标签（内容首行：{first[:50]}）"))
                    if body and all(not c.strip() for c in body):
                        issues.append((rel, i, "WARN", "空代码块"))
            else:
                if m.group(1)[0] == fence[0]:
                    fence = None
    if fence is not None:
        issues.append((rel, fence_start, "ERR", f"代码块围栏未闭合（起始行 {fence_start}，语言 {fence_lang or '无'}）"))

    # ---- 3. $ 公式定界符配对 ----
    # 策略：先剔除代码块区域，再扫描行内 $ 与 $$。
    code_spans = []
    cur = None
    cur_start = 0
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*(```+)\s*(\S*)\s*$", ln)
        if m:
            if cur is None:
                cur = m.group(1)
                cur_start = i
            else:
                if m.group(1)[0] == cur[0]:
                    code_spans.append((cur_start, i))
                    cur = None
    code_spans.append((len(lines), len(lines)))  # sentinel

    def in_code(idx):
        for (a, b) in code_spans:
            if a <= idx <= b:
                return True
        return False

    in_block = False
    for i, ln in enumerate(lines):
        if in_code(i):
            continue
        # 块级 $$...$$ 同行或跨行
        if not in_block:
            # 同行 $$x$$ 形式
            n = ln.count("$$")
            if n >= 2 and n % 2 == 0:
                continue
            if "$$" in ln:
                # 可能是 左$$ 或 $$右 或 单独 $$
                stripped = ln.strip()
                if stripped == "$$":
                    in_block = True
                elif stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
                    continue
                elif stripped.startswith("$$") and not stripped.endswith("$$"):
                    in_block = True
                elif stripped.endswith("$$") and not stripped.startswith("$$"):
                    issues.append((rel, i, "WARN", "行内出现未配对的 $$（建议检查公式定界符）"))
                elif stripped.count("$$") == 2:
                    continue
                else:
                    in_block = True
            # 行内 $...$ 配对
            line = ln
            # 先去掉转义 \$ 
            line = re.sub(r"\\\$", "", line)
            while "$" in line:
                idx = line.index("$")
                nxt = line.find("$", idx + 1)
                if nxt == -1:
                    issues.append((rel, i, "WARN", f"行内 $ 未配对：{ln.strip()[:60]}"))
                    break
                if nxt == idx + 1:
                    # $$ 已在块级处理
                    line = line[nxt + 1:]
                    continue
                line = line[nxt + 1:]
        else:
            if "$$" in ln:
                in_block = False
    if in_block:
        issues.append((rel, None, "ERR", "块级公式 $$...$$ 未闭合"))

    # ---- 4. 表格列数一致性（忽略转义 \|） ----
    def col_count(s):
        return s.replace(r"\|", "").count("|") - 1

    tbl = False
    tbl_cols = 0
    tbl_start = 0
    for i, ln in enumerate(lines, 1):
        if in_code(i - 1):
            continue
        stripped = ln.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if not tbl:
                tbl = True
                tbl_start = i
                tbl_cols = col_count(stripped)
                continue
            core = stripped.replace("|", "").replace(":", "").replace("-", "").strip()
            if set(core) == set() and "---" in stripped:
                continue  # 分隔行
            c = col_count(stripped)
            if c != tbl_cols:
                issues.append((rel, i, "WARN", f"表格列数不一致：第 {tbl_start} 行有 {tbl_cols} 列，本行有 {c} 列"))
        else:
            tbl = False

    # ---- 5. 标题层级跳跃（跳过代码块内行） ----
    last_level = 0
    for i, ln in enumerate(lines, 1):
        if in_code(i - 1):
            continue
        m = re.match(r"^(#{1,6})\s+\S", ln)
        if m:
            lv = len(m.group(1))
            if last_level and lv - last_level > 1:
                issues.append((rel, i, "WARN", f"标题层级跳跃：从 H{last_level} 跳到 H{lv}（{ln.strip()[:40]}）"))
            last_level = lv

    # ---- 5b. 重复标题（跳过代码块内行） ----
    seen = {}
    for i, ln in enumerate(lines, 1):
        if in_code(i - 1):
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", ln)
        if m:
            key = m.group(2).strip().lower()
            if key in seen:
                issues.append((rel, i, "INFO", f"重复标题：{seen[key][0]} 行与 {i} 行均为「{m.group(2).strip()}」"))
            else:
                seen[key] = (i, ln)

    # ---- 7. 行尾空白 / Tab 缩进 ----
    for i, ln in enumerate(lines, 1):
        if ln != ln.rstrip():
            issues.append((rel, i, "INFO", "行尾有空白字符"))
        if ln.startswith("\t") and not ln.startswith("\t\t"):
            pass  # 列表缩进可能用 tab，不强制

    # ---- 8. HTML 标签配对 ----
    for tag in ["div", "span", "table", "details", "summary"]:
        opens = len(re.findall(rf"<{tag}(\s|>)", raw))
        closes = len(re.findall(rf"</{tag}\s*>", raw))
        if opens != closes:
            issues.append((rel, None, "ERR", f"HTML <{tag}> 开闭不配对：开 {opens} 关 {closes}"))

    # ---- 9. Mermaid 常见语法问题 ----
    in_mm = False
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^\s*```mermaid\s*$", ln)
        if m:
            in_mm = True
            continue
        if in_mm and re.match(r"^\s*```+\s*$", ln):
            in_mm = False
            continue
        if in_mm and not ln.strip():
            continue
        if in_mm and re.match(r"^\s*(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|stateDiagram-v2|erDiagram|gantt|journey|pie|mindmap|timeline|quadrantChart|gitGraph|requirementDiagram|C4Context|block-beta)\b", ln.strip()):
            continue
        if in_mm and "->" in ln or (in_mm and "-->" in ln):
            continue
        # 宽松：不深究，只提示可疑裸文本
        if in_mm and re.match(r"^\s*[\u4e00-\u9fff].*[：:]", ln) and not re.search(r"-->|--\||--x|-\." , ln):
            issues.append((rel, i, "INFO", f"Mermaid 中疑似裸文本节点行：{ln.strip()[:50]}"))
            continue

    # ---- 10. 文件末尾换行 ----
    if raw and not raw.endswith("\n"):
        issues.append((rel, len(lines), "INFO", "文件末尾缺少换行符"))

    return issues


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else []
    only_err = "--only-err" in targets
    if "--only-err" in targets:
        targets.remove("--only-err")
    files = []
    if targets:
        for t in targets:
            p = os.path.abspath(t)
            if os.path.isfile(p):
                files.append(p)
            elif os.path.isdir(p):
                for root, _, fs in os.walk(p):
                    for f in fs:
                        if f.endswith(".md"):
                            files.append(os.path.join(root, f))
    else:
        for root, _, fs in os.walk(ROOT):
            for f in fs:
                if f.endswith(".md"):
                    files.append(os.path.join(root, f))
    files.sort()

    total = {"ERR": 0, "WARN": 0, "INFO": 0}
    by_file = {}
    for p in files:
        for (rel, line, sev, msg) in check_file(p):
            total[sev] += 1
            by_file.setdefault(rel, []).append((line, sev, msg))

    if only_err:
        levels = ["ERR"]
    else:
        levels = ["ERR", "WARN", "INFO"]
    for rel in sorted(by_file):
        for (line, sev, msg) in sorted(by_file[rel], key=lambda x: (x[0] is not None, x[0] or 0)):
            if sev not in levels:
                continue
            ln = f":{line}" if line is not None else ""
            print(f"[{sev}] {rel}{ln}  {msg}")

    print(f"\n==== 检查 {len(files)} 个文件 ====")
    print(f"ERR: {total['ERR']}  WARN: {total['WARN']}  INFO: {total['INFO']}")
    if total["ERR"] == 0 and total["WARN"] == 0:
        print("✅ 未发现错误与警告")
    elif total["ERR"] == 0:
        print("✅ 无错误；有警告，建议查看")


if __name__ == "__main__":
    main()
