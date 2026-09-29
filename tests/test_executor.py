from app.executor import run_sql, validate_sql


def test_select_returns_columns_rows_and_ok(mini_db):
    r = run_sql(mini_db, "SELECT name, city FROM users ORDER BY id")
    assert r.ok
    assert r.columns == ["name", "city"]
    assert r.rows[0] == ["张三", "广州"]
    assert r.error == ""


def test_rejects_insert_update_delete_drop(mini_db):
    for sql in [
        "INSERT INTO users VALUES (9,'x','y')",
        "UPDATE users SET name='x'",
        "DELETE FROM users",
        "DROP TABLE users",
    ]:
        r = run_sql(mini_db, sql)
        assert not r.ok
        assert r.error


def test_rejects_multiple_statements(mini_db):
    r = run_sql(mini_db, "SELECT 1; SELECT 2")
    assert not r.ok
    assert "多" in r.error


def test_rejects_pragma_and_attach(mini_db):
    assert validate_sql("PRAGMA table_info(users)")
    assert validate_sql("ATTACH DATABASE 'x' AS y")


def test_allows_cte_query(mini_db):
    r = run_sql(mini_db, "WITH t AS (SELECT * FROM users) SELECT COUNT(*) AS n FROM t")
    assert r.ok and r.rows[0][0] == 3


def test_truncates_rows_beyond_max_and_flags(mini_db):
    r = run_sql(mini_db, "SELECT id FROM users", max_rows=2)
    assert r.ok
    assert len(r.rows) == 2
    assert r.truncated


def test_sql_error_reported_not_raised(mini_db):
    r = run_sql(mini_db, "SELECT nope FROM users")
    assert not r.ok
    assert "nope" in r.error


def test_timeout_kills_runaway_query(mini_db):
    sql = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c"
    r = run_sql(mini_db, sql, timeout_ms=200)
    assert not r.ok
    assert "超时" in r.error


def test_trailing_semicolon_accepted(mini_db):
    r = run_sql(mini_db, "SELECT COUNT(*) FROM users;")
    assert r.ok and r.rows[0][0] == 3
