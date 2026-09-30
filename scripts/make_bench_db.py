"""生成 15 表中文教务基准库 data/bench_academic.db（确定性种子，可复现）。

为消融实验设计：表多（linking 必须做取舍）、注释全中文（桥接可生效）、
所有 top-1 问题的答案行强制唯一（避免并列导致误判）。
"""

import random
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "bench_academic.db"

SURNAMES = "赵钱孙李周吴郑王陈林黄徐杨刘高梁宋唐"
GIVEN = ["志远", "雨欣", "浩然", "思琪", "子轩", "梦瑶", "俊杰", "婷婷", "宇航", "雪",
         "晨曦", "嘉懿", "明轩", "雅静", "博文", "心怡", "天佑", "语嫣", "泽洋", "若彤"]

COMMENTS = [
    ("departments", "院系表：学院名称与所在教学楼"),
    ("majors", "专业表：专业名称及所属院系"),
    ("students", "学生表：姓名、性别、专业、年级与 GPA"),
    ("teachers", "教师表：姓名、职称与所属院系"),
    ("courses", "课程表：课程名、学分、开课院系与授课教师"),
    ("classrooms", "教室表：教学楼、房间号与容量"),
    ("schedules", "排课表：课程在教室的星期与节次安排"),
    ("enrollments", "选课成绩表：学生选课记录与考试分数"),
    ("scholarships", "奖学金表：奖项名称与金额"),
    ("scholarship_awards", "获奖记录表：学生获某奖学金的年份"),
    ("dormitories", "宿舍楼表：楼栋与总床位容量"),
    ("dorm_rooms", "宿舍房间表：楼栋、房号与床位容量"),
    ("dorm_assignments", "住宿分配表：学生与宿舍房间的对应"),
    ("clubs", "社团表：社团名称、类别与成立年份"),
    ("club_members", "社团成员表：成员身份（社长/部长/成员）"),
    ("students.gpa", "绩点，范围 2.00-4.00"),
    ("enrollments.score", "考试分数，0-100，低于 60 为不及格"),
    ("enrollments.semester", "学期：2025秋 / 2026春"),
]


