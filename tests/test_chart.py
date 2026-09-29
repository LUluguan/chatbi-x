from app.chart import recommend_chart


class TestRecommendChart:
    def test_string_plus_number_becomes_bar(self):
        rec = recommend_chart(["city", "n"], [["广州", 11], ["深圳", 5], ["佛山", 3]])
        assert rec["type"] == "bar"
        assert rec["x"] == "city"
        assert rec["y"] == ["n"]

    def test_date_like_label_becomes_line(self):
        rec = recommend_chart(
            ["created_at", "n"],
            [["2026-09-22", 3], ["2026-09-23", 5], ["2026-09-24", 2]],
        )
        assert rec["type"] == "line"
        assert rec["x"] == "created_at"

    def test_share_like_values_become_pie(self):
        rec = recommend_chart(
            ["category", "pct"],
            [["数码", 60.0], ["日用", 30.0], ["文具", 10.0]],
        )
        assert rec["type"] == "pie"
        assert rec["x"] == "category"

    def test_non_share_values_stay_bar_even_when_few(self):
        rec = recommend_chart(
            ["category", "total"],
            [["数码", 900.0], ["日用", 300.0], ["文具", 100.0]],
        )
        assert rec["type"] == "bar"

    def test_many_rows_stay_bar_not_pie(self):
        rows = [[f"类{i}", i + 1] for i in range(10)]
        rec = recommend_chart(["name", "n"], rows)
        assert rec["type"] == "bar"

    def test_one_label_two_numbers_is_multi_series_bar(self):
        rec = recommend_chart(
            ["city", "orders", "users"],
            [["广州", 50, 11], ["深圳", 30, 5]],
        )
        assert rec["type"] == "bar"
        assert rec["y"] == ["orders", "users"]

    def test_single_scalar_result_stays_table(self):
        rec = recommend_chart(["n"], [[3]])
        assert rec["type"] == "table"

    def test_no_numeric_column_stays_table(self):
        rec = recommend_chart(["name", "city"], [["张三", "广州"]])
        assert rec["type"] == "table"

    def test_empty_rows_stay_table(self):
        rec = recommend_chart(["a", "b"], [])
        assert rec["type"] == "table"

    def test_rec_includes_reason(self):
        rec = recommend_chart(["city", "n"], [["广州", 11]])
        assert rec["reason"]
