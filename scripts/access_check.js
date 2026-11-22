/**
 * ============================================================
 *  机构文献访问链路检测 / 下载（校园网 IP 授权版）
 * ============================================================
 *  链路：图书馆首页 -> 出版社/数据库 -> 机构出口 IP 授权 -> 下载
 *
 *  用法（NODE_PATH 指向含 playwright 的 node_modules）：
 *    node access_check.js                      # 全量检测（IEEE + CNKI）
 *    node access_check.js ieee                 # 只测 IEEE
 *    node access_check.js cnki "关键词1" ...  # 按关键词下知网 PDF
 *
 *  环境变量：
 *    CHROME_EXE   Chromium/Chrome 可执行文件绝对路径
 *    PW_PROFILE   持久化浏览器 profile 目录（保留登录态/过滑块）
 *    OUT_DIR      PDF 输出目录
 *    LIB_URL      图书馆入口 URL（默认华南理工 #page-2）
 *    ORG_NAME     机构名（用于 CNKI 授权识别，默认 华南理工大学）
 *    SHOW_WINDOW  设 1 时窗口正常显示；默认启动即最小化，不抢前台焦点
 *    IEEE_PROBE   IEEE 检测用的检索词
 *
 *  已验证结论（2026-10-24，华南理工大学校园网）：
 *    · 图书馆 #page-2 本身不产生 cookie，真正的授权靠校园网出口 IP，
 *      所以「先访问图书馆」只是导航，不是授权前提；直连出版社同样有效。
 *    · IEEE：headless 模式被 Cloudflare 拦（HTTP 418），必须 headless:false。
 *      PDF 直取 stampPDF/getPDF.jsp?tp=&arnumber=<id>&ref= ，
 *      需带 Referer: https://ieeexplore.ieee.org/document/<id>
 *      机构授权成功的标志是页面出现 "Access provided by ..." 横幅。
 *    · 知网：首页显示机构名即 IP 授权成功。
 *      检索结果页的「下载」给的是 .caj（文件头 KDH）；
 *      要 PDF 必须进详情页点 #pdfDown（#cajDown 是 CAJ）。
 *    · 知网连续检索会触发滑块验证，持久化 profile + 自动拖拽可缓解。
 *
 *  窗口策略：
 *    · 默认「启动即最小化」：--start-minimized 打底，启动后再用 CDP 把本脚本
 *      所属窗口压到任务栏；只作用于本窗口，不枚举/触碰其它 Chrome 窗口。
 *    · 设 SHOW_WINDOW=1 可恢复可见窗口，用于手动过滑块或确认机构授权横幅。
 *    · 代价：最小化后页面进入 hidden，Cloudflare / 知网可能更容易出验证；
 *      若下载成功率下降，临时用 SHOW_WINDOW=1 跑一次。
 *    · 自检：node access_check.js --selftest（只起窗口、不访问任何网站）
 *
 *  合规：仅限本人通过所在机构合法订阅、用于个人学习科研；
 *        不批量抓整刊整卷、不分发、不共享账号。
 * ============================================================
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const EXE = process.env.CHROME_EXE
  || 'C:\\Users\\xl\\AppData\\Local\\ms-playwright\\chromium-1194\\chrome-win\\chrome.exe';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const PROFILE = process.env.PW_PROFILE || path.join(process.cwd(), '.pw-profile');
const OUT_DIR = process.env.OUT_DIR || path.join(process.cwd(), 'papers');
const LIB_URL = process.env.LIB_URL || 'https://www.lib.scut.edu.cn/main.htm#page-2';
const ORG_NAME = process.env.ORG_NAME || '华南理工大学';
const IEEE_HOME = 'https://ieeexplore.ieee.org/Xplore/home.jsp';
const CNKI_HOME = 'https://www.cnki.net/';
const DEFAULT_KW = ['暂态电压稳定 Koopman'];

/* 默认启动即最小化，不抢前台焦点；SHOW_WINDOW=1 时恢复可见窗口 */
const SHOW_WINDOW = process.env.SHOW_WINDOW === '1';
const MINIMIZE_WINDOW = !SHOW_WINDOW;

