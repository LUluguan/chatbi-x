from app.schema import load_schema, schema_prompt, table_prompt


def test_load_schema_lists_tables_with_columns_and_counts(mini_db):
    tables = load_schema(mini_db)
    names = [t.name for t in tables]
    assert names == ["orders", "users"]  # 排序稳定；schema_comments 是元数据不外露
    orders = tables[0]
    assert [c["name"] for c in orders.columns] == ["id", "user_id", "amount", "created_at"]
    assert orders.row_count == 3
    assert orders.samples[0] == [1, 1, 99.5, "2026-09-01"]


def test_comments_bridged_into_description(mini_db):
    tables = {t.name: t for t in load_schema(mini_db)}
    assert "订单表" in tables["orders"].description
    assert "用户表" in tables["users"].description


def test_table_prompt_contains_columns_rows_and_sample(mini_db):
    orders = load_schema(mini_db)[0]
    text = table_prompt(orders)
    assert text.startswith("orders(id INTEGER, user_id INTEGER, amount REAL, created_at TEXT)")
    assert "3行" in text
    assert "订单表" in text
    assert "样例" in text


def test_schema_prompt_joins_all_tables(mini_db):
    text = schema_prompt(load_schema(mini_db))
    assert "users(" in text and "orders(" in text
