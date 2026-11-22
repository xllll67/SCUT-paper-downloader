# 完整串联示例：一次 200 篇规模综述的文献获取

这是这套方法实际跑通的流程，可作为新任务的模板。任务：写「电力系统暂态电压稳定性」综述，先收集文献、每篇写阅读报告、再成文。

## 第 0 步：准备任务清单

两种来源：

**A. 已有 DOI 清单**（例如从参考文献表里抄出来的）
```json
[
  {"key":"V2","prefix":"02","doi":"10.1109/ACCESS.2025.3548609",
   "title":"Short-Term Voltage Stability Prediction ...","outDir":"D:/paper2/xxx/papers"},
  {"key":"V4","prefix":"04","doi":"10.3390/electronics15040840",
   "title":"Hierarchical Risk-Warning Method ...","outDir":"D:/paper2/xxx/papers"}
]
```
`ieee_batch.js` / `nav_download` 类脚本吃这个格式（含 `key` / `prefix` / `outDir`）。

**B. 什么都没有，按主题检索**
```bash
python scripts/search_openalex.py \
  "transient voltage stability" "short-term voltage stability" \
  "transient voltage stability assessment" "short-term voltage instability" \
  "voltage stability assessment power system" "dynamic voltage stability" \
  "voltage collapse transient" "transient voltage stability margin" \
  "voltage stability index" "voltage stability review power system" \
  "short-term voltage stability machine learning" "PMU measurement" \
  --out candidates.json --tasks tasks.json --limit 50 \
  --filter 'voltage.*(stab|instab|collapse)'
```
产出 `candidates.json`（含标题/年份/期刊/引用量/摘要/命中查询）与 `tasks.json`（`[{"doi":..., "name":"01_xxx"}, ...]`，可直接给两个下载器）。

> 多查询合并的价值：单一关键词容易漏掉「short-term voltage stability」这类同义表述，18 组查询合并去重后能从 200+ 条扩到 600+ 候选。取回后本地按「是否综述 → 引用量」排序，把综述和高被引顶到前面。

## 第 1 步：OA 兜底（先跑）

```bash
python scripts/oa_fetch.py tasks.json --out ./papers --email you@example.org
```
按 `arXiv → Unpaywall → OpenAlex best_oa_location` 找免费直链。MDPI、IEEE Access、arXiv 预印本通常在这一轮就拿到。看 `papers/manifest.json` 里 `status=no_oa` 的条目，生成 `tasks_rest.json` 进入下一轮。

## 第 2 步：按出版社分流

把 `tasks_rest.json` 按 DOI 前缀分组：

- `10.1109` → `ieee_batch.js`（机构 IP 授权，request 层直取，最快）
- `10.3390` / `10.1049` / `10.1155` → 也可先用 `nav_download` 式的下载事件路径（本 skill 的 `download_by_doi.py` 已内建 `dl_event` 回退）
- 其余 → `download_by_doi.py`

```bash
NODE_PATH=<node_modules> node scripts/ieee_batch.js ieee_tasks.json
python scripts/download_by_doi.py tasks_rest.json --out ./papers
```

实测一次批量：IEEE 25 篇全部 `ok`（arnumber 全部解析成功，单篇 0.3～17 MB）；非 IEEE 导航批次 MDPI 3 篇成功，Wiley / T&F / Springer 共 5 篇失败（多为图书章节类 DOI，无开放 PDF）。**失败是正常的，别为了凑数反复重试**，记进 manifest 即可。

## 第 3 步：补漏

对失败条目，`download_by_doi.py` 里已有 Elsevier 的 PII 匹配、IEEE 的 `rest/search` 反查、Wiley 双域名尝试。仍拿不到的，用 `access_check.js cnki "中文关键词"` 补中文文献，或转 `ablesci-downloader` 互助。

## 第 4 步：转文本供精读

```bash
python scripts/pdf2txt.py ./papers --out ./txt
```
输出每篇的页数 / 字符数 / 中文字符数。这一步能顺带发现坏 PDF（0 页、`[ERR]`）。

精读时可再按「开头 1600 字 + 章节骨架正则 + 结论段」抽摘要，避免把整篇 PDF 文本塞进上下文：

```python
heads = re.findall(r"(?m)^\s*((?:[IVX]+|\d{1,2})\.\s+[A-Z][A-Za-z \-]{3,60})$", txt)
m = list(re.finditer(r"(?i)\b(conclusions?|concluding remarks)\b", txt))
tail = txt[m[-1].start(): m[-1].start()+1100] if m else txt[-1100:]
```

## 第 5 步：证据分级

下载是否成功直接决定证据等级，写综述时要如实标注：

| 等级 | 含义 | 数量（本次实测） |
|---|---|---|
| 全文精读 | 拿到 PDF → 转 txt → 逐篇读 | 32 篇 |
| 摘要级 | 只有 OpenAlex/S2 摘要，无全文 | 168 篇 |
| 仅题录 | 只有标题/作者/年份，连摘要都没有 | 26 篇 |

附录里逐篇标注，不要把「摘要级」写成「全文精读」。这条比多下几篇 PDF 更影响综述可信度。

## 断点续传

所有脚本都检查目标文件是否存在且 > 2 KB，存在即 SKIP。所以：

- 中途断了直接重跑同一条命令；
- 新增文献只需往 `tasks.json` 里追加，不用改脚本；
- `manifest.json` / `*_result.json` 每轮覆盖，但 PDF 不会被覆盖。

## 常见组合

| 场景 | 命令链 |
|---|---|
| 只想下 3 篇，有 DOI | `oa_fetch.py` → 不够再 `download_by_doi.py` |
| 写综述要 100+ 篇 | `search_openalex.py` → `oa_fetch.py` → 分流 → `pdf2txt.py` |
| 中文文献 | `access_check.js cnki "关键词1" "关键词2"` |
| 学校没订阅 | `oa_fetch.py` → `ablesci-downloader`（另一个 skill） |
| 排查「为什么下不了」 | `access_check.js ieee` 看授权横幅与 HTTP 码 |
