import json

from app.eval.metrics import execution_accuracy
from app.eval.runner import EvalItem, load_dataset, load_shots, resolve_db, run_compare, run_eval
from app.executor import ExecutionResult
from app.providers.mock import MockProvider


class TestExecutionAccuracy:
    def test_identical_results_score_one(self):
        a = ExecutionResult(ok=True, columns=["n"], rows=[[3]])
        b = ExecutionResult(ok=True, columns=["cnt"], rows=[[3]])
        assert execution_accuracy(a, b) == 1.0

    def test_row_order_insensitive(self):
        a = ExecutionResult(ok=True, columns=["city", "n"], rows=[["广州", 2], ["深圳", 1]])
        b = ExecutionResult(ok=True, columns=["c", "k"], rows=[["深圳", 1], ["广州", 2]])
        assert execution_accuracy(a, b) == 1.0

    def test_different_values_score_zero(self):
        a = ExecutionResult(ok=True, columns=["n"], rows=[[3]])
        b = ExecutionResult(ok=True, columns=["n"], rows=[[4]])
        assert execution_accuracy(a, b) == 0.0

    def test_column_count_mismatch_scores_zero(self):
        a = ExecutionResult(ok=True, columns=["n"], rows=[[1]])
        b = ExecutionResult(ok=True, columns=["a", "b"], rows=[[1, 2]])
        assert execution_accuracy(a, b) == 0.0

    def test_float_tolerated_to_six_decimals(self):
        a = ExecutionResult(ok=True, columns=["s"], rows=[[99.500000001]])
        b = ExecutionResult(ok=True, columns=["s"], rows=[[99.5]])
        assert execution_accuracy(a, b) == 1.0

    def test_error_on_either_side_scores_zero(self):
        err = ExecutionResult(ok=False, error="boom")
        good = ExecutionResult(ok=True, columns=["n"], rows=[[1]])
        assert execution_accuracy(err, good) == 0.0
        assert execution_accuracy(good, err) == 0.0

    def test_null_cells_sortable_and_comparable(self):
        # BIRD 真实数据中金标 SQL 会返回 NULL：
        # 首列相同时排序会比较 (值, None) 与 (值, 数值) —— 必须可排序
        a = ExecutionResult(ok=True, columns=["x", "y"], rows=[["A", None], ["A", 1]])
        b = ExecutionResult(ok=True, columns=["c", "d"], rows=[["A", 1], ["A", None]])
        assert execution_accuracy(a, b) == 1.0
        c = ExecutionResult(ok=True, columns=["x", "y"], rows=[["A", None], ["A", None]])
        assert execution_accuracy(a, c) == 0.0


class TestLoadDataset:
    def test_reads_question_and_gold_sql(self, tmp_path):
        f = tmp_path / "d.json"
        f.write_text(json.dumps([
            {"question": "多少用户", "gold_sql": "SELECT COUNT(*) FROM users"},
            {"question": "多少订单", "SQL": "SELECT COUNT(*) FROM orders", "db_id": "x"},
        ], ensure_ascii=False), encoding="utf-8")
        items = load_dataset(str(f))
        assert len(items) == 2
        assert items[0].gold_sql == "SELECT COUNT(*) FROM users"
        assert items[1].gold_sql == "SELECT COUNT(*) FROM orders"
        assert items[1].db_id == "x"  # BIRD 风格 db_id 落到 db_id 字段

    def test_reads_difficulty_field(self, tmp_path):
        f = tmp_path / "d.json"
        f.write_text(json.dumps([
            {"question": "q1", "gold_sql": "SELECT 1", "difficulty": "simple"},
            {"question": "q2", "gold_sql": "SELECT 2", "difficulty": "challenging"},
            {"question": "q3", "gold_sql": "SELECT 3"},
        ], ensure_ascii=False), encoding="utf-8")
        items = load_dataset(str(f))
        assert [i.difficulty for i in items] == ["simple", "challenging", ""]


class TestResolveDb:
    def test_empty_ref_uses_default(self):
        assert resolve_db("", "default.db", datasets_root="") == "default.db"

    def test_existing_path_passthrough(self, tmp_path):
        p = tmp_path / "x.sqlite"
        p.write_text("")
        assert resolve_db(str(p), "default.db", datasets_root="") == str(p)

    def test_bird_layout_dev_databases(self, tmp_path):
        db = tmp_path / "dev_databases" / "california_schools" / "california_schools.sqlite"
        db.parent.mkdir(parents=True)
        db.write_text("")
        got = resolve_db("california_schools", "default.db", datasets_root=str(tmp_path))
        assert got == str(db)

    def test_flat_layout(self, tmp_path):
        db = tmp_path / "financial" / "financial.sqlite"
        db.parent.mkdir(parents=True)
        db.write_text("")
        got = resolve_db("financial", "default.db", datasets_root=str(tmp_path))
        assert got == str(db)

    def test_unknown_ref_raises_instead_of_silent_wrong_db(self):
        import pytest
        with pytest.raises(FileNotFoundError):
            resolve_db("nope", "default.db", datasets_root="")


