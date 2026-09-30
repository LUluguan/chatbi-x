from app.executor import run_sql, validate_sql


def test_readonly_connection_blocks_attach_writes(mini_db, tmp_path):
    """mode=ro 只锁主库不锁 ATTACH 附件库；连接层必须有 query_only 兜底。

    模拟绕过 validate_sql 的最坏情况：直接用同一连接 ATTACH 外部文件并写入。
    """
    import sqlite3

    import pytest

    from app.schema import connect_ro

    evil = tmp_path / "evil.db"
    con = connect_ro(mini_db)
    try:
        with pytest.raises(sqlite3.Error):
            con.executescript(
                f"ATTACH DATABASE '{evil.as_posix()}' AS evil; CREATE TABLE evil.t(x);"
            )
    finally:
        con.close()


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


class TestWhitelistFalsePositives:
    """合法只读 SQL 不应被语境盲视的校验误杀（评审发现的 6 类）。"""

    def test_parenthesized_select_accepted(self):
        assert validate_sql("(SELECT 1)") is None

    def test_values_table_accepted(self):
        assert validate_sql("VALUES (1),(2)") is None

    def test_semicolon_inside_string_literal_accepted(self):
        assert validate_sql("SELECT 'a;b'") is None

    def test_forbidden_word_inside_string_literal_accepted(self):
        assert validate_sql("SELECT * FROM users WHERE name LIKE '%attach%'") is None

    def test_keywords_inside_comments_accepted(self):
        assert validate_sql("SELECT 1 -- vacuum 清理") is None
        assert validate_sql("/* pragma debug */ SELECT 1") is None

    def test_still_rejects_real_second_statement(self):
        assert validate_sql("SELECT 1; DELETE FROM users") is not None

    def test_still_rejects_bare_dangerous_commands(self):
        for sql in ["PRAGMA data_version", "ATTACH DATABASE 'x' AS y", "VACUUM"]:
            assert validate_sql(sql) is not None, sql

    def test_string_with_semicolon_executes(self, mini_db):
        r = run_sql(mini_db, "SELECT 'a;b' AS s")
        assert r.ok and r.rows[0][0] == "a;b"

    def test_like_with_keyword_executes(self, mini_db):
        r = run_sql(mini_db, "SELECT COUNT(*) AS n FROM users WHERE name LIKE '%attach%'")
        assert r.ok and r.rows[0][0] == 0
