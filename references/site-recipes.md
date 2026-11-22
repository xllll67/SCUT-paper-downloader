# 各出版社 PDF 取法与失败排查

## 核心原理：导航 + 响应监听

大多数出版社的 PDF 不是静态文件，而是**先过一层 JS 挑战 / 会话校验，再由浏览器发起第二次请求**去 CDN 拉真身。直接 `ctx.request.get(pdfUrl)` 或 `urllib.urlopen` 只能拿到挑战页 HTML 或 403。

解决办法是把浏览器当客户端用：

```python
def capture_nav(ctx, page, url, wait_ms=9000):
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
        page.goto(url, timeout=180000)
    except Exception:
        pass
    for _ in range(int(wait_ms / 1500)):
        if box.get("b"):
            break
        page.wait_for_timeout(1500)
    page.remove_listener("response", on_resp)
    return box.get("b")
```

要点：
- 监听条件不能只写 `.pdf`——ScienceDirect 的真实响应来自 `pdf.sciencedirectassets.com`（URL 里没有 `.pdf`），IEEE 的是 `stampPDF`，ASME 是 `article-pdf`。
- `page.goto` 常常超时或抛异常（PDF 响应会中断导航），所以**必须 try/except 包住**，之后靠轮询等 `box["b"]`。
- 一律验魔数 `%PDF-`。挑战页也是 200，光看状态码会误判成功。
- 别忘了 `remove_listener`，否则下一个任务会叠加监听器。

另一条备用路径是 `page.expect_download()`，对 MDPI / Wiley 这类触发浏览器下载事件的站更有效。脚本里 `dl_event()` 与 `capture_nav()` 是「或」的关系。

## Elsevier / ScienceDirect（最麻烦）

```
1. page.goto("https://www.sciencedirect.com/")   # 首页热身，建立会话与 cookie
2. wait_page(page, rounds=5)                    # 等 Cloudflare "Just a moment" 过去
3. page.goto("https://doi.org/" + doi)          # 跳到文章页
4. 循环 14 次，每次等 3s，用 JS 找 PDF 按钮链接：
   location.pathname.match(/pii\/([A-Z0-9]+)/) 取当前页 PII
   a[href*="/pdf?md5="] 或 a[href*="/pdfft?md5="]
   优先选 href 里含当前 PII 的那个
5. capture_nav(ctx, page, 该链接)
```

**坑**：新版界面有 `/pdfft?md5=` 与老版 `/pdf?md5=` 两种形态，正则要都认；页面右侧「相关推荐」也会出现 `/pdf?md5=` 链接，不按 PII 匹配就会下到别的文章。

## IEEE Xplore

DOI `10.1109/*` 跳转后 URL 形如 `https://ieeexplore.ieee.org/document/8384030`，取 `8384030` 即 arnumber。

```
https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=<arnumber>&ref=
Referer: https://ieeexplore.ieee.org/document/<arnumber>
```

- 在机构 IP 授权下，`ctx.request.get` 就能直接拿到 PDF（`ieee_batch.js` 走这条路，最快，可 headless）。
- 不在授权网络内时，需要浏览器先访问一次 Xplore 建立会话，且 **headless 会被 Cloudflare 返回 418**，必须 `headless:false`。
- DOI 偶尔不跳转或跳到别处，此时用检索接口反查：

```json
POST https://ieeexplore.ieee.org/rest/search
Content-Type: application/json
Referer: https://ieeexplore.ieee.org/search/searchresult.jsp

{"queryText":"<标题或DOI>","returnType":"SEARCH","rowsPerPage":"3","highlight":true}
```
返回 `records[0].articleNumber`。

## 其它站点

| 站点 | 备注 |
|---|---|
| Wiley / IET | `10.1049`（IET 期刊）常跳到 `ietresearch.onlinelibrary.wiley.com`，`onlinelibrary.wiley.com` 与子域都试一遍更稳 |
| T&F | `/doi/pdf/<doi>?download=true`，有时要 `?needAccess=true` |
| IOP | `/article/<doi>/pdf`，OA 居多，OA 阶段常就能拿到 |
| Springer | `/content/pdf/<doi>.pdf`；图书章节类 DOI（`10.1007/978-..._N`）成功率低，实测多失败 |
| MDPI | 全 OA，`文章URL + /pdf`，成功率高；优先放 OA 兜底轮 |
| Hindawi | 页面内正则找 `.pdf` 链接 |
| ASME | 文章页抓 `/article-pdf/` 路径，相对路径补 `https://asmedigitalcollection.asme.org` |
| SSRN | 跳转 URL 里取 `abstract_id=(\d+)` 拼 `Delivery.cfm` |
| IEICE / J-STAGE | 页面内找 `_article` 或 `.pdf` 链接 |

## 失败模式对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 拿到 HTML 而非 PDF | JS 挑战未过 / 无授权 | 首页热身 + 加长等待；确认在机构网内 |
| HTTP 418 | Cloudflare 拦 headless | 改 `--no-headless`；或用 `request` 层接口（IEEE） |
| 下到别的文章 | Elsevier 未按 PII 匹配 | 用脚本里的 PII 过滤逻辑 |
| `未识别站点` | DOI 跳到未适配的出版社 | 看 `cur` URL，把该站规律加进 `get_one()` |
| arnumber 为空 | DOI 未跳转 | `POST /rest/search` 反查 |
| 文件很小 (< 20 KB) | 多半是错误页 | 已按 `%PDF-` 拦掉；重跑前删掉坏文件 |
| 知网拿到 `KDH` 头 | 点了 `#cajDown` 或结果页下载 | 进详情页点 `#pdfDown` |

## 排查顺序

1. 先看 `manifest.json` 的 `note` 字段，脚本已把失败原因分类写进去了。
2. 魔数不对 → 挑战/授权问题，不是代码问题。
3. 同一站点连续失败 → 换 `--no-headless` 手动看一次页面标题（是不是 `Just a moment` / `Unable to Load`）。
4. 单篇失败 → 用浏览器手工打开 `https://doi.org/<doi>`，看真实落地 URL，再把规律补进路由表。
5. 全部失败 → 检查网络出口（是否在校园网/VPN 内）、代理设置（Clash 系统代理可能让 pip/浏览器走错路）。

## 关于反爬工具的选择

早期试过自己做人机验证绕过，结论是不要造轮子：直接用 `camoufox`（带真实 Firefox 指纹的 Playwright 发行版，`humanize=True` 模拟人类鼠标）比自写 UA/指纹稳定得多。本 skill 的 `access_check.js` 里保留的 `navigator.webdriver = undefined` 只用于知网滑块场景，属于轻量补丁，不是通用反检测方案。
