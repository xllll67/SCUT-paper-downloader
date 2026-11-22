# paper-downloader

按 DOI / 标题**批量下载学术论文 PDF** 的实战工具箱，也是一个可直接加载的 [WorkBuddy](https://www.workbuddy.cn/) Skill。

它把「找文献 → 判断能不能下 → 下载 → 校验 → 转文本」串成一条链。方法来自一次 200 篇规模综述的实际下载，各站点取法都在真机上跑通，不是理论推导。

## 功能特性

- **OA 免费兜底**：先用 OpenAlex / Unpaywall / arXiv 拿开放获取全文，纯 HTTP、几秒出结果。
- **机构订阅直取**：在校园网 / VPN / 已登录图书馆的环境下，支持 IEEE、CNKI 及各出版社的 PDF 直取。
- **通用浏览器兜底**：对 JS 挑战站点（ScienceDirect / Wiley / IOP / T&F / ASME 等）用「导航 + 响应监听」截取 PDF。
- **严格校验**：每个文件验 PDF 魔数 `%PDF-`，避免把 HTML 错误页当 PDF 存下来。
- **批量转文本**：下载完可一键转 txt，方便精读。
- **断点续传**：已存在且大于 2 KB 的文件自动跳过，可安全重跑。
- **内置检索**：给主题词即可生成候选清单与下载任务清单。

## 工作流程

```
有文献清单(DOI/标题)?
├─ 没有 → search_openalex.py 生成 candidates.json + tasks.json
└─ 有   ↓
第一轮 OA 兜底（免费、零依赖、最快）
  oa_fetch.py tasks.json --out ./papers
  → arXiv → Unpaywall → OpenAlex best_oa_location
  ↓ 剩下的 no_oa / failed 条目
是否在机构网络内（校园网 / VPN / 已登录图书馆）?
├─ 是 → IEEE 走 ieee_batch.js（request 层直取 stampPDF，最快）
│        其它站走 download_by_doi.py（浏览器导航 + 响应监听）
│        CNKI 中文文献走 access_check.js cnki
└─ 否 → 只保留 OA 结果
最后：pdf2txt.py ./papers  转文本供精读
```

> **先跑 OA 再跑机构链路**，别反过来。OA 阶段出现 `403 Forbidden` 是正常且预期的（MDPI、Elsevier 等用 Cloudflare 拦纯 HTTP 请求），说明接口已经拿到正确直链，只是最后一跳需要浏览器。把 `manifest.json` 里 `status=failed` / `no_oa` 的条目交给浏览器链路即可，不要重试 OA 脚本。

## 安装

### 1. 放置技能

把本仓库下载 / 克隆为技能目录下的 `paper-downloader` 文件夹：

```bash
# 克隆方式（推荐，方便后续 git pull 更新）
cd <你的工作目录>/.workbuddy/skills
git clone https://github.com/xllll67/SCUT-paper-downloader.git paper-downloader

# 或：下载 ZIP 后解压，把文件夹改名为 paper-downloader，放进 skills 目录
```

WorkBuddy 用户目录通常是 `~/.workbuddy/skills/`（Windows 为 `C:\Users\<用户名>\.workbuddy\skills\`）。重启 WorkBuddy 后即可加载该技能。

### 2. 安装依赖

Python 侧（建议 Python 3.10+）：

```bash
pip install -r scripts/requirements.txt
# 若 pip 被代理拦，可清空代理并换清华源：
#   HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= \
#   pip install -r requirements.txt --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

首次使用 camoufox 需要拉取浏览器：

```bash
python -m camoufox fetch
```

Node 侧（仅 `access_check.js` / `ieee_batch.js` 需要）：

```bash
npm install -g playwright
# 脚本复用本机 Chromium，可用环境变量 CHROME_EXE 指定路径
```

## 使用

以下命令中 `S` 指技能目录下的 `scripts` 文件夹。

```bash
S=<技能目录>/scripts

# 1) 检索（可选）：主题词 → 候选 + 下载任务
python $S/search_openalex.py "transient voltage stability" "short-term voltage stability" \
    --out candidates.json --tasks tasks.json --limit 50

# 2) OA 兜底（先跑）
python $S/oa_fetch.py tasks.json --out ./papers

# 3) 通用多站下载（浏览器兜底，OA 没拿到的）
python $S/download_by_doi.py tasks_rest.json --out ./papers

# 4) IEEE 批量（机构 IP 授权，Node）
NODE_PATH="$(npm root -g)" node $S/ieee_batch.js ieee_tasks.json

# 5) 机构链路检测 / 知网中文（有界面，Node）
NODE_PATH="$(npm root -g)" node $S/access_check.js ieee
NODE_PATH="$(npm root -g)" node $S/access_check.js cnki "暂态电压稳定" "电压崩溃"

# 6) 批量转 txt
python $S/pdf2txt.py ./papers --out ./txt
```

JS 脚本支持的环境变量：`CHROME_EXE`、`PW_PROFILE`、`OUT_DIR`、`LIB_URL`、`ORG_NAME`、`IEEE_PROBE`。

### 各站点取法速查

| 站点 | DOI 前缀 / 特征 | PDF 取法 |
|---|---|---|
| IEEE | `10.1109` | `stampPDF/getPDF.jsp?tp=&arnumber=<id>&ref=` + Referer |
| Elsevier | `10.1016` | 首页热身 → 文章页 `/pdf?md5=` → 导航截响应 |
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

## 输出与校验

- 每个脚本都写 `manifest.json` / `*_result.json`，字段含 `status`（`ok` / `exists` / `fail` / `no_oa`）、`bytes`、`file`、`note`。
- 任务清单里的 `name` 会做 slug 化处理（非字母数字汉字转 `_`，截 70～80 字符），避免 Windows 路径非法字符。
- 已存在且大于 2 KB 的文件自动跳过。

## 合规声明

仅限本人通过所在机构**合法订阅**、或**开放获取**渠道，用于个人学习与科研。不批量抓整刊整卷、不绕过付费墙做再分发、不共享账号与 Cookie。脚本不读取或存储密码、验证码。

## 目录结构

```
paper-downloader/
├── SKILL.md                       # WorkBuddy 技能定义与完整决策树
├── README.md                      # 本说明
├── references/
│   ├── site-recipes.md            # 各出版社取法细节、失败模式与排查顺序
│   ├── institution-access.md      # 机构 IP 授权链路、Cloudflare/滑块处理、CNKI 细节
│   └── workflow-example.md        # 一次 200 篇综述的完整串联示例与任务清单格式
└── scripts/
    ├── search_openalex.py         # 主题词检索 → 任务清单
    ├── oa_fetch.py                # OA 兜底下载
    ├── download_by_doi.py         # 通用浏览器下载（camoufox）
    ├── ieee_batch.js              # IEEE stampPDF 批量直取
    ├── access_check.js            # 机构链路检测 / 知网下载
    ├── pdf2txt.py                 # 批量 PDF 转文本
    └── requirements.txt           # Python 依赖
```
