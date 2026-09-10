"""启动页的 CSS / JS / 文案字面量——与 frontend/index.html 逐字同构的那一份。

为什么单独成文件：这些不是 Python 逻辑，而是**被脚本机器读写的设计资产**。
`scripts/sync_boot_splash_index.py` 把它们灌进 `frontend/index.html`；
`scripts/sync_boot_splash_from_index.py` 反向按正则整块替换本文件的 `_CSS`。
和渲染逻辑同住一个文件时两种改动互相踩：改 Python 要在 500 行字面量里翻页，
而正则回灌又会把整块 CSS 换掉。分开后本文件只随前端样式变。

`_CSS` 必须保持「赋值后紧跟三引号换行、独立三引号收尾」的写法——回灌脚本的正则
认的是这个形状，换成别的写法会匹配不到而静默什么都不做。
"""

from __future__ import annotations

BOOT_SPLASH_REV = "2026-08-ths-fullpage-v4"

_TIPS_JSON = (
    '["晨光落印，账本启封","本地服务正在苏醒","行情纸面缓缓铺开",'
    '"复盘笔墨次第就位","候选与持仓对齐中","开市铃将在片刻后响起"]'
)

_EXIT_TIP = "账本封存，明日再见"
_ERROR_TIP = "开账未成，请查看日志"

_CSS = """
html,body{margin:0;height:100%;background:#e7ebf0;color:#0e1a29;
font-family:"Microsoft YaHei UI","PingFang SC","Noto Sans SC","Segoe UI",system-ui,sans-serif}
#boot-splash,.loci-boot-root{position:fixed;inset:0;z-index:9999;overflow:hidden;
background:#e7ebf0;transition:opacity .32s ease}
#boot-splash.is-hide,.loci-boot-root.is-hide{opacity:0;pointer-events:none}
.loci-boot-map{position:absolute;inset:0;width:100%;height:100%;display:block}
.loci-boot-brand{position:absolute;top:10vh;left:0;right:0;display:flex;
flex-direction:column;align-items:center;gap:10px;pointer-events:none;z-index:2}
/* 印记方章是 logo：这是 --stamp #c41e3a 唯一允许出现的地方之一（品牌色已换 --seal） */
.loci-boot-mark{position:relative;width:56px;height:56px;border-radius:3px;
background:#c41e3a;color:#fff;display:grid;place-items:center;
font-family:Consolas,"Cascadia Mono",monospace;font-weight:700;font-size:20px;
letter-spacing:.08em;outline:1px solid rgba(255,255,255,.28);outline-offset:-6px}
.loci-boot-name{font-family:Consolas,"Cascadia Mono",monospace;
font-size:20px;font-weight:700;letter-spacing:.14em;color:#0e1a29;line-height:1}
.loci-boot-copy{position:absolute;left:50%;top:calc(var(--loci-zero-pct,58%) + 8%);
transform:translateX(-50%);max-width:360px;text-align:center;padding:0 24px;
pointer-events:none;z-index:2}
.loci-boot-kicker{font-family:Consolas,"Cascadia Mono",monospace;font-size:11px;
letter-spacing:.14em;color:#6b7a8b;margin-bottom:4px}
.loci-boot-tip{font-size:13px;font-weight:600;
color:#3c4b5c;letter-spacing:.03em;line-height:1.35}
.loci-tip-blink{animation:loci-tip-blink 1.6s ease-in-out infinite}
@keyframes loci-tip-blink{0%,100%{opacity:1}50%{opacity:.28}}

/* 收市 / 中断：无分时，居中落章 */
.phase-exit,.phase-error{background:
  radial-gradient(ellipse 50% 36% at 50% 42%,rgba(14,76,102,.05),transparent 70%),#e7ebf0}
.phase-exit .loci-boot-map,.phase-error .loci-boot-map{display:none}
.phase-exit .loci-boot-brand,.phase-error .loci-boot-brand{top:auto;position:static}
.phase-exit .loci-boot-copy,.phase-error .loci-boot-copy{
  position:static;left:auto;top:auto;transform:none;margin-top:4px}
.loci-boot-close{position:absolute;inset:0;display:flex;flex-direction:column;
align-items:center;justify-content:center;gap:16px;padding:24px;z-index:2;
animation:loci-close-rise .45s ease-out both}
.loci-boot-close-rail{width:min(11rem,42vw);height:1px;border:0;
background:linear-gradient(90deg,transparent,#0e4c66 18%,#0e4c66 82%,transparent);
transform-origin:center;animation:loci-close-rail .65s cubic-bezier(.22,1,.36,1) .12s both}
.phase-error .loci-boot-mark{background:#6b7a8b}
.phase-error .loci-boot-close-rail{
background:linear-gradient(90deg,transparent,#b6c0cd 18%,#b6c0cd 82%,transparent)}
.phase-exit .loci-tip-blink,.phase-error .loci-tip-blink{animation:none;opacity:1}
@keyframes loci-close-rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes loci-close-rail{from{transform:scaleX(.12);opacity:0}to{transform:scaleX(1);opacity:1}}
@media (prefers-reduced-motion:reduce){
.loci-tip-blink,.loci-boot-close,.loci-boot-close-rail{animation:none!important;opacity:1;transform:none}
}
""".strip()

