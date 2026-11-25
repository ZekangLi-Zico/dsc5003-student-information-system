"""Execute sql/queries.sql against the built database and print results.

The file is split on the "-- [Qnn]" markers so each query runs separately
and gets its own labelled output. Any query that raises is reported with the
SQLite error message rather than aborting the run, so one bad statement
cannot hide the state of the others.

Usage:
    python run_queries.py            # run every query, short preview
    python run_queries.py Q27 Q28    # run only the named queries
    python run_queries.py --rows 20  # show up to 20 rows per query
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C

QUERIES_FILE = C.PROJECT_ROOT / "sql" / "queries.sql"
MARKER = re.compile(r"^--\s*\[(Q\d+)\]\s*(.*)$")


def parse(sql_text):
    """Split the file into [(qid, title, sql), ...]."""
    out = []
    qid = title = None
    buf = []
    for line in sql_text.splitlines():
        m = MARKER.match(line)
        if m:
            if qid:
                out.append((qid, title, "\n".join(buf).strip()))
            qid, title, buf = m.group(1), m.group(2).strip(), []
            # keep the comment line so the executed SQL stays self-documenting
            buf.append(line)
        elif qid:
            buf.append(line)
    if qid:
        out.append((qid, title, "\n".join(buf).strip()))
    return out


def course_review(conn, student_id, target_term):
    """Show every course with a failed attempt and its latest graded outcome."""
    target_year, target_semester = target_term
    rows = conn.execute("""
        SELECT e.course_code, c.course_title, e.academic_year, e.semester, e.grade,
               latest.is_passing, c.semester_offered, c.course_level, s.year_of_study
          FROM Enrolment e
          JOIN Course c ON c.course_code = e.course_code
          JOIN Student s ON s.student_id = e.student_id
          JOIN v_latest_enrolment latest
            ON latest.student_id = e.student_id AND latest.course_code = e.course_code
         WHERE e.student_id = ? AND EXISTS (
               SELECT 1 FROM Enrolment f JOIN GradeScale gs ON gs.grade = f.grade
                WHERE f.student_id = e.student_id AND f.course_code = e.course_code
                  AND gs.is_passing = 0)
         ORDER BY latest.is_passing, e.course_code, e.academic_year, e.semester
    """, (student_id,))
    missing = {}
    for code, prereq in conn.execute("""
            SELECT pr.course_code, pr.prereq_code FROM Prerequisite pr
              JOIN v_latest_enrolment latest
                ON latest.course_code = pr.course_code AND latest.student_id = ?
         LEFT JOIN v_latest_enrolment previous
                ON previous.student_id = latest.student_id
               AND previous.course_code = pr.prereq_code
             WHERE latest.is_passing = 0 AND COALESCE(previous.is_passing, 0) = 0
             ORDER BY pr.course_code, pr.prereq_code""", (student_id,)):
        missing.setdefault(code, []).append(prereq)
    courses = {}
    for code, title, year, sem, grade, passed, offered, level, study_year in rows:
        if code not in courses:
            reasons = []
            if offered not in (0, target_semester):
                reasons.append("not offered in semester %d" % target_semester)
            if code in missing:
                reasons.append("missing " + ", ".join(missing[code]))
            if level > study_year + 1:
                reasons.append("exceeds the planning year-level limit")
            availability = "Eligible" if not reasons else "Deferred: " + "; ".join(reasons)
            courses[code] = {"course_code": code, "course_title": title, "passed": bool(passed),
                             "availability": "Already passed" if passed else availability,
                             "history": []}
        courses[code]["history"].append("%s S%d: %s" % (year, sem, grade or "pending"))
        if (year, sem) == (target_year, target_semester) and not passed:
            courses[code]["availability"] = "Already enrolled this term" + (" (grade pending)" if grade is None else "")
    return list(courses.values())


def saved_courses(conn, plan_id):
    """Read the course choices persisted with this plan, in their saved order."""
    return [dict(row) for row in conn.execute("""
        SELECT pc.position, c.course_code, c.course_title, c.department, c.credits,
               CASE WHEN e.course_code IS NULL THEN 'Suggested' ELSE 'Registered' END AS status
          FROM PlanCourse pc JOIN Course c ON c.course_code = pc.course_code
          JOIN StudyPlan p ON p.plan_id = pc.plan_id
          LEFT JOIN Enrolment e ON e.student_id = p.student_id AND e.course_code = pc.course_code
             AND e.academic_year = p.target_academic_year AND e.semester = p.target_semester
         WHERE pc.plan_id = ? ORDER BY pc.position""", (plan_id,))]


def run_one(cur, qid, title, sql, max_rows):
    print("\n" + "=" * 78)
    print("[%s] %s" % (qid, title))
    print("=" * 78)
    try:
        cur.execute(sql)
    except sqlite3.Error as e:
        print("  SQL ERROR: %s" % e)
        return False, 0
    if cur.description is None:
        print("  (no result set)")
        return True, 0
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print("  columns: %s" % ", ".join(cols))
    print("  rows returned: %d%s" % (len(rows),
          "" if len(rows) <= max_rows else "  (showing first %d)" % max_rows))
    if not rows:
        print("  (empty result)")
        return True, 0
    widths = [len(c) for c in cols]
    shown = rows[:max_rows]
    for r in shown:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(str(v)) if v is not None else 4)
    widths = [min(w, 34) for w in widths]
    print("  " + " | ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in shown:
        cells = []
        for v, w in zip(r, widths):
            s = "NULL" if v is None else str(v)
            cells.append(s[:w].ljust(w))
        print("  " + " | ".join(cells))
    return True, len(rows)


def main():
    args = sys.argv[1:]
    max_rows = 8
    only = []
    i = 0
    while i < len(args):
        if args[i] == "--rows":
            max_rows = int(args[i + 1])
            i += 2
        else:
            only.append(args[i].upper())
            i += 1

    if not C.DB_PATH.exists():
        print("database not found:", C.DB_PATH)
        print("run:  python build_database.py")
        sys.exit(1)

    sql_text = QUERIES_FILE.read_text(encoding="utf-8")
    queries = parse(sql_text)
    if only:
        queries = [q for q in queries if q[0] in only]

    print("database : %s" % C.DB_PATH)
    print("query file: %s" % QUERIES_FILE)
    print("parsed %d queries%s" % (len(queries),
          (" (filtered: %s)" % ", ".join(only)) if only else ""))

    conn = sqlite3.connect(str(C.DB_PATH))
    cur = conn.cursor()
    n_ok = n_err = n_empty = 0
    results = []
    try:
        for qid, title, sql in queries:
            ok, n = run_one(cur, qid, title, sql, max_rows)
            if ok:
                n_ok += 1
                if n == 0:
                    n_empty += 1
            else:
                n_err += 1
            results.append((qid, ok, n))
    finally:
        conn.close()

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print("  executed OK : %d" % n_ok)
    print("  SQL errors  : %d" % n_err)
    print("  empty results: %d  (Q34, Q35, Q36 and Q38 list exceptions; Q37 returns counts)" % n_empty)
    if n_err:
        print("\n  FAILING:")
        for qid, ok, n in results:
            if not ok:
                print("    -", qid)
        sys.exit(1)
    print("\n  ALL QUERIES EXECUTED WITHOUT ERROR")


if __name__ == "__main__":
    main()