const results = [];
const rec = (step, ok, detail) => {
  results.push({ step, ok, detail });
  console.log(`[${ok === true ? 'PASS' : ok === false ? 'FAIL' : 'INFO'}] ${step} :: ${detail}`);
};

/* ---------------- 浏览器：必须 headless:false，默认最小化 ---------------- */
async function launch() {
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    executablePath: EXE,
    headless: false,               // 关键：headless 会被 Cloudflare 418
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    userAgent: UA,
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-sandbox',
      ...(MINIMIZE_WINDOW ? ['--start-minimized'] : []),  // 窗口创建时就最小化，缩短前台闪现
    ],
  });
  await ctx.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
  });
  return ctx;
}

/**
 * CDP 兜底：把「这个 page 所属的窗口」压到最小化。
 * 用 getWindowForTarget 精确定位本脚本的窗口，绝不枚举或触碰主人其它 Chrome 窗口。
 * 失败时静默降级（--start-minimized 仍在），不影响下载主流程。
 */
async function minimizeWindow(page) {
  if (!MINIMIZE_WINDOW) return;
  let session;
  try {
    session = await page.context().newCDPSession(page);
    const { windowId } = await session.send('Browser.getWindowForTarget');
    await session.send('Browser.setWindowBounds', {
      windowId,
      bounds: { windowState: 'minimized' },
    });
  } catch (e) {
    console.log(`[WARN] 窗口最小化兜底失败（不影响下载）: ${String(e.message || e).split('\n')[0]}`);
  } finally {
    if (session) await session.detach().catch(() => {});
  }
}

/* ---------------- 滑块（知网） ---------------- */
async function hasCaptcha(page) {
  return page.evaluate(() => /请完成安全验证/.test(document.body.innerText)).catch(() => false);
}

async function solveSlider(page) {
  const sels = ['.verify-move-block', '.nc_iconfont.btn_slide', '.yidun_slider',
    '#nc_1_n1z', '.btn_slide', '.slider-btn'];
  for (const s of sels) {
    const el = await page.$(s).catch(() => null);
    if (!el) continue;
    const b = await el.boundingBox();
    if (!b || !b.width) continue;
    const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    for (let i = 1; i <= 14; i++) {
      await page.mouse.move(cx + i * 28, cy + Math.sin(i / 2) * 2, { steps: 2 });
      await page.waitForTimeout(45);
    }
    await page.mouse.up();
    await page.waitForTimeout(2500);
    if (!(await hasCaptcha(page))) return true;
  }
  return false;
}

/* ---------------- 1. 图书馆入口 ---------------- */
async function openLibrary(page) {
  const r = await page.goto(LIB_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => null);
  await page.waitForTimeout(1500);
  rec('图书馆首页', !!r && r.status() < 400, r ? `HTTP ${r.status()} | ${await page.title()}` : '无法访问');
}

/* ---------------- 2. IEEE ---------------- */
async function ieeeSearch(ctx, query, rows = 5) {
  const r = await ctx.request.post('https://ieeexplore.ieee.org/rest/search', {
    headers: { 'Content-Type': 'application/json', Referer: 'https://ieeexplore.ieee.org/search/searchresult.jsp' },
    data: { queryText: query, highlight: true, returnFacets: ['ALL'], returnType: 'SEARCH', matchPubs: true, rowsPerPage: String(rows) },
  }).catch(() => null);
  if (!r || r.status() !== 200) return null;
  return r.json();
}

