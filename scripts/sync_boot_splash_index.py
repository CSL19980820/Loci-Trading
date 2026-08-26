"""Rewrite frontend/index.html boot-splash from src.shared.boot_splash (keep fonts/meta)."""

from __future__ import annotations

from pathlib import Path

from src.shared.boot_splash import BOOT_SPLASH_REV, spa_boot_splash_markup

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend" / "index.html"


def main() -> None:
    css, body, js = spa_boot_splash_markup()
    text = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#c41e3a" />
    <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate" />
    <meta http-equiv="Pragma" content="no-cache" />
    <link rel="icon" href="/favicon.ico" sizes="any" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Mono:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&family=Noto+Serif+SC:wght@600;700&display=swap"
      rel="stylesheet"
    />
    <title>Loci</title>
    <style>
{css}
    </style>
  </head>
  <body>
    <div id="boot-splash" class="loci-boot-root" data-rev="{BOOT_SPLASH_REV}" aria-busy="true" aria-live="polite">
{body}
    </div>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
    <script>
{js}
    </script>
  </body>
</html>
"""
    INDEX.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {INDEX} rev={BOOT_SPLASH_REV} bytes={INDEX.stat().st_size}")


if __name__ == "__main__":
    main()
