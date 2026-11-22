# 机构 IP 授权链路（校园网 / 图书馆）

## 链路真相

用户最初的问题是「按学校图书馆网站跳转到出版社，这个链路是否清楚」。实测结论：

```
图书馆首页 (lib.scut.edu.cn/main.htm#page-2)
        │  只是导航链接，不产生授权 cookie
        ▼
出版社 / 数据库（IEEE Xplore、知网、ScienceDirect…）
        │  判断请求来源 IP 是否属于机构订阅范围
        ▼
机构出口 IP 授权 → 页面显示 "Access provided by ..." / 机构名
        ▼
PDF 可下载
```

**授权判定发生在出版社侧，依据是校园网出口 IP，不是图书馆跳转带来的会话。** 因此：

- 直连 `https://ieeexplore.ieee.org/Xplore/home.jsp` 与从图书馆点进去，效果一样；
- 出了校园网（在家、用手机热点）就失效，除非连学校 VPN；
- 不需要真的去点图书馆页面，脚本里 `openLibrary()` 只是保留链路完整性检查。

判断有没有授权，看两个信号：

| 平台 | 授权信号 |
|---|---|
| IEEE | 页面文本出现 `Access provided by <机构名>` 横幅；`POST /rest/search` 返回 200 |
| CNKI | 首页 `document.body.innerText` 含机构名（默认「华南理工大学」，用 `ORG_NAME` 改） |

## 三条技术分支

### 1. IEEE：headless 的 418 问题

- 用浏览器**打开页面**时，`headless: true` 会被 Cloudflare 判为机器人，返回 **HTTP 418** 或标题 `Unable to Load`。必须 `headless: false`（`launchPersistentContext`）。
- 但**只用 `ctx.request` 打接口**（`rest/search`、`stampPDF`）时不渲染页面，可以 headless。`ieee_batch.js` 走的就是这条路，因此速度最快、不抢前台。
- 交互检测脚本 `access_check.js` 必须 `headless:false`，会占用一个可见浏览器窗口。用户明确说过「别抢我前台」——所以批量任务优先用 `ieee_batch.js`，只在排查时跑 `access_check.js`。

配套的反自动化补丁（只对知网/滑块有意义，别当通用反检测）：

```js
await ctx.addInitScript(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
});
```

启动参数：`--disable-blink-features=AutomationControlled --no-sandbox`，`locale: zh-CN`，`timezoneId: Asia/Shanghai`。

### 2. CNKI 中文文献

- 检索入口：`https://kns.cnki.net/kns8s/defaultresult/index?kw=<urlencoded>`，结果表格选择器 `table.result-table-list tbody tr`，首条链接 `td.name a`（或 `a.fz14`）。
- **必须进详情页**：结果页的「下载」按钮给 `.caj`，文件头是 `KDH`；详情页 `#pdfDown` 才是真 PDF，`#cajDown` 是 CAJ。脚本里 `cnkiPdfFromDetail()` 优先找 `#pdfDown`，并回退到 `#cajDown` 后用魔数判断是否真 PDF。
- 下载用 `page.waitForEvent('download')` + `dl.path()` 读字节，再写盘（比 `saveAs` 可控）。
- 文件名要过滤 Windows 非法字符 `[\\/:*?"<>|]`。

### 3. 滑块验证

连续检索会触发「请完成安全验证」滑块。缓解办法：

- 用 `launchPersistentContext(PROFILE)` 持久化 profile，登录态和验证状态跨次保留；
- `solveSlider()` 按常见选择器列表（`.verify-move-block`、`.nc_iconfont.btn_slide`、`.yidun_slider`、`#nc_1_n1z`、`.btn_slide`、`.slider-btn`）找滑块，鼠标按下后分 14 步带轻微正弦抖动拖过去，模拟人手；
- 拖完检测验证码是否消失，消失即重跑检索；
- **过不了就别硬试**，脚本会记 `人工确认` 并跳过，避免反复触发风控。

用户当时的要求是「不要自己造轮子，看看 GitHub 上有没有开源的过人机验证方案」。最终结论：对这种滑块，用成熟的浏览器指纹方案（camoufox）比自写过验证逻辑更划算；这里的拖拽只是低频中文库场景的轻量兜底，不是通用验证码破解器。

## 实测结果（2026-10-24，华南理工大学校园网）

| 检查项 | 结果 |
|---|---|
| 图书馆首页 | PASS（HTTP 200） |
| IEEE 打开 + 机构授权横幅 | PASS |
| IEEE `rest/search` 检索接口 | PASS |
| IEEE PDF 直取（stampPDF + Referer） | PASS，`%PDF-` |
| CNKI 打开 + 机构标识 | PASS（显示「华南理工大学」） |
| CNKI 检索 / 首条 / 详情页下载 | 结果页给 CAJ，详情页 `#pdfDown` 给 PDF |
| 连续检索滑块 | 会触发，持久化 profile + 自动拖拽可缓解 |

## 环境变量

| 变量 | 用途 | 默认值 |
|---|---|---|
| `CHROME_EXE` | Chromium 可执行文件 | `C:\Users\xl\AppData\Local\ms-playwright\chromium-1194\chrome-win\chrome.exe` |
| `PW_PROFILE` | 持久化 profile 目录 | `<cwd>/.pw-profile` |
| `OUT_DIR` | PDF 输出目录 | `<cwd>/papers` |
| `LIB_URL` | 图书馆入口 | `https://www.lib.scut.edu.cn/main.htm#page-2` |
| `ORG_NAME` | 机构名（CNKI 识别用） | `华南理工大学` |
| `IEEE_PROBE` | IEEE 探测用检索词 | `transient voltage stability` |

换学校只需改 `LIB_URL` 和 `ORG_NAME`，出版社侧的取法不用动。

## 合规

仅限本人通过所在机构合法订阅、用于个人学习科研；不批量抓整刊整卷、不绕过付费墙分发、不共享账号与 Cookie。脚本不读取或存储密码、验证码；滑块由本地浏览器自动完成，过不了就留给人工。
