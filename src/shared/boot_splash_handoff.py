"""原生启动页 → SPA 的交接：boot_splash 里唯一带副作用的一段。

为什么单独成文件：这里要注入 JS、等一个 `threading.Event`、再切回 UI 线程调
`load_url`，失败模式是死锁和超时，与「拼字符串」是完全不同的调试路径。

它还自带一份**独立的**注入脚本 `_COMPLETE_BEFORE_NAVIGATION_JS`：那份脚本的配色
与 TIPS 是写死的字面量，与 `boot_splash_assets._JS`（模板 + 占位符替换）并不是同一
份内容。两份摆在同一个文件里，看的人会以为可以合并去重，一合并就把原生页与 SPA
页的配色搅到一起——所以按「谁在用」而不是「长得像」来分。
"""

from __future__ import annotations

import threading
from typing import Any, Callable

_BOOT_SPLASH_DONE_PARAM = "_boot_splash=done"
_COMPLETE_BEFORE_NAVIGATION_JS = r"""
(function () {
  var REV = "2026-08-ths-fullpage-v4";
  var VW = 960, VH = 640;
  // 与 style.base.css 的 :root 令牌逐字对齐（内联脚本取不到 CSS 变量，只能抄一份字面值）
  var ACCENT = "#e03127", BLUE = "#1f5fa0", GREEN = "#12a06a";
  var PAPER = "#e7ebf0", RAIL = "#d2d9e2", MUTE = "#6b7a8b";
  var TIPS = ["本地服务启动中","行情缓存校验中","候选与复盘对齐中","盘口即将就绪"];
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
""".strip()


def _completed_target(target: str) -> str:
    separator = "&" if "?" in target else "?"
    return f"{target}{separator}{_BOOT_SPLASH_DONE_PARAM}"


def handoff_to_spa(
    window: Any,
    target: str,
    *,
    timeout: float = 2.5,
    log: Callable[[str], None] | None = None,
) -> tuple[str, bool]:
    """让原生启动页完成 100% 动画，再导航到不会重复开幕的 SPA。"""
    from src.shared.webview_ui import run_on_ui_thread

    done = threading.Event()
    outcome: list[str] = []

    def resolved(result: Any = None) -> None:
        outcome.append(str(result or ""))
        done.set()

    def request_completion() -> None:
        try:
            window.evaluate_js(_COMPLETE_BEFORE_NAVIGATION_JS, callback=resolved)
        except Exception as exc:  # noqa: BLE001 — 启动交接失败须降级继续开窗
            outcome.append(f"error:{type(exc).__name__}")
            done.set()

    # WebView2 的 evaluate_js 内部会切回 UI 线程并同步等待结果；外层再次投递到
    # WinForms UI 线程会让 ContinueWith 无法执行，形成死锁。此函数由启动后台线程调用。
    request_completion()

    completed = done.wait(max(0.0, timeout)) and bool(outcome) and outcome[-1] == "completed"
    resolved_target = _completed_target(target) if completed else target
    if log is not None:
        detail = outcome[-1] if outcome else "timeout"
        log(f"boot splash handoff={detail} → load_url {resolved_target}")
    run_on_ui_thread(window, lambda: window.load_url(resolved_target), wait=False)
    return resolved_target, completed
