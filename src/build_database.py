"""Build and verify the report database, or generate a fresh synthetic history.

Default report build:
    1. execute sql/schema_sqlite.sql          (tables, triggers, views)
    2. load Department/Programme/Course/Prerequisite/ProgrammeCourse/GradeScale
    3. reproduce the seeded student profiles and load the report's enrolment history
    4. ANALYZE so the query planner has statistics
    5. run the assertion battery

Use --generate for a separately generated synthetic cohort.
"""
import argparse
import csv
import random
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C
import course_catalogue as CC
import generate_data as G

SCHEMA = C.PROJECT_ROOT / "sql" / "schema_sqlite.sql"
REPORT_HISTORY = C.PROJECT_ROOT / "fixtures" / "enrolment-history.tsv"

FAILED = []


def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print("  [%s] %s%s" % (status, name, ("  — " + detail) if detail else ""))
    if not ok:
        FAILED.append(name)


def load(conn, *, generate=False):
    cur = conn.cursor()

    # schema (tables, triggers, views)
    print("executing schema ...")
    cur.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()

    # --- catalogue ---
    print("loading catalogue ...")
    cur.executemany(
        "INSERT INTO Course (course_code, course_title, department, credits,"
        " semester_offered, course_level, is_core)"
        " VALUES (:course_code, :course_title, :department, :credits,"
        " :semester_offered, :course_level, :is_core)",
        CC.CATALOGUE)

    pre_rows = [(c["course_code"], p) for c in CC.CATALOGUE for p in c["prerequisites"]]
    cur.executemany(
        "INSERT INTO Prerequisite (course_code, prereq_code) VALUES (?, ?)", pre_rows)

    # --- programme curriculum ---
    if generate:
        students, enrolments, pc_rows = G.generate_all()
    else:
        students = G.generate_students(random.Random(C.RANDOM_SEED), C.N_STUDENTS)
        pc_rows = G.PROGRAMME_COURSE_ROWS
        with REPORT_HISTORY.open(encoding="utf-8", newline="") as history:
            reader = csv.DictReader(history, delimiter="\t")
            enrolments = list(reader)
        if len(enrolments) != 15927:
            raise ValueError(f"Expected 15,927 report enrolments, found {len(enrolments):,}.")
    cur.executemany(
        "INSERT INTO ProgrammeCourse (programme_code, course_code,"
        " requirement_type, recommended_year)"
        " VALUES (:programme_code, :course_code, :requirement_type, :recommended_year)",
        pc_rows)

    # --- students ---
    print("loading %d students ..." % len(students))
    cur.executemany(
        "INSERT INTO Student (student_id, name_en, name_zh, gender, date_of_birth,"
        " phone_hk, email, admission_year, year_of_study, programme_code)"
        " VALUES (:student_id, :name_en, :name_zh, :gender, :date_of_birth,"
        " :phone_hk, :email, :admission_year, :year_of_study, :programme_code)",
        [{k: s[k] for k in ("student_id", "name_en", "name_zh", "gender",
                            "date_of_birth", "phone_hk", "email",
                            "admission_year", "year_of_study", "programme_code")}
         for s in students])

    # --- enrolments ---
    print("loading %d enrolments ..." % len(enrolments))
    cur.executemany(
        "INSERT INTO Enrolment (student_id, course_code, academic_year, semester,"
        " grade, is_repeat)"
        " VALUES (:student_id, :course_code, :academic_year, :semester,"
        " :grade, :is_repeat)",
        enrolments)

    conn.commit()
    cur.execute("ANALYZE")
    conn.commit()
    return students, enrolments, pc_rows


