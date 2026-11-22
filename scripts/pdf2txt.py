#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF -> txt 批量提取 + 篇幅统计（用于后续精读 / 写阅读报告）
用法：python pdf2txt.py ./papers [--out ./txt]
依赖：pymupdf（pip install pymupdf）
"""
import argparse
import re
import pathlib

try:
    import pymupdf
except ImportError:
    raise SystemExit("需要 pymupdf：pip install pymupdf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="PDF 所在目录")
    ap.add_argument("--out", default="", help="txt 输出目录（默认 <src>/../txt）")
    args = ap.parse_args()

    src = pathlib.Path(args.src)
    dst = pathlib.Path(args.out) if args.out else src.parent / "txt"
    dst.mkdir(parents=True, exist_ok=True)

    rows = []
    for f in sorted(src.glob("*.pdf")):
        try:
            doc = pymupdf.open(str(f))
            txt = "\n".join(p.get_text() for p in doc)
            txt = re.sub(r"[ \t]+", " ", txt)
            txt = re.sub(r"\n{3,}", "\n\n", txt)
            (dst / (f.stem + ".txt")).write_text(txt, encoding="utf-8")
            cn = len(re.findall(r"[\u4e00-\u9fff]", txt))
            rows.append((len(doc), len(txt), cn, f.stem))
        except Exception as e:
            rows.append((0, 0, 0, f.stem + "  [ERR] " + str(e)[:40]))

    for pages, n, cn, name in rows:
        print(f"{pages:3d}页 {n:7d}字符 {cn:6d}中文  {name[:70]}")
    print(f"\n共 {len(rows)} 篇 -> {dst}")


if __name__ == "__main__":
    main()