class TestShots:
    def test_load_shots_accepts_train_format(self, tmp_path):
        f = tmp_path / "train.json"
        f.write_text(json.dumps([
            {"question": "多少用户", "SQL": "SELECT COUNT(*) FROM users"},
            {"question": "订单总数", "gold_sql": "SELECT COUNT(*) FROM orders"},
        ], ensure_ascii=False), encoding="utf-8")
        shots = load_shots(str(f))
        assert shots == [
            {"question": "多少用户", "sql": "SELECT COUNT(*) FROM users"},
            {"question": "订单总数", "sql": "SELECT COUNT(*) FROM orders"},
        ]

    def test_load_shots_keeps_db_id_when_present(self, tmp_path):
        f = tmp_path / "train.json"
        f.write_text(json.dumps([
            {"question": "多少用户", "SQL": "SELECT COUNT(*) FROM users", "db_id": "financial"},
        ], ensure_ascii=False), encoding="utf-8")
        assert load_shots(str(f)) == [
            {"question": "多少用户", "sql": "SELECT COUNT(*) FROM users", "db_id": "financial"}
        ]

    def test_shots_file_feeds_single_shot_prompt(self, mini_db, tmp_path, scripted_provider):
        shots_file = tmp_path / "shots.json"
        shots_file.write_text(json.dumps(
            [{"question": "每个城市有多少用户", "SQL": "SELECT city, COUNT(*) FROM users GROUP BY city"}],
            ensure_ascii=False), encoding="utf-8")
        p = scripted_provider(['{"action": "final", "sql": "SELECT 1"}'])
        items = [EvalItem(question="广州有多少用户", gold_sql="SELECT 1")]
        run_eval(items, p, mini_db, mode="single_shot", shots=load_shots(str(shots_file)))
        assert "参考示例" in p.calls[0][0]["content"]
        assert "每个城市有多少用户" in p.calls[0][0]["content"]

    def test_shots_prefer_same_database(self, mini_db, scripted_provider):
        shots = [
            {"question": "数量", "sql": "SELECT COUNT(*) AS n FROM orders", "db_id": "orders_db"},
            {"question": "数量", "sql": "SELECT COUNT(*) AS n FROM users", "db_id": "users_db"},
        ]
        items = [EvalItem(question="有多少个用户", gold_sql="SELECT COUNT(*) AS n FROM users",
                          db_path=mini_db, db_id="users_db")]
        p = scripted_provider(['{"action": "final", "sql": "SELECT 1"}'])
        run_eval(items, p, mini_db, mode="single_shot", shots=shots)
        prompt = p.calls[0][0]["content"]
        assert "FROM users" in prompt
        assert "FROM orders" not in prompt