def verify(conn, students, enrolments, pc_rows):
    cur = conn.cursor()
    one = lambda q, *a: cur.execute(q, a).fetchone()[0]

    print("\n=== 1. ROW COUNTS ===")
    check("1000 students", one("SELECT COUNT(*) FROM Student") == 1000,
          "actual %d" % one("SELECT COUNT(*) FROM Student"))
    n_en = one("SELECT COUNT(*) FROM Enrolment")
    check("enrolments loaded", n_en == len(enrolments),
          "db %d vs generated %d" % (n_en, len(enrolments)))
    check("142 courses", one("SELECT COUNT(*) FROM Course") == len(CC.CATALOGUE),
          "actual %d" % one("SELECT COUNT(*) FROM Course"))
    check("prerequisite edges match", one("SELECT COUNT(*) FROM Prerequisite")
          == sum(len(c["prerequisites"]) for c in CC.CATALOGUE))
    grades = {grade: (point, bool(passed)) for grade, point, passed in
              cur.execute("SELECT grade, grade_point, is_passing FROM GradeScale")}
    check("numeric grade scale and pass flags match the generator",
          grades == {grade: (point, grade in C.PASSING_GRADES)
                     for grade, point in C.GRADE_SCALE.items()})
    check("4 programmes", one("SELECT COUNT(*) FROM Programme") == 4)
    check("programme-course rows match",
          one("SELECT COUNT(*) FROM ProgrammeCourse") == len(pc_rows))

    print("\n=== 2. REFERENTIAL INTEGRITY (no orphans) ===")
    check("no orphan enrolment.student_id", one(
        "SELECT COUNT(*) FROM Enrolment e WHERE NOT EXISTS"
        " (SELECT 1 FROM Student s WHERE s.student_id=e.student_id)") == 0)
    check("no orphan enrolment.course_code", one(
        "SELECT COUNT(*) FROM Enrolment e WHERE NOT EXISTS"
        " (SELECT 1 FROM Course c WHERE c.course_code=e.course_code)") == 0)
    check("no orphan student.programme_code", one(
        "SELECT COUNT(*) FROM Student s WHERE NOT EXISTS"
        " (SELECT 1 FROM Programme p WHERE p.programme_code=s.programme_code)") == 0)
    check("no orphan enrolment.grade", one(
        "SELECT COUNT(*) FROM Enrolment e WHERE e.grade IS NOT NULL AND NOT EXISTS"
        " (SELECT 1 FROM GradeScale g WHERE g.grade=e.grade)") == 0)
    check("no orphan prerequisite", one(
        "SELECT COUNT(*) FROM Prerequisite p WHERE NOT EXISTS"
        " (SELECT 1 FROM Course c WHERE c.course_code=p.prereq_code)") == 0)
    check("no orphan ProgrammeCourse", one(
        "SELECT COUNT(*) FROM ProgrammeCourse pc WHERE NOT EXISTS"
        " (SELECT 1 FROM Course c WHERE c.course_code=pc.course_code)") == 0)
    fk = cur.execute("PRAGMA foreign_key_check").fetchall()
    check("PRAGMA foreign_key_check clean", len(fk) == 0,
          "%d violations" % len(fk))

    print("\n=== 3. THE 4-6 COURSES PER SEMESTER RULE ===")
    bad = cur.execute(
        "SELECT COUNT(*) FROM (SELECT student_id, academic_year, semester,"
        " COUNT(*) n FROM Enrolment GROUP BY student_id, academic_year, semester"
        " HAVING n < ? OR n > ?)",
        (C.MIN_COURSES_PER_SEM, C.MAX_COURSES_PER_SEM)).fetchone()[0]
    check("every student-term has 4..6 courses", bad == 0, "%d violating terms" % bad)
    violations = one("SELECT COUNT(*) FROM v_enrolment_prereq_violation")
    check("all prerequisites were passed before the dependent term",
          violations == 0, "%d missing prerequisite records" % violations)
    dist = dict(cur.execute(
        "SELECT n, COUNT(*) FROM (SELECT COUNT(*) n FROM Enrolment"
        " GROUP BY student_id, academic_year, semester) GROUP BY n").fetchall())
    print("        distribution:", dict(sorted(dist.items())))
    n_terms = sum(dist.values())
    check("all students have >=1 completed term", one(
        "SELECT COUNT(*) FROM Student s WHERE NOT EXISTS"
        " (SELECT 1 FROM Enrolment e WHERE e.student_id=s.student_id)") == 0)

    print("\n=== 4. UNIQUE-KEY AND FORMAT CONSTRAINTS ===")
    check("student_id unique & 10 chars", one(
        "SELECT COUNT(*) FROM Student WHERE LENGTH(student_id)<>10") == 0
        and one("SELECT COUNT(DISTINCT student_id) FROM Student") == 1000)
    check("email unique", one(
        "SELECT COUNT(DISTINCT email) FROM Student") == 1000)
    check("email domain ok", one(
        "SELECT COUNT(*) FROM Student WHERE email NOT LIKE '%@connect.hku.hk'") == 0)
    check("phone is 8 digits starting 5-9", one(
        "SELECT COUNT(*) FROM Student WHERE phone_hk NOT GLOB"
        " '[56789][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'") == 0)
    check("gender in M/F/U", one(
        "SELECT COUNT(*) FROM Student WHERE gender NOT IN ('M','F','U')") == 0)
    check("year_of_study 1..4", one(
        "SELECT COUNT(*) FROM Student WHERE year_of_study NOT BETWEEN 1 AND 4") == 0)
    check("dob plausible (age 17..30)", one(
        "SELECT COUNT(*) FROM v_student_profile WHERE age<17 OR age>30") == 0,
        "min %s max %s" % cur.execute(
            "SELECT MIN(age), MAX(age) FROM v_student_profile").fetchone())
    check("no duplicate enrolment key", one(
        "SELECT COUNT(*) FROM (SELECT student_id, course_code, academic_year,"
        " semester FROM Enrolment GROUP BY 1,2,3,4 HAVING COUNT(*)>1)") == 0)

    print("\n=== 5. TRIGGERS ACTUALLY FIRE ===")
    # a) exceeding 6 courses in one term must be rejected
    sid, ay, sem, free = cur.execute("""
        SELECT t.student_id, t.academic_year, t.semester, c.course_code
        FROM (SELECT student_id, academic_year, semester FROM Enrolment
              GROUP BY student_id, academic_year, semester HAVING COUNT(*)=6) t
        JOIN Course c ON c.semester_offered IN (0, t.semester)
        WHERE NOT EXISTS
              (SELECT 1 FROM Prerequisite p WHERE p.course_code=c.course_code)
          AND NOT EXISTS (SELECT 1 FROM Enrolment e
              WHERE e.student_id=t.student_id AND e.course_code=c.course_code)
        LIMIT 1""").fetchone()
    try:
        cur.execute("INSERT INTO Enrolment (student_id, course_code,"
                    " academic_year, semester, grade) VALUES (?,?,?,?,?)",
                    (sid, free, ay, sem, "B"))
        check("trigger blocks a 7th course in a term", False, "insert was allowed")
        conn.rollback()
    except sqlite3.IntegrityError as e:
        check("trigger blocks a 7th course in a term",
              "more than 6 courses" in str(e), str(e)[:70])
        conn.rollback()
    # b) blank-string grade must be rejected
    try:
        cur.execute("INSERT INTO Enrolment (student_id, course_code, academic_year,"
                    " semester, grade) VALUES (?,?,?,?,?)", (sid, free, ay, sem, " "))
        check("trigger rejects blank grade", False, "insert was allowed")
        conn.rollback()
    except sqlite3.IntegrityError as e:
        check("trigger rejects blank grade", "valid GradeScale" in str(e), str(e)[:70])
        conn.rollback()
    # c) unknown grade must be rejected by the FK
    try:
        cur.execute("INSERT INTO Enrolment (student_id, course_code, academic_year,"
                    " semester, grade) VALUES (?,?,?,?,?)", (sid, free, "2099-00", sem, "Z+"))
        check("FK rejects an unknown grade", False, "insert was allowed")
        conn.rollback()
    except sqlite3.IntegrityError:
        check("FK rejects an unknown grade", True)
        conn.rollback()
    check("trigger tests left the data untouched",
          one("SELECT COUNT(*) FROM Enrolment") == n_en)

    print("\n=== 6. VIEWS WORK ===")
    check("v_student_profile returns 1000 rows",
          one("SELECT COUNT(*) FROM v_student_profile") == 1000)
    check("v_student_gpa returns rows", one("SELECT COUNT(*) FROM v_student_gpa") > 0,
          "%d" % one("SELECT COUNT(*) FROM v_student_gpa"))
    check("GPA within 0..4.3", one(
        "SELECT COUNT(*) FROM v_student_gpa WHERE cumulative_gpa<0"
        " OR cumulative_gpa>4.3") == 0)
    gpa = cur.execute("SELECT MIN(cumulative_gpa), AVG(cumulative_gpa),"
                      " MAX(cumulative_gpa) FROM v_student_gpa").fetchone()
    print("        cumulative GPA  min %.2f  mean %.2f  max %.2f" % gpa)
    check("v_programme_rank rank<=size for all", one(
        "SELECT COUNT(*) FROM v_programme_rank WHERE gpa_rank>programme_size") == 0)
    # percentile direction: rank 1 must be a SMALL top-percentile (~1/size),
    # the last rank must be ~100. An inverted formula flips these.
    p_first = one("""SELECT gpa_percentile_top FROM v_programme_rank
                      WHERE gpa_rank=1 AND programme_size>100 LIMIT 1""")
    p_last = one("""SELECT MAX(gpa_percentile_top) FROM v_programme_rank
                     WHERE gpa_rank=programme_size AND programme_size>100""")
    check("percentile direction correct (rank1 small, last ~100)",
          p_first is not None and p_first < 5 and p_last > 95,
          "rank1 top %.2f%%, last top %.2f%%" % (p_first or -1, p_last or -1))
    check("v_course_stats covers courses that were taken",
          one("SELECT COUNT(*) FROM v_course_stats") > 0,
          "%d courses" % one("SELECT COUNT(*) FROM v_course_stats"))
    check("v_prereq_gap runs", True,
          "%d gap rows" % one("SELECT COUNT(*) FROM v_prereq_gap"))

    print("\n=== 7. DOMAIN SANITY (what the engine will reason about) ===")
    gd = dict(cur.execute("SELECT grade, COUNT(*) FROM Enrolment GROUP BY grade").fetchall())
    tot = sum(gd.values())
    print("        grade distribution:",
          {g: "%.1f%%" % (100 * gd.get(g, 0) / tot) for g in C.GRADE_SCALE})
    n_fail_stu = one("SELECT COUNT(DISTINCT student_id) FROM Enrolment WHERE grade='F'")
    check("some students have a failure (engine has work to do)", n_fail_stu >= 30,
          "%d students" % n_fail_stu)
    check("retakes present in the data",
          one("SELECT COUNT(*) FROM Enrolment WHERE is_repeat=1") > 0,
          "%d repeat rows" % one("SELECT COUNT(*) FROM Enrolment WHERE is_repeat=1"))
    check("prerequisite gaps exist for planning",
          one("SELECT COUNT(*) FROM v_prereq_gap") > 0)
    by_prog = cur.execute(
        "SELECT s.programme_code, COUNT(DISTINCT s.student_id),"
        " ROUND(AVG(g.cumulative_gpa),3) FROM Student s"
        " JOIN v_student_gpa g ON g.student_id=s.student_id"
        " GROUP BY s.programme_code ORDER BY s.programme_code").fetchall()
    print("        by programme (code, n, mean GPA):")
    for r in by_prog:
        print("          %s  n=%-4d  GPA %.3f" % r)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true",
                        help="generate new synthetic enrolments instead of restoring the report cohort")
    args = parser.parse_args()
    with TemporaryDirectory(dir=C.DATA_DIR) as work:
        fresh = Path(work) / C.DB_PATH.name
        conn = sqlite3.connect(str(fresh))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            students, enrolments, pc_rows = load(conn, generate=args.generate)
            verify(conn, students, enrolments, pc_rows)
        finally:
            conn.close()
        if FAILED:
            raise SystemExit("Fresh database failed verification: " + ", ".join(FAILED))
        fresh.replace(C.DB_PATH)

    size_kb = C.DB_PATH.stat().st_size / 1024
    print("\n=== RESULT ===")
    print("database : %s (%.1f KB)" % (C.DB_PATH, size_kb))
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