def main():
    rng = random.Random(7)
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE departments(id INTEGER PRIMARY KEY, name TEXT, building TEXT);
        CREATE TABLE majors(id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER);
        CREATE TABLE students(id INTEGER PRIMARY KEY, name TEXT, gender TEXT, major_id INTEGER, grade INTEGER, gpa REAL);
        CREATE TABLE teachers(id INTEGER PRIMARY KEY, name TEXT, title TEXT, dept_id INTEGER);
        CREATE TABLE courses(id INTEGER PRIMARY KEY, name TEXT, credits INTEGER, dept_id INTEGER, teacher_id INTEGER);
        CREATE TABLE classrooms(id INTEGER PRIMARY KEY, building TEXT, room_no INTEGER, capacity INTEGER);
        CREATE TABLE schedules(id INTEGER PRIMARY KEY, course_id INTEGER, classroom_id INTEGER, week_day INTEGER, slot INTEGER);
        CREATE TABLE enrollments(id INTEGER PRIMARY KEY, student_id INTEGER, course_id INTEGER, semester TEXT, score INTEGER);
        CREATE TABLE scholarships(id INTEGER PRIMARY KEY, name TEXT, amount INTEGER);
        CREATE TABLE scholarship_awards(id INTEGER PRIMARY KEY, student_id INTEGER, scholarship_id INTEGER, year INTEGER);
        CREATE TABLE dormitories(id INTEGER PRIMARY KEY, building TEXT, capacity INTEGER);
        CREATE TABLE dorm_rooms(id INTEGER PRIMARY KEY, dormitory_id INTEGER, room_no INTEGER, capacity INTEGER);
        CREATE TABLE dorm_assignments(id INTEGER PRIMARY KEY, student_id INTEGER, room_id INTEGER);
        CREATE TABLE clubs(id INTEGER PRIMARY KEY, name TEXT, category TEXT, founded_year INTEGER);
        CREATE TABLE club_members(id INTEGER PRIMARY KEY, club_id INTEGER, student_id INTEGER, role TEXT);
        CREATE TABLE schema_comments(name TEXT PRIMARY KEY, description TEXT);
        """
    )

    # departments: 每个院系都有楼栋
    depts = ["计算机学院", "软件学院", "数学学院", "外国语学院", "经济管理学院", "机械工程学院"]
    con.executemany("INSERT INTO departments VALUES (?,?,?)",
                    [(i, n, f"{chr(64 + i)}栋") for i, n in enumerate(depts, 1)])

    # majors: 轮转分配保证每个院系 ≥1 个专业
    major_names = ["软件工程", "计算机科学与技术", "人工智能", "应用数学", "统计学",
                   "英语", "日语", "会计学", "金融学", "机械设计制造"]
    con.executemany("INSERT INTO majors VALUES (?,?,?)",
                    [(i, n, (i - 1) % 6 + 1) for i, n in enumerate(major_names, 1)])

    # students: 姓名/性别随机，专业轮转，年级 2022-2025，GPA 从不重复池采样
    gpas = sorted(rng.sample([x / 100 for x in range(200, 401)], 120), reverse=True)
    rng.shuffle(gpas)
    student_rows = []
    names = set()
    for i in range(1, 121):
        if i == 1:
            name = "陈志远"
        else:
            while True:
                name = rng.choice(SURNAMES) + rng.choice(GIVEN)
                if name not in names:
                    break
        names.add(name)
        grade = 2022 + (i - 1) % 4
        student_rows.append((i, name, rng.choice(["男", "女"]), (i - 1) % 10 + 1, grade, gpas[i - 1]))
    con.executemany("INSERT INTO students VALUES (?,?,?,?,?,?)", student_rows)

    # teachers: 轮转保证每个院系 ≥1 名
    titles = ["教授", "副教授", "讲师", "助教"]
    con.executemany("INSERT INTO teachers VALUES (?,?,?,?)",
                    [(i, rng.choice(SURNAMES) + rng.choice(GIVEN),
                      titles[(i - 1) % 4], (i - 1) % 6 + 1) for i in range(1, 31)])

    # courses: 每位教师 ≥1 门（前 30 门轮转），后 10 门随机；course 7 = 数据库原理（4 学分）
    course_names = ["数据库原理", "数据结构", "操作系统", "计算机网络", "机器学习",
                    "高等数学", "线性代数", "概率论", "大学英语", "商务英语",
                    "会计学原理", "金融市场", "机械制图", "软件工程导论", "编译原理",
                    "深度学习", "信息安全", "数值分析", "英国文学", "财务管理",
                    "工程力学", "算法设计", "Web开发", "移动应用开发", "大数据技术",
                    "云计算", "数字逻辑", "微机原理", "复变函数", "实变函数"]
    con.execute("INSERT INTO courses VALUES (7, '数据库原理', 4, 1, 7)")
    course_rows = []
    cid = 1
    while cid <= 40:
        if cid == 7:
            cid += 1
            continue
        name = course_names[(cid - 1) % len(course_names)]
        if cid > 30:
            name = name + f"（专题{cid - 30}）"
        course_rows.append((cid, name, rng.randint(1, 5), (cid - 1) % 6 + 1, (cid - 1) % 30 + 1))
        cid += 1
    con.executemany("INSERT INTO courses VALUES (?,?,?,?,?)", course_rows)

    # classrooms: 3 楼 × 4 间
    room_rows = []
    rid = 1
    for b in ["A栋", "B栋", "C栋"]:
        for r in range(101, 105):
            room_rows.append((rid, b, r, rng.choice([60, 80, 120, 200])))
            rid += 1
    con.executemany("INSERT INTO classrooms VALUES (?,?,?,?)", room_rows)

    # schedules: 60 条，每间教室 5 节（轮转）；保证周三第 2 节非空
    sched_rows = []
    for i in range(60):
        sched_rows.append((i + 1, (i % 40) + 1, (i % 12) + 1, (i % 5) + 1, (i % 4) + 1))
    con.execute("INSERT INTO schedules VALUES (61, 7, 3, 3, 2)")  # 周三第2节：数据库原理
    con.executemany("INSERT INTO schedules VALUES (?,?,?,?,?)", sched_rows)

    # enrollments: 每门课 15 条轮转（course 7 额外 1 条 = 16 → 选课人数 top 唯一），
    # student 1 强制 5 条；两学期都有 <60 的记录
    enroll_rows = []
    eid = 1
    for course in range(1, 41):
        for k in range(15):
            stu = ((course - 1) * 15 + k) % 120 + 1
            sem = "2025秋" if (course + k) % 2 == 0 else "2026春"
            score = rng.randint(40, 100)
            if score >= 60 and (course + k) % 17 == 0:
                score = rng.randint(35, 55)
            enroll_rows.append((eid, stu, course, sem, score))
            eid += 1
    # course 7 拿到 17 条（选课人数 top 唯一），student 1（陈志远）共 4 条
    con.execute("INSERT INTO enrollments VALUES (601, 88, 7, '2026春', 77)")
    con.execute("INSERT INTO enrollments VALUES (602, 1, 7, '2025秋', 92)")
    con.execute("INSERT INTO enrollments VALUES (603, 1, 2, '2025秋', 55)")
    con.execute("INSERT INTO enrollments VALUES (604, 1, 3, '2026春', 81)")
    con.execute("INSERT INTO enrollments VALUES (605, 1, 4, '2026春', 68)")
    con.executemany("INSERT INTO enrollments VALUES (?,?,?,?,?)", enroll_rows)

    # scholarships
    sch = [("国家奖学金", 8000), ("校一等奖学金", 3000), ("校二等奖学金", 2000),
           ("校三等奖学金", 1000), ("专项奖学金", 500)]
    con.executemany("INSERT INTO scholarships VALUES (?,?,?)", [(i, n, a) for i, (n, a) in enumerate(sch, 1)])

    # awards: student 5 恰 3 次（其中 2 次国家奖学金），其余学生 ≤2 次，两年都有
    award_rows = [(1, 5, 1, 2024), (2, 5, 1, 2025), (3, 5, 4, 2024)]
    aid, used = 4, {}
    while aid <= 40:
        stu = rng.randint(1, 120)
        if stu == 5 or used.get(stu, 0) >= 2:
            continue
        used[stu] = used.get(stu, 0) + 1
        award_rows.append((aid, stu, rng.randint(2, 5), rng.choice([2024, 2025])))
        aid += 1
    con.executemany("INSERT INTO scholarship_awards VALUES (?,?,?,?)", award_rows)

    # dormitories + rooms（每栋 10 间 × 4 床）+ 100 条分配
    con.executemany("INSERT INTO dormitories VALUES (?,?,?)",
                    [(i, f"{b}栋宿舍", 500) for i, b in enumerate(["A", "B", "C"], 1)])
    room_rows = [(i, (i - 1) % 3 + 1, 100 + i, 4) for i in range(1, 31)]
    con.executemany("INSERT INTO dorm_rooms VALUES (?,?,?,?)", room_rows)
    seen = set()
    assign_rows = []
    aid = 1
    while aid <= 100:
        stu, room = rng.randint(1, 120), rng.randint(1, 30)
        if stu in seen:
            continue
        seen.add(stu)
        assign_rows.append((aid, stu, room))
        aid += 1
    # 保证 A 栋（dormitory 1 → room 1-10）有住宿学生
    con.execute("INSERT INTO dorm_assignments VALUES (101, 1, 1)")
    con.executemany("INSERT INTO dorm_assignments VALUES (?,?,?)", assign_rows)

    # clubs: club 3 恰 30 名成员（成员数 top 唯一），每个社团恰 1 名社长
    clubs = [("开源软件协会", "学术", 2015), ("篮球社", "体育", 1998), ("动漫社", "文艺", 2003),
             ("吉他社", "文艺", 2005), ("辩论队", "学术", 1995), ("志愿者协会", "志愿", 2008),
             ("田径队", "体育", 2010), ("话剧社", "文艺", 2012)]
    con.executemany("INSERT INTO clubs VALUES (?,?,?,?)", [(i, n, c, y) for i, (n, c, y) in enumerate(clubs, 1)])
    member_rows = []
    mid = 1
    assigned = set()
    for club in range(1, 9):
        target = 30 if club == 3 else rng.randint(10, 20)
        count = 0
        while count < target:
            stu = rng.randint(1, 120)
            if (club, stu) in assigned:
                continue
            assigned.add((club, stu))
            member_rows.append((mid, club, stu, "成员"))
            mid += 1
            count += 1
    # 每社团 1 名社长（覆盖部分成员行）
    for club in range(1, 9):
        first_member = next(m[0] for m in member_rows if m[1] == club)
        member_rows[first_member - 1] = (first_member, club, member_rows[first_member - 1][2], "社长")
    con.executemany("INSERT INTO club_members VALUES (?,?,?,?)", member_rows)

    con.executemany("INSERT INTO schema_comments VALUES (?,?)", COMMENTS)
    con.commit()
    con.close()
    print(f"已生成 {DB}（15 表 + 注释）")


if __name__ == "__main__":
    main()
