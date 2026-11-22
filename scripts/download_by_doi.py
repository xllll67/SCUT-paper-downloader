#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用 DOI 批量 PDF 下载器（camoufox, headless）
================================================
核心思路：导航到 PDF URL -> 监听 page.on('response') 截取 %PDF- 响应体。
  ScienceDirect 的 PDF 走 /craft/challenge/pdf 的 JS 挑战，
  ctx.request 拿不到（403/HTML），但 page.on('response') 能截到真身。
  对 Wiley / IOP / T&F / ASME / Springer / MDPI / IEEE 等同样适用。

各站已实测的取法：
  Elsevier : 首页热身 -> 文章页 -> a[href*="/pdf?md5="] -> 导航 -> 截响应
  Wiley    : /doi/pdfdirect/<doi>?download=true
  T&F      : /doi/pdf/<doi>?download=true
  IOP      : /article/<doi>/pdf
  ASME     : 文章页 /article-pdf/ 链接
  Springer : /content/pdf/<doi>.pdf
  MDPI     : 文章页 + /pdf
  IEEE     : stampPDF/getPDF.jsp?tp=&arnumber=<id>&ref=
  Hindawi  : 页面内正则找 .pdf 链接
  SSRN     : Delivery.cfm/<id>.pdf?abstractid=<id>&mirid=1
  IEICE    : 页面内 _article / .pdf 链接

用法：
  python download_by_doi.py tasks.json --out ./papers [--headless] [--humanize]
  python download_by_doi.py tasks.json --out ./papers --no-headless   # 有界面模式（Cloudflare 重的站）

tasks.json 格式（每条必须有 doi，name 可选用于文件名）：
  [
    {"doi": "10.1109/tpwrs.2018.2846744", "name": "01_Paper_Title"},
    {"doi": "10.1016/j.epsr.2024.111035", "name": "05_Choi_STVS"}
  ]
