#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAlex 多查询文献检索 -> 生成下载任务清单
============================================
用途：写综述时先按主题批量找文献，输出可直接喂给
      oa_fetch.py / download_by_doi.py 的 tasks.json。

用法：
  python search_openalex.py "transient voltage stability" "short-term voltage stability" \
      --out candidates.json --tasks tasks.json --limit 50 --email you@example.org

注意（实测结论）：
  · OpenAlex 的 search 与 sort 同时用时，sort 会让相关性失效，
    所以不排序，取回后本地按「是否综述 -> 引用量」排序。
  · 用 --filter 加标题关键词正则做相关性过滤（默认 voltage + stab/instab/collapse）。
  · 每查询间隔 0.35s，属 polite pool，别并发。
"""
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import pathlib

BASE = "https://api.openalex.org/works"


def get(url, email, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": f"paper-downloader/1.0 (mailto:{email})"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def abstract_of(w):
    inv = w.get("abstract_inverted_index")
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def slug(s, n=70):
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "_", s or "").strip("_")[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+", help="一个或多个检索词")
    ap.add_argument("--out", default="candidates.json", help="完整候选（含摘要/引用量）")
    ap.add_argument("--tasks", default="", help="可选：同时生成下载任务清单 tasks.json")
    ap.add_argument("--limit", type=int, default=50, help="每查询取回条数 (<=200)")
    ap.add_argument("--email", default="anonymous@example.org")
    ap.add_argument("--filter", default="", help="标题必须匹配的正则，如 'voltage.*stab'")
    ap.add_argument("--top", type=int, default=0, help="生成 tasks 时只取前 N 条 (0=全部)")
    args = ap.parse_args()

    store = {}
    for q in args.queries:
        params = {"search": q, "per-page": str(args.limit), "mailto": args.email}
        url = BASE + "?" + urllib.parse.urlencode(params)
        try:
            d = get(url, args.email)
        except Exception as e:
            print(f"[ERR] {q}: {e}")
            continue
        n = 0
        for w in d.get("results", []):
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            key = doi or w.get("id")
            if not key or key in store:
                continue
            title = (w.get("title") or "").strip()
            if not title:
                continue
            store[key] = {
                "doi": doi,
                "title": title,
                "year": w.get("publication_year"),
                "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                "cites": w.get("cited_by_count", 0),
                "type": w.get("type"),
                "abstract": abstract_of(w)[:1500],
                "query": q,
            }
            n += 1
        print(f"[{n:3d}] {q}")
        time.sleep(0.35)

    keep = list(store.values())
    if args.filter:
        rx = re.compile(args.filter, re.I)
        keep = [v for v in keep if rx.search(v["title"])]

    def rank(v):
        is_rev = 1 if re.search(r"review|survey|overview|综述", (v["title"] + v["abstract"]).lower()) else 0
        return (-is_rev, -(v["cites"] or 0))

    items = sorted(keep, key=rank)
    pathlib.Path(args.out).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n收集 {len(store)}，过滤后 {len(items)} -> {args.out}")

    if args.tasks:
        picked = items[: args.top] if args.top else items
        tasks = [{"doi": v["doi"], "name": f"{i:02d}_{slug(v['title'])}"}
                 for i, v in enumerate(picked, 1) if v["doi"]]
        pathlib.Path(args.tasks).write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"下载任务 {len(tasks)} 条 -> {args.tasks}")

    for v in items[:20]:
        rev = "R" if re.search(r"review|survey|overview", (v["title"] + v["abstract"]).lower()) else " "
        print(f"{rev} {v['cites']:5d} {v['year']} {v['title'][:76]}")


if __name__ == "__main__":
    main()
