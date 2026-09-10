import re
import sys

FORBIDDEN = [
    r"src[\\/]market[\\/]application[\\/]realtime_.*\.py",
    r"src[\\/]market[\\/]infrastructure[\\/]store_hot\.py",
    r"src[\\/]ops[\\/]application[\\/]paper_eod_bars\.py",
    r"src[\\/]ops[\\/]application[\\/]jobs[\\/](screen|registry|market_gate)\.py",
    r"src[\\/]strategy[\\/]api[\\/]router\.py",
    r"src[\\/]strategy[\\/]application[\\/](screen_run|screen_skills)\.py",
    r"src[\\/]ai[\\/]application[\\/]system_toolbus_strategy\.py",
    r"src[\\/]shared[\\/]screen_capacity\.py",
    r"tests[\\/]market[\\/](test_hot_fallback_reason|test_realtime_signal_internals)\.py",
    r"tests[\\/]shared[\\/]test_screen_capacity\.py",
    r"tests[\\/]review[\\/]test_insights\.py",
]


def main(path):
    skip = []
    keep = []
    for line in open(path, encoding="utf-8").read().splitlines():
        m = re.match(r"^(.+?):(\d+):(\d+): (F\d+)", line)
 if not m:
     continue
        f = m.group(1)
        if any(re.match(p, f) for p in FORBIDDEN):
     skip.append(line)
 else:
            keep.append(line)
    print("SKIP", len(skip))
    for line in skip:
        print("  " + line)
    print("KEEP", len(keep))
    for line in keep:
        print("  " + line)


if __name__ == "__main__":
    main(sys.argv[1])
