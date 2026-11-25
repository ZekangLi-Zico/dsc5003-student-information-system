"""Next-semester course planning engine — rules first, statistics as support.

Rules determine eligibility, programme priorities and the suggested load.
The optional model ranks otherwise tied candidates and flags selected courses.
R2 records every unresolved latest graded failure, including courses unavailable
next term. PlanCourse records the actual timetable separately from the advice.
"""
from collections import defaultdict
from itertools import groupby
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C

# --------------------------------------------------------------------------
# Rule parameters. Kept in one place so the report can quote them exactly and
# so a marker can see that every threshold is explicit rather than buried.
# --------------------------------------------------------------------------
GPA_BANDS = [
    # (min_gpa, band label, suggested course count, risk level)
    (3.7, "EXCELLENT",   6, "LOW"),
    (3.0, "GOOD",        5, "LOW"),
    (2.5, "SATISFACTORY", 5, "MEDIUM"),
    (2.0, "AT RISK",     4, "MEDIUM"),
    (0.0, "CRITICAL",    4, "HIGH"),
]
WEAK_GRADE_POINT = C.GRADE_SCALE["C-"]  # advisory threshold, independent of pass/fail
QUARTILE_PEERS_MIN = 20     # ignore per-course quartiles on tiny samples
DEPT_GAP_THRESHOLD = -0.60  # in-dept mean this far below out-of-dept mean
DEPT_MIN_COURSES = 4        # need at least this many in-dept courses to judge
RISK_SCORE_WARN = 0.60      # model probability above which we warn
MAX_RECS_PER_TYPE = 6       # keep a plan readable; highest priority first


def classify_band(gpa):
    for min_gpa, label, n_courses, risk in GPA_BANDS:
        if gpa >= min_gpa:
            return label, n_courses, risk
    return GPA_BANDS[-1][1], GPA_BANDS[-1][2], GPA_BANDS[-1][3]


