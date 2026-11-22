---
name: paper-downloader
version: 1.0.0
tags: [literature, paper-download, doi, pdf, ieee, cnki, elsevier, openalex, camoufox, 文献下载, 论文下载, 校园网, 机构授权]
description: "按 DOI / 标题批量下载学术论文 PDF 的实战工具箱：先走 OpenAlex/Unpaywall/arXiv 的 OA 免费兜底，有机构（校园网出口 IP）订阅时用 IEEE stampPDF、CNKI 详情页 #pdfDown 与各出版社直取，全部失败再用 camoufox「导航 + 响应监听」绕过 JS 挑战。适用：用户说「下载文献 / 下 PDF / 找全文 / 按 DOI 批量下载 / 学校图书馆能不能下 / 写综述要收集文献」，或需要把 PDF 批量转 txt 做精读。内置检索脚本可直接生成下载任务清单。"
agent_created: true
---

# 文献批量下载工具箱 (paper-downloader)

把「找文献 → 判断能不能下 → 下载 → 校验 → 转 txt」串成一条链。这套方法来自一次 200 篇规模综述的实际下载，各站点取法都在真机上跑通过，不是理论推导。

## 何时使用

用户要下载论文/PDF、按 DOI 批量下、问「学校图书馆跳转出版社能不能下」、写综述要收集文献、或要把 PDF 批量转文本精读。

## 决策树（先判断，再动手）

```
有文献清单(DOI/标题)?
├─ 没有 → scripts/search_openalex.py 生成 candidates.json + tasks.json
└─ 有   ↓
第一轮 OA 兜底（免费、零依赖、最快）
  scripts/oa_fetch.py tasks.json --out ./papers
  → arXiv → Unpaywall → OpenAlex best_oa_location
  ↓ 剩下的 no_oa / failed 条目
是否在机构网络内（校园网 / VPN / 已登录图书馆）?
├─ 是 → IEEE 走 ieee_batch.js（request 层直取 stampPDF，最快）
│        其它站走 download_by_doi.py（camoufox 导航+响应监听）
│        CNKI 中文文献走 access_check.js cnki
└─ 否 → 只保留 OA 结果，或改用已装的 ablesci-downloader 互助
最后：scripts/pdf2txt.py ./papers  转文本供精读
```

**先跑 OA 再跑机构链路**，别反过来：OA 是纯 HTTP，几秒出结果，且不需要浏览器；机构链路要开浏览器、慢得多。

OA 阶段出现 `403 Forbidden` 是**正常且预期**的（MDPI、Elsevier 等用 Cloudflare 拦纯 HTTP 请求），说明接口已经拿到了正确直链，只是下载的最后一跳需要浏览器。把 `manifest.json` 里 `status=failed` / `no_oa` 的条目挑出来交给 `download_by_doi.py` 即可，不要重试 OA 脚本。

## 已验证的关键结论（这些是整套方法的价值所在）

1. **机构授权靠出口 IP，不靠图书馆 cookie。** 图书馆 `#page-2` 只是导航页，本身不产生任何授权态。直连出版社页面效果相同。所以检测链路时先看 IEEE 是否出现 `Access provided by ...`、知网首页是否显示机构名，而不是看有没有走过图书馆。
2. **IEEE：headless 会被 Cloudflare 拦（HTTP 418）**，浏览器交互必须 `headless:false`；但只用 `ctx.request` 打 `stampPDF` 接口时可以 headless（不渲染页面）。
   PDF 直取地址 `https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=<id>&ref=`，**必须带 `Referer: https://ieeexplore.ieee.org/document/<id>`**。
   arnumber 可从 `https://doi.org/<doi>` 跳转后的 URL `/document/(\d+)` 取，或用 `POST /rest/search` 按标题/DOI 反查 `records[0].articleNumber`。
3. **知网：检索结果页「下载」给的是 CAJ（文件头 `KDH`）**。要 PDF 必须进详情页点 `#pdfDown`（`#cajDown` 是 CAJ）。连续检索触发滑块验证，用持久化 profile + 自动拖拽缓解。
4. **ScienceDirect 的 PDF 走 JS 挑战**，`ctx.request` 拿到的只会是 403/HTML；必须用 `page.goto(pdfUrl)` + `page.on('response')` 监听并截取 `%PDF-` 响应体。这个「导航 + 响应监听」是通用兜底，对 Wiley / IOP / T&F / ASME 同样有效。
5. **每个文件都要验魔数** `buf[:5] == b'%PDF-'`。下载器返回 200 但给 HTML 是常态，不能只看状态码和长度。
6. **OpenAlex 的 `search` 与 `sort` 同时用会让相关性失效**，脚本里不排序，取回后本地按「是否综述 → 引用量」重排。
7. 每条之间留 2～3 秒随机间隔，别并发；出版社对批量请求敏感。

## 各站点取法速查

