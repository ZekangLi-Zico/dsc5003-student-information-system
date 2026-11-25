"""Student Information Management System — interactive CLI.

Standard library only (sqlite3), so it runs anywhere Python 3 does:
    python src/management_system.py            # interactive menu
    python src/management_system.py --demo     # scripted tour, no typing needed

The menu covers the full life cycle a student-records system needs:
    1  search students (id / name / programme / year)
    2  view one student: profile, transcript, GPA, programme rank
    3  view a student's next-semester plan and recommendations
    4  add a student
    5  update a student's contact details
    6  record or amend a grade
    7  cohort statistics by programme / year / grade band
    8  run an ad-hoc SQL query (read-only guard)
    9  regenerate all recommendations with the engine
    0  quit

Every write operation is committed immediately and reported with the number
of rows affected, so nothing happens silently.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C
from run_queries import course_review, saved_courses

W = 78


def rule(ch="="):
    return ch * W


def head(title):
    print("\n" + rule())
    print("  " + title)
    print(rule())


def print_course_review(reviews, term, selected=None):
    for passed, heading in [(False, "COURSES STILL UNPASSED"), (True, "PREVIOUS FAILURES NOW PASSED")]:
        found = [item for item in reviews if item["passed"] == passed]
        print("\n  %s (%d) — %s semester %d" % (heading, len(found), *term))
        for item in found:
            print("    %s  %s" % (item["course_code"], item["course_title"]))
            print("      Attempts: " + " / ".join(item["history"]))
            print("      Retake eligibility: " + item["availability"])
            if selected is not None and not passed:
                print("      In saved plan: " + ("Yes" if item["course_code"] in selected else "No"))


def table(rows, cols, maxw=None):
    """Print a simple aligned text table."""
    if not rows:
        print("  (no rows)")
        return
    maxw = maxw or {}
    widths = [len(c) for c in cols]
    for r in rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len("" if v is None else str(v)))
    widths = [min(w, maxw.get(cols[i], 40)) for i, w in enumerate(widths)]
    print("  " + " | ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in rows:
        cells = []
        for v, w in zip(r, widths):
            s = "" if v is None else str(v)
            cells.append((s[:w - 1] + "…") if len(s) > w else s.ljust(w))
        print("  " + " | ".join(cells))


class SIMS:
    def __init__(self, db_path=None):
        self.db = str(db_path or C.DB_PATH)
        if not Path(self.db).exists():
            sys.exit("database not found: %s\nrun: python src/build_database.py" % self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.cur = self.conn.cursor()

    def close(self):
        self.conn.close()

    # ---------------- helpers ----------------
    def q(self, sql, args=()):
        return self.cur.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        r = self.cur.execute(sql, args).fetchone()
        return r[0] if r else None

    # ---------------- 1. search ----------------
    def search(self, term=None, programme=None, year=None, limit=25):
        where, args = [], []
        if term:
            where.append("(s.student_id LIKE ? OR s.name_en LIKE ? OR s.name_zh LIKE ?"
                         " OR s.email LIKE ?)")
            like = "%" + term + "%"
            args += [like] * 4
        if programme:
            where.append("s.programme_code = ?")
            args.append(programme)
        if year:
            where.append("s.year_of_study = ?")
            args.append(int(year))
        sql = """SELECT s.student_id, s.name_en, s.name_zh, s.gender, s.year_of_study,
                        s.programme_code, p.programme_name, s.email, s.phone_hk,
                        g.cumulative_gpa AS gpa
                   FROM Student s
                   JOIN Programme p ON p.programme_code = s.programme_code
              LEFT JOIN v_student_gpa g ON g.student_id = s.student_id"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.student_id LIMIT ?"
        args.append(limit)
        rows = self.q(sql, args)
        head("SEARCH RESULTS  (%d rows, limit %d)" % (len(rows), limit))
        table([[r["student_id"], r["name_en"], r["name_zh"], r["gender"],
                r["year_of_study"], r["programme_code"],
                ("%.2f" % r["gpa"]) if r["gpa"] is not None else "pending", r["email"]] for r in rows],
              ["student_id", "name_en", "name_zh", "G", "Yr", "prog", "GPA", "email"],
              {"email": 34})
        return rows

    # ---------------- 2. student detail ----------------
    def show_student(self, sid):
        s = self.q("""SELECT v.*, s.date_of_birth, s.admission_year, s.gender
                        FROM v_student_profile v JOIN Student s ON s.student_id=v.student_id
                       WHERE v.student_id=?""", (sid,))
        if not s:
            print("  no such student: %s" % sid)
            return False
        s = s[0]
        head("STUDENT %s" % sid)
        print("  name (EN)      : %s" % s["name_en"])
        print("  name (ZH)      : %s" % s["name_zh"])
        print("  gender         : %s" % s["gender"])
        print("  date of birth  : %s   (age %d, derived at query time)"
              % (s["date_of_birth"], s["age"]))
        print("  phone          : %s" % s["phone_hk"])
        print("  email          : %s" % s["email"])
        print("  admitted       : %d" % s["admission_year"])
        print("  year of study  : %d" % s["year_of_study"])
        print("  programme      : %s (%s)" % (s["programme_name"], s["programme_code"]))

        g = self.q("""SELECT * FROM v_student_gpa WHERE student_id=?""", (sid,))
        r = self.q("""SELECT gpa_rank, programme_size, gpa_percentile_top
                        FROM v_programme_rank WHERE student_id=?""", (sid,))
        if g:
            g = g[0]
            print("\n  ACADEMIC STANDING")
            print("    graded attempts    : %d" % g["courses_taken"])
            print("    credits attempted  : %d" % g["credits_attempted"])
            print("    credits passed     : %d" % g["credits_passed"])
            print("    cumulative GPA     : %.3f" % g["cumulative_gpa"])
            print("    failed attempts (all terms): %d" % g["n_failed"])
            print("    last term on record: %s" % g["last_term"])
        if r:
            r = r[0]
            print("    rank in programme  : %d of %d  (top %.1f%%)"
                  % (r["gpa_rank"], r["programme_size"], r["gpa_percentile_top"]))

        print_course_review(course_review(self.conn, sid, C.NEXT_TERM), C.NEXT_TERM)
        print("\n  TRANSCRIPT")
        tr = self.q("""SELECT e.academic_year, e.semester, e.course_code, c.course_title,
                              c.credits, c.department, e.grade, gs.grade_point, e.is_repeat
                         FROM Enrolment e
                         JOIN Course c ON c.course_code=e.course_code
                    LEFT JOIN GradeScale gs ON gs.grade=e.grade
                        WHERE e.student_id=?
                     ORDER BY e.academic_year, e.semester, e.course_code""", (sid,))
        table([[r["academic_year"], r["semester"], r["course_code"], r["course_title"],
                r["department"], r["credits"], r["grade"] or "-",
                ("%.1f" % r["grade_point"]) if r["grade_point"] is not None else "-",
                "R" if r["is_repeat"] else ""] for r in tr],
              ["term", "sem", "code", "course_title", "dept", "cr", "grade", "pt", ""],
              {"course_title": 46})
        print("  (%d enrolments; R = repeat attempt)" % len(tr))
        return True

    # ---------------- 3. plan ----------------
    def show_plan(self, sid):
        p = self.q("""SELECT * FROM StudyPlan WHERE student_id=?
                       AND target_academic_year=? AND target_semester=?""", (sid, *C.NEXT_TERM))
        if not p:
            print("  no plan on record for %s — run menu option 9" % sid)
            return
        p = p[0]
        s = self.q("SELECT name_en, name_zh, programme_code, year_of_study"
                   " FROM Student WHERE student_id=?", (sid,))[0]
        head("NEXT-SEMESTER PLAN  %s  (%s %s)" % (sid, s["name_en"], s["name_zh"]))
        print("  target term        : %s semester %d" % (p["target_academic_year"],
                                                          p["target_semester"]))
        print("  cumulative GPA     : %.2f   band=%s   risk=%s"
              % (p["cumulative_gpa"], p["gpa_band"], p["risk_level"]))
        print("  credits completed  : %d" % p["credits_completed"])
        print("  suggested load     : %d courses (%d credits)"
              % (p["recommended_course_count"], p["recommended_credits"]))
        print("  advice entries     : retake=%d  extra_effort=%d  swap=%d"
              "  prereq_gap=%d  major_adjust=%d"
              % (p["n_retake"], p["n_extra_effort"], p["n_swap"],
                 p["n_prereq_gap"], p["need_major_adjustment"]))

        choices = saved_courses(self.conn, p["plan_id"])
        print("\n  SAVED COURSE LIST (%d)" % len(choices))
        table([[c["position"], c["course_code"], c["course_title"], c["credits"], c["status"]]
               for c in choices], ["#", "course", "title", "credits", "status"], {"title": 68})
        term = (p["target_academic_year"], p["target_semester"])
        print_course_review(course_review(self.conn, sid, term), term, {c["course_code"] for c in choices})
        lang = "both"
        recs = self.q("""SELECT rec_type, course_code, rule_id, priority, source,
                                rationale_en, rationale_zh, model_risk_score
                           FROM Recommendation WHERE plan_id=?
                         ORDER BY priority, CASE WHEN rec_type = 'RETAKES' THEN 0 ELSE 1 END,
                                  rec_type, course_code""", (p["plan_id"],))
        print("\n  RECOMMENDATIONS (%d)" % len(recs))
        for i, r in enumerate(recs, 1):
            print("  %2d. [%s] %s p%d %s%s"
                  % (i, r["rule_id"], r["rec_type"], r["priority"],
                     (r["course_code"] + " ") if r["course_code"] else "",
                     ("(model risk %.2f)" % r["model_risk_score"])
                     if r["model_risk_score"] is not None else ""))
            if lang in ("en", "both"):
                for line in _wrap(r["rationale_en"], W - 8):
                    print("      EN: " + line)
            if lang in ("zh", "both"):
                for line in _wrap(r["rationale_zh"], W - 8):
                    print("      中文: " + line)
            print()

    # ---------------- 4. add student ----------------
    def add_student(self):
        head("ADD STUDENT")
        print("  Press Enter to accept the default shown in [brackets].")
        sid = _ask("student_id (10 chars)", "")
        if not sid:
            nxt = self.one("SELECT MAX(CAST(SUBSTR(student_id,5) AS INTEGER)) FROM Student")
            sid = "3036%06d" % ((nxt or 0) + 1)
            print("  -> generated %s" % sid)
        if self.one("SELECT 1 FROM Student WHERE student_id=?", (sid,)):
            print("  ERROR: %s already exists" % sid)
            return
        name_en = _ask("name_en", "CHAN Tai Man")
        name_zh = _ask("name_zh", "陳大文")
        gender = _ask("gender (M/F/U)", "U").upper()[:1] or "U"
        dob = _ask("date_of_birth (YYYY-MM-DD)", "2006-09-01")
        phone = _ask("phone_hk (8 digits, 5-9 first)", "91234567")
        email = _ask("email", "%s@connect.hku.hk" % name_en.split()[0].lower())
        admit = int(_ask("admission_year", str(C.NEXT_YEAR)) or C.NEXT_YEAR)
        year = int(_ask("year_of_study (1-4)", "1"))
        progs = [r["programme_code"] for r in self.q("SELECT programme_code FROM Programme ORDER BY 1")]
        prog = _ask("programme_code %s" % progs, progs[0])
        try:
            self.cur.execute("""INSERT INTO Student (student_id, name_en, name_zh, gender,
                     date_of_birth, phone_hk, email, admission_year, year_of_study,
                     programme_code) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                             (sid, name_en, name_zh, gender, dob, phone, email,
                              admit, year, prog))
            self.conn.commit()
            print("  INSERTED 1 student: %s (%s)" % (sid, name_en))
        except sqlite3.Error as e:
            self.conn.rollback()
            print("  REJECTED by a constraint: %s" % e)
            print("  (check the phone pattern, email uniqueness/domain, year range,"
                  " and that the programme code exists)")

    # ---------------- 5. update contact ----------------
    def update_student(self):
        head("UPDATE STUDENT CONTACT DETAILS")
        sid = _ask("student_id", "")
        if not sid or not self.one("SELECT 1 FROM Student WHERE student_id=?", (sid,)):
            print("  no such student")
            return
        cur = self.q("SELECT * FROM Student WHERE student_id=?", (sid,))[0]
        phone = _ask("phone_hk [%s]" % cur["phone_hk"], "") or cur["phone_hk"]
        email = _ask("email [%s]" % cur["email"], "") or cur["email"]
        year = _ask("year_of_study [%d]" % cur["year_of_study"], "") or cur["year_of_study"]
        try:
            self.cur.execute("UPDATE Student SET phone_hk=?, email=?, year_of_study=?"
                             " WHERE student_id=?", (phone, email, int(year), sid))
            self.conn.commit()
            print("  UPDATED %d row(s) for %s" % (self.cur.rowcount, sid))
        except sqlite3.Error as e:
            self.conn.rollback()
            print("  REJECTED by a constraint: %s" % e)

    # ---------------- 6. record grade ----------------
    def record_grade(self):
        head("RECORD OR AMEND A GRADE")
        sid = _ask("student_id", "")
        if not self.one("SELECT 1 FROM Student WHERE student_id=?", (sid,)):
            print("  no such student")
            return
        rows = self.q("""SELECT academic_year, semester, course_code, grade
                           FROM Enrolment WHERE student_id=?
                        ORDER BY academic_year DESC, semester DESC""", (sid,))
        print("  existing enrolments:")
        table([[r["academic_year"], r["semester"], r["course_code"], r["grade"] or "-"]
               for r in rows[:12]], ["term", "sem", "code", "grade"])
        code = _ask("course_code", "")
        if not self.one("SELECT 1 FROM Course WHERE course_code=?", (code,)):
            print("  no such course")
            return
        ay = _ask("academic year", C.NEXT_TERM[0])
        semester = _ask("semester (1/2)", str(C.NEXT_SEM))
        if semester not in ("1", "2"):
            print("  enter semester 1 or 2")
            return
        sem = int(semester)
        grades = [r["grade"] for r in self.q(
            "SELECT grade FROM GradeScale ORDER BY grade_order DESC")]
        grade = _ask("grade %s (blank = pending)" % grades, "").strip().upper() or None
        if grade is not None and grade not in grades:
            print("  grade is not in the project grade scale")
            return
        try:
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                key = (sid, code, ay, sem)
                old = self.cur.execute("""SELECT grade FROM Enrolment WHERE student_id=?
                    AND course_code=? AND academic_year=? AND semester=?""", key).fetchone()
                if old is not None and grade == old["grade"]:
                    print("  grade unchanged")
                    return
                if old is None:
                    self.cur.execute("""INSERT INTO Enrolment
                        (student_id, course_code, academic_year, semester, grade, is_repeat)
                        VALUES (?,?,?,?,?,EXISTS (
                            SELECT 1 FROM Enrolment WHERE student_id=? AND course_code=?
                            AND (academic_year, semester) < (?,?)))""", (*key, grade, *key))
                    self.cur.execute("""UPDATE Enrolment SET is_repeat=1 WHERE student_id=?
                        AND course_code=? AND (academic_year, semester) > (?,?) AND is_repeat=0""", key)
                else:
                    self.cur.execute("""UPDATE Enrolment SET grade=? WHERE student_id=?
                        AND course_code=? AND academic_year=? AND semester=?""", (grade, *key))
                self.cur.execute("""DELETE FROM StudyPlan WHERE student_id=?
                          AND (target_academic_year, target_semester) >= (?,?)""", (sid, ay, sem))
                invalidated = self.cur.rowcount
            print("  SAVED %s for %s in %s semester %d" % (grade or "pending", code, ay, sem))
            if invalidated:
                print("  Cleared %d affected plan(s). Regenerate before reviewing the new plan."
                      % invalidated)
        except sqlite3.Error as e:
            print("  REJECTED: %s" % e)

    # ---------------- 7. statistics ----------------
    def statistics(self):
        head("COHORT STATISTICS")
        print("\n  BY PROGRAMME")
        table([[r["programme_code"], r["programme_name"], r["n_students"],
                "%.3f" % r["mean_gpa"], "%.2f" % r["min_gpa"], "%.2f" % r["max_gpa"],
                r["total_failures"], "%.1f" % r["mean_courses"]]
               for r in self.q("""SELECT p.programme_code, p.programme_name,
                        COUNT(DISTINCT s.student_id) n_students,
                        ROUND(AVG(g.cumulative_gpa),3) mean_gpa,
                        MIN(g.cumulative_gpa) min_gpa, MAX(g.cumulative_gpa) max_gpa,
                        SUM(g.n_failed) total_failures,
                        ROUND(AVG(g.courses_taken),1) mean_courses
                   FROM Programme p JOIN Student s ON s.programme_code=p.programme_code
                   JOIN v_student_gpa g ON g.student_id=s.student_id
               GROUP BY p.programme_code, p.programme_name
               ORDER BY mean_gpa DESC""")],
              ["code", "programme", "n", "mean GPA", "min", "max", "failed attempts", "courses"],
              {"programme": 34})

        print("\n  BY YEAR OF STUDY")
        table([[r["year_of_study"], r["n"], "%.3f" % r["mean_gpa"], r["n_failed"]]
               for r in self.q("""SELECT s.year_of_study, COUNT(*) n,
                        ROUND(AVG(g.cumulative_gpa),3) mean_gpa, SUM(g.n_failed) n_failed
                   FROM Student s JOIN v_student_gpa g ON g.student_id=s.student_id
               GROUP BY s.year_of_study ORDER BY s.year_of_study""")],
              ["year", "n", "mean GPA", "failed attempts"])

        print("\n  GRADE DISTRIBUTION (all enrolments)")
        tot = self.one("SELECT COUNT(*) FROM Enrolment WHERE grade IS NOT NULL")
        table([[r["grade"], r["n"], "%.1f%%" % (100.0 * r["n"] / tot), r["grade_point"]]
               for r in self.q("""SELECT e.grade, COUNT(*) n, g.grade_point
                   FROM Enrolment e JOIN GradeScale g ON g.grade=e.grade
               GROUP BY e.grade, g.grade_point, g.grade_order
               ORDER BY g.grade_order DESC""")],
              ["grade", "n", "share", "points"])

        print("\n  HARDEST COURSES (lowest mean grade point, n>=30)")
        table([[r["course_code"], r["course_title"], r["department"], r["n_taken"],
                "%.2f" % r["mean_grade_point"], "%.1f%%" % r["fail_rate_pct"]]
               for r in self.q("""SELECT * FROM v_course_stats WHERE n_taken>=30
                                  ORDER BY mean_grade_point ASC LIMIT 10""")],
              ["code", "course_title", "dept", "n", "mean pt", "fail"],
              {"course_title": 44})

        print("\n  RECOMMENDATION SUMMARY")
        table([[r["rec_type"], r["n"], r["n_students"]] for r in self.q(
            """SELECT rec_type, COUNT(*) n, COUNT(DISTINCT student_id) n_students
                 FROM Recommendation GROUP BY rec_type ORDER BY n DESC""")],
              ["rec_type", "rows", "students"])
        table([[r["risk_level"], r["n"]] for r in self.q(
            """SELECT risk_level, COUNT(*) n FROM StudyPlan
                GROUP BY risk_level ORDER BY CASE risk_level
                  WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END""")],
              ["risk_level", "students"])

    # ---------------- 8. ad-hoc SQL ----------------
    def adhoc(self):
        head("AD-HOC SQL (read-only)")
        print("  Only SELECT / WITH / PRAGMA statements are allowed.")
        print("  Type 'q' to return to the menu.")
        while True:
            sql = input("\n  sql> ").strip()
            if sql.lower() in ("q", "quit", "exit"):
                return
            if not sql:
                continue
            first = sql.split()[0].lower().rstrip(";")
            if first not in ("select", "with", "pragma", "explain"):
                print("  refused: only read-only statements are permitted here.")
                continue
            try:
                rows = self.q(sql)
                if not rows:
                    print("  (0 rows)")
                    continue
                cols = rows[0].keys()
                table([[r[c] for c in cols] for r in rows[:30]], list(cols))
                print("  %d row(s)%s" % (len(rows),
                      "" if len(rows) <= 30 else ", showing first 30"))
            except sqlite3.Error as e:
                print("  SQL error: %s" % e)

    # ---------------- 9. regenerate ----------------
    def regenerate(self):
        head("REGENERATE ALL RECOMMENDATIONS")
        print("  This runs the engine over every student and rewrites the")
        print("  StudyPlan and Recommendation tables. It takes a few seconds.")
        ans = _ask("  proceed? (y/N)", "n").lower()
        if ans not in ("y", "yes"):
            print("  cancelled")
            return
        from recommendation_engine import Engine
        eng = Engine(self.db)
        try:
            summary = eng.run_all(use_model=True)
        finally:
            eng.close()
        print("  done: %d students, %d recommendations"
              % (summary["n_students"], summary["n_recommendations"]))
        print("  by type:", summary["by_type"])
        if summary.get("model_auc") is not None:
            print("  held-out term AUC: %.3f" % summary["model_auc"])

    # ---------------- menu ----------------
    MENU = """
  1  search students            6  record / amend a grade
  2  view one student            7  cohort statistics
  3  view next-semester plan     8  ad-hoc SQL (read-only)
  4  add a student               9  regenerate recommendations
  5  update contact details      0  quit
"""

    def loop(self):
        head("STUDENT INFORMATION MANAGEMENT SYSTEM")
        print("  database : %s" % self.db)
        print("  students : %d   courses : %d   enrolments : %d   plans : %d"
              % (self.one("SELECT COUNT(*) FROM Student"),
                 self.one("SELECT COUNT(*) FROM Course"),
                 self.one("SELECT COUNT(*) FROM Enrolment"),
                 self.one("SELECT COUNT(*) FROM StudyPlan")))
        while True:
            print(self.MENU)
            ch = input("  choose> ").strip()
            if ch == "1":
                t = _ask("search term (id/name/email, blank=all)", "")
                p = _ask("programme code filter (blank=any)", "")
                y = _ask("year filter (blank=any)", "")
                self.search(t or None, p or None, y or None)
            elif ch == "2":
                sid = _ask("student_id", "")
                if sid:
                    self.show_student(sid)
            elif ch == "3":
                sid = _ask("student_id", "")
                if sid:
                    self.show_plan(sid)
            elif ch == "4":
                self.add_student()
            elif ch == "5":
                self.update_student()
            elif ch == "6":
                self.record_grade()
            elif ch == "7":
                self.statistics()
            elif ch == "8":
                self.adhoc()
            elif ch == "9":
                self.regenerate()
            elif ch in ("0", "q", "quit", "exit"):
                print("  bye")
                break
            else:
                print("  unknown option")

    # ---------------- scripted demo ----------------
    def demo(self):
        print("\n### scripted demo (equivalent to typing the menu choices)\n")
        self.search(limit=6)
        row = self.q("""SELECT s.student_id FROM Student s
                          JOIN v_student_gpa g ON g.student_id=s.student_id
                         WHERE g.n_failed > 0
                         ORDER BY g.cumulative_gpa ASC LIMIT 1""")
        sid = row[0]["student_id"] if row else "3036000001"
        self.show_student(sid)
        self.show_plan(sid)
        top = self.q("""SELECT student_id FROM v_student_gpa
                         ORDER BY cumulative_gpa DESC LIMIT 1""")[0]["student_id"]
        self.show_plan(top)
        self.statistics()


def _ask(prompt, default):
    try:
        v = input("  %s: " % prompt).strip()
    except EOFError:
        return default
    return v if v else default


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def main():
    ap = argparse.ArgumentParser(description="Student Information Management System")
    ap.add_argument("--demo", action="store_true", help="run a scripted tour")
    ap.add_argument("--db", help="database path (default: data/student_info.db)")
    a = ap.parse_args()
    app = SIMS(a.db)
    try:
        if a.demo:
            app.demo()
        else:
            app.loop()
    finally:
        app.close()


if __name__ == "__main__":
    main()
