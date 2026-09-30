import sqlite3

from app.linker import (fk_edges, join_closure, rank_shots, rank_tables, recall_at_k,
                        tables_in_sql, textgrams)
from app.schema import TableInfo, load_schema


def test_textgrams_extracts_cjk_bigrams_and_words():
    g = textgrams("订单总金额 Order")
    assert "订单" in g and "单总" in g and "金额" in g
    assert "order" in g


def test_rank_tables_puts_order_table_first_for_cn_question(mini_db):
    tables = load_schema(mini_db)
    ranked = rank_tables(tables, "统计每个用户的订单总金额", k=1)
    assert len(ranked) == 1
    assert ranked[0].name == "orders"


def test_rank_tables_puts_users_first_for_user_question(mini_db):
    tables = load_schema(mini_db)
    ranked = rank_tables(tables, "广州有多少个用户", k=1)
    assert ranked[0].name == "users"


def test_rank_tables_k_limits_output(mini_db):
    tables = load_schema(mini_db)
    assert len(rank_tables(tables, "随便问点什么", k=2)) == 2


def test_rank_shots_returns_most_similar_example_first():
    shots = [
        {"question": "每个城市的用户数量", "sql": "SELECT city, COUNT(*) FROM users GROUP BY city"},
        {"question": "价格最贵的商品", "sql": "SELECT name FROM products ORDER BY price DESC LIMIT 1"},
        {"question": "有多少订单被取消", "sql": "SELECT COUNT(*) FROM orders WHERE status='已取消'"},
    ]
    ranked = rank_shots(shots, "被取消的订单有多少个", k=2)
    assert len(ranked) == 2
    assert ranked[0]["question"] == "有多少订单被取消"


class TestRecallMetrics:
    def test_tables_in_sql_extracts_from_and_join(self):
        sql = "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id WHERE o.id IN (SELECT order_id FROM items)"
        assert tables_in_sql(sql) == {"users", "orders", "items"}

    def test_tables_in_sql_ignores_subquery_paren_and_literals(self):
        assert tables_in_sql("SELECT * FROM (SELECT 1) t") == set()
        assert tables_in_sql("SELECT 'FROM fake' FROM users") == {"users"}

    def test_recall_at_k_full_and_partial(self):
        ranked = ["orders", "users", "products"]
        assert recall_at_k({"orders"}, ranked, 1) == 1.0
        assert recall_at_k({"orders", "users"}, ranked, 1) == 0.5
        assert recall_at_k({"orders", "users"}, ranked, 2) == 1.0
        assert recall_at_k({"missing"}, ranked, 6) == 0.0
        assert recall_at_k(set(), ranked, 3) == 0.0


# departments <- majors -> students：majors 是连接两端必需的桥表
CHAIN_Q = "每个院系的学生平均GPA是多少"
CHAIN_TABLES = [
    TableInfo("students", [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"},
                           {"name": "gpa", "type": "REAL"}, {"name": "major_id", "type": "INTEGER"}],
              200, [], "学生表：学生姓名与GPA"),
    TableInfo("departments", [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}],
              8, [], "院系表：学校各院系的名称"),
    TableInfo("majors", [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"},
                         {"name": "dept_id", "type": "INTEGER"}],
              30, [], "专业表：各专业及其所属院系"),
]