| 站点 | DOI 前缀 / 特征 | PDF 取法 |
|---|---|---|
| IEEE | `10.1109` | `stampPDF/getPDF.jsp?tp=&arnumber=<id>&ref=` + Referer |
| Elsevier | `10.1016` | 首页热身 → 文章页 `a[href*="/pdf?md5="]`（按 PII 匹配）→ 导航截响应 |
| Wiley / IET | `10.1002`, `10.1049` | `/doi/pdfdirect/<doi>?download=true` |
| T&F | `10.1080` | `/doi/pdf/<doi>?download=true` |
| IOP | `10.1088` | `/article/<doi>/pdf` |
| Springer | `10.1007` | `/content/pdf/<doi>.pdf` |
| MDPI | `10.3390` | 文章 URL + `/pdf` |
| Hindawi | `10.1155` | 页面内正则找 `.pdf` |
| ASME | — | 文章页 `/article-pdf/` 链接 |
| SSRN | `10.2139` | `Delivery.cfm/<id>.pdf?abstractid=<id>&mirid=1` |
| arXiv | — | `https://arxiv.org/pdf/<id>` |
| CNKI | — | 详情页 `#pdfDown`（非结果页下载按钮） |

## 命令速查

```bash
S=<技能目录>/scripts
PY=C:/Users/xl/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe

# 1) 检索（可选）：主题词 → 候选 + 下载任务
$PY $S/search_openalex.py "transient voltage stability" "short-term voltage stability" \
    --out candidates.json --tasks tasks.json --limit 50

# 2) OA 兜底（先跑）
$PY $S/oa_fetch.py tasks.json --out ./papers

# 3) 通用多站下载（camoufox，OA 没拿到的）
$PY $S/download_by_doi.py tasks_rest.json --out ./papers

# 4) IEEE 批量（机构 IP 授权，Node）
NODE_PATH="$(npm root -g)" node $S/ieee_batch.js ieee_tasks.json

# 5) 机构链路检测 / 知网中文（有界面，Node）
NODE_PATH="$(npm root -g)" node $S/access_check.js ieee
NODE_PATH="$(npm root -g)" node $S/access_check.js cnki "暂态电压稳定" "电压崩溃"

# 6) 批量转 txt
$PY $S/pdf2txt.py ./papers --out ./txt
```

环境变量（仅 JS 脚本）：`CHROME_EXE`、`PW_PROFILE`、`OUT_DIR`、`LIB_URL`、`ORG_NAME`、`IEEE_PROBE`。

## 依赖

- Python：`pip install -r scripts/requirements.txt`（`camoufox[geoip]`、`pymupdf`）。本机若被代理拦，见 requirements.txt 里的清华源写法。
- Node：`npm install playwright`，脚本复用本机 Chromium（`CHROME_EXE` 指定路径，默认 `C:\Users\xl\AppData\Local\ms-playwright\chromium-1194\chrome-win\chrome.exe`）。首次用 camoufox 需 `python -m camoufox fetch`。
- 本机 Python 解释器：`C:\Users\xl\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe`。

### 本机安装状态（2026-11-08，已实测）

- 系统 `python` 与上面这个 `$PY` 两套解释器均已装 `pymupdf`、`camoufox[geoip]`，`fpgen` 指纹模型已就位（不需要联网）。
- Camoufox 浏览器已装 `v156.0.1-beta.36`（约 2.4 GB，位于 `%LOCALAPPDATA%\camoufox\camoufox\Cache`），并已用 `python -m camoufox set 156.0.1-beta.36-096fd483` 固定到该版本，绕过 0.5.9 包默认配对的 158 版本。两套 Python 实测均可 `headless` 启动。
- **不要重跑 `python -m camoufox fetch`**：本机到 GitHub 不通（代理 502 / 直连超时），重跑只会报错；现有浏览器可直接用。
- Node `playwright` 已全局安装，用 `NODE_PATH="$(npm root -g)"` 指向即可；Chromium 复用本机 `ms-playwright\chromium-1194`。
- GeoIP mmdb 数据库未安装（数据源也在 GitHub），但本套脚本没有启用 `geoip`，不影响使用；只有显式传 `geoip=True` 时才需要另想办法补。

## 输出与校验

- 每个脚本都写 `manifest.json` / `*_result.json`，字段含 `status` (`ok`/`exists`/`fail`/`no_oa`)、`bytes`、`file`、`note`。
- 任务清单里的 `name` 会做 slug 化处理（非字母数字汉字转 `_`，截 70～80 字符），避免 Windows 路径非法字符。
- 已存在且 > 2 KB 的文件自动 SKIP，可安全重跑做断点续传。

## 合规边界

仅限本人通过所在机构合法订阅、或开放获取渠道，用于个人学习与科研；不批量抓整刊整卷、不绕过付费墙做再分发、不共享账号与 Cookie。脚本不读取或存储密码、验证码。

## 详细资料（按需加载，勿主动读入上下文）

- `references/site-recipes.md` — 各出版社取法细节、失败模式与排查顺序、camoufox 原理。
- `references/institution-access.md` — 机构 IP 授权链路、Cloudflare/滑块处理、CNKI 细节、实测结果。
- `references/workflow-example.md` — 一次 200 篇综述从检索到精读的完整串联示例与任务清单格式。
