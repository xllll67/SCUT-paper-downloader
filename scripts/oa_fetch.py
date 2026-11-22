#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OA 优先兜底下载器（纯 urllib，零第三方依赖）
=============================================
顺序：arXiv -> Unpaywall -> OpenAlex best_oa_location。
适合在机构链路拿不到时先试免费渠道，或作为批量任务的第一轮。

用法：
  python oa_fetch.py tasks.json --out ./papers [--email you@example.org]

tasks.json: [{"doi":"...", "name":"01_Title", "arxiv_url":"https://arxiv.org/abs/2401.01234"}, ...]
输出：<out>/manifest.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import pathlib

# API 查询用 polite-pool UA（带 mailto），PDF 下载用浏览器 UA，两者不要混用
API_UA = {"User-Agent": "paper-downloader/1.0 (mailto:anonymous@example.org)"}
DL_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get_json(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers=API_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"_error": str(e)}


def arxiv_pdf(task):
    u = task.get("arxiv_url") or task.get("url") or ""
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(v\d+)?", u)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    if task.get("arxiv_id"):
        return f"https://arxiv.org/pdf/{task['arxiv_id']}"
    return None


def unpaywall_pdf(doi, email):
    d = get_json(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={email}")
    if "_error" in d:
        return None
    best = d.get("best_oa_location") or {}
    if best.get("url_for_pdf"):
        return best["url_for_pdf"]
    for loc in d.get("oa_locations", []) or []:
        if loc.get("url_for_pdf"):
            return loc["url_for_pdf"]
    return None


def openalex_pdf(doi):
    d = get_json(f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}")
    if "_error" in d:
        return None
    best = d.get("best_oa_location") or {}
    if best.get("pdf_url"):
        return best["pdf_url"]
    for loc in d.get("locations", []) or []:
        if loc.get("pdf_url"):
            return loc["pdf_url"]
    return None


def download(url, path, timeout=60):
    try:
        req = urllib.request.Request(url, headers=DL_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if data[:5] != b"%PDF-":
            return False, len(data), "not-pdf (改用 download_by_doi.py)"
        path.write_bytes(data)
        return True, len(data), "ok"
    except Exception as e:
        msg = str(e)[:60]
        if "403" in msg or "Forbidden" in msg:
            msg += " | 站点拦纯 HTTP，转 download_by_doi.py (camoufox)"
        return False, 0, msg


def slug(s, n=70):
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "_", s or "").strip("_")[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks")
    ap.add_argument("--out", default="./papers")
    ap.add_argument("--email", default="anonymous@example.org")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    global API_UA
    API_UA = {"User-Agent": f"paper-downloader/1.0 (mailto:{args.email})"}

    tasks = json.loads(pathlib.Path(args.tasks).read_text(encoding="utf-8"))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []

    for i, t in enumerate(tasks, 1):
        doi = (t.get("doi") or "").strip()
        name = slug(t.get("name") or doi or f"paper_{i}")
        fp = out / f"{name}.pdf"
        if fp.exists() and fp.stat().st_size > 2000:
            manifest.append({"doi": doi, "status": "cached", "file": str(fp)})
            print(f"[{i}] cached {name[:50]}")
            continue

        url, via = arxiv_pdf(t), "arxiv"
        if not url and doi:
            url, via = unpaywall_pdf(doi, args.email), "unpaywall"
        if not url and doi:
            url, via = openalex_pdf(doi), "openalex"

        if not url:
            manifest.append({"doi": doi, "status": "no_oa", "file": ""})
            print(f"[{i}] NO-OA  {name[:50]}")
            continue

        ok, n, msg = download(url, fp)
        if not ok and fp.exists():
            fp.unlink()
        manifest.append({"doi": doi, "status": "downloaded" if ok else "failed",
                         "file": str(fp) if ok else "", "via": via, "url": url, "note": msg, "bytes": n})
        print(f"[{i}] {'downloaded' if ok else 'failed':10s} via={via:9s} {n//1024}KB  {name[:50]}")
        time.sleep(args.delay)

    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for m in manifest if m["status"] in ("downloaded", "cached"))
    print(f"\nDONE: {ok}/{len(tasks)} PDF 可用 -> {out / 'manifest.json'}")


if __name__ == "__main__":
    main()
