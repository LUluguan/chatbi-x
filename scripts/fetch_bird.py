"""下载并解压 BIRD-dev 数据集（官方阿里云 OSS 源，国内直连）。

用法: python scripts/fetch_bird.py
结果: data/bird/dev.json + data/bird/dev_databases/<db_id>/<db_id>.sqlite
"""

import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip"
ROOT = Path(__file__).resolve().parent.parent / "data" / "bird"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    zpath = ROOT / "dev.zip"
    if not zpath.exists():
        part = zpath.parent / (zpath.name + ".part")
        req = urllib.request.Request(URL, headers={"User-Agent": "chatbi-x"})
        print(f"下载 {URL}")
        with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:.0f} / {total / 1e6:.0f} MB", end="", flush=True)
        part.replace(zpath)
        print("\n下载完成")
    else:
        print("dev.zip 已存在，跳过下载")

    marker = ROOT / "dev.json"
    if not marker.exists():
        print("解压中...")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(ROOT)
        # zip 内有一层 dev_<date>/ 目录，展平
        for child in ROOT.iterdir():
            if child.is_dir() and child.name.startswith("dev_2"):
                for f in child.iterdir():
                    f.replace(ROOT / f.name)
                child.rmdir()
        # 嵌套的 dev_databases.zip
        nested = ROOT / "dev_databases.zip"
        if nested.exists() and not (ROOT / "dev_databases").exists():
            with zipfile.ZipFile(nested) as z:
                z.extractall(ROOT)
            nested.unlink()
        # 清理 macOS 垃圾
        macos = ROOT / "__MACOSX"
        if macos.exists():
            import shutil
            shutil.rmtree(macos)
        for junk in ROOT.rglob(".DS_Store"):
            junk.unlink()
        print("解压完成:", ROOT)
    else:
        print("已解压过，跳过")


if __name__ == "__main__":
    sys.exit(main())