"""
import argparse
import json
import re
import sys
import time
import pathlib

try:
    from camoufox.sync_api import Camoufox
except ImportError:
    print("需要 camoufox：pip install camoufox[geoip]", file=sys.stderr)
    sys.exit(1)


def slug(s: str, n: int = 80) -> str:
    """把标题转成安全的文件名片段"""
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", s or "").strip("_")
    return s[:n]


def capture_nav(ctx, page, url, wait_ms=9000, timeout=180000):
    """导航到 url，同时监听所有 PDF 响应，返回字节"""
    box = {}

    def on_resp(r):
        u = r.url.lower()
        if ".pdf" in u or "pdf.sciencedirectassets" in u or "article-pdf" in u or "stamp" in u:
            try:
                b = r.body()
                if b[:5] == b"%PDF-":
                    box["b"] = b
            except Exception:
                pass

    page.on("response", on_resp)
    try:
        page.goto(url, timeout=timeout)
    except Exception:
        pass
    for _ in range(int(wait_ms / 1500)):
        if box.get("b"):
            break
        page.wait_for_timeout(1500)
    page.remove_listener("response", on_resp)
    return box.get("b")


def wait_page(page, need=None, rounds=18):
    """等待页面加载完成，跳过 Cloudflare 挑战页"""
    for _ in range(rounds):
        page.wait_for_timeout(3000)
        try:
            t, h = page.title(), page.content()
        except Exception:
            continue
        if "Just a moment" in t or "Are you a robot" in t or t.startswith("Loading") or not t.strip():
            continue
        if need and need not in h:
            continue
        return t, h
    try:
        return page.title(), page.content()
    except Exception:
        return "", ""


def dl_event(page, url, timeout=120000):
    """用 page.expect_download 触发下载事件"""
    try:
        with page.expect_download(timeout=timeout) as d:
            try:
                page.goto(url, timeout=timeout)
            except Exception:
                pass
        p = d.value
        tmp = p.path()
        return pathlib.Path(tmp).read_bytes()
    except Exception:
        return None


def get_one(browser, doi: str):
    """根据 DOI 前缀路由到不同站点的 PDF 提取策略，返回 (bytes, how)"""
    pre = doi.split("/")[0]
    ctx = browser.new_context(accept_downloads=True)
    page = ctx.new_page()
    try:
        # ---------- Elsevier (10.1016) ----------
        if pre == "10.1016":
            page.goto("https://www.sciencedirect.com/", wait_until="domcontentloaded", timeout=120000)
            wait_page(page, None, 5)
            page.goto("https://doi.org/" + doi, wait_until="domcontentloaded", timeout=120000)
            u = None
            for _ in range(14):
                page.wait_for_timeout(3000)
                u = page.evaluate("""() => {
                    const m = location.pathname.match(/pii\\/([A-Z0-9]+)/);
                    const pii = m ? m[1] : null;
                    const as = [...document.querySelectorAll('a')]
                        .filter(a => /\\/(pdf|pdfft)\\?md5=/.test(a.href));
                    const hit = (pii && as.find(a => a.href.includes(pii))) || as[0];
                    return hit ? hit.href : null;}""")
                if u:
                    break
            if not u:
                return None, "Elsevier 未找到 PDF 按钮链接"
            buf = capture_nav(ctx, page, u)
            return (buf, "elsevier-capture") if buf else (None, "elsevier 无 PDF 响应")

        # ---------- 其他站点：先解析 DOI 跳转 ----------
        page.goto("https://doi.org/" + doi, wait_until="domcontentloaded", timeout=120000)
        t, h = wait_page(page, None, 12)
        cur = page.url
        low = cur.lower()

        if "wiley.com" in low:
            u = "https://onlinelibrary.wiley.com/doi/pdfdirect/" + doi + "?download=true"
            buf = capture_nav(ctx, page, u)
            if not buf:
                buf = dl_event(page, u)
            return (buf, "wiley") if buf else (None, "wiley 无 PDF")

        if "tandfonline.com" in low:
            u = "https://www.tandfonline.com/doi/pdf/" + doi + "?download=true"
            buf = capture_nav(ctx, page, u)
            if not buf:
                buf = dl_event(page, u)
            return (buf, "tandf") if buf else (None, "tandf 无 PDF")

        if "iopscience" in low:
            u = "https://iopscience.iop.org/article/" + doi + "/pdf"
            return capture_nav(ctx, page, u), "iop"

        if "springer.com" in low:
            u = "https://link.springer.com/content/pdf/" + doi + ".pdf"
            return capture_nav(ctx, page, u), "springer"

        if "mdpi.com" in low:
            u = cur.rstrip("/") + "/pdf"
            buf = capture_nav(ctx, page, u)
            if not buf:
                buf = dl_event(page, u)
            return (buf, "mdpi") if buf else (None, "mdpi 无 PDF")

        if "ieeexplore" in low:
            m = re.search(r"/document/(\d+)", cur) or re.search(r"arnumber=(\d+)", cur)
            if not m:
                # 尝试用检索接口按 DOI 反查
                try:
                    r = ctx.request.post("https://ieeexplore.ieee.org/rest/search", data={
                        "queryText": doi, "returnType": "SEARCH", "rowsPerPage": "3",
                    }, headers={"Content-Type": "application/json",
                                "Referer": "https://ieeexplore.ieee.org/search/searchresult.jsp"})
                    j = r.json()
                    if j.get("records"):
                        an = j["records"][0]["articleNumber"]
                        u = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={an}&ref="
                        return capture_nav(ctx, page, u), "ieee-search"
                except Exception:
                    pass
                return None, f"IEEE 无 arnumber ({t[:30]})"
            u = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={m.group(1)}&ref="
            return capture_nav(ctx, page, u), "ieee"

        if "hindawi" in low:
            c = re.findall(r"https?://[^\"'\s<>]+\.pdf", h)
            if c:
                return capture_nav(ctx, page, c[0]), "hindawi"
            return None, "Hindawi 无 .pdf 链接"

        if "asme" in low:
            c = re.findall(r"[^\"'\s<>]*/article-pdf/[^\"'\s<>]+", h)
            if c:
                u = c[0] if c[0].startswith("http") else "https://asmedigitalcollection.asme.org" + c[0]
                return capture_nav(ctx, page, u), "asme"
            return None, "ASME 无链接"

        if "ssrn" in low:
            m = re.search(r"abstract_id=(\d+)", cur)
            if m:
                u = f"https://papers.ssrn.com/sol3/Delivery.cfm/{m.group(1)}.pdf?abstractid={m.group(1)}&mirid=1"
                return capture_nav(ctx, page, u), "ssrn"
            return None, "SSRN 无 abstract_id"

        if "jstage" in low or "ieice" in low:
            c = re.findall(r"[^\"'\s<>]*_article[^\"'\s<>]*", h) + re.findall(r"https?://[^\"'\s<>]+\.pdf", h)
            if c:
                return capture_nav(ctx, page, c[0]), "ieice"
            return None, "IEICE 无链接"

        # 通用兜底：正则找页面里的 .pdf 链接
        c = re.findall(r"https?://[^\"'\s<>]+\.pdf(?:\?[^\"'\s<>]*)?", h)
        if c:
            return capture_nav(ctx, page, c[0]), "generic"
        return None, f"未识别站点 ({cur[:60]})"
    except Exception as e:
        return None, "异常 " + str(e)[:80]
    finally:
        ctx.close()


def main():
    ap = argparse.ArgumentParser(description="通用 DOI 批量 PDF 下载器")
    ap.add_argument("tasks", help="JSON 任务文件路径")
    ap.add_argument("--out", default="./papers", help="PDF 输出目录 (默认 ./papers)")
    ap.add_argument("--headless", action="store_true", default=True, help="无头模式 (默认开)")
    ap.add_argument("--no-headless", dest="headless", action="store_false", help="有界面模式 (Cloudflare 重的站)")
    ap.add_argument("--humanize", action="store_true", default=True, help="模拟人类鼠标行为 (默认开)")
    ap.add_argument("--delay", type=float, default=2.0, help="两条之间的间隔秒数")
    args = ap.parse_args()

    tasks = json.loads(pathlib.Path(args.tasks).read_text(encoding="utf-8"))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    results = []
    ok_count = 0
    with Camoufox(headless=args.headless, humanize=args.humanize, os="windows") as browser:
        for i, t in enumerate(tasks, 1):
            doi = t["doi"]
            name = t.get("name") or slug(doi)
            fname = f"{slug(name)}.pdf"
            fp = out / fname

            if fp.exists() and fp.stat().st_size > 2000:
                results.append({"doi": doi, "name": name, "status": "exists", "file": str(fp), "bytes": fp.stat().st_size})
                print(f"[{i}/{len(tasks)}] SKIP {name[:52]} (已存在)")
                continue

            buf, how = get_one(browser, doi)
            if buf and buf[:5] == b"%PDF-":
                fp.write_bytes(buf)
                results.append({"doi": doi, "name": name, "status": "ok", "file": str(fp), "bytes": len(buf), "how": how})
                ok_count += 1
                print(f"[{i}/{len(tasks)}] OK   {name[:52]} | {len(buf)//1024}KB | {how}")
            else:
                results.append({"doi": doi, "name": name, "status": "fail", "note": how})
                print(f"[{i}/{len(tasks)}] FAIL {name[:52]} | {how}")

            time.sleep(args.delay)

    manifest = out / "manifest.json"
    manifest.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n成功 {ok_count}/{len(tasks)} -> {manifest}")


if __name__ == "__main__":
    main()