class TestJoinClosure:
    """词面相似度会把三表连接的桥表挤出 Top-k，join 闭包必须把它补回来。"""

    def test_closure_adds_bridge_table_between_two_selected(self):
        # users <- orders <- payments：选中两端，桥表 orders 必须补回来
        tabs = [TableInfo("users", [{"name": "id", "type": "INTEGER"}], 3, [], "用户表"),
                TableInfo("orders", [{"name": "id", "type": "INTEGER"},
                                     {"name": "user_id", "type": "INTEGER"}], 5, [], "订单表"),
                TableInfo("payments", [{"name": "id", "type": "INTEGER"},
                                       {"name": "order_id", "type": "INTEGER"}], 5, [], "支付表")]
        got = join_closure(tabs, ["users", "payments"])
        assert {t.name for t in got} == {"users", "orders", "payments"}
        assert [t.name for t in got] == ["users", "payments", "orders"]  # 种子在前，桥表追加

    def test_closure_adds_nothing_when_selected_already_connected(self):
        tabs = [TableInfo("users", [{"name": "id", "type": "INTEGER"}], 3, [], "用户表"),
                TableInfo("orders", [{"name": "id", "type": "INTEGER"},
                                     {"name": "user_id", "type": "INTEGER"}], 5, [], "订单表")]
        got = join_closure(tabs, ["users", "orders"])
        assert [t.name for t in got] == ["users", "orders"]

    def test_naming_does_not_invent_edge_for_abbreviation(self):
        # dept 不是 departments 的前缀/子串，缩写关系词面推不出来 —— 不许瞎猜
        assert frozenset({"majors", "departments"}) not in fk_edges(CHAIN_TABLES)
        assert frozenset({"students", "majors"}) in fk_edges(CHAIN_TABLES)

    def test_declared_edges_connect_abbreviated_relationship(self):
        # 库里声明了外键时（major_id->majors, dept_id->departments），桥表必须补回来
        declared = {frozenset({"students", "majors"}), frozenset({"majors", "departments"})}
        got = join_closure(CHAIN_TABLES, ["students", "departments"], edges=declared)
        assert {t.name for t in got} == {"students", "majors", "departments"}
        assert got[0].name == "students"  # 种子顺序保持

    def test_fk_edges_prefer_declared_metadata(self, tmp_path):
        db = tmp_path / "fk.db"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE departments(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE majors(id INTEGER PRIMARY KEY, name TEXT,
                                dept_id INTEGER REFERENCES departments(id));
        """)
        con.commit()
        con.close()
        tables = load_schema(str(db))
        assert frozenset({"majors", "departments"}) in fk_edges(tables)

    def test_ambiguous_fk_stem_is_not_guessed(self):
        # room_id 同时可能是 dorm_rooms 或 classrooms：有歧义就不推断，也不硬塞第三张表
        tabs = [TableInfo("dorm_assignments", [{"name": "room_id", "type": "INTEGER"}], 9, [], "住宿分配"),
                TableInfo("dorm_rooms", [{"name": "id", "type": "INTEGER"}], 6, [], "宿舍房间"),
                TableInfo("classrooms", [{"name": "id", "type": "INTEGER"}], 7, [], "教室")]
        got = join_closure(tabs, ["dorm_assignments", "dorm_rooms"])
        assert {t.name for t in got} == {"dorm_assignments", "dorm_rooms"}

    def test_rank_tables_without_closure_keeps_old_behaviour(self):
        ranked = rank_tables(CHAIN_TABLES, CHAIN_Q, k=2)
        assert len(ranked) == 2
        assert "majors" not in {t.name for t in ranked}  # 前提：桥表被词面相似度挤出 Top-2

    def test_rank_tables_with_closure_recovers_dropped_bridge(self):
        tabs = [TableInfo("payments", [{"name": "id", "type": "INTEGER"},
                                       {"name": "order_id", "type": "INTEGER"},
                                       {"name": "channel", "type": "TEXT"},
                                       {"name": "amount", "type": "REAL"}], 6, [], "支付表：支付渠道与金额"),
                TableInfo("users", [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"},
                                    {"name": "city", "type": "TEXT"}], 3, [], "用户表：姓名与所在城市"),
                TableInfo("orders", [{"name": "id", "type": "INTEGER"}, {"name": "user_id", "type": "INTEGER"},
                                     {"name": "status", "type": "TEXT"}], 5, [], "订单表：下单记录与状态")]
        q = "各支付渠道的金额合计是多少，按用户所在城市分组"
        without = rank_tables(tabs, q, k=2)
        assert "orders" not in {t.name for t in without}          # 前提：桥表被挤出
        got = rank_tables(tabs, q, k=2, closure=True)
        assert "orders" in {t.name for t in got}
        assert got[0].name in {"payments", "users"}                # 种子仍在最前