_JS = r"""
(function () {
  var REV = "__REV__";
  var VW = 960, VH = 640;
  var ACCENT = "#c41e3a", BLUE = "#4A86E8", GREEN = "#1a9f4b";
  var PAPER = "#eef2f6", RAIL = "#c5ced9", MUTE = "#5b6b7c";
  var TIPS = __TIPS__;
  var PHASE = "__PHASE__";

  function buildSeries() {
    var volH = 88, tipBand = 12;
    var chartBottom = VH - volH - tipBand;
    var plotLift = Math.round((chartBottom - 120) * 0.25);
    var zeroY = chartBottom - 2 - plotLift;
    var padT = 120, plotH = chartBottom - padT, n = 72;
    var main = [], bench = [], volumes = [], volUp = [];
    for (var i = 0; i < n; i++) {
      var t = i / (n - 1);
      var x = t * VW;
      var jag = Math.sin(i * 1.85) * 14 + Math.sin(i * 0.4) * 8;
      var lift = t < 0.38 ? t * 0.08 : 0.03 + Math.pow((t - 0.38) / 0.62, 1.35) * 0.62;
      var yMain = zeroY - plotH * lift - jag * (0.15 + t * 0.45);
      var yBench = zeroY - (Math.sin(i * 1.4) * 3 + Math.sin(i * 0.6) * 2);
      main.push([x, Math.min(zeroY - 2, Math.max(padT + 8, yMain))]);
      bench.push([x, Math.min(zeroY, Math.max(zeroY - 10, yBench))]);
      var vBase = 0.18 + t * 0.58 + (Math.sin(i * 2.3) * 0.5 + 0.5) * 0.32;
      volumes.push(Math.max(0.1, Math.min(1, vBase)));
      if (i === 0) volUp.push(true);
      else volUp.push(main[i][1] <= main[i - 1][1]);
    }
    return {
      main: main, bench: bench, volumes: volumes, volUp: volUp,
      zeroY: zeroY, padT: padT, chartBottom: chartBottom, volH: volH,
      tipBand: tipBand, n: n, plotH: plotH
    };
  }

  function toD(pts) {
    var out = "";
    for (var i = 0; i < pts.length; i++) {
      out += (i === 0 ? "M" : "L") + pts[i][0].toFixed(1) + "," + pts[i][1].toFixed(1);
    }
    return out;
  }

  function render(svg, series, pct) {
    var n = series.n;
    var lit = Math.max(3, Math.round((pct / 100) * (n - 1)));
    var mainLit = series.main.slice(0, lit + 1);
    var benchLit = series.bench.slice(0, lit + 1);
    var last = mainLit[mainLit.length - 1];
    var gridYs = [0.12, 0.28, 0.44, 0.6, 0.76, 0.92];
    var accent = ACCENT;
    var parts = [];
    parts.push('<rect width="' + VW + '" height="' + VH + '" fill="' + PAPER + '"/>');
    for (var g = 0; g < gridYs.length; g++) {
      var gy = series.padT + series.plotH * gridYs[g];
      parts.push('<line x1="0" x2="' + VW + '" y1="' + gy + '" y2="' + gy +
        '" stroke="' + RAIL + '" stroke-width="1.2" stroke-dasharray="6 5" opacity="0.4"/>');
    }
    for (var v = 0; v < 12; v++) {
      var vx = ((v + 1) / 13) * VW;
      parts.push('<line y1="' + series.padT + '" y2="' + series.chartBottom +
        '" x1="' + vx + '" x2="' + vx +
        '" stroke="' + RAIL + '" stroke-width="1" stroke-dasharray="2 7" opacity="0.2"/>');
    }
    parts.push('<line x1="0" x2="' + VW + '" y1="' + series.zeroY + '" y2="' + series.zeroY +
      '" stroke="' + RAIL + '" stroke-width="1.4" opacity="0.65"/>');
    parts.push('<text x="' + (VW - 10) + '" y="' + (series.zeroY - 6) +
      '" text-anchor="end" fill="' + MUTE +
      '" font-family="Consolas, monospace" font-size="11" opacity="0.8">0%</text>');
    for (var i = 0; i < series.volumes.length; i++) {
      var t = i / (n - 1);
      var x = t * VW;
      var bw = VW / n - 1.5;
      var bh = series.volumes[i] * (series.volH - 8);
      var on = i <= lit;
      var dim = series.volUp[i] ? accent : GREEN;
      parts.push('<rect x="' + x + '" y="' + (VH - series.tipBand - bh) +
        '" width="' + Math.max(2, bw) + '" height="' + bh +
        '" fill="' + dim + '" opacity="' + (on ? 0.55 : 0.16) + '"/>');
    }
    parts.push('<path d="' + toD(series.bench) + '" fill="none" stroke="' + BLUE +
      '" stroke-width="1.6" opacity="0.14"/>');
    parts.push('<path d="' + toD(series.main) + '" fill="none" stroke="' + accent +
      '" stroke-width="1.8" opacity="0.1"/>');
    parts.push('<path d="' + toD(benchLit) + '" fill="none" stroke="' + BLUE +
      '" stroke-width="2" stroke-linejoin="miter"/>');
    parts.push('<path d="' + toD(mainLit) + '" fill="none" stroke="' + accent +
      '" stroke-width="2.4" stroke-linejoin="miter"/>');
    if (last) {
      var tagW = 54, tagH = 26;
      var tagX = last[0] + 10, tagY = last[1] - tagH / 2;
      if (tagX + tagW > VW - 12) tagX = last[0] - tagW - 10;
      if (tagY < series.padT + 4) tagY = last[1] + 12;
      var rounded = Math.round(pct);
      var label = (rounded < 10 ? "0" + rounded : String(rounded)) + "%";
      parts.push('<line x1="' + last[0] + '" x2="' + last[0] + '" y1="' + series.padT +
        '" y2="' + series.zeroY + '" stroke="' + accent +
        '" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.35"/>');
      parts.push('<circle cx="' + last[0] + '" cy="' + last[1] + '" r="4" fill="' + accent + '"/>');
      parts.push('<rect x="' + tagX + '" y="' + tagY + '" width="' + tagW + '" height="' + tagH +
        '" rx="2" fill="' + accent + '"/>');
      parts.push('<text x="' + (tagX + tagW / 2) + '" y="' + (tagY + 17) +
        '" text-anchor="middle" fill="#fff" font-family="Consolas, monospace" font-size="13" font-weight="700">' +
        label + "</text>");
    }
    svg.innerHTML = parts.join("");
  }

  function bootQuiet(root) {
    root.setAttribute("data-loci-boot", REV);
    window.__lociBootSplash = {
      rev: REV,
      setMessage: function (text) {
        var msgEl = root.querySelector(".loci-boot-msg");
        if (msgEl) msgEl.textContent = text;
      },
      complete: function (done) {
        root.classList.add("is-hide");
        setTimeout(function () {
          if (typeof done === "function") done();
        }, 320);
      }
    };
  }

  function bootEnter(root) {
    root.setAttribute("data-loci-boot", REV);
    var svg = root.querySelector(".loci-boot-map");
    var tipEl = root.querySelector(".loci-boot-tip");
    if (!svg) return;
    var series = buildSeries();
    root.style.setProperty("--loci-zero-pct", ((series.zeroY / VH) * 100).toFixed(2) + "%");

    // 开账：从 0 缓爬；complete 时约 1s 从当前位拉到 100%，再淡出（不回撤）
    var FINISH_MS = 1000;
    var IDLE_CEILING = 88;
    var pct = 0;
    var finishing = false;
    var finishFrom = 0;
    var finishStart = 0;
    var finishDone = null;
    var raf = 0;
    var lastTs = 0;
    var tipIdx = Math.floor(Math.random() * TIPS.length);
    var tipTimer = null;
    var preferReduced = false;
    try {
      preferReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {}

    function setTip(i) {
      tipIdx = i;
      if (tipEl) tipEl.textContent = TIPS[tipIdx % TIPS.length];
    }
    function paint() { render(svg, series, pct); }
    function fadeOut(done) {
      root.classList.add("is-hide");
      setTimeout(function () {
        if (typeof done === "function") done();
      }, 320);
    }
    function stopTips() {
      if (tipTimer) { clearInterval(tipTimer); tipTimer = null; }
    }
    function idleRate(p) {
      if (p < 25) return 0.042;
      if (p < 55) return 0.02;
      return 0.007;
    }
    function frame(ts) {
      if (!lastTs) lastTs = ts;
      var dt = Math.min(48, ts - lastTs);
      lastTs = ts;
      if (finishing) {
        var t = Math.min(1, (ts - finishStart) / FINISH_MS);
        var e = 1 - Math.pow(1 - t, 3);
        pct = finishFrom + (100 - finishFrom) * e;
        paint();
        if (t >= 1) {
          raf = 0;
          fadeOut(finishDone);
          return;
        }
      } else if (pct < IDLE_CEILING) {
        pct = Math.min(IDLE_CEILING, pct + idleRate(pct) * dt);
        paint();
      }
      raf = requestAnimationFrame(frame);
    }

    setTip(tipIdx);
    paint();
    if (!preferReduced) raf = requestAnimationFrame(frame);

    if (!preferReduced && TIPS.length > 1) {
      tipTimer = setInterval(function () {
        var next = tipIdx;
        while (next === tipIdx) next = Math.floor(Math.random() * TIPS.length);
        setTip(next);
      }, 2400);
    }

    window.__lociBootSplash = {
      rev: REV,
      setMessage: function (text) {
        var msgEl = root.querySelector(".loci-boot-msg");
        if (msgEl) msgEl.textContent = text;
      },
      complete: function (done) {
        stopTips();
        if (preferReduced || finishing) {
          if (!finishing) {
            pct = 100;
            paint();
            fadeOut(done);
          } else if (typeof done === "function") {
            finishDone = done;
          }
          return;
        }
        finishing = true;
        finishFrom = pct;
        finishDone = done;
        if (finishFrom >= 99.5) {
          pct = 100;
          paint();
          fadeOut(done);
          return;
        }
        finishStart = (typeof performance !== "undefined" && performance.now)
          ? performance.now() : Date.now();
        lastTs = 0;
        if (!raf) raf = requestAnimationFrame(frame);
      }
    };
  }

  function nativeSplashCompleted() {
    try {
      return new URLSearchParams(window.location.search).get("_boot_splash") === "done";
    } catch (e) {
      return false;
    }
  }

  function start() {
    var root = document.getElementById("boot-splash") || document.querySelector(".loci-boot-root");
    if (!root || root.getAttribute("data-loci-boot") === REV) return;
    if (PHASE === "enter" && nativeSplashCompleted()) {
      root.remove();
      return;
    }
    if (PHASE === "exit" || PHASE === "error") bootQuiet(root);
    else bootEnter(root);
  }
  // 脚本固定写在 splash 标记之后，解析期立即初始化，确保 defer/module 主入口可调用 complete。
  start();
})();
""".replace("__REV__", BOOT_SPLASH_REV).replace("__TIPS__", _TIPS_JSON)