async function ieeePdf(ctx, arnumber) {
  const pr = await ctx.request.get(
    `https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=${arnumber}&ref=`,
    { headers: { Referer: 'https://ieeexplore.ieee.org/document/' + arnumber }, timeout: 60000 }
  ).catch(() => null);
  if (!pr || !pr.ok()) return { ok: false, status: pr ? pr.status() : 'NA', buf: Buffer.alloc(0) };
  const buf = await pr.body();
  return { ok: buf.slice(0, 5).toString() === '%PDF-', status: pr.status(), buf };
}

async function checkIEEE(ctx, page, probeQuery) {
  const r = await page.goto(IEEE_HOME, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => null);
  await page.waitForTimeout(3500);
  const title = await page.title();
  rec('IEEE 打开', !/Unable to Load/i.test(title), `HTTP ${r ? r.status() : 'NA'} | ${title}`);
  if (/Unable to Load/i.test(title)) return;

  const banner = await page.evaluate(() => {
    const m = (document.body.innerText || '').match(/Access provided by[^\n]{0,80}/i);
    return m ? m[0] : null;
  }).catch(() => null);
  rec('IEEE 机构授权', !!banner, banner || '未检出授权横幅（确认在校园网内）');

  const j = await ieeeSearch(ctx, probeQuery);
  rec('IEEE 检索接口', !!j, j ? `${j.totalRecords} 条` : '接口不可用');
  if (!j) return;

  const hit = (j.records || [])[0];
  if (!hit) return;
  const { ok, status, buf } = await ieeePdf(ctx, hit.articleNumber);
  rec('IEEE PDF 下载', ok, `HTTP ${status} | ${buf.length} bytes | magic=${buf.slice(0, 5).toString() || 'empty'}`);
  if (ok) {
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const f = path.join(OUT_DIR, `_ieee_probe_${hit.articleNumber}.pdf`);
    fs.writeFileSync(f, buf);
    rec('IEEE 落盘', true, f);
  }
}

