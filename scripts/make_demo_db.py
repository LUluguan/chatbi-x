"""生成演示电商库 data/demo_ecom.db（确定性随机种子，可重复生成）。

包含 schema_comments 中文注释表 —— linker 用它把中文问题桥接到英文表名。
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "demo_ecom.db"

CITIES = ["广州", "深圳", "佛山", "东莞"]
SURNAMES = "赵钱孙李周吴郑王陈林黄"
GIVEN = ["伟", "芳", "娜", "军", "磊", "静", "强", "敏", "杰", "丽"]
PRODUCTS = [
    ("无线鼠标", "数码", 129.0), ("机械键盘", "数码", 349.0), ("USB-C 扩展坞", "数码", 199.0),
    ("蓝牙耳机", "数码", 259.0), ("数据线", "数码", 29.9),
    ("保温杯", "日用", 59.0), ("雨伞", "日用", 45.0), ("抽纸", "日用", 15.9), ("洗衣液", "日用", 39.9),
    ("笔记本", "文具", 12.5), ("签字笔", "文具", 6.0),
    ("帆布包", "服饰", 89.0),
]
STATUSES = ["已完成", "已完成", "已完成", "待发货", "已取消"]

COMMENTS = [
    ("users", "用户表：姓名、所在城市与注册日期"),
    ("products", "商品表：名称、类别与定价"),
    ("orders", "订单表：用户下单记录，含订单状态与下单日期"),
    ("order_items", "订单明细表：每笔订单包含的商品、数量与成交单价"),
    ("orders.status", "订单状态：已完成 / 待发货 / 已取消"),
    ("orders.created_at", "下单日期，格式 YYYY-MM-DD"),
]


def main():
    rng = random.Random(42)
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, city TEXT, created_at TEXT);
        CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
        CREATE TABLE orders(id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, created_at TEXT);
        CREATE TABLE order_items(id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, qty INTEGER, unit_price REAL);
        CREATE TABLE schema_comments(name TEXT PRIMARY KEY, description TEXT);
        """
    )
    users = [
        (i, rng.choice(SURNAMES) + rng.choice(GIVEN), rng.choice(CITIES),
         f"2026-{rng.randint(1, 7):02d}-{rng.randint(1, 28):02d}")
        for i in range(1, 21)
    ]
    con.executemany("INSERT INTO users VALUES (?,?,?,?)", users)
    con.executemany("INSERT INTO products VALUES (?,?,?,?)",
                    [(i, n, c, p) for i, (n, c, p) in enumerate(PRODUCTS, 1)])

    start = date(2026, 8, 1)
    oid, item_id = 1, 1
    for _ in range(120):
        uid = rng.randint(1, 20)
        status = rng.choice(STATUSES)
        d = start + timedelta(days=rng.randint(0, 58))
        con.execute("INSERT INTO orders VALUES (?,?,?,?)", (oid, uid, status, d.isoformat()))
        for _ in range(rng.randint(1, 4)):
            pid = rng.randint(1, len(PRODUCTS))
            price = round(PRODUCTS[pid - 1][2] * rng.uniform(0.9, 1.0), 2)
            con.execute("INSERT INTO order_items VALUES (?,?,?,?,?)",
                        (item_id, oid, pid, rng.randint(1, 3), price))
            item_id += 1
        oid += 1
    con.executemany("INSERT INTO schema_comments VALUES (?,?)", COMMENTS)
    con.commit()
    con.close()
    print(f"已生成 {DB}")


if __name__ == "__main__":
    main()
