import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

COMMENTS_TABLE = "schema_comments"


@dataclass
class TableInfo:
    name: str
    columns: list[dict]  # [{name, type}]
    row_count: int = 0
    samples: list[list] = field(default_factory=list)
    description: str = ""  # 来自 schema_comments 的中文业务描述


def connect_ro(db_path: str) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    # mode=ro 只锁主库；ATTACH 的外部库不受它约束，query_only 在连接层兜底
    con.execute("PRAGMA query_only=ON")
    return con


def load_schema(db_path: str) -> list[TableInfo]:
    con = connect_ro(db_path)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != ? ORDER BY name",
            (COMMENTS_TABLE,),
        )
        tables = [r[0] for r in rows]
        comments: dict[str, str] = {}
        try:
            for n, d in con.execute(f"SELECT name, description FROM {COMMENTS_TABLE}"):
                comments[n] = d or ""
        except sqlite3.OperationalError:
            pass  # 库里没有注释表
        out = []
        for t in tables:
            cols = [{"name": r[1], "type": r[2] or ""} for r in con.execute(f'PRAGMA table_info("{t}")')]
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            samples = [list(r) for r in con.execute(f'SELECT * FROM "{t}" LIMIT 3')]
            out.append(TableInfo(t, cols, n, samples, comments.get(t, "")))
        return out
    finally:
        con.close()


def table_prompt(t: TableInfo) -> str:
    cols = ", ".join(f'{c["name"]} {c["type"]}'.strip() for c in t.columns)
    head = f"{t.name}({cols}) -- {t.row_count}行"
    if t.description:
        head += f"｜{t.description}"
    lines = [head] + [f"  样例: {tuple(s)!r}" for s in t.samples]
    return "\n".join(lines)


def schema_prompt(tables: list[TableInfo]) -> str:
    return "\n".join(table_prompt(t) for t in tables)
