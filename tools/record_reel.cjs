// record_reel.cjs — screen recordings of the studio for the showcase reel (Playwright + headless Chromium with software WebGL).
// One webm per scene under OUT/; the reel is cut from them by tools/build_reel.sh. No people's pages, no photos, no e-mail views
// are recorded: the dashboard, timeline, 3D bubbles, globe, money, graph and leads only.
//   URL=http://127.0.0.1:8670 OUT=~/efiles/cache/reel node tools/record_reel.cjs
const { chromium } = require(process.env.PW || (process.env.HOME + '/.hermes/hermes-agent/node_modules/playwright'));
const fs = require('fs'); const path = require('path');
const URL = process.env.URL || 'http://127.0.0.1:8670'; const OUT = process.env.OUT || 'reel'; fs.mkdirSync(OUT, { recursive: true });
const W = 1920, H = 1080;
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function scene(b, name, run) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: OUT, size: { width: W, height: H } }, deviceScaleFactor: 1 });
  const p = await ctx.newPage();
  p.on('pageerror', e => console.log(`  [${name}] page error: ${e.message.slice(0, 120)}`));
  try { await run(p); } catch (e) { console.log(`  [${name}] ${e.message.slice(0, 160)}`); }
  const v = p.video(); await ctx.close();
  const src = await v.path(); const dst = path.join(OUT, name + '.webm'); fs.renameSync(src, dst);
  console.log(`${name}: ${dst}`);
}
const tab = (p, t) => p.evaluate(t => document.querySelector(`#tabs button[data-t=${t}]`).click(), t);
const scrollTo = async (p, y, ms) => { const steps = Math.max(1, Math.round(ms / 40)); const y0 = await p.evaluate(() => window.scrollY); for (let i = 1; i <= steps; i++) { await p.evaluate(v => window.scrollTo(0, v), y0 + (y - y0) * i / steps); await sleep(40); } };
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl', '--no-sandbox'] });
  await scene(b, '01-dashboard', async p => { await p.goto(URL + '/'); await sleep(5000); await scrollTo(p, 700, 5000); await sleep(1500); await scrollTo(p, 1500, 5000); await sleep(1500); });
  await scene(b, '02-timeline', async p => { await p.goto(URL + '/'); await sleep(2500); await tab(p, 'timeline'); await sleep(1200); await p.evaluate(() => loadTimeline()); await sleep(6000); });
  await scene(b, '03-bubbles', async p => { await p.goto(URL + '/'); await sleep(2500); await p.evaluate(() => { document.querySelector('#c3').value = 'Jeffrey Epstein'; }); await tab(p, 'g3d'); await sleep(14000); });
  await scene(b, '04-globe', async p => { await p.goto(URL + '/#globe'); await sleep(3000); await tab(p, 'globe'); await sleep(16000); });
  await scene(b, '05-money', async p => { await p.goto(URL + '/'); await sleep(2500); await tab(p, 'money'); await sleep(4000); await scrollTo(p, 500, 4000); await sleep(1500); });
  await scene(b, '06-graph', async p => { await p.goto(URL + '/#graph:Ghislaine Maxwell'); await sleep(3000); await sleep(8000); });
  await scene(b, '07-leads', async p => { await p.goto(URL + '/'); await sleep(2500); await tab(p, 'leads'); await sleep(5000); await scrollTo(p, 400, 3000); await sleep(1000); });
  await b.close();
})();