/* ---------------- 3. CNKI ---------------- */
async function cnkiOpen(page, kw) {
  await page.goto('https://kns.cnki.net/kns8s/defaultresult/index?kw=' + encodeURIComponent(kw),
    { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => null);
  await page.waitForTimeout(3500);

  if (await hasCaptcha(page)) {
    rec('CNKI 滑块', null, '触发，尝试自动拖拽');
    const ok = await solveSlider(page);
    rec('CNKI 滑块通过', ok, ok ? '已通过' : '未通过（需人工介入）');
    if (!ok) return false;
    await page.goto('https://kns.cnki.net/kns8s/defaultresult/index?kw=' + encodeURIComponent(kw),
      { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => null);
    await page.waitForTimeout(2500);
  }
  try {
    await page.waitForSelector('table.result-table-list tbody tr', { timeout: 20000 });
    await page.waitForTimeout(1000);
    return true;
  } catch (_) {
    return false;
  }
}

async function cnkiFirstDetail(page) {
  const row = await page.$('table.result-table-list tbody tr');
  if (!row) return null;
  return row.evaluate(r => {
    const a = r.querySelector('td.name a') || r.querySelector('a.fz14');
    return a ? { href: a.href, title: a.innerText.trim() } : null;
  });
}

/** 详情页 -> #pdfDown 才是真 PDF；结果页直给的「下载」是 CAJ */
async function cnkiPdfFromDetail(page, href) {
  await page.goto(href, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(3000);
  const btn = await page.$('#pdfDown') || await page.$('#cajDown');
  if (!btn) return { ok: false, msg: '详情页未找到 #pdfDown' };
  const isPdfBtn = await btn.evaluate(e => e.id === 'pdfDown');
  try {
    const dlp = page.waitForEvent('download', { timeout: 40000 });
    await btn.click({ timeout: 15000 });
    const dl = await dlp;
    const buf = fs.readFileSync(await dl.path());
    const magic = buf.slice(0, 5).toString();
    const name = (dl.suggestedFilename() || 'cnki_file').replace(/[\\/:*?"<>|]/g, '_');
    const isPdf = magic === '%PDF-';
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const dst = path.join(OUT_DIR, name);
    fs.writeFileSync(dst, buf);
    return { ok: isPdf, msg: `${buf.length} bytes | magic=${magic} | ${name}`, dst, kind: isPdfBtn ? 'PDF' : 'CAJ' };
  } catch (e) {
    return { ok: false, msg: e.message.split('\n')[0] };
  }
}

async function checkCNKI(ctx, page, kws) {
  const r = await page.goto(CNKI_HOME, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => null);
  await page.waitForTimeout(2500);
  rec('CNKI 打开', !!r && r.status() < 400, `HTTP ${r ? r.status() : 'NA'} | ${await page.title()}`);

  const org = await page.evaluate(n => (document.body.innerText.match(new RegExp(n)) || [null])[0], ORG_NAME).catch(() => null);
  rec('CNKI 机构标识', !!org, org || '未识别（确认在校园网内）');

  for (const kw of kws) {
    console.log(`\n-- 知网检索: ${kw}`);
    const loaded = await cnkiOpen(page, kw);
    rec('CNKI 检索', loaded, loaded ? '结果已加载' : '未加载（可能被验证码拦截）');
    if (!loaded) continue;
    const d = await cnkiFirstDetail(page);
    if (!d) { rec('CNKI 首条', false, '无结果'); continue; }
    rec('CNKI 首条', true, d.title.slice(0, 40) + ' | ' + d.href.slice(0, 60));
    const out = await cnkiPdfFromDetail(page, d.href);
    rec('CNKI 下载', out.ok, out.msg + (out.kind ? ` | 按钮=${out.kind}` : ''));
    if (out.dst) rec('CNKI 落盘', true, out.dst);
  }
}

/* ---------------- main ---------------- */
(async () => {
  const argv = process.argv.slice(2);

  // 自检：只起窗口、不访问任何网站，用来确认最小化是否真的生效
  if (argv.includes('--selftest')) {
    const c = await launch();
    const p = c.pages()[0] || await c.newPage();
    await minimizeWindow(p);
    let state = 'unknown';
    let s;
    try {
      s = await c.newCDPSession(p);
      const { windowId } = await s.send('Browser.getWindowForTarget');
      const { bounds } = await s.send('Browser.getWindowBounds', { windowId });
      state = bounds.windowState;
    } catch (e) {
      state = '查询失败: ' + String(e.message || e).split('\n')[0];
    } finally {
      if (s) await s.detach().catch(() => {});
    }
    console.log(`窗口状态: ${state} | 模式: ${MINIMIZE_WINDOW ? '默认最小化' : 'SHOW_WINDOW=1 正常显示'}`);
    await c.close();
    return;
  }

  const mode = (argv[0] && !argv[0].startsWith('--') ? argv[0] : 'all').toLowerCase();
  const kws = argv.slice(1).length ? argv.slice(1) : DEFAULT_KW;
  const probeQuery = process.env.IEEE_PROBE || 'transient voltage stability';

  const ctx = await launch();
  const page = ctx.pages()[0] || await ctx.newPage();
  page.setDefaultTimeout(45000);
  await minimizeWindow(page);                                   // 兜底压到任务栏
  ctx.on('page', p => { minimizeWindow(p).catch(() => {}); });  // 之后新开的窗口也不弹前台

  console.log('==== 机构访问链路检测 | 模式 ' + mode + ' | 输出 ' + OUT_DIR + ' ====\n');
  await openLibrary(page);
  if (mode === 'all' || mode === 'ieee') await checkIEEE(ctx, page, probeQuery);
  if (mode === 'all' || mode === 'cnki') await checkCNKI(ctx, page, kws);

  await ctx.close();
  const p = results.filter(r => r.ok === true).length;
  const f = results.filter(r => r.ok === false).length;
  console.log(`\n==== PASS ${p} / FAIL ${f} / 人工确认 ${results.filter(r => r.ok === null).length} ====`);
})().catch(e => { console.error('FATAL', e); process.exit(1); });