class TestRunEval:
    def test_evidence_passed_into_prompt(self, mini_db, scripted_provider):
        p = scripted_provider(['{"action": "final", "sql": "SELECT 1"}'])
        items = [EvalItem(question="广州用户多少", gold_sql="SELECT 1", evidence="广州 是城市名")]
        run_eval(items, p, mini_db, mode="single_shot")
        assert "广州 是城市名" in p.calls[0][1]["content"]

    def test_db_id_resolved_through_datasets_root(self, tmp_path, scripted_provider):
        import sqlite3

        root = tmp_path / "root"
        db = root / "dev_databases" / "users_db" / "users_db.sqlite"
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE users(id INTEGER)")
        con.execute("INSERT INTO users VALUES (7)")
        con.commit()
        con.close()
        p = scripted_provider(['{"action": "final", "sql": "SELECT COUNT(*) AS n FROM users"}'])
        items = [EvalItem(question="有多少个用户", gold_sql="SELECT COUNT(*) AS n FROM users", db_id="users_db")]
        report = run_eval(items, p, "unused_default.db", mode="single_shot", datasets_root=str(root))
        assert report.accuracy == 1.0

    def test_mock_with_canned_hits_full_accuracy(self, mini_db, tmp_path):
        eval_file = tmp_path / "d.json"
        items_data = [
            {"question": "有多少个用户", "gold_sql": "SELECT COUNT(*) AS n FROM users"},
            {"question": "有多少个订单", "gold_sql": "SELECT COUNT(*) AS n FROM orders"},
        ]
        eval_file.write_text(json.dumps(items_data, ensure_ascii=False), encoding="utf-8")
        items = load_dataset(str(eval_file))
        canned = {i["question"]: i["gold_sql"] for i in items_data}
        report = run_eval(items, MockProvider(canned), mini_db, mode="single_shot")
        assert report.total == 2
        assert report.accuracy == 1.0
        assert all(d["acc"] == 1.0 for d in report.details)

    def test_mock_without_canned_scores_zero(self, mini_db):
        items = [EvalItem(question="未知问题", gold_sql="SELECT COUNT(*) AS n FROM users")]
        report = run_eval(items, MockProvider({}), mini_db, mode="single_shot")
        assert report.accuracy == 0.0
        assert report.details[0]["ok"] is False

    def test_agent_mode_with_canned_hits_full_accuracy(self, mini_db, tmp_path):
        eval_file = tmp_path / "d.json"
        data = [{"question": "有多少个用户", "gold_sql": "SELECT COUNT(*) AS n FROM users"}]
        eval_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        canned = {i["question"]: i["gold_sql"] for i in data}
        report = run_eval(load_dataset(str(eval_file)), MockProvider(canned), mini_db, mode="agent")
        assert report.accuracy == 1.0
        assert report.mode == "agent"

    def test_persistent_provider_failure_recorded_not_raised(self, mini_db):
        from app.providers.openai_compat import ProviderError

        class BoomProvider:
            name = "boom"

            def chat(self, messages, temperature=None):
                raise ProviderError("LLM 调用失败: boom")

        items = [EvalItem(question="有多少个用户", gold_sql="SELECT COUNT(*) AS n FROM users")]
        for mode in ("single_shot", "agent"):
            report = run_eval(items, BoomProvider(), mini_db, mode=mode)
            assert report.accuracy == 0.0
            assert report.total == 1
            assert "boom" in report.details[0]["error"]

    def test_judge_compares_full_result_sets_not_truncated(self, tmp_path, mini_db, scripted_provider):
        """金标返回超过 50 行时，判据必须比对全量结果集。

        回归：v3 判据用 max_rows=50 截断两边后比前 50 行（物理顺序），
        顺序不同/行数不同都会误判。此测试在旧行为下必然失败。
        """
        import sqlite3

        big = tmp_path / "big.db"
        con = sqlite3.connect(big)
        con.executescript("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT);")
        con.executemany("INSERT INTO t VALUES (?,?)", [(i, f"v{i}") for i in range(1, 121)])
        con.commit()
        con.close()
        gold = "SELECT id FROM t"                       # 120 行，物理顺序
        pred = "SELECT id FROM t ORDER BY id DESC"      # 同一结果集，倒序输出
        p = scripted_provider([json.dumps({"action": "final", "sql": pred}, ensure_ascii=False)])
        report = run_eval([EvalItem(question="q", gold_sql=gold)], p, str(big), mode="single_shot")
        assert report.accuracy == 1.0
        assert report.details[0]["truncated"] is False

    def test_truncated_flag_set_when_capped(self, tmp_path, scripted_provider):
        import sqlite3

        big = tmp_path / "big.db"
        con = sqlite3.connect(big)
        con.executescript("CREATE TABLE t(id INTEGER PRIMARY KEY);")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(1, 31)])
        con.commit()
        con.close()
        p = scripted_provider([json.dumps({"action": "final", "sql": "SELECT id FROM t"}, ensure_ascii=False)])
        report = run_eval([EvalItem(question="q", gold_sql="SELECT id FROM t")],
                          p, str(big), mode="single_shot", eval_max_rows=10)
        assert report.details[0]["truncated"] is True

    def test_details_carry_failure_category(self, mini_db):
        items = [
            EvalItem(question="有多少个用户", gold_sql="SELECT COUNT(*) AS n FROM users"),
            EvalItem(question="未知问题A", gold_sql="SELECT COUNT(*) AS n FROM users"),
            EvalItem(question="错误SQL题", gold_sql="SELECT COUNT(*) AS n FROM users"),
        ]
        canned = {
            "有多少个用户": "SELECT COUNT(*) AS n FROM users",   # correct
            "错误SQL题": "SELECT 1",                              # 执行成功但结果不匹配
        }
        report = run_eval(items, MockProvider(canned), mini_db, mode="single_shot")
        cats = {d["question"]: d["category"] for d in report.details}
        assert cats["有多少个用户"] == "correct"
        assert cats["未知问题A"] == "empty_sql"
        assert cats["错误SQL题"] == "result_mismatch"

    def test_difficulty_breakdown_reported(self, mini_db):
        items = [
            EvalItem(question="有多少个用户", gold_sql="SELECT COUNT(*) AS n FROM users", difficulty="simple"),
            EvalItem(question="有多少个订单", gold_sql="SELECT COUNT(*) AS n FROM orders", difficulty="simple"),
            EvalItem(question="未知问题A", gold_sql="SELECT COUNT(*) AS n FROM users", difficulty="challenging"),
        ]
        canned = {"有多少个用户": "SELECT COUNT(*) AS n FROM users"}
        report = run_eval(items, MockProvider(canned), mini_db, mode="single_shot")
        assert report.by_difficulty["simple"] == {"total": 2, "accuracy": 0.5}
        assert report.by_difficulty["challenging"] == {"total": 1, "accuracy": 0.0}


class TestRunCompare:
    def test_compare_returns_both_modes_and_delta(self, mini_db):
        items = [EvalItem(question="有多少个用户", gold_sql="SELECT COUNT(*) AS n FROM users")]
        canned = {"有多少个用户": "SELECT COUNT(*) AS n FROM users"}
        out = run_compare(items, MockProvider(canned), mini_db)
        assert out["single_shot"]["accuracy"] == 1.0
        assert out["agent"]["accuracy"] == 1.0
        assert out["delta"] == 0.0
        assert out["single_shot"]["mode"] == "single_shot"
        assert out["agent"]["mode"] == "agent"
