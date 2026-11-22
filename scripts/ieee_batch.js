/**
 * IEEE Xplore 批量下载（依赖校园网 IP 机构授权，走 request 层，最快）
 * =================================================================
 * 与 camoufox 版的区别：本脚本不导航到 PDF 页，直接用 ctx.request.get
 * 取 stampPDF，前提是浏览器已处于机构授权 IP 网络内。
 * 若返回非 %PDF-（通常是 403/HTML），改用 download_by_doi.py 或 access_check.js。
 *
 * 用法：
 *   NODE_PATH=<含playwright的node_modules> node ieee_batch.js tasks.json [--out-dir DIR]
 *
 * tasks.json:
 *   [{"key":"L21","prefix":"21","doi":"10.1109/tpwrs.2018.2846744",
 *     "title":"A Robust Data-Driven Koopman Kalman Filter","outDir":"D:/papers"}, ...]
 *
 * 环境变量：CHROME_EXE（默认本机 playwright chromium）
 * 输出：<cwd>/ieee_batch_result.json（每轮覆盖，含 status/arnumber/bytes/file/note）
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const EXE = process.env.CHROME_EXE
  || 'C:\\Users\\xl\\AppData\\Local\\ms-playwright\\chromium-1194\\chrome-win\\chrome.exe';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const sleep = ms => new Promise(r => setTimeout(r, ms));
const slug = t => (t || 'untitled').replace(/[^\w\u4e00-\u9fa5]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 70);

async function main() {
  const tasksFile = process.argv[2];
  if (!tasksFile) { console.error('用法: node ieee_batch.js tasks.json'); process.exit(1); }
  const tasks = JSON.parse(fs.readFileSync(tasksFile, 'utf8'));

  const browser = await chromium.launch({ headless: true, executablePath: EXE });
  const ctx = await browser.newContext({ userAgent: UA, viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
  const page = await ctx.newPage();

  const results = [];
  let ok = 0, fail = 0;

  for (let i = 0; i < tasks.length; i++) {
    const t = tasks[i];
    const rec = { key: t.key, doi: t.doi, title: t.title, status: '', arnumber: '', bytes: 0, file: '', note: '' };
    const fn = `${t.prefix}_${slug(t.title)}.pdf`;
    const fp = path.join(t.outDir, fn);

    if (fs.existsSync(fp) && fs.statSync(fp).size > 20000) {
      rec.status = 'exists'; rec.file = fp; rec.bytes = fs.statSync(fp).size;
      results.push(rec); console.log(`[${i + 1}/${tasks.length}] SKIP ${t.key} (已存在)`);
      continue;
    }

    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        // DOI 跳转到 document 页，取出 arnumber
        await page.goto('https://doi.org/' + t.doi, { waitUntil: 'domcontentloaded', timeout: 60000 });
        await sleep(1500);
        const url = page.url();
        rec.url = url;
        const m = url.match(/\/document\/(\d+)/);
        if (!m) throw new Error('非 IEEE 文档页: ' + url.slice(0, 90));
        rec.arnumber = m[1];

        // 关键：stampPDF + Referer 指向 document 页
        const pdfUrl = `https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=${m[1]}&ref=`;
        const r = await ctx.request.get(pdfUrl, { timeout: 120000, headers: { Referer: url } });
        const buf = await r.body();
        if (buf.slice(0, 5).toString() !== '%PDF-') throw new Error('非 PDF (HTTP ' + r.status() + ')');

        fs.mkdirSync(t.outDir, { recursive: true });
        fs.writeFileSync(fp, buf);
        rec.status = 'ok'; rec.bytes = buf.length; rec.file = fp;
        break;
      } catch (e) {
        rec.status = 'fail'; rec.note = e.message.slice(0, 140);
        if (attempt === 1) await sleep(4000);
      }
    }

    if (rec.status === 'ok') ok++; else fail++;
    results.push(rec);
    console.log(`[${i + 1}/${tasks.length}] ${rec.status.toUpperCase()} ${t.key} ar=${rec.arnumber} ${(rec.bytes / 1024).toFixed(0)}KB ${rec.note || ''}`);
    fs.writeFileSync('ieee_batch_result.json', JSON.stringify(results, null, 1));
    await sleep(3000 + Math.random() * 2500);
  }

  console.log(`\nDONE ok=${ok} fail=${fail} total=${tasks.length}`);
  await browser.close();
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
