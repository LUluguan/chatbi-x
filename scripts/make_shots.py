"""把 BIRD train parquet（hf-mirror）转成 few-shot 池 JSON。

前置: curl -L -o data/bird/train.parquet "https://hf-mirror.com/datasets/xu3kev/BIRD-SQL-data-train/resolve/main/data/train-00000-of-00001-fe8894d41b7815be.parquet"
      pip install pyarrow
用法: python scripts/make_shots.py
"""

import json
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "bird" / "train.parquet"
DST = ROOT / "data" / "eval" / "bird_train_shots.json"


def main():
    t = pq.read_table(SRC)
    out = []
    for i in range(t.num_rows):
        q = t.column("question")[i].as_py()
        sql = t.column("SQL")[i].as_py()
        db = t.column("db_id")[i].as_py() or ""
        if q and sql:
            entry = {"question": q, "sql": sql}
            if db:
                entry["db_id"] = db
            out.append(entry)
    DST.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"已生成 {DST} ({len(out)} 条)")


if __name__ == "__main__":
    main()
