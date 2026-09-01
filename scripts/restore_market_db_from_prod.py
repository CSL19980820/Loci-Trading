"""把生产 market.db 的 zstd 快照拉回本机并流式解压。

为什么要这么绕:本机到 my-debian 实测 **0.27 MB/s**(200 MB 花了 12m31s),
4.29 GB 裸传要 4.5 小时。服务器侧 `zstd -15 --long=27` 压到 854 MB(5.02x),
把 ETA 砍到约 53 分钟。

边收边解而不是先落盘再解压:磁盘上只留最终那一份,不为临时文件多写 854 MB。

断点续传按 1 MiB 块对齐:重跑本脚本会把 .part 截到整块边界,再用
`dd skip=<块数>` 从那里续。网络抖一下不用从头再来。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".local" / "pylib"))
import zstandard  # noqa: E402

REMOTE = "my-debian"
REMOTE_FILE = "/tmp/mkt15.zst"
REMOTE_SIZE = 854151312
DEST_DIR = Path(r"E:\entertainment_software\Loci\data")
PART = DEST_DIR / "market.db.part"
FINAL = DEST_DIR / "market.db"
CHUNK = 1 << 20


def fetch() -> None:
    """把远端 zstd 流拉到 PART;已有部分则按整块边界续传。"""
    have = PART.stat().st_size if PART.exists() else 0
    if have >= REMOTE_SIZE:
        print(f"已完整收到 {have} 字节,跳过下载")
        return
    blocks = have // CHUNK
    if have % CHUNK:
        # 上次停在半块中间,截到块首重收该块,免得中间少字节。
        print(f"截断 {have % CHUNK} 字节的残块")
    start_at = blocks * CHUNK
    mode = "r+b" if PART.exists() else "wb"
    print(f"续传起点 {start_at / 1e6:.1f} MB / {REMOTE_SIZE / 1e6:.0f} MB")
    cmd = [
        "ssh",
        REMOTE,
        f"dd if={REMOTE_FILE} bs=1M skip={blocks} 2>/dev/null",
    ]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    assert proc.stdout is not None
    with open(PART, mode) as sink:
        sink.seek(start_at)
        sink.truncate(start_at)
        last = started
        while True:
            buf = proc.stdout.read(CHUNK)
            if not buf:
                break
            sink.write(buf)
            now = time.monotonic()
            if now - last >= 60:
                pos = sink.tell()
                rate = (pos - start_at) / max(1e-9, now - started)
                left = (REMOTE_SIZE - pos) / max(1.0, rate)
                print(
                    f"  {pos / 1e6:7.1f} / {REMOTE_SIZE / 1e6:.0f} MB "
                    f"({100 * pos / REMOTE_SIZE:5.1f}%)  {rate / 1e6:.2f} MB/s  "
                    f"剩 {left / 60:.0f} min",
                    flush=True,
                )
                last = now
    proc.wait()
    print(f"下载结束 {PART.stat().st_size} / {REMOTE_SIZE} 字节,ssh rc={proc.returncode}")


def decompress() -> None:
    size = PART.stat().st_size
    if size != REMOTE_SIZE:
        raise SystemExit(f"字节数不符({size} != {REMOTE_SIZE}),不解压;重跑本脚本续传")
    print("流式解压 -> market.db ...")
    started = time.monotonic()
    with open(PART, "rb") as src, open(FINAL, "wb") as dst:
        zstandard.ZstdDecompressor().copy_stream(
            src, dst, read_size=CHUNK, write_size=CHUNK
        )
    print(
        f"解压完成 {FINAL.stat().st_size / 1e9:.2f} GB,"
        f"用时 {time.monotonic() - started:.0f}s"
    )


if __name__ == "__main__":
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    fetch()
    decompress()
    print("OK")