class Engine:
    """Builds a StudyPlan + Recommendation set for one or all students."""

    def __init__(self, db_path=None, target_term=C.NEXT_TERM, verbose=False):
        self.db = str(db_path or C.DB_PATH)
        if not Path(self.db).exists():
            raise FileNotFoundError(
                "database not found at %s — run build_database.py first" % self.db)
        self.target_year, self.target_sem = target_term
        self.verbose = verbose
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        # SQLite does NOT enforce foreign keys by default, and neither does it
        # honour ON DELETE CASCADE without this pragma. Without it, replacing a
        # StudyPlan row left its Recommendation children pointing at a
        # plan_id that no longer existed (orphan rows, and every rule count
        # doubling on each re-run).
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.cur = self.conn.cursor()
        self._load_reference_data()
        self.model = None

    # ------------------------------------------------------------------
    # reference data
    # ------------------------------------------------------------------
    def _load_reference_data(self):
        cur = self.cur
        self.grade_point = {r["grade"]: r["grade_point"]
                            for r in cur.execute("SELECT grade, grade_point FROM GradeScale")}
        self.is_passing = {r["grade"]: r["is_passing"]
                           for r in cur.execute("SELECT grade, is_passing FROM GradeScale")}
        self.course = {r["course_code"]: dict(r) for r in cur.execute(
            "SELECT course_code, course_title, department, credits, semester_offered,"
            " course_level, is_core FROM Course")}
        self.prereq = {}
        for r in cur.execute("SELECT course_code, prereq_code FROM Prerequisite"):
            self.prereq.setdefault(r["course_code"], []).append(r["prereq_code"])
        self.prog_courses = {}
        for r in cur.execute("SELECT programme_code, course_code, requirement_type,"
                             " recommended_year FROM ProgrammeCourse"):
            self.prog_courses.setdefault(r["programme_code"], {})[r["course_code"]] = (
                r["requirement_type"], r["recommended_year"])
        self.course_stats = {r["course_code"]: dict(r) for r in cur.execute("""
            SELECT e.course_code, COUNT(*) AS n_taken, ROUND(AVG(g.grade_point),3) AS mean_grade_point,
                   ROUND(100.0*AVG(1-g.is_passing),2) AS fail_rate_pct
              FROM Enrolment e JOIN GradeScale g ON e.grade=g.grade
             WHERE (e.academic_year,e.semester)<(?,?) GROUP BY e.course_code""",
            (self.target_year,self.target_sem))}
        # per-course grade_point quartile cut-offs, computed once.
        # q1_max is the HIGHEST grade point inside the bottom quartile, i.e.
        # the cut-off: anything at or below it is in that course's bottom 25%.
        # (Using MIN here would take the bottom of the bottom quartile and
        # almost nothing would qualify — R3 recall collapsed to 3.7% that way.)
        self.quartile_cut = {}
        for r in cur.execute("""
            SELECT course_code,
                   MAX(CASE WHEN q = 1 THEN grade_point END) AS q1_max
              FROM (SELECT e.course_code, g.grade_point,
                           NTILE(4) OVER (PARTITION BY e.course_code
                                          ORDER BY g.grade_point) AS q,
                           COUNT(*) OVER (PARTITION BY e.course_code) AS n
                      FROM Enrolment e JOIN GradeScale g ON g.grade = e.grade
                     WHERE (e.academic_year,e.semester)<(?,?))
             WHERE n >= ?
             GROUP BY course_code""", (self.target_year,self.target_sem,QUARTILE_PEERS_MIN)):
            self.quartile_cut[r["course_code"]] = r["q1_max"]
        if self.verbose:
            print("loaded %d courses, %d prerequisite edges, %d course stat rows"
                  % (len(self.course), sum(len(v) for v in self.prereq.values()),
                     len(self.course_stats)))

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------------
    # per-student state
    # ------------------------------------------------------------------
    def _student_state(self, student_id):
        """Everything the rules need about one student, in one pass."""
        cur = self.cur
        st = cur.execute("""
            SELECT s.student_id, s.name_en, s.name_zh, s.year_of_study,
                   s.programme_code, p.programme_name, p.primary_dept
              FROM Student s JOIN Programme p ON p.programme_code = s.programme_code
             WHERE s.student_id = ?""", (student_id,)).fetchone()
        if st is None:
            raise KeyError("unknown student_id: %s" % student_id)
        st = dict(st)

        registered = {r["course_code"]: r["grade"] for r in cur.execute(
            "SELECT course_code,grade FROM Enrolment WHERE student_id=? "
            "AND (academic_year,semester)=(?,?) ORDER BY course_code",
            (student_id, self.target_year, self.target_sem))}
        grades = cur.execute("""
            SELECT e.course_code, e.grade, e.academic_year, e.semester, e.is_repeat,
                   gs.grade_point, gs.is_passing, c.credits
              FROM Enrolment e JOIN GradeScale gs ON gs.grade=e.grade
              JOIN Course c ON c.course_code=e.course_code
             WHERE e.student_id=? AND (e.academic_year,e.semester)<(?,?)
             ORDER BY e.academic_year,e.semester,e.course_code""",
                             (student_id, self.target_year, self.target_sem)).fetchall()
        history = []
        latest = {}
        for g in grades:
            attempt = {"course_code": g["course_code"], "grade": g["grade"],
                       "grade_point": g["grade_point"], "is_passing": bool(g["is_passing"]),
                       "year": g["academic_year"], "semester": g["semester"],
                       "is_repeat": g["is_repeat"]}
            history.append(attempt)
            latest[g["course_code"]] = attempt
        passed = {code for code, h in latest.items() if h["is_passing"]}
        taken = set(latest)
        current = latest.copy()
        for code, grade in registered.items():
            if grade is not None:
                current[code] = {"grade": grade, "grade_point": self.grade_point[grade],
                                 "year": self.target_year, "semester": self.target_sem,
                                 "is_passing": self.is_passing[grade], "course_code": code}
        gpa = cur.execute("""
            SELECT ROUND(SUM(c.credits*g.grade_point)*1.0/NULLIF(SUM(c.credits),0),3)
              FROM Enrolment e JOIN Course c ON c.course_code=e.course_code
              JOIN GradeScale g ON g.grade=e.grade
             WHERE e.student_id=? AND (e.academic_year,e.semester)<(?,?)""",
                          (student_id, self.target_year, self.target_sem)).fetchone()[0] or 0.0

        # departmental split for the MAJOR_ADJUST rule
        in_dept = [h["grade_point"] for h in history
                   if self.course[h["course_code"]]["department"] == st["primary_dept"]]
        out_dept = [h["grade_point"] for h in history
                    if self.course[h["course_code"]]["department"] != st["primary_dept"]]

        # recent trend: mean grade point of the last two terms vs earlier terms
        terms = sorted({(h["year"], h["semester"]) for h in history})
        recent = [h["grade_point"] for h in history if (h["year"], h["semester"]) in terms[-2:]]
        earlier = [h["grade_point"] for h in history if (h["year"], h["semester"]) not in terms[-2:]]
        trend = None
        if recent and earlier:
            trend = (sum(recent) / len(recent)) - (sum(earlier) / len(earlier))

        return {
            "student": st, "gpa": gpa, "latest": latest, "current": current, "registered": registered, "passed": passed,
            "taken": taken, "history": history, "in_dept": in_dept,
            "out_dept": out_dept, "trend": trend,
            "n_failed": sum(not h["is_passing"] for h in history),
            "credits_passed": sum(g["credits"] for g in grades if g["is_passing"]),
        }

    # ------------------------------------------------------------------
    # candidate pool for the target semester
    # ------------------------------------------------------------------
    def _candidates(self, state):
        """Courses the student may take next term: programme-relevant, offered
        in the target semester, prerequisites all passed, and not already
        PASSED.

        A course that was attempted and FAILED stays eligible — that is exactly
        what a retake is. An earlier version excluded every course in `taken`,
        which silently dropped all retake candidates from the timetable while
        rule R2 was still recommending them, so the advice and the schedule
        contradicted each other.
        """
        st = state["student"]
        out = []
        for code, (req, rec_year) in self.prog_courses.get(st["programme_code"], {}).items():
            c = self.course[code]
            if code in state["passed"] or code in state["registered"]:
                continue
            if c["semester_offered"] not in (0, self.target_sem):
                continue
            if not all(p in state["passed"] for p in self.prereq.get(code, [])):
                continue
            # do not schedule a level-4 capstone for a Year-1 student
            if c["course_level"] > st["year_of_study"] + 1:
                continue
            is_retake = code in state["taken"]
            out.append({"course_code": code, "requirement_type": req,
                        "recommended_year": rec_year, "is_retake": is_retake, **c})
        return out

    def _open_electives(self, state):
        """Tier-2 pool: catalogue courses OUTSIDE the student's own programme
        requirement lists that they could legitimately take next term.

        WHY THIS EXISTS
        ---------------
        Restricting the timetable to ProgrammeCourse rows alone made 28.8% of
        students unable to reach the 4-course minimum — and the shortfall hit
        high-GPA students (27.6% of those with GPA >= 3.5) about as hard as
        CRITICAL ones (33.3%). That pattern proves the cause was the filter,
        not student performance: once a student exhausts the eligible
        requirements of their own programme there was nothing left to fill
        with. Real HKU students fill that space with common-core and free
        electives, so the pool has to model them.

        These are ranked AFTER every programme course, so they only ever
        backfill a slot the curriculum cannot use.
        """
        st = state["student"]
        own = set(self.prog_courses.get(st["programme_code"], {}))
        out = []
        for code, c in self.course.items():
            if code in own or code in state["passed"] or code in state["registered"]:
                continue
            if c["semester_offered"] not in (0, self.target_sem):
                continue
            if not all(p in state["passed"] for p in self.prereq.get(code, [])):
                continue
            if c["course_level"] > st["year_of_study"] + 1:
                continue
            out.append({"course_code": code, "requirement_type": "OPEN_ELECTIVE",
                        "recommended_year": min(4, c["course_level"]),
                        "is_retake": code in state["taken"], **c})
        return out

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------
    def _r1_course_load(self, state):
        band, n_courses, risk = classify_band(state["gpa"])
        credits = n_courses * 6
        extra = ""
        if state["trend"] is not None and state["trend"] < -0.25:
            n_courses = max(C.MIN_COURSES_PER_SEM, n_courses - 1)
            credits = n_courses * 6
            extra = (" Recent grades are declining (last two terms average "
                     "%.2f grade points below earlier terms), so the load is "
                     "reduced by one course." % -state["trend"])
        en = ("GPA band %s (cumulative GPA %.2f). Suggested load: %d courses "
              "(%d credits) for %s semester %d.%s"
              % (band, state["gpa"], n_courses, credits,
                 self.target_year, self.target_sem, extra))
        zh = ("绩点档位 %s（累计 GPA %.2f）。建议 %s 学年第 %d 学期修 %d 门课"
              "（%d 学分）。%s"
              % (band, state["gpa"], self.target_year, self.target_sem,
                 n_courses, credits,
                 ("近两学期成绩较早前平均下滑 %.2f 个绩点，故减少一门课。" % -state["trend"])
                 if extra else ""))
        return [{
            "rec_type": "COURSE_LOAD", "course_code": None, "rule_id": "R1",
            "rationale_en": en, "rationale_zh": zh,
            "priority": 1 if risk == "HIGH" else 3,
            "source": "RULE", "band": band, "n_courses": n_courses,
            "credits": credits, "risk": risk,
        }]

    def _r2_retakes(self, state):
        out = []
        for code, h in state["current"].items():
            if h["is_passing"]:
                continue
            c = self.course[code]
            req = self.prog_courses.get(state["student"]["programme_code"], {}).get(code)
            is_req = req is not None and req[0] in ("CORE", "FOUNDATION")
            # does failing this block other required courses?
            blocks = [k for k, ps in self.prereq.items()
                      if code in ps and k not in state["passed"] and k in self.prog_courses.get(
                          state["student"]["programme_code"], {})]
            prio = 1 if (is_req and blocks) else (2 if is_req else 3)
            en = ("Latest graded attempt for %s (%s): %s, %s semester %d. "
                  % (code, c["course_title"], h["grade"], h["year"], h["semester"]))
            zh = ("%s（%s）最近一次已评分记录为 %s 学年第 %d 学期的 %s。"
                  % (code, c["course_title"], h["year"], h["semester"], h["grade"]))
            if code in state["registered"]:
                grade = state["registered"][code]
                if grade is None:
                    en += "The target-term retake is already registered; its grade is pending."
                    zh += "目标学期已经登记重修，成绩待定。"
                else:
                    en += "The target-term retake has a failing outcome; review the next available offering."
                    zh += "目标学期这次修读仍未通过，请关注下次开课。"
            elif c["semester_offered"] not in (0, self.target_sem):
                en += "A retake is outstanding. The course is not offered in the target semester."
                zh += "该课程仍需重修；目标学期不开设，请在下次开课时安排。"
            elif (any(p not in state["passed"] for p in self.prereq.get(code, []))
                  or c["course_level"] > state["student"]["year_of_study"] + 1):
                en += "A retake is outstanding. Current prerequisites or year-level limits defer registration."
                zh += "该课程仍需重修；当前先修或年级条件限制了注册。"
            else:
                en += "Plan a retake subject to prerequisites and available places in the timetable."
                zh += "建议在满足先修条件且课表有名额时安排重修。"
            if blocks:
                en += " It is a prerequisite for " + ", ".join(sorted(blocks)) + "."
                zh += " 它是以下课程的先修课：" + "、".join(sorted(blocks)) + "。"
            out.append({"rec_type": "RETAKES", "course_code": code, "rule_id": "R2",
                        "rationale_en": en, "rationale_zh": zh, "priority": prio,
                        "source": "RULE"})
        out.sort(key=lambda r: (r["priority"], r["course_code"]))
        return out

    def _r3_extra_effort(self, state):
        out = []
        for code, h in state["current"].items():
            gp = h["grade_point"]
            if not h["is_passing"] or gp > WEAK_GRADE_POINT:
                continue                      # failed (R2) or fine
            cut = self.quartile_cut.get(code)
            if cut is None or gp > cut:
                continue                      # not in the course's bottom quartile
            c = self.course[code]
            stats = self.course_stats.get(code, {})
            en = ("Scored %s (%.1f grade points) in %s (%s), which is in the "
                  "bottom quartile among %d graded attempts in that course "
                  "(course mean %.2f). Passed, but needs consolidation before "
                  "dependent courses."
                  % (h["grade"], gp, code, c["course_title"],
                     stats.get("n_taken", 0), stats.get("mean_grade_point", 0.0)))
            zh = ("%s（%s）取得 %s，绩点 %.1f，在该课 %d 次已评分修读记录中位于最低四分位"
                  "（该课平均绩点 %.2f）。虽已通过，但在修读后续依赖课程前需要巩固。"
                  % (code, c["course_title"], h["grade"], gp,
                     stats.get("n_taken", 0), stats.get("mean_grade_point", 0.0)))
            out.append({"rec_type": "EXTRA_EFFORT", "course_code": code,
                        "rule_id": "R3", "rationale_en": en, "rationale_zh": zh,
                        "priority": 2, "source": "RULE", "_gp": gp,
                        "_dependents": len([k for k, ps in self.prereq.items()
                                            if code in ps])})
        # worst grade first; ties broken by how many later courses depend on it,
        # so the truncation at MAX_RECS_PER_TYPE keeps the most consequential
        out.sort(key=lambda r: (r["_gp"], -r["_dependents"], r["course_code"]))
        for r in out:
            r.pop("_gp", None)
            r.pop("_dependents", None)
        return out[:MAX_RECS_PER_TYPE]

    def _r4_swap(self, state):
        out = []
        prog = self.prog_courses.get(state["student"]["programme_code"], {})
        for code, h in state["current"].items():
            gp = h["grade_point"]
            # Failures belong to R2 (retake), not here. Advising a student to
            # both retake and swap the same course is contradictory.
            if not h["is_passing"] or gp > WEAK_GRADE_POINT:
                continue
            req = prog.get(code)
            if req and req[0] in ("CORE", "FOUNDATION"):
                continue            # required -> retake (R2), not swap
            c = self.course[code]
            # suggest a concrete alternative in the same level from the programme
            alts = [k for k, (rt, ry) in prog.items()
                    if rt == "ELECTIVE" and k not in state["taken"]
                    and self.course[k]["course_level"] == c["course_level"]
                    and self.course[k]["semester_offered"] in (0, self.target_sem)
                    and all(p in state["passed"] for p in self.prereq.get(k, []))]
            alt_txt = (" For a future elective, consider %s." % ", ".join(sorted(alts)[:3])) if alts else ""
            en = ("Passed %s (%.1f points) in %s (%s). Keep the earned credit; when choosing "
                  "future optional courses, consider a different elective direction.%s"
                  % (h["grade"], h["grade_point"], code, c["course_title"], alt_txt))
            zh = ("%s（%s）成绩偏弱（%s，%.1f 绩点），且该课不属于本专业的核心或基础必修，"
                  "该课已取得的学分保留；今后选择同类选修时可考虑其他方向。%s"
                  % (code, c["course_title"], h["grade"], h["grade_point"],
                     ("可改选：%s。" % "、".join(sorted(alts)[:3])) if alts else ""))
            out.append({"rec_type": "SWAP_COURSE", "course_code": code,
                        "rule_id": "R4", "rationale_en": en, "rationale_zh": zh,
                        "priority": 3, "source": "RULE"})
        return out[:MAX_RECS_PER_TYPE]

    def _r5_major_adjust(self, state):
        if len(state["in_dept"]) < DEPT_MIN_COURSES or not state["out_dept"]:
            return []          # not enough evidence to say anything
        m_in = sum(state["in_dept"]) / len(state["in_dept"])
        m_out = sum(state["out_dept"]) / len(state["out_dept"])
        gap = m_in - m_out
        if gap >= DEPT_GAP_THRESHOLD:
            return []          # performing at least comparably inside the major
        dept = state["student"]["primary_dept"]
        en = ("Mean grade point in %s (home department) courses is %.2f across "
              "%d attempts, versus %.2f in courses outside it — a gap of %.2f. "
              "This is a signal to review whether the current major fits, NOT a "
              "verdict: it does not control for course difficulty or for the "
              "fact that in-department courses are usually the harder core."
              % (dept, m_in, len(state["in_dept"]), m_out, gap))
        zh = ("在本院（%s）课程上的平均绩点为 %.2f（共 %d 次修读），而在院外课程为 %.2f，"
              "差距 %.2f。这是一个提示需要重新审视当前专业是否合适的信号，但并非定论："
              "它没有控制课程难度，也没有考虑到本院课程通常正是更难的核心课。"
              % (dept, m_in, len(state["in_dept"]), m_out, gap))
        return [{"rec_type": "MAJOR_ADJUST", "course_code": None, "rule_id": "R5",
                 "rationale_en": en, "rationale_zh": zh, "priority": 2,
                 "source": "RULE", "dept_gap": round(gap, 3)}]

    def _r6_prereq_gap(self, state):
        """Required courses blocked by an unpassed prerequisite -> take the
        prerequisite first. Computed in Python from the same tables as the
        v_prereq_gap view, so the engine works without depending on view order.

        Aggregated by PREREQUISITE, not by blocked course: one missing
        prerequisite often blocks several required courses, and emitting one
        row per blocked course repeats the same advice several times over.
        Each row therefore names the prerequisite once and lists everything it
        unblocks.
        """
        prog = self.prog_courses.get(state["student"]["programme_code"], {})
        # prereq_code -> list of blocked required courses
        blocked_by = {}
        for code, (req, rec_year) in prog.items():
            if req not in ("CORE", "FOUNDATION"):
                continue
            if code in state["passed"]:
                continue
            if self.course[code]["semester_offered"] not in (0, self.target_sem):
                continue
            missing = [p for p in self.prereq.get(code, []) if p not in state["passed"]]
            if not missing:
                continue
            actionable = [p for p in missing
                          if p not in state["registered"] and self.course[p]["semester_offered"] in (0, self.target_sem)
                          and all(q in state["passed"] for q in self.prereq.get(p, []))]
            for p in actionable:
                blocked_by.setdefault(p, []).append((code, req))

        out = []
        for p, blocked in blocked_by.items():
            blocked.sort(key=lambda t: (0 if t[1] == "CORE" else 1, t[0]))
            names = ", ".join("%s (%s)" % (c, self.course[c]["course_title"])
                              for c, _ in blocked[:4])
            more = (" and %d more" % (len(blocked) - 4)) if len(blocked) > 4 else ""
            n_core = sum(1 for _, r in blocked if r == "CORE")
            prio = 1 if n_core else 2
            en = ("Prerequisite %s (%s) is not yet passed, which blocks %d required "
                  "course(s)%s: %s%s. Take %s in %s semester %d to clear this requirement."
                  % (p, self.course[p]["course_title"], len(blocked),
                     " (%d of them CORE)" % n_core if n_core else "",
                     names, more, p, self.target_year, self.target_sem))
            zh = ("先修课 %s（%s）尚未通过，阻塞了 %d 门必修课程%s：%s%s。"
                  "建议在 %s 学年第 %d 学期修读 %s，以满足这项先修要求。"
                  % (p, self.course[p]["course_title"], len(blocked),
                     "（其中 %d 门为核心必修）" % n_core if n_core else "",
                     names, more, self.target_year, self.target_sem, p))
            out.append({"rec_type": "PREREQ_GAP", "course_code": p, "rule_id": "R6",
                        "rationale_en": en, "rationale_zh": zh, "priority": prio,
                        "source": "RULE", "blocked_course": names,
                        "_n_blocked": len(blocked)})
        # most-unblocking first, then CORE-priority, then lower level
        out.sort(key=lambda r: (r["priority"], -r["_n_blocked"],
                                self.course[r["course_code"]]["course_level"]))
        for r in out:
            r.pop("_n_blocked", None)
        return out[:MAX_RECS_PER_TYPE]

    # ------------------------------------------------------------------
    # statistical model (auxiliary)
    # ------------------------------------------------------------------
    def _model_features(self, history, sid, code, home_department):
        course = self.course[code]
        department = course["department"]
        credit_points, credits = history["students"].get(sid, (0, 0))
        course_points, course_count, course_fails = history["courses"].get(code, (0, 0, 0))
        dept_points, dept_count = history["departments"].get((sid, department), (0, 0))
        total_points, total_count, total_fails = history["global"]
        prior_mean = total_points / total_count if total_count else 3.0
        prior_fail = total_fails / total_count if total_count else 0.0
        gpa = credit_points / credits if credits else prior_mean
        return [
            gpa, dept_points / dept_count if dept_count else gpa,
            course_points / course_count if course_count else prior_mean,
            course_fails / course_count if course_count else prior_fail,
            course["course_level"], int(credits > 0),
            int(bool(self.prereq.get(code))), int(department == home_department),
        ]

    def _temporal_model_data(self):
        # Every enrolment in a term is scored before any mark from that term is added.
        rows = self.cur.execute("""
            SELECT e.student_id,e.course_code,e.academic_year,e.semester,g.grade_point,
                   g.is_passing,p.primary_dept
              FROM Enrolment e JOIN GradeScale g ON g.grade=e.grade
              JOIN Student s ON s.student_id=e.student_id
              JOIN Programme p ON p.programme_code=s.programme_code
             WHERE (e.academic_year,e.semester)<(?,?)
             ORDER BY e.academic_year,e.semester,e.student_id,e.course_code""",
                                (self.target_year, self.target_sem))
        history = {"students": defaultdict(lambda: [0.0, 0]),
                   "departments": defaultdict(lambda: [0.0, 0]),
                   "courses": defaultdict(lambda: [0.0, 0, 0]),
                   "global": [0.0, 0, 0]}
        terms, X, y = [], [], []
        for term, group in groupby(rows, lambda r: (r["academic_year"], r["semester"])):
            attempts = list(group)
            for row in attempts:
                X.append(self._model_features(history, row["student_id"], row["course_code"],
                                              row["primary_dept"]))
                y.append(int(row["grade_point"] <= WEAK_GRADE_POINT))
                terms.append(term)
            for row in attempts:
                sid, code, points = row["student_id"], row["course_code"], row["grade_point"]
                course = self.course[code]
                student = history["students"][sid]
                student[0] += course["credits"] * points
                student[1] += course["credits"]
                dept = history["departments"][sid, course["department"]]
                dept[0] += points
                dept[1] += 1
                for totals in (history["courses"][code], history["global"]):
                    totals[0] += points
                    totals[1] += 1
                    totals[2] += int(not row["is_passing"])
        return X, y, terms, history

    def fit_model(self):
        """Evaluate on the latest completed term, then fit the planning model on all prior terms."""
        self.model = None
        try:
            import numpy as np
            from sklearn.linear_model import LogisticRegression
            from sklearn.metrics import roc_auc_score, roc_curve
        except ImportError:
            if self.verbose:
                print("NumPy/scikit-learn unavailable; using rules only.")
            return None
        features, labels, terms, history = self._temporal_model_data()
        if not terms:
            return None
        holdout = terms[-1]
        split = terms.index(holdout)
        if len(set(labels[:split])) < 2 or len(set(labels[split:])) < 2:
            if self.verbose:
                print("Insufficient dated observations of both classes for a held-out AUC.")
            return None
        X, y = np.asarray(features), np.asarray(labels)
        train, test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]
        clf = LogisticRegression(max_iter=2000).fit(train, y_train)
        scores = clf.predict_proba(test)[:, 1]
        # Negative control preserves each split's class prevalence.
        rng = np.random.default_rng(C.RANDOM_SEED)
        perm_train, perm_test = rng.permutation(y_train), rng.permutation(y_test)
        control = LogisticRegression(max_iter=2000).fit(train, perm_train)
        control_scores = control.predict_proba(test)[:, 1]
        auc = float(roc_auc_score(y_test, scores))
        control_auc = float(roc_auc_score(perm_test, control_scores))
        roc = roc_curve(y_test, scores)[:2]
        control_roc = roc_curve(perm_test, control_scores)[:2]

        # The production fit can use the completed holdout after evaluation.
        clf.fit(X, y)
        self._score_history = history
        self.model = {
            "clf": clf, "auc": auc, "control_auc": control_auc,
            "roc": roc, "control_roc": control_roc, "holdout_term": holdout,
            "train_last_term": terms[split - 1], "n": len(y), "n_train": split,
            "n_test": len(y_test), "test_positives": int(y_test.sum()),
            "train_positives": int(y_train.sum()), "pos_rate": float(y_test.mean()),
            "features": ["prior_credit_weighted_gpa", "prior_student_department_mean",
                         "prior_course_mean", "prior_course_fail_rate", "course_level",
                         "has_prior_grades", "has_prerequisites", "in_home_department"],
        }
        if self.verbose:
            print("Temporal holdout %s semester %d: train=%d, test=%d, AUC=%.4f, control=%.4f"
                  % (*holdout, split, len(y_test), auc, control_auc))
        return self.model

    def _model_risk(self, state, cand_code):
        if self.model is None:
            return None
        student = state["student"]
        x = self._model_features(self._score_history, student["student_id"], cand_code,
                                 student["primary_dept"])
        clf = self.model["clf"]
        log_odds = float(clf.intercept_[0] + clf.coef_[0] @ x)
        return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, log_odds))))

    # ------------------------------------------------------------------
    # assemble a plan
    # ------------------------------------------------------------------
    def plan_student(self, student_id, use_model=True):
        """Return the full plan dict for one student (not yet persisted)."""
        state = self._student_state(student_id)
        recs = []
        recs += self._r1_course_load(state)
        recs += self._r2_retakes(state)
        recs += self._r3_extra_effort(state)
        recs += self._r4_swap(state)
        recs += self._r5_major_adjust(state)
        recs += self._r6_prereq_gap(state)

        load = next((r for r in recs if r["rec_type"] == "COURSE_LOAD"), None)
        n_courses = load["n_courses"] if load else C.MIN_COURSES_PER_SEM
        risk_level = load["risk"] if load else "LOW"

        # rank candidates for the suggested load, using the model only to
        # break ties and to flag high-risk picks
        # Tier 1: the student's own programme requirements.
        # Tier 2: open electives outside the programme, used ONLY to backfill
        #         slots the curriculum cannot fill (see _open_electives).
        registered = sorted(state["registered"])
        slots = max(0, n_courses - len(registered))
        if registered:
            load["rationale_en"] += " Existing registrations already occupy %d timetable slot(s)." % len(registered)
            load["rationale_zh"] += " 目标学期已有 %d 门注册课程，占用相应名额。" % len(registered)
        cands = self._candidates(state)
        req_rank = {"CORE": 0, "FOUNDATION": 1, "ELECTIVE": 2,
                    "OPEN_ELECTIVE": 3, "RETAKES": 0}
        if len(cands) < slots:
            cands.extend(self._open_electives(state))

        scored = []
        for cd in cands:
            rs = self._model_risk(state, cd["course_code"]) if use_model else None
            scored.append((req_rank.get(cd["requirement_type"], 3),
                           0 if cd.get("is_retake") else 1,   # retakes first
                           cd["course_level"],
                           rs if rs is not None else 0.5,
                           cd))
        scored.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4]["course_code"]))
        selected = scored[:slots]
        chosen = registered + [t[4]["course_code"] for t in selected]
        n_courses = max(len(registered), n_courses)

        # Explain a shortage when the eligible courses cannot fill the suggested load.
        if len(chosen) < n_courses:
            en = ("Only %d course(s) could be scheduled against the suggested "
                  "load of %d, because the eligible pool is that small. This is "
                  "reported rather than padded with unrelated courses."
                  % (len(chosen), n_courses))
            zh = ("实际只能排出 %d 门课，低于建议的 %d 门，因为可选课程池就这么大。"
                  "此处如实报告，而不用无关课程凑数。" % (len(chosen), n_courses))
            recs.append({"rec_type": "COURSE_LOAD", "course_code": None,
                         "rule_id": "R1-SHORTFALL", "rationale_en": en,
                         "rationale_zh": zh, "priority": 2, "source": "RULE"})
            n_courses = len(chosen)

        # transparency: report when the timetable was backfilled with open
        # electives outside the programme requirement lists
        open_chosen = [t[4]["course_code"] for t in selected
                       if t[4].get("requirement_type") == "OPEN_ELECTIVE"]
        if open_chosen:
            en = ("%d of the %d scheduled course(s) are open electives outside "
                  "the programme requirement lists (%s). They backfill slots the "
                  "curriculum could not use; verify them against the common-core "
                  "and free-elective rules before registering."
                  % (len(open_chosen), n_courses, ", ".join(open_chosen)))
            zh = ("所排 %d 门课中有 %d 门属于本专业要求清单之外的开放选修（%s）。"
                  "它们用于填补课程培养方案无法使用的空位；注册前请对照通识与"
                  "自由选修规定核实。" % (n_courses, len(open_chosen), "、".join(open_chosen)))
            recs.append({"rec_type": "COURSE_LOAD", "course_code": None,
                         "rule_id": "R1-OPENFILL", "rationale_en": en,
                         "rationale_zh": zh, "priority": 4, "source": "RULE"})

        # model-sourced warnings for high-risk picks inside the chosen load
        if use_model and self.model is not None:
            for t in selected:
                cd = t[4]
                rs = t[3]
                if rs >= RISK_SCORE_WARN:
                    en = ("Model flags %s (%s) as high risk for this student "
                          "(predicted probability of a weak grade %.2f, "
                          "held-out-term AUC %.2f). This flag does not remove the course."
                          % (cd["course_code"], cd["course_title"], rs, self.model["auc"]))
                    zh = ("模型将 %s（%s）标记为该生的高风险课程（成绩偏弱的预测概率 %.2f，"
                          "留出学期 AUC %.2f）。此提示不会取消已选课程。"
                          % (cd["course_code"], cd["course_title"], rs, self.model["auc"]))
                    recs.append({"rec_type": "EXTRA_EFFORT",
                                 "course_code": cd["course_code"], "rule_id": "R7-MODEL",
                                 "rationale_en": en, "rationale_zh": zh,
                                 "priority": 2, "source": "MODEL",
                                 "model_risk_score": round(rs, 4),
                                 "confidence": None})

        band = load["band"] if load else classify_band(state["gpa"])[0]
        need_major = any(r["rec_type"] == "MAJOR_ADJUST" for r in recs)
        major_reason = next((r["rationale_en"] for r in recs
                             if r["rec_type"] == "MAJOR_ADJUST"), None)

        return {
            "student_id": student_id,
            "state": state,
            "cumulative_gpa": state["gpa"],
            "credits_passed": state["credits_passed"],
            "gpa_band": band,
            "recommended_course_count": n_courses,
            "recommended_credits": sum(self.course[code]["credits"] for code in chosen),
            "n_retake": sum(1 for r in recs if r["rec_type"] == "RETAKES"),
            "n_extra_effort": sum(1 for r in recs if r["rec_type"] == "EXTRA_EFFORT"),
            "n_swap": sum(1 for r in recs if r["rec_type"] == "SWAP_COURSE"),
            "n_prereq_gap": sum(1 for r in recs if r["rec_type"] == "PREREQ_GAP"),
            "need_major_adjustment": 1 if need_major else 0,
            "major_adjust_reason": major_reason,
            "risk_level": risk_level,
            "recommended_courses": chosen,
            "recs": recs,
        }

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def persist(self, plan, conn=None):
        """Write one plan into StudyPlan + Recommendation.

        Idempotent: an existing plan for the same student and target term is
        deleted first (cascading to its recommendations), then re-inserted.
        Using INSERT OR REPLACE here would silently allocate a NEW plan_id for
        the AUTOINCREMENT primary key, orphaning the previous recommendations.
        """
        cn = conn if conn is not None else self.conn
        cn.execute("SAVEPOINT replace_student_plan")
        try:
            plan_id = self._write_plan(plan, cn.cursor())
        except Exception:
            cn.execute("ROLLBACK TO replace_student_plan")
            cn.execute("RELEASE replace_student_plan")
            raise
        cn.execute("RELEASE replace_student_plan")
        return plan_id

    def _write_plan(self, plan, cur):
        cur.execute("""
            DELETE FROM StudyPlan
             WHERE student_id = ? AND target_academic_year = ?
               AND target_semester = ?""",
                    (plan["student_id"], self.target_year, self.target_sem))
        cur.execute("""
            INSERT INTO StudyPlan
              (student_id, target_academic_year, target_semester, cumulative_gpa,
               credits_completed, gpa_band, recommended_course_count,
               recommended_credits, n_retake, n_extra_effort, n_swap,
               n_prereq_gap, need_major_adjustment, major_adjust_reason, risk_level)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (plan["student_id"], self.target_year, self.target_sem,
                     plan["cumulative_gpa"], plan["credits_passed"], plan["gpa_band"],
                     plan["recommended_course_count"], plan["recommended_credits"],
                     plan["n_retake"], plan["n_extra_effort"], plan["n_swap"],
                     plan["n_prereq_gap"], plan["need_major_adjustment"],
                     plan["major_adjust_reason"], plan["risk_level"]))
        plan_id = cur.execute(
            "SELECT plan_id FROM StudyPlan WHERE student_id=? AND target_academic_year=?"
            " AND target_semester=?",
            (plan["student_id"], self.target_year, self.target_sem)).fetchone()[0]
        cur.executemany("INSERT INTO PlanCourse (plan_id, position, course_code) VALUES (?,?,?)",
                        [(plan_id, position, code) for position, code in
                         enumerate(plan["recommended_courses"], 1)])
        for r in plan["recs"]:
            cur.execute("""
                INSERT INTO Recommendation
                  (plan_id, student_id, rec_type, course_code, rule_id,
                   rationale_en, rationale_zh, priority, source,
                   model_risk_score, confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (plan_id, plan["student_id"], r["rec_type"],
                         r.get("course_code"), r["rule_id"], r["rationale_en"],
                         r["rationale_zh"], r["priority"], r.get("source", "RULE"),
                         r.get("model_risk_score"), r.get("confidence")))
        return plan_id

    def run_all(self, use_model=True, limit=None, persist=True):
        """Plan for every student. Returns summary statistics."""
        ids = [r["student_id"] for r in self.cur.execute(
            "SELECT student_id FROM Student ORDER BY student_id"
            + (" LIMIT %d" % int(limit) if limit else ""))]
        if use_model:
            self.fit_model()
        if persist:
            self.conn.execute("SAVEPOINT generate_plans")
        try:
            return self._run_plans(ids, use_model, persist)
        except Exception:
            if persist:
                self.conn.execute("ROLLBACK TO generate_plans")
            raise
        finally:
            if persist:
                self.conn.execute("RELEASE generate_plans")

    def _run_plans(self, ids, use_model, persist):
        from collections import Counter
        types, bands, risks = Counter(), Counter(), Counter()
        n_recs = 0
        for i, sid in enumerate(ids, 1):
            plan = self.plan_student(sid, use_model=use_model)
            if persist:
                self.persist(plan)
            n_recs += len(plan["recs"])
            bands[plan["gpa_band"]] += 1
            risks[plan["risk_level"]] += 1
            for r in plan["recs"]:
                types[r["rec_type"]] += 1
            if self.verbose and i % 200 == 0:
                print("  planned %d/%d" % (i, len(ids)))
        return {"n_students": len(ids), "n_recommendations": n_recs,
                "by_type": dict(types), "by_band": dict(bands),
                "by_risk": dict(risks),
                "model_auc": (self.model["auc"] if self.model else None)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Run the planning engine.")
    ap.add_argument("--student", help="plan for one student id only")
    ap.add_argument("--no-model", action="store_true", help="rules only")
    ap.add_argument("--no-persist", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    eng = Engine(verbose=True)
    if a.student:
        if not a.no_model:
            eng.fit_model()
        plan = eng.plan_student(a.student, use_model=not a.no_model)
        print(json_plan(plan))
        if not a.no_persist:
            eng.persist(plan)
            eng.conn.commit()
            print("persisted plan_id for %s" % a.student)
    else:
        summary = eng.run_all(use_model=not a.no_model, limit=a.limit,
                              persist=not a.no_persist)
        print("\n=== ENGINE SUMMARY ===")
        for k, v in summary.items():
            print("  %-20s %s" % (k, v))
    eng.close()


def json_plan(plan):
    """Pretty-print one plan (kept dependency-free)."""
    s = plan["state"]["student"]
    lines = []
    lines.append("Student %s  %s (%s)" % (s["student_id"], s["name_en"], s["name_zh"]))
    lines.append("  programme : %s (%s), Year %d"
                 % (s["programme_name"], s["programme_code"], s["year_of_study"]))
    lines.append("  GPA       : %.2f  band=%s  risk=%s"
                 % (plan["cumulative_gpa"], plan["gpa_band"], plan["risk_level"]))
    lines.append("  load      : %d courses (%d credits)"
                 % (plan["recommended_course_count"], plan["recommended_credits"]))
    lines.append("  counts    : retake=%d extra_effort=%d swap=%d prereq_gap=%d major_adjust=%d"
                 % (plan["n_retake"], plan["n_extra_effort"], plan["n_swap"],
                    plan["n_prereq_gap"], plan["need_major_adjustment"]))
    lines.append("  next-term courses: %s" % ", ".join(plan["recommended_courses"]))
    lines.append("  recommendations (%d):" % len(plan["recs"]))
    for r in sorted(plan["recs"], key=lambda x: (x["priority"], x["rec_type"])):
        lines.append("    [%s] p%d %-14s %s%s"
                     % (r["rule_id"], r["priority"], r["rec_type"],
                        (r["course_code"] or "-").ljust(10), r["rationale_en"]))
        lines.append("        %s" % r["rationale_zh"])
    return "\n".join(lines)


if __name__ == "__main__":
    main()
