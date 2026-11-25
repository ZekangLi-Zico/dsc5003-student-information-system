"""Verify persisted engine output and diagnose the MAJOR_ADJUST rule.

Checks:
  1. StudyPlan has exactly one row per student for the target term
  2. Recommendation rows are all attached to a real plan (no orphans)
  3. rule_id is never empty and every rec_type is in the CHECK list
  4. bilingual rationale is present on every row
  5. recommended_course_count is within 4..6 (or the recorded shortfall)
  6. DIAGNOSTIC: why MAJOR_ADJUST fires for so few students — print the
     distribution of the in-dept vs out-of-dept gap so the threshold can be
     judged rather than guessed.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C
from recommendation_engine import (DEPT_GAP_THRESHOLD, DEPT_MIN_COURSES,
                                   Engine)

FAILED = []


def check(name, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  — " + detail) if detail else ""))
    if not ok:
        FAILED.append(name)


def main():
    FAILED.clear()
    conn = sqlite3.connect(str(C.DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    one = lambda q, *a: cur.execute(q, a).fetchone()[0]

    print("=== 1. PERSISTED PLANS ===")
    n_plans = one("SELECT COUNT(*) FROM StudyPlan WHERE (target_academic_year,target_semester)=(?,?)",
                  *C.NEXT_TERM)
    check("one plan per student for the target term", n_plans == one("SELECT COUNT(*) FROM Student"),
          "%d plans" % n_plans)
    totals = cur.execute("""
        SELECT p.plan_id,p.recommended_course_count,p.recommended_credits,
               COUNT(pc.course_code) AS stored,COALESCE(SUM(c.credits),0) AS credits,
               COALESCE(MIN(pc.position),0) AS first,COALESCE(MAX(pc.position),0) AS last,
               EXISTS(SELECT 1 FROM Recommendation r
                      WHERE r.plan_id=p.plan_id AND r.rule_id='R1-SHORTFALL') AS short
          FROM StudyPlan p LEFT JOIN PlanCourse pc USING(plan_id)
          LEFT JOIN Course c USING(course_code) GROUP BY p.plan_id""").fetchall()
    differences = [r["plan_id"] for r in totals
                   if r["stored"] != r["recommended_course_count"]
                   or r["credits"] != r["recommended_credits"]
                   or r["last"] != r["stored"] or (r["stored"] and r["first"] != 1)
                   or r["stored"] > C.MAX_COURSES_PER_SEM
                   or (r["stored"] < C.MIN_COURSES_PER_SEM and not r["short"])]
    check("scheduled courses, order, load and credits agree for every plan",
          not differences, "%d inconsistent plans" % len(differences))
    print("        load distribution:", dict(cur.execute(
        "SELECT recommended_course_count,count(*) FROM StudyPlan GROUP BY 1 ORDER BY 1")))

    print("\n=== 2. PERSISTED RECOMMENDATIONS ===")
    n_recs = one("SELECT COUNT(*) FROM Recommendation")
    print("        total recommendations:", n_recs)
    check("no orphan recommendations", one(
        "SELECT COUNT(*) FROM Recommendation r WHERE NOT EXISTS"
        " (SELECT 1 FROM StudyPlan p WHERE p.plan_id=r.plan_id)") == 0)
    check("rule_id never empty", one(
        "SELECT COUNT(*) FROM Recommendation WHERE rule_id IS NULL OR TRIM(rule_id)=''") == 0)
    check("rec_type all valid", one("""
        SELECT COUNT(*) FROM Recommendation WHERE rec_type NOT IN
        ('COURSE_LOAD','RETAKES','EXTRA_EFFORT','SWAP_COURSE','MAJOR_ADJUST','PREREQ_GAP')""") == 0)
    check("every rec has EN rationale", one(
        "SELECT COUNT(*) FROM Recommendation WHERE rationale_en IS NULL"
        " OR TRIM(rationale_en)=''") == 0)
    check("every rec has ZH rationale", one(
        "SELECT COUNT(*) FROM Recommendation WHERE rationale_zh IS NULL"
        " OR TRIM(rationale_zh)=''") == 0)
    check("course_code FK valid where present", one("""
        SELECT COUNT(*) FROM Recommendation r WHERE r.course_code IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code=r.course_code)""") == 0)
    print("        by rule_id:", dict(cur.execute(
        "SELECT rule_id, COUNT(*) FROM Recommendation GROUP BY rule_id"
        " ORDER BY COUNT(*) DESC").fetchall()))
    print("        by source :", dict(cur.execute(
        "SELECT source, COUNT(*) FROM Recommendation GROUP BY source").fetchall()))

    print("\n=== 3. NO CONTRADICTORY ADVICE ===")
    # the same course must not be both "retake" and "swap" for one student
    n_conflict = one("""
        SELECT COUNT(*) FROM Recommendation a
          JOIN Recommendation b
            ON b.plan_id=a.plan_id AND b.course_code=a.course_code
         WHERE a.rec_type='RETAKES' AND b.rec_type='SWAP_COURSE'""")
    check("no course is both RETAKE and SWAP", n_conflict == 0, "%d conflicts" % n_conflict)

    print("\n=== 4. DIAGNOSTIC: why so few MAJOR_ADJUST? ===")
    eng = Engine()
    gaps = []
    eligible = 0
    for r in cur.execute("SELECT student_id FROM Student"):
        st = eng._student_state(r["student_id"])
        if len(st["in_dept"]) >= DEPT_MIN_COURSES and st["out_dept"]:
            eligible += 1
            m_in = sum(st["in_dept"]) / len(st["in_dept"])
            m_out = sum(st["out_dept"]) / len(st["out_dept"])
            gaps.append(m_in - m_out)
    gaps.sort()
    print("        students with enough in-dept history: %d / 1000" % eligible)
    if gaps:
        import statistics
        print("        dept_gap  min %.2f  p10 %.2f  median %.2f  p90 %.2f  max %.2f"
              % (gaps[0], gaps[len(gaps)//10], statistics.median(gaps),
                 gaps[len(gaps)*9//10], gaps[-1]))
        for thr in (-1.0, -0.8, -0.6, -0.5, -0.4, -0.3):
            print("        threshold %+.2f -> %4d students flagged (%.1f%%)"
                  % (thr, sum(1 for g in gaps if g < thr),
                     100.0 * sum(1 for g in gaps if g < thr) / len(gaps)))
    print("        current DEPT_GAP_THRESHOLD = %.2f, DEPT_MIN_COURSES = %d"
          % (DEPT_GAP_THRESHOLD, DEPT_MIN_COURSES))
    n_flagged = one("SELECT COUNT(*) FROM Recommendation WHERE rec_type='MAJOR_ADJUST'")
    print("        currently flagged: %d" % n_flagged)
    eng.close()
    conn.close()

    print("\n=== RESULT ===")
    if FAILED:
        print("FAILED: %d" % len(FAILED))
        for f in FAILED:
            print("   -", f)
        sys.exit(1)
    print("ALL PERSISTENCE CHECKS PASSED")


if __name__ == "__main__":
    main()
