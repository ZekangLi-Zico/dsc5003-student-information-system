"""Export flat CSV extracts of the database for Excel / LOAD DATA use.

Writes to output/:
    students.csv        one row per student
    enrolments.csv      one row per graded enrolment (with grade point joined)
    courses.csv         the 2026-27 catalogue
    recommendations.csv every engine recommendation with its rule id

CSVs are a convenience layer for people who want to open the data in a
spreadsheet; the SQLite file remains the authoritative deliverable.
"""
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C

QUERIES = {
    "students.csv": """
        SELECT v.student_id, v.name_en, v.name_zh, v.gender, v.date_of_birth, v.age,
               v.phone_hk, v.email, v.admission_year, v.year_of_study,
               v.programme_code, v.programme_name,
               g.cumulative_gpa, g.courses_taken, g.credits_passed, g.n_failed AS failed_attempts,
               (SELECT COUNT(*) FROM v_latest_enrolment x WHERE x.student_id=v.student_id AND x.is_passing=0) AS outstanding_courses
          FROM v_student_profile v
          LEFT JOIN v_student_gpa g ON g.student_id = v.student_id
         ORDER BY v.student_id""",
    "enrolments.csv": """
        SELECT e.student_id, s.name_en, s.programme_code, e.course_code,
               c.course_title, c.department, c.credits, c.course_level,
               e.academic_year, e.semester, e.grade, g.grade_point, e.is_repeat
          FROM Enrolment e
          JOIN Student s    ON s.student_id  = e.student_id
          JOIN Course c     ON c.course_code = e.course_code
          LEFT JOIN GradeScale g ON g.grade  = e.grade
         ORDER BY e.student_id, e.academic_year, e.semester, e.course_code""",
    "courses.csv": """
        SELECT course_code, course_title, department, credits,
               semester_offered, course_level, is_core
          FROM Course ORDER BY course_code""",
    "plan_courses.csv": """
        SELECT p.student_id, p.target_academic_year, p.target_semester,
               pc.position, pc.course_code, c.course_title, c.credits
          FROM StudyPlan p JOIN PlanCourse pc ON pc.plan_id=p.plan_id
          JOIN Course c ON c.course_code=pc.course_code
         ORDER BY p.student_id, p.target_academic_year, p.target_semester, pc.position""",
    "recommendations.csv": """
        SELECT r.rec_id, r.student_id, s.name_en, p.target_academic_year,
               p.target_semester, r.rec_type, r.course_code, r.rule_id,
               r.priority, r.source, r.model_risk_score,
               r.rationale_en, r.rationale_zh
          FROM Recommendation r
          JOIN StudyPlan p ON p.plan_id = r.plan_id
          JOIN Student s ON s.student_id = r.student_id
         ORDER BY r.student_id, r.priority, r.rec_id""",
}


def main():
    if not C.DB_PATH.exists():
        sys.exit("database missing - run build_database.py first")
    conn = sqlite3.connect(str(C.DB_PATH))
    conn.row_factory = sqlite3.Row
    for name, q in QUERIES.items():
        cursor = conn.execute(q)
        columns = [field[0] for field in cursor.description]
        rows = cursor.fetchall()
        path = C.OUTPUT_DIR / name
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(columns)
            for r in rows:
                w.writerow(list(r))
        print("  wrote %-22s %6d rows" % (name, len(rows)))
    conn.close()
    print("csv extracts complete")


if __name__ == "__main__":
    main()
