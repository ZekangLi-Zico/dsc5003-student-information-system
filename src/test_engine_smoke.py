"""Focused checks for retake completeness, chronological grades and model features."""
import sqlite3
import unittest

from recommendation_engine import Engine


class EnginePolicyTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE Student(student_id, name_en, name_zh, year_of_study, programme_code);
            CREATE TABLE Programme(programme_code, programme_name, primary_dept);
            CREATE TABLE Course(course_code, credits);
            CREATE TABLE GradeScale(grade, grade_point, is_passing);
            CREATE TABLE Enrolment(student_id,course_code,academic_year,semester,grade,is_repeat);
            INSERT INTO Student VALUES('S','Test','测试',2,'P');
            INSERT INTO Programme VALUES('P','Test','CS');
            INSERT INTO GradeScale VALUES('F',0,0),('D',1.0,1),('D+',1.3,1),('A',4.0,1);
        """)
        self.engine = Engine.__new__(Engine)
        self.engine.cur = self.conn.cursor()
        self.engine.target_year, self.engine.target_sem = "2026-27", 1
        self.engine.prog_courses = {"P": {}}
        self.engine.prereq = {}
        self.engine.grade_point = {"F":0.0,"D":1.0,"D+":1.3,"A":4.0}
        self.engine.is_passing = {"F":False,"D":True,"D+":True,"A":True}
        self.engine.course_stats = {}
        self.engine.quartile_cut = {}
        self.engine.model = None
        self.engine.course = {}
        for i in range(10):
            code = "C%d" % i
            self.conn.execute("INSERT INTO Course VALUES(?,6)", (code,))
            self.engine.course[code] = {"course_code": code, "course_title": code,
                "department":"CS", "credits":6, "course_level":1, "semester_offered":2 if i==0 else 0}

    def add(self, code, year, semester, grade):
        self.conn.execute("INSERT INTO Enrolment VALUES('S',?,?,?,?,0)", (code, year, semester, grade))

    def test_latest_graded_outcome_and_complete_retake_advice(self):
        for i in range(8):
            self.add("C%d" % i, "2024-25", 1, "F")
        self.add("C8", "2024-25", 1, "F")
        self.add("C8", "2025-26", 1, "D")
        self.add("C8", "2025-26", 2, None)
        self.add("C9", "2024-25", 2, "D+")
        self.add("C9", "2025-26", 1, "F")
        state = self.engine._student_state("S")
        self.assertEqual(state["passed"], {"C8"})
        advice = self.engine._r2_retakes(state)
        self.assertEqual(sorted(r["course_code"] for r in advice), ["C%d" % i for i in (*range(8),9)])
        deferred = next(r for r in advice if r["course_code"]=="C0")
        self.assertIn("not offered", deferred["rationale_en"])
        # Two passes among twelve graded attempts. Pending is excluded; the
        # first pass on C9 still contributes to GPA after the failing retake.
        self.assertEqual(state["gpa"], round((1.0 + 1.3) / 12, 3))
        self.engine.prog_courses["P"] = {"C2": ("CORE",1), "C3": ("CORE",1)}
        self.engine.prereq = {"C2": ["C8"], "C3": ["C9"]}
        self.assertEqual([r["course_code"] for r in self.engine._candidates(state)], ["C2"])

    def test_registered_courses_consume_slots_and_zero_pool_is_reported(self):
        for i in range(10):
            self.engine.course["C%d" % i]["semester_offered"] = 2
        empty = self.engine.plan_student("S", use_model=False)
        self.assertEqual(empty["recommended_courses"], [])
        self.assertIn("R1-SHORTFALL", {r["rule_id"] for r in empty["recs"]})
        self.engine.course["C1"]["semester_offered"] = 0
        self.add("C1","2024-25",1,"F")
        self.add("C1","2026-27",1,None)
        plan = self.engine.plan_student("S", use_model=False)
        self.assertEqual(plan["recommended_courses"], ["C1"])
        self.assertEqual(plan["recommended_credits"], 6)
        msg = next(r["rationale_en"] for r in plan["recs"] if r["rule_id"]=="R2")
        self.assertIn("already registered", msg)
        self.conn.execute("UPDATE Enrolment SET grade='D' WHERE academic_year='2026-27'")
        self.assertEqual(self.engine.plan_student("S", use_model=False)["n_retake"],0)

    def test_same_term_and_future_marks_do_not_enter_features(self):
        self.add("C0", "2024-25", 1, "A")
        self.add("C1", "2024-25", 2, "D")
        self.add("C2", "2024-25", 2, "F")
        X, y, terms, _ = self.engine._temporal_model_data()
        self.assertEqual(X[1][0], 4.0)
        self.assertEqual(X[2][1], 4.0)
        self.conn.execute("UPDATE Enrolment SET grade='A' WHERE semester=2")
        self.add("C5", "2026-27", 1, "A")
        X2, y2, terms2, _ = self.engine._temporal_model_data()
        self.assertEqual((X, terms), (X2, terms2))
        self.assertNotEqual(y, y2)


if __name__ == "__main__":
    unittest.main()
