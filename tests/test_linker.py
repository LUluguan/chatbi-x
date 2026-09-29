from app.linker import rank_shots, rank_tables, textgrams
from app.schema import load_schema


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
