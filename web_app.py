#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSC5003 Student Information Management System - Web Edition (no third-party deps)

One command starts the whole system:
    python web_app.py

The browser opens automatically; if it does not, visit the URL printed in the terminal.

This file only does "UI + orchestration". All business logic still lives in the
project modules:
    src/build_database.py          build schema, load data, 40+ assertions
    src/run_queries.py             library of 38 SQL queries
    src/recommendation_engine.py   six-rule recommendation engine (rules first)
    src/validate_engine.py         invariants + label-shuffled control run
    src/export_csv.py              CSV export
    src/make_figures.py            seven report figures

The web server uses only the Python standard library http.server, so Flask /
Streamlit are not required.

Safety model:
    * The database is opened read-only (URI mode=ro), so browsing cannot corrupt it.
    * The SQL page accepts a single SELECT / WITH statement only.
    * Regenerating a plan writes its selections and advice. Pipeline actions can
      regenerate every plan or rebuild the database from simulated inputs.

Command line options:
    --port 8765     listen on a fixed port (default: pick a free one)
    --no-browser    do not open the browser automatically
    --rebuild       rebuild the database before serving
"""
import argparse
import contextlib
import html
import io
import json
import mimetypes
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import config as C                      # noqa: E402  paths, terms, grade scale
import run_queries as RQ                # noqa: E402  query library parser
from recommendation_engine import Engine  # noqa: E402  recommendation engine

DB_PATH = Path(C.DB_PATH)
QUERIES_FILE = ROOT / "sql" / "queries.sql"
FIGURE_DIR = ROOT / "output" / "figures"
MAX_ROWS = 300          # rows rendered per web table
MAX_BODY = 256 * 1024   # POST body limit

# ---------------------------------------------------------------------------
# Background tasks (rebuild, validation and other long-running jobs)
# ---------------------------------------------------------------------------
TASK_LOCK = threading.Lock()
TASK = {"name": None, "running": False, "log": "", "rc": None, "started": None}


def task_start(name, argv):
    """Run one of the src scripts in a background thread, capturing its output."""
    with TASK_LOCK:
        if TASK["running"]:
            return False, "A task is already running: %s" % TASK["name"]
        TASK.update(name=name, running=True, log="", rc=None)

    def worker():
        buf = io.StringIO()
        rc = -1
        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            proc = subprocess.Popen(
                [sys.executable, "-X", "utf8"] + argv,
                cwd=str(SRC), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env, text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout:
                buf.write(line)
                with TASK_LOCK:
                    TASK["log"] = buf.getvalue()
            proc.wait()
            rc = proc.returncode
        except Exception:
            buf.write("\n[failed to start]\n" + traceback.format_exc())
        with TASK_LOCK:
            TASK.update(running=False, rc=rc, log=buf.getvalue())

    threading.Thread(target=worker, daemon=True).start()
    return True, "Started: %s" % name


def task_state():
    with TASK_LOCK:
        return dict(TASK)


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def ro_conn():
    """Read-only connection: browsing the web UI cannot damage the database."""
    conn = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows_to_dict(rows):
    return [dict(r) for r in rows]


def overview():
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        counts = {}
        for t in ("Student", "Course", "Enrolment", "Programme", "Department",
                  "Prerequisite", "ProgrammeCourse", "StudyPlan", "Recommendation"):
            counts[t] = cur.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        progs = rows_to_dict(cur.execute("""
            SELECT p.programme_code, p.programme_name, p.degree_title,
                   COUNT(s.student_id) AS n_students,
                   ROUND(AVG(g.cumulative_gpa), 3) AS mean_gpa
              FROM Programme p
              LEFT JOIN Student s ON s.programme_code = p.programme_code
              LEFT JOIN v_student_gpa g ON g.student_id = s.student_id
             GROUP BY p.programme_code ORDER BY p.programme_code"""))
        bands = rows_to_dict(cur.execute("""
            SELECT gpa_band, COUNT(*) AS n FROM StudyPlan
             GROUP BY gpa_band ORDER BY n DESC"""))
        risks = rows_to_dict(cur.execute("""
            SELECT risk_level, COUNT(*) AS n FROM StudyPlan
             GROUP BY risk_level
             ORDER BY CASE risk_level WHEN 'HIGH' THEN 0
                                      WHEN 'MEDIUM' THEN 1 ELSE 2 END"""))
        recs = rows_to_dict(cur.execute("""
            SELECT rec_type, COUNT(*) AS n, COUNT(DISTINCT student_id) AS n_students
              FROM Recommendation GROUP BY rec_type ORDER BY n DESC"""))
        top = rows_to_dict(cur.execute("""
            SELECT s.student_id, s.name_en, s.name_zh, s.programme_code,
                   s.year_of_study, ROUND(g.cumulative_gpa, 3) AS gpa,
                   g.courses_taken, g.n_failed
              FROM Student s JOIN v_student_gpa g ON g.student_id = s.student_id
             ORDER BY g.cumulative_gpa DESC, s.student_id LIMIT 10"""))
        watch = rows_to_dict(cur.execute("""
            SELECT s.student_id, s.name_en, s.name_zh, s.programme_code,
                   s.year_of_study, ROUND(g.cumulative_gpa, 3) AS gpa, g.n_failed
              FROM Student s JOIN v_student_gpa g ON g.student_id = s.student_id
             WHERE g.n_failed >= 3
             ORDER BY g.n_failed DESC, g.cumulative_gpa ASC LIMIT 10"""))
    return {"counts": counts, "programmes": progs, "bands": bands,
            "risks": risks, "rec_types": recs, "top": top, "watch": watch,
            "db_size_kb": round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0,
            "next_term": "AY %s, Semester %d" % C.NEXT_TERM}


def search_students(term="", programme="", year="", limit=50):
    where, args = [], []
    if term:
        where.append("(s.student_id LIKE ? OR s.name_en LIKE ? OR s.name_zh LIKE ?"
                     " OR s.email LIKE ?)")
        args += ["%" + term + "%"] * 4
    if programme:
        where.append("s.programme_code = ?")
        args.append(programme)
    if year:
        where.append("s.year_of_study = ?")
        args.append(int(year))
    sql = """SELECT s.student_id, s.name_en, s.name_zh, s.gender, s.year_of_study,
                    s.programme_code, p.programme_name, s.email,
                    ROUND(g.cumulative_gpa, 3) AS gpa,
                    COALESCE(g.n_failed, 0) AS n_failed
               FROM Student s
               JOIN Programme p ON p.programme_code = s.programme_code
          LEFT JOIN v_student_gpa g ON g.student_id = s.student_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    total_sql = "SELECT COUNT(*) FROM Student s" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY s.student_id LIMIT ?"
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        total = cur.execute(total_sql, args).fetchone()[0]
        rows = rows_to_dict(cur.execute(sql, args + [int(limit)]))
    return {"rows": rows, "total": total}


def student_detail(sid):
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        prof = cur.execute("""
            SELECT v.*, s.date_of_birth AS dob
              FROM v_student_profile v JOIN Student s ON s.student_id = v.student_id
             WHERE v.student_id = ?""", (sid,)).fetchone()
        if prof is None:
            return None
        gpa = cur.execute("SELECT * FROM v_student_gpa WHERE student_id=?",
                          (sid,)).fetchone()
        rank = cur.execute("""SELECT gpa_rank, programme_size, gpa_percentile_top
                                FROM v_programme_rank WHERE student_id=?""",
                           (sid,)).fetchone()
        review = RQ.course_review(cn, sid, C.NEXT_TERM)
        transcript = rows_to_dict(cur.execute("""
            SELECT e.academic_year, e.semester, e.course_code, c.course_title,
                   c.department, c.credits, e.grade, gs.grade_point, gs.is_passing, e.is_repeat
              FROM Enrolment e
              JOIN Course c ON c.course_code = e.course_code
         LEFT JOIN GradeScale gs ON gs.grade = e.grade
             WHERE e.student_id = ?
             ORDER BY e.academic_year, e.semester, e.course_code""", (sid,)))
        gaps = rows_to_dict(cur.execute("""
            SELECT blocked_course, blocked_title, missing_prereq, missing_prereq_title,
                   requirement_type, recommended_year
              FROM v_prereq_gap WHERE student_id = ?
             ORDER BY recommended_year, blocked_course""", (sid,)))
    return {"profile": dict(prof), "gpa": dict(gpa) if gpa else None,
            "rank": dict(rank) if rank else None,
            "transcript": transcript, "gaps": gaps, "course_review": review,
            "review_term": "%s semester %d" % C.NEXT_TERM}


def plan_detail(sid):
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        plan = cur.execute("""
            SELECT * FROM StudyPlan WHERE student_id = ?
             AND target_academic_year = ? AND target_semester = ?""", (sid, *C.NEXT_TERM)).fetchone()
        if plan is None:
            return None
        courses = RQ.saved_courses(cn, plan["plan_id"])
        review = RQ.course_review(cn, sid, (plan["target_academic_year"], plan["target_semester"]))
        recs = rows_to_dict(cur.execute("""
            SELECT r.rec_type, r.course_code, r.rule_id, r.priority, r.source,
                   r.rationale_en, r.rationale_zh, r.model_risk_score, r.confidence,
                   c.course_title, c.credits, c.department
              FROM Recommendation r
         LEFT JOIN Course c ON c.course_code = r.course_code
             WHERE r.plan_id = ?
             ORDER BY r.priority, CASE WHEN r.rec_type = 'RETAKES' THEN 0 ELSE 1 END,
                      r.rec_type, r.course_code""", (plan["plan_id"],)))
    return {"plan": dict(plan), "recs": recs, "courses": courses, "course_review": review}


def regenerate_plan(sid, use_model=True):
    """Recompute and persist a plan using the shared advising engine."""
    eng = Engine()
    try:
        if use_model:
            info = eng.fit_model()
        else:
            info = None
        plan = eng.plan_student(sid, use_model=use_model)
        eng.persist(plan)
        eng.conn.commit()
        return {"ok": True, "model_auc": (info or {}).get("auc"),
                "n_courses": plan["recommended_course_count"],
                "n_recs": len(plan["recs"]),
                "courses": plan["recommended_courses"]}
    finally:
        eng.close()


def course_list(term="", dept="", level=""):
    where, args = [], []
    if term:
        where.append("(c.course_code LIKE ? OR c.course_title LIKE ?)")
        args += ["%" + term + "%"] * 2
    if dept:
        where.append("c.department = ?")
        args.append(dept)
    if level:
        where.append("c.course_level = ?")
        args.append(int(level))
    sql = """SELECT c.course_code, c.course_title, c.department, c.credits,
                    c.course_level, c.semester_offered, c.is_core,
                    COALESCE(v.n_taken, 0) AS n_taken,
                    v.mean_grade_point, v.fail_rate_pct
               FROM Course c LEFT JOIN v_course_stats v ON v.course_code = c.course_code"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.course_code LIMIT ?"
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        rows = rows_to_dict(cur.execute(sql, args + [MAX_ROWS]))
        depts = [r[0] for r in cur.execute(
            "SELECT DISTINCT department FROM Course ORDER BY department")]
    return {"rows": rows, "departments": depts}


def course_detail(code):
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        base = cur.execute("""SELECT c.*, v.n_taken, v.mean_grade_point,
                                     v.fail_rate_pct, v.weak_rate_pct
                                FROM Course c
                           LEFT JOIN v_course_stats v ON v.course_code = c.course_code
                               WHERE c.course_code = ?""", (code,)).fetchone()
        if base is None:
            return None
        pre = rows_to_dict(cur.execute("""
            SELECT p.prereq_code, c.course_title FROM Prerequisite p
              JOIN Course c ON c.course_code = p.prereq_code
             WHERE p.course_code = ? ORDER BY p.prereq_code""", (code,)))
        unlocks = rows_to_dict(cur.execute("""
            SELECT p.course_code, c.course_title FROM Prerequisite p
              JOIN Course c ON c.course_code = p.course_code
             WHERE p.prereq_code = ? ORDER BY p.course_code""", (code,)))
        progs = rows_to_dict(cur.execute("""
            SELECT pc.programme_code, pr.programme_name, pc.requirement_type,
                   pc.recommended_year
              FROM ProgrammeCourse pc JOIN Programme pr
                ON pr.programme_code = pc.programme_code
             WHERE pc.course_code = ? ORDER BY pc.programme_code""", (code,)))
        grades = rows_to_dict(cur.execute("""
            SELECT e.grade, COUNT(*) AS n, g.grade_point
              FROM Enrolment e JOIN GradeScale g ON g.grade = e.grade
             WHERE e.course_code = ? AND e.grade IS NOT NULL
             GROUP BY e.grade, g.grade_point, g.grade_order
             ORDER BY g.grade_order DESC""", (code,)))
    return {"course": dict(base), "prereqs": pre, "unlocks": unlocks,
            "programmes": progs, "grades": grades}


def statistics():
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        by_prog = rows_to_dict(cur.execute("""
            SELECT p.programme_code, p.programme_name,
                   COUNT(DISTINCT s.student_id) AS n_students,
                   ROUND(AVG(g.cumulative_gpa), 3) AS mean_gpa,
                   ROUND(MIN(g.cumulative_gpa), 2) AS min_gpa,
                   ROUND(MAX(g.cumulative_gpa), 2) AS max_gpa,
                   SUM(g.n_failed) AS total_failures,
                   ROUND(AVG(g.courses_taken), 1) AS mean_courses
              FROM Programme p
              JOIN Student s ON s.programme_code = p.programme_code
              JOIN v_student_gpa g ON g.student_id = s.student_id
             GROUP BY p.programme_code ORDER BY mean_gpa DESC"""))
        by_year = rows_to_dict(cur.execute("""
            SELECT s.year_of_study, COUNT(*) AS n,
                   ROUND(AVG(g.cumulative_gpa), 3) AS mean_gpa,
                   SUM(g.n_failed) AS n_failed
              FROM Student s JOIN v_student_gpa g ON g.student_id = s.student_id
             GROUP BY s.year_of_study ORDER BY s.year_of_study"""))
        tot = cur.execute(
            "SELECT COUNT(*) FROM Enrolment WHERE grade IS NOT NULL").fetchone()[0]
        grades = rows_to_dict(cur.execute("""
            SELECT e.grade, COUNT(*) AS n, g.grade_point
              FROM Enrolment e JOIN GradeScale g ON g.grade = e.grade
             GROUP BY e.grade, g.grade_point, g.grade_order
             ORDER BY g.grade_order DESC"""))
        for g in grades:
            g["share_pct"] = round(100.0 * g["n"] / tot, 1) if tot else 0.0
        hardest = rows_to_dict(cur.execute("""
            SELECT course_code, course_title, department, n_taken,
                   mean_grade_point, fail_rate_pct
              FROM v_course_stats WHERE n_taken >= 30
             ORDER BY mean_grade_point ASC LIMIT 12"""))
        rules = rows_to_dict(cur.execute("""
            SELECT rule_id, COUNT(*) AS n, COUNT(DISTINCT student_id) AS n_students
              FROM Recommendation GROUP BY rule_id ORDER BY n DESC"""))
    return {"by_programme": by_prog, "by_year": by_year, "grades": grades,
            "hardest": hardest, "rules": rules, "graded_enrolments": tot}


def query_library():
    if not QUERIES_FILE.exists():
        return []
    return [{"qid": q, "title": t} for q, t, _ in
            RQ.parse(QUERIES_FILE.read_text(encoding="utf-8"))]


WRITE_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|VACUUM|"
    r"REINDEX|PRAGMA|BEGIN|COMMIT|ROLLBACK|GRANT|TRIGGER)\b", re.I)


def run_sql(sql, qid=None):
    """Execute read-only SQL. When qid is given, take that statement from the library."""
    if qid:
        parsed = RQ.parse(QUERIES_FILE.read_text(encoding="utf-8"))
        found = [(t, s) for q, t, s in parsed if q == qid]
        if not found:
            return {"ok": False, "error": "No such query in the library: %s" % qid}
        title, sql = found[0]
    else:
        title = "Custom query"
    if not sql or not sql.strip():
        return {"ok": False, "error": "Empty SQL"}
    body = sql.strip()
    # Multi-statement detection must strip comments and string literals first:
    # the library's own comments contain semicolons (e.g. Q07 ends with
    # "never from a duplicated column on Enrolment."), and a naive ';' search
    # would wrongly reject a legitimate single query.
    probe = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    probe = re.sub(r"--[^\n]*", "", probe)
    probe = re.sub(r"'(?:''|[^'])*'", "''", probe)
    probe = re.sub(r'"(?:""|[^"])*"', '""', probe)
    if ";" in probe.strip().rstrip(";"):
        return {"ok": False,
                "error": "Only a single statement is allowed (semicolon-separated statements detected)"}
    if not re.match(r"^\s*(SELECT|WITH)\b", probe, re.I):
        return {"ok": False, "error": "Only SELECT / WITH queries are allowed"}
    if WRITE_RE.search(probe):
        return {"ok": False, "error": "Write keyword detected; web queries are read-only"}
    with contextlib.closing(ro_conn()) as cn:
        cur = cn.cursor()
        try:
            cur.execute(body)
        except sqlite3.Error as e:
            return {"ok": False, "error": "SQL error: %s" % e, "sql": body, "title": title}
        if cur.description is None:
            return {"ok": True, "columns": [], "rows": [], "n_total": 0,
                    "sql": body, "title": title}
        cols = [d[0] for d in cur.description]
        fetched = cur.fetchmany(MAX_ROWS + 1)
        n_total = len(fetched)
        truncated = n_total > MAX_ROWS
        rows = [[("" if v is None else v) for v in r] for r in fetched[:MAX_ROWS]]
    return {"ok": True, "columns": cols, "rows": rows, "n_total": n_total,
            "truncated": truncated, "sql": body, "title": title}


FIGURES = [
    ("fig_er_diagram.png", "ER diagram"),
    ("fig_programme_gpa.png", "GPA distribution by programme"),
    ("fig_grade_distribution.png", "Grade distribution"),
    ("fig_gpa_bands.png", "Students per GPA band"),
    ("fig_rec_types.png", "Recommendation types"),
    ("fig_prereq_chain.png", "Prerequisite chain"),
    ("fig_model_validation.png", "Model validation (with shuffled-label control)"),
]


def figures_state():
    return [{"file": f, "title": t, "exists": (FIGURE_DIR / f).exists(),
             "kb": round((FIGURE_DIR / f).stat().st_size / 1024, 1)
             if (FIGURE_DIR / f).exists() else 0} for f, t in FIGURES]


def api(route, params, body):
    """Single entry point for all JSON endpoints."""
    if route == "overview":
        return overview()
    if route == "search":
        return search_students(params.get("term", ""), params.get("programme", ""),
                               params.get("year", ""), params.get("limit", 50))
    if route == "student":
        d = student_detail(params.get("sid", ""))
        return d or {"error": "Student not found: %s" % params.get("sid", "")}
    if route == "plan":
        d = plan_detail(params.get("sid", ""))
        return d or {"error": "No plan record for this student yet", "missing": True}
    if route == "courses":
        return course_list(params.get("term", ""), params.get("dept", ""),
                           params.get("level", ""))
    if route == "course":
        d = course_detail(params.get("code", ""))
        return d or {"error": "Course not found: %s" % params.get("code", "")}
    if route == "stats":
        return statistics()
    if route == "queries":
        return {"items": query_library()}
    if route == "sql":
        return run_sql(body.get("sql", ""), body.get("qid") or None)
    if route == "figures":
        return {"items": figures_state()}
    if route == "task":
        return task_state()
    if route == "regenerate":
        sid = body.get("sid", "")
        if not student_detail(sid):
            return {"ok": False, "error": "Student not found: %s" % sid}
        return regenerate_plan(sid, use_model=bool(body.get("use_model", True)))
    if route == "run":
        which = body.get("which", "")
        jobs = {
            "rebuild": ("Rebuild database (drop and regenerate)", ["build_database.py", "--generate"]),
            "engine": ("Generate plans for all students", ["recommendation_engine.py"]),
            "validate": ("Engine validation + shuffled-label control", ["validate_engine.py"]),
            "verify": ("Verify persisted engine output", ["verify_engine_output.py"]),
            "queries": ("Run the 38-query library", ["run_queries.py", "--rows", "3"]),
            "figures": ("Regenerate the seven figures", ["make_figures.py"]),
            "csv": ("Export CSV files", ["export_csv.py"]),
            "all": ("Full pipeline", ["run_all.py"]),
        }
        if which not in jobs:
            return {"ok": False, "error": "Unknown task"}
        name, argv = jobs[which]
        ok, msg = task_start(name, argv)
        return {"ok": ok, "message": msg}
    return {"error": "Unknown endpoint: %s" % route}


# ---------------------------------------------------------------------------
# Page (HTML / CSS / JS all inline, no CDN dependency)
# ---------------------------------------------------------------------------
CSS = """
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;
 color:#1c2430;background:#f4f6f9}
a{color:#1a5fb4;text-decoration:none}a:hover{text-decoration:underline}
header{background:#12314f;color:#fff;padding:14px 22px;display:flex;
 align-items:baseline;gap:16px;flex-wrap:wrap}
header h1{font-size:18px;margin:0;font-weight:600}
header .sub{font-size:12px;color:#a9c4de}
nav{background:#fff;border-bottom:1px solid #dde3ea;padding:0 14px;display:flex;
 flex-wrap:wrap;position:sticky;top:0;z-index:9}
nav button{background:none;border:0;border-bottom:3px solid transparent;
 padding:12px 15px;font:inherit;font-size:14px;color:#41505f;cursor:pointer}
nav button:hover{color:#12314f;background:#f7f9fc}
nav button.on{color:#12314f;border-bottom-color:#1a5fb4;font-weight:600}
main{padding:20px 22px 60px;max-width:1500px;margin:0 auto}
.card{background:#fff;border:1px solid #e2e8ef;border-radius:8px;padding:16px 18px;
 margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid #eef2f6}
.card h3{font-size:14px;margin:16px 0 8px;color:#2c3e50}
.grid{display:grid;gap:14px}
.g4{grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.g2{grid-template-columns:repeat(auto-fit,minmax(400px,1fr))}
.kpi{background:#fff;border:1px solid #e2e8ef;border-left:4px solid #1a5fb4;
 border-radius:6px;padding:12px 14px}
.kpi .v{font-size:24px;font-weight:600;color:#12314f}
.kpi .l{font-size:12px;color:#6b7a89;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 9px;border-bottom:1px solid #eef2f6;text-align:left;
 vertical-align:top}
th{background:#f7f9fc;color:#41505f;font-weight:600;white-space:nowrap;
 position:sticky;top:0}
tbody tr:hover{background:#f9fbfe}
.tw{max-height:520px;overflow:auto;border:1px solid #eef2f6;border-radius:6px}
.num{text-align:right;font-variant-numeric:tabular-nums}
input,select,textarea,button.btn{font:inherit;padding:7px 10px;border:1px solid #cfd8e3;
 border-radius:5px;background:#fff;color:#1c2430}
textarea{width:100%;min-height:150px;font-family:Consolas,"Courier New",monospace;
 font-size:13px;line-height:1.5}
button.btn{cursor:pointer;background:#1a5fb4;color:#fff;border-color:#1a5fb4}
button.btn:hover{background:#164f96}
button.btn.sec{background:#fff;color:#41505f;border-color:#cfd8e3}
button.btn.sec:hover{background:#f2f6fb}
button.btn:disabled{opacity:.55;cursor:not-allowed}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;
 background:#eef3f9;color:#3a5a7a;border:1px solid #dbe5ef}
.tag.hi{background:#fdecec;color:#a12;border-color:#f6d4d4}
.tag.mid{background:#fff5e5;color:#96601a;border-color:#f3e2c4}
.tag.lo{background:#eaf6ec;color:#256b32;border-color:#cfe7d4}
.muted{color:#6b7a89;font-size:12px}
.err{background:#fdecec;border:1px solid #f6d4d4;color:#a12;padding:10px 12px;
 border-radius:6px}
.ok{background:#eaf6ec;border:1px solid #cfe7d4;color:#256b32;padding:10px 12px;
 border-radius:6px}
pre{background:#f7f9fc;border:1px solid #eef2f6;border-radius:6px;padding:12px;
 overflow:auto;font-family:Consolas,"Courier New",monospace;font-size:12px;
 line-height:1.5;max-height:460px;white-space:pre-wrap;word-break:break-word}
.rec{border:1px solid #e6ecf3;border-left:3px solid #1a5fb4;border-radius:6px;
 padding:10px 12px;margin-bottom:9px;background:#fcfdff}
.rec .hd{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:5px}
.rec .en{color:#1c2430}
.rec .meta{color:#6b7a89;font-size:12px;margin-top:4px}
.bar{height:9px;background:#eef2f6;border-radius:5px;overflow:hidden;min-width:70px}
.bar>i{display:block;height:100%;background:#1a5fb4}
figure{margin:0}figure img{width:100%;border:1px solid #e2e8ef;border-radius:6px;
 background:#fff}figcaption{font-size:13px;color:#41505f;margin-top:6px}
.hide{display:none}
.spin{color:#6b7a89;font-size:13px}
.dl{display:grid;grid-template-columns:150px 1fr;gap:5px 12px;font-size:13px}
.dl dt{color:#6b7a89}.dl dd{margin:0}
code{background:#f2f6fb;padding:1px 5px;border-radius:3px;font-size:12px}
footer{text-align:center;color:#8b98a5;font-size:12px;padding:18px}
"""

JS = r"""
const $ = s => document.querySelector(s);
const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>(
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = v => (typeof v==='number') ? v.toLocaleString() : esc(v);

async function jget(route, params){
  const qs = new URLSearchParams(params||{}).toString();
  const r = await fetch('/api/'+route+(qs?'?'+qs:''));
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}
async function jpost(route, body){
  const r = await fetch('/api/'+route,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}
function tbl(cols, rows, numCols){
  if(!rows || !rows.length) return '<p class="muted">(no data)</p>';
  numCols = numCols||[];
  let h = '<div class="tw"><table><thead><tr>';
  cols.forEach(c=>h+='<th>'+esc(c.label||c.key)+'</th>');
  h += '</tr></thead><tbody>';
  rows.forEach(r=>{
    h += '<tr>';
    cols.forEach(c=>{
      let v = r[c.key];
      let cls = numCols.includes(c.key) ? ' class="num"' : '';
      let cell = c.fmt ? c.fmt(v, r) : (typeof v==='number'? num(v) : esc(v));
      h += '<td'+cls+'>'+cell+'</td>';
    });
    h += '</tr>';
  });
  return h+'</tbody></table></div>';
}
const sidLink = v => '<a href="#" onclick="openStudent(\''+esc(v)+'\');return false">'
  +esc(v)+'</a>';
const codeLink = v => v ? '<a href="#" onclick="openCourse(\''+esc(v)
  +'\');return false">'+esc(v)+'</a>' : '';
function courseReviewHtml(rows, term, selected){
  const cols = [{key:'course_code',label:'Course',fmt:codeLink},
    {key:'history',label:'Attempts, oldest first',fmt:v=>v.map(esc).join('<br>')},
    {key:'availability',label:'Retake eligibility · '+term}];
  if(selected){
    cols.push({key:'course_code',label:'In saved plan',fmt:v=>selected.has(v)?'Yes':'No'});
  }
  const open = rows.filter(r=>!r.passed), cleared = rows.filter(r=>r.passed);
  let h = '<div class="card"><h2>Courses still unpassed ('+open.length+')</h2>';
  h += '<p class="muted">Retake status follows the latest graded attempt. F is a fail; D (1.0) and D+ (1.3) are passes. Pending grades do not change a course outcome.</p>';
  h += open.length ? tbl(cols,open) : '<p>No course has a failing latest graded attempt.</p>';
  if(cleared.length){
    h += '<h3>Previously failed, now passed ('+cleared.length+')</h3>'+tbl(cols,cleared);
  }
  return h+'</div>';
}
const riskTag = v => '<span class="tag '+(v==='HIGH'?'hi':v==='MEDIUM'?'mid':'lo')
  +'">'+esc(v||'-')+'</span>';

const TABS = [
  ['overview','Overview'],['students','Students'],['plan','Study Plan'],
  ['courses','Courses'],['stats','Statistics'],['sql','SQL Queries'],
  ['figures','Figures'],['ops','Pipeline'],['about','About']
];
let cur = 'overview';
function nav(){
  $('nav').innerHTML = TABS.map(([k,t])=>
    '<button data-k="'+k+'" class="'+(k===cur?'on':'')+'">'+t+'</button>').join('');
  $('nav').querySelectorAll('button').forEach(b=>
    b.onclick = ()=>go(b.dataset.k));
}
async function go(k, keepHash){
  if(!VIEWS[k]) k = 'overview';
  cur = k; nav();
  if(!keepHash && location.hash !== '#'+k){
    history.replaceState(null,'','#'+k);
  }
  $('#view').innerHTML = '<p class="spin">Loading...</p>';
  try{ await VIEWS[k](); }
  catch(e){ $('#view').innerHTML = '<div class="err">Failed to load: '+esc(e.message)+'</div>'; }
}
window.addEventListener('hashchange', ()=>{
  const k = location.hash.slice(1);
  if(k && k!==cur) go(k, true);
});
function openStudent(sid){ go('students').then(()=>{
  $('#q_term').value = sid; doSearch(); showStudent(sid); }); }
function openCourse(code){ go('courses').then(()=>{
  $('#c_term').value = code; doCourses(); showCourse(code); }); }

const VIEWS = {};

VIEWS.overview = async () => {
  const d = await jget('overview');
  const c = d.counts;
  const kpis = [['Students',c.Student],['Courses',c.Course],['Enrolments',c.Enrolment],
    ['Programmes',c.Programme],['Study plans generated',c.StudyPlan],
    ['Recommendation entries',c.Recommendation]];
  let h = '<div class="grid g4">'+kpis.map(([l,v])=>
    '<div class="kpi"><div class="v">'+num(v)+'</div><div class="l">'+l+'</div></div>'
    ).join('')+'</div>';
  h += '<div class="card"><h2>System status</h2><p class="muted">Database '
    +num(d.db_size_kb)+' KB &middot; planning target <b>'+esc(d.next_term)
    +'</b> &middot; all students are synthetic; course codes and titles come from '
    +'the HKU public course list.</p></div>';
  h += '<div class="grid g2"><div class="card"><h2>Programmes</h2>'
    + tbl([{key:'programme_code',label:'Code'},{key:'programme_name',label:'Programme'},
           {key:'n_students',label:'Students'},{key:'mean_gpa',label:'Mean GPA'}],
          d.programmes,['n_students','mean_gpa'])+'</div>';
  h += '<div class="card"><h2>Risk distribution</h2>'
    + tbl([{key:'risk_level',label:'Risk level',fmt:riskTag},
           {key:'n',label:'Students'}], d.risks,['n'])
    + '<h3>GPA bands</h3>'
    + tbl([{key:'gpa_band',label:'Band'},{key:'n',label:'Students'}], d.bands,['n'])
    + '</div></div>';
  h += '<div class="card"><h2>Recommendation types</h2>'
    + tbl([{key:'rec_type',label:'Type'},{key:'n',label:'Entries'},
           {key:'n_students',label:'Students affected'}], d.rec_types,['n','n_students'])+'</div>';
  h += '<div class="grid g2"><div class="card"><h2>Top 10 by GPA</h2>'
    + tbl([{key:'student_id',label:'Student ID',fmt:sidLink},{key:'name_en',label:'Name'},
           {key:'programme_code',label:'Programme'},
           {key:'year_of_study',label:'Year'},{key:'gpa',label:'GPA'}],
          d.top,['year_of_study','gpa'])+'</div>';
  h += '<div class="card"><h2>Students with 3+ historical failed attempts</h2>'
    + tbl([{key:'student_id',label:'Student ID',fmt:sidLink},{key:'name_en',label:'Name'},
           {key:'programme_code',label:'Programme'},{key:'gpa',label:'GPA'},
           {key:'n_failed',label:'Failed attempts'}], d.watch,['gpa','n_failed'])+'</div></div>';
  $('#view').innerHTML = h;
};

VIEWS.students = async () => {
  const d = await jget('overview');
  let h = '<div class="card"><h2>Student search</h2><div class="row">'
    + '<input id="q_term" placeholder="Student ID / name / email" style="min-width:280px">'
    + '<select id="q_prog"><option value="">All programmes</option>'
    + d.programmes.map(p=>'<option value="'+esc(p.programme_code)+'">'
        +esc(p.programme_code)+' '+esc(p.programme_name)+'</option>').join('')
    + '</select><select id="q_year"><option value="">All years</option>'
    + [1,2,3,4].map(y=>'<option value="'+y+'">Year '+y+'</option>').join('')
    + '</select><button class="btn" id="q_go">Search</button>'
    + '<span class="muted" id="q_info"></span></div><div id="q_res"></div></div>'
    + '<div id="s_detail"></div>';
  $('#view').innerHTML = h;
  $('#q_go').onclick = doSearch;
  $('#q_term').onkeydown = e => { if(e.key==='Enter') doSearch(); };
  doSearch();
};
async function doSearch(){
  const d = await jget('search',{term:$('#q_term').value,
    programme:$('#q_prog').value, year:$('#q_year').value, limit:100});
  $('#q_info').textContent = d.total+' match(es), showing '+d.rows.length;
  $('#q_res').innerHTML = tbl([
    {key:'student_id',label:'Student ID',fmt:sidLink},{key:'name_en',label:'Name'},
    {key:'name_zh',label:'Name (ZH)'},{key:'gender',label:'Gender'},
    {key:'year_of_study',label:'Year'},{key:'programme_code',label:'Programme'},
    {key:'gpa',label:'GPA',fmt:v=>v==null?'Pending':num(v)},{key:'n_failed',label:'Failed attempts'},
    {key:'email',label:'Email'}], d.rows,['year_of_study','gpa','n_failed']);
}
async function showStudent(sid){
  $('#s_detail').innerHTML = '<p class="spin">Loading student profile...</p>';
  const d = await jget('student',{sid});
  if(d.error){ $('#s_detail').innerHTML='<div class="err">'+esc(d.error)+'</div>'; return; }
  const p = d.profile, g = d.gpa||{}, r = d.rank||{};
  let h = '<div class="card"><h2>Student profile '+esc(p.student_id)+'</h2><div class="grid g2">'
    + '<dl class="dl"><dt>Name (EN)</dt><dd>'+esc(p.name_en)+'</dd>'
    + '<dt>Name (ZH)</dt><dd>'+esc(p.name_zh)+'</dd>'
    + '<dt>Gender</dt><dd>'+esc(p.gender)+'</dd>'
    + '<dt>Date of birth</dt><dd>'+esc(p.date_of_birth)+' (age '+esc(p.age)
      +', derived at query time)</dd>'
    + '<dt>Phone</dt><dd>'+esc(p.phone_hk)+'</dd>'
    + '<dt>Email</dt><dd>'+esc(p.email)+'</dd>'
    + '<dt>Admission year</dt><dd>'+esc(p.admission_year)+'</dd>'
    + '<dt>Year of study</dt><dd>Year '+esc(p.year_of_study)+'</dd>'
    + '<dt>Programme</dt><dd>'+esc(p.programme_name)+' ('+esc(p.programme_code)+')</dd></dl>'
    + '<dl class="dl"><dt>Graded attempts</dt><dd>'+num(g.courses_taken||0)+'</dd>'
    + '<dt>Credits attempted</dt><dd>'+num(g.credits_attempted||0)+'</dd>'
    + '<dt>Credits passed</dt><dd>'+num(g.credits_passed||0)+'</dd>'
    + '<dt>Cumulative GPA</dt><dd><b>'
      + esc(g.cumulative_gpa!=null?g.cumulative_gpa.toFixed(3):'-')+'</b></dd>'
    + '<dt>Failed attempts (all terms)</dt><dd>'+num(g.n_failed||0)+'</dd>'
    + '<dt>Courses still unpassed</dt><dd>'+num(d.course_review.filter(r=>!r.passed).length)+'</dd>'
    + '<dt>Last term</dt><dd>'+esc(g.last_term||'-')+'</dd>'
    + '<dt>Programme rank</dt><dd>'+(r.gpa_rank?num(r.gpa_rank)+' / '
        +num(r.programme_size)+' (top '+esc(r.gpa_percentile_top)+'%)':'-')+'</dd></dl></div>'
    + '<div class="row" style="margin-top:14px">'
    + '<button class="btn" onclick="gotoPlan(\''+esc(p.student_id)
    + '\')">View study plan</button></div></div>';
  h += courseReviewHtml(d.course_review,d.review_term);
  h += '<div class="card"><h2>Transcript ('+d.transcript.length+' enrolment records)</h2>'
    + tbl([{key:'academic_year',label:'Academic year'},{key:'semester',label:'Semester'},
           {key:'course_code',label:'Course',fmt:codeLink},{key:'course_title',label:'Title'},
           {key:'department',label:'Department'},{key:'credits',label:'Credits'},
           {key:'grade',label:'Grade',fmt:v=>esc(v||'Pending')},{key:'grade_point',label:'Grade point'},
           {key:'is_passing',label:'Outcome',fmt:v=>v==null?'Pending':(v?'Pass':'Fail')},
           {key:'is_repeat',label:'Repeat',fmt:v=>v?'<span class="tag mid">repeat</span>':''}],
          d.transcript,['semester','credits','grade_point'])+'</div>';
  if(d.gaps.length){
    h += '<div class="card"><h2>Prerequisite gaps ('+d.gaps.length+' items)</h2>'
      + tbl([{key:'blocked_course',label:'Blocked course',fmt:codeLink},
             {key:'blocked_title',label:'Title'},
             {key:'missing_prereq',label:'Missing prerequisite',fmt:codeLink},
             {key:'missing_prereq_title',label:'Prerequisite title'},
             {key:'requirement_type',label:'Requirement type'},
             {key:'recommended_year',label:'Recommended year'}], d.gaps,['recommended_year'])+'</div>';
  }
  $('#s_detail').innerHTML = h;
  $('#s_detail').scrollIntoView({behavior:'smooth',block:'start'});
}
function gotoPlan(sid){ go('plan').then(()=>{ $('#p_sid').value=sid; loadPlan(); }); }

VIEWS.plan = async () => {
  $('#view').innerHTML = '<div class="card"><h2>Next-semester study plan</h2>'
    + '<div class="row"><input id="p_sid" placeholder="Student ID, e.g. 3036000001" '
    + 'style="min-width:220px"><button class="btn" id="p_go">View plan</button>'
    + '<label class="muted"><input type="checkbox" id="p_model" checked> '
    + 'use statistical model as tie-breaker</label>'
    + '<button class="btn sec" id="p_regen">Regenerate and save</button>'
    + '<span class="muted" id="p_msg"></span></div>'
    + '<p class="muted">Plans come from six rules (course load, retakes, extra effort, '
    + 'course swap, major adjustment, prerequisite gaps). The statistical model is only '
    + 'used to order items and flag risk; it never replaces a rule.</p></div>'
    + '<div id="p_out"></div>';
  $('#p_go').onclick = loadPlan;
  $('#p_sid').onkeydown = e => { if(e.key==='Enter') loadPlan(); };
  $('#p_regen').onclick = regenPlan;
};
async function loadPlan(){
  const sid = $('#p_sid').value.trim();
  if(!sid){ $('#p_out').innerHTML='<div class="err">Please enter a student ID</div>'; return; }
  $('#p_out').innerHTML = '<p class="spin">Loading plan...</p>';
  const d = await jget('plan',{sid});
  if(d.missing){ $('#p_out').innerHTML =
    '<div class="err">No plan record for this student yet. '
    + 'Click "Regenerate and save".</div>'; return; }
  if(d.error){ $('#p_out').innerHTML='<div class="err">'+esc(d.error)+'</div>'; return; }
  const p = d.plan;
  let h = '<div class="card"><h2>Study plan '+esc(p.student_id)+'</h2><div class="grid g4">'
    + [['Target term','AY '+esc(p.target_academic_year)+' Sem '+esc(p.target_semester)],
       ['Cumulative GPA',esc(Number(p.cumulative_gpa).toFixed(3))],
       ['GPA band',esc(p.gpa_band)],
       ['Recommended',num(p.recommended_course_count)+' courses / '
         +num(p.recommended_credits)+' credits']]
      .map(([l,v])=>'<div class="kpi"><div class="v" style="font-size:18px">'+v
        +'</div><div class="l">'+l+'</div></div>').join('')+'</div>'
    + '<div class="row" style="margin-top:12px">'+riskTag(p.risk_level)
    + '<span class="tag">retake advice '+num(p.n_retake)+'</span>'
    + '<span class="tag">extra effort '+num(p.n_extra_effort)+'</span>'
    + '<span class="tag">swaps '+num(p.n_swap)+'</span>'
    + '<span class="tag">prerequisite gaps '+num(p.n_prereq_gap)+'</span>'
    + (p.need_major_adjustment?'<span class="tag hi">major adjustment advised</span>':'')
    + '<span class="muted">generated at '+esc(p.generated_at)+'</span></div>';
  h += '<h3>Saved course list ('+d.courses.length+')</h3>';
  if(d.courses.length){
    h += tbl([{key:'position',label:'#'},
      {key:'course_code',label:'Course',fmt:codeLink},{key:'course_title',label:'Title'},
      {key:'department',label:'Department'},{key:'credits',label:'Credits'},{key:'status',label:'Status'}],
      d.courses,['position','credits']);
  }else{
    h += '<p>This plan contains no saved course selections.</p>';
  }
  h += '</div>'+courseReviewHtml(d.course_review,p.target_academic_year+' semester '+p.target_semester,
    new Set(d.courses.map(c=>c.course_code)))
    + '<div class="card"><h2>Recommendation details ('+d.recs.length+' entries)</h2>';
  d.recs.forEach(r=>{
    h += '<div class="rec"><div class="hd"><span class="tag">'+esc(r.rule_id)+'</span>'
      + '<span class="tag">'+esc(r.rec_type)+'</span>'
      + (r.course_code?'<b>'+codeLink(r.course_code)+'</b>':'')+'</div>'
      + '<div class="en">'+esc(r.rationale_en)+'</div>'
      + '<div class="meta">priority '+esc(r.priority)+' &middot; source '+esc(r.source)
      + (r.model_risk_score!=null?' &middot; model risk '+esc(r.model_risk_score):'')
      + (r.confidence!=null?' &middot; confidence '+esc(r.confidence):'')
      + '</div></div>';
  });
  $('#p_out').innerHTML = h+'</div>';
}
async function regenPlan(){
  const sid = $('#p_sid').value.trim();
  if(!sid){ $('#p_msg').textContent='Please enter a student ID first'; return; }
  $('#p_regen').disabled = true;
  $('#p_msg').textContent = 'Recomputing (includes model training, please wait)...';
  try{
    const r = await jpost('regenerate',{sid, use_model:$('#p_model').checked});
    if(r.ok){
      const mode = r.model_auc==null ? 'rules only' : 'held-out AUC '+r.model_auc.toFixed(3);
      $('#p_msg').textContent = 'Saved: '+r.courses.length+' selected courses / '+r.n_recs
        + ' recommendations ('+mode+')';
      loadPlan();
    } else { $('#p_msg').textContent = 'Failed: '+(r.error||'unknown error'); }
  }catch(e){ $('#p_msg').textContent = 'Failed: '+e.message; }
  $('#p_regen').disabled = false;
}

VIEWS.courses = async () => {
  const d0 = await jget('courses',{});
  $('#view').innerHTML = '<div class="card"><h2>Course catalogue</h2><div class="row">'
    + '<input id="c_term" placeholder="Course code or title" style="min-width:260px">'
    + '<select id="c_dept"><option value="">All departments</option>'
    + d0.departments.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select>'
    + '<select id="c_level"><option value="">All levels</option>'
    + [1,2,3,4].map(y=>'<option value="'+y+'">'+y+'xxx</option>').join('')+'</select>'
    + '<button class="btn" id="c_go">Search</button><span class="muted" id="c_info"></span>'
    + '</div><div id="c_res"></div></div><div id="c_detail"></div>';
  $('#c_go').onclick = doCourses;
  $('#c_term').onkeydown = e => { if(e.key==='Enter') doCourses(); };
  $('#c_res').innerHTML = courseTable(d0.rows);
  $('#c_info').textContent = 'showing '+d0.rows.length+' courses';
};
function courseTable(rows){
  return tbl([{key:'course_code',label:'Code',fmt:codeLink},
    {key:'course_title',label:'Title'},{key:'department',label:'Department'},
    {key:'credits',label:'Credits'},{key:'course_level',label:'Level'},
    {key:'semester_offered',label:'Offered',fmt:v=>v===0?'year-round':'Sem '+v},
    {key:'is_core',label:'Core',fmt:v=>v?'<span class="tag">core</span>':''},
    {key:'n_taken',label:'Taken by'},{key:'mean_grade_point',label:'Mean grade point'},
    {key:'fail_rate_pct',label:'Fail rate %'}], rows,
    ['credits','course_level','n_taken','mean_grade_point','fail_rate_pct']);
}
async function doCourses(){
  const d = await jget('courses',{term:$('#c_term').value,
    dept:$('#c_dept').value, level:$('#c_level').value});
  $('#c_info').textContent = 'showing '+d.rows.length+' courses';
  $('#c_res').innerHTML = courseTable(d.rows);
}
async function showCourse(code){
  $('#c_detail').innerHTML = '<p class="spin">Loading course details...</p>';
  const d = await jget('course',{code});
  if(d.error){ $('#c_detail').innerHTML='<div class="err">'+esc(d.error)+'</div>'; return; }
  const c = d.course;
  let h = '<div class="card"><h2>'+esc(c.course_code)+' &middot; '+esc(c.course_title)+'</h2>'
    + '<div class="row"><span class="tag">'+esc(c.department)+'</span>'
    + '<span class="tag">'+num(c.credits)+' credits</span>'
    + '<span class="tag">level '+esc(c.course_level)+'xxx</span>'
    + '<span class="tag">'+(c.semester_offered===0?'offered year-round'
        :'Semester '+esc(c.semester_offered))+'</span>'
    + (c.is_core?'<span class="tag">core course</span>':'')+'</div>'
    + '<div class="grid g4">'
    + [['Taken by',num(c.n_taken||0)],
       ['Mean grade point',c.mean_grade_point!=null?esc(c.mean_grade_point):'-'],
       ['Fail rate',c.fail_rate_pct!=null?esc(c.fail_rate_pct)+'%':'-'],
       ['Weak-grade rate',c.weak_rate_pct!=null?esc(c.weak_rate_pct)+'%':'-']]
      .map(([l,v])=>'<div class="kpi"><div class="v" style="font-size:19px">'+v
        +'</div><div class="l">'+l+'</div></div>').join('')+'</div>';
  if(d.prereqs.length) h += '<h3>Prerequisites</h3>'+tbl([
    {key:'prereq_code',label:'Code',fmt:codeLink},{key:'course_title',label:'Title'}],d.prereqs);
  if(d.unlocks.length) h += '<h3>Courses this unlocks</h3>'+tbl([
    {key:'course_code',label:'Code',fmt:codeLink},{key:'course_title',label:'Title'}],d.unlocks);
  if(d.programmes.length) h += '<h3>Included in these programme requirements</h3>'+tbl([
    {key:'programme_code',label:'Programme code'},{key:'programme_name',label:'Programme'},
    {key:'requirement_type',label:'Requirement type'},
    {key:'recommended_year',label:'Recommended year'}],d.programmes,['recommended_year']);
  if(d.grades.length) h += '<h3>Grade distribution</h3>'+tbl([
    {key:'grade',label:'Grade'},{key:'grade_point',label:'Grade point'},
    {key:'n',label:'Count'}],d.grades,['grade_point','n']);
  $('#c_detail').innerHTML = h+'</div>';
  $('#c_detail').scrollIntoView({behavior:'smooth',block:'start'});
}

VIEWS.stats = async () => {
  const d = await jget('stats');
  let h = '<div class="card"><h2>By programme</h2>'+tbl([
    {key:'programme_code',label:'Code'},{key:'programme_name',label:'Programme'},
    {key:'n_students',label:'Students'},{key:'mean_gpa',label:'Mean GPA'},
    {key:'min_gpa',label:'Min'},{key:'max_gpa',label:'Max'},
    {key:'total_failures',label:'Failed attempts'},
    {key:'mean_courses',label:'Mean courses taken'}],
    d.by_programme,['n_students','mean_gpa','min_gpa','max_gpa','total_failures','mean_courses'])
    +'</div>';
  h += '<div class="grid g2"><div class="card"><h2>By year of study</h2>'+tbl([
    {key:'year_of_study',label:'Year'},{key:'n',label:'Students'},
    {key:'mean_gpa',label:'Mean GPA'},{key:'n_failed',label:'Failed attempts'}],
    d.by_year,['year_of_study','n','mean_gpa','n_failed'])+'</div>';
  const gmax = Math.max(...d.grades.map(g=>g.n),1);
  h += '<div class="card"><h2>Grade distribution ('+num(d.graded_enrolments)
    + ' graded enrolments)</h2>'
    + tbl([{key:'grade',label:'Grade'},{key:'grade_point',label:'Grade point'},
           {key:'n',label:'Count'},{key:'share_pct',label:'Share %'},
           {key:'n',label:'Distribution',fmt:v=>'<div class="bar"><i style="width:'
             +(100*v/gmax).toFixed(1)+'%"></i></div>'}],
          d.grades,['grade_point','n','share_pct'])+'</div></div>';
  h += '<div class="card"><h2>Hardest courses (30+ students, ascending mean grade point)</h2>'+tbl([
    {key:'course_code',label:'Code',fmt:codeLink},{key:'course_title',label:'Title'},
    {key:'department',label:'Department'},{key:'n_taken',label:'Taken by'},
    {key:'mean_grade_point',label:'Mean grade point'},{key:'fail_rate_pct',label:'Fail rate %'}],
    d.hardest,['n_taken','mean_grade_point','fail_rate_pct'])+'</div>';
  h += '<div class="card"><h2>Rule trigger counts</h2>'+tbl([
    {key:'rule_id',label:'Rule ID'},{key:'n',label:'Entries'},
    {key:'n_students',label:'Students affected'}],d.rules,['n','n_students'])+'</div>';
  $('#view').innerHTML = h;
};

VIEWS.sql = async () => {
  const d = await jget('queries');
  $('#view').innerHTML = '<div class="card"><h2>SQL query library ('+d.items.length+' queries)</h2>'
    + '<div class="row"><select id="s_qid" style="min-width:520px">'
    + '<option value="">- pick a saved query -</option>'
    + d.items.map(q=>'<option value="'+esc(q.qid)+'">'+esc(q.qid)+' &middot; '
        +esc(q.title)+'</option>').join('')+'</select>'
    + '<button class="btn" id="s_run">Run</button>'
    + '<button class="btn sec" id="s_clear">Clear</button>'
    + '<span class="muted">Read-only: a single SELECT / WITH statement only</span></div>'
    + '<textarea id="s_sql" placeholder="SELECT * FROM Student LIMIT 10;"></textarea>'
    + '</div><div id="s_out"></div>';
  $('#s_run').onclick = runSQL;
  $('#s_clear').onclick = ()=>{ $('#s_sql').value=''; $('#s_qid').value='';
    $('#s_out').innerHTML=''; };
  $('#s_qid').onchange = ()=>{ $('#s_sql').value=''; };
};
async function runSQL(){
  const qid = $('#s_qid').value, sql = $('#s_sql').value;
  if(!qid && !sql.trim()){ $('#s_out').innerHTML=
    '<div class="err">Pick a saved query or enter some SQL</div>'; return; }
  $('#s_out').innerHTML = '<p class="spin">Running...</p>';
  const d = await jpost('sql',{qid, sql});
  if(!d.ok){ $('#s_out').innerHTML='<div class="err">'+esc(d.error)+'</div>'
    + (d.sql?'<pre>'+esc(d.sql)+'</pre>':''); return; }
  let h = '<div class="card"><h2>'+esc(d.title||'Query result')+'</h2>'
    + '<p class="muted">'+num(d.n_total)+' row(s) returned'
    + (d.truncated?' (table shows the first '+d.rows.length+' rows only)':'')+'</p>';
  if(d.columns.length){
    h += '<div class="tw"><table><thead><tr>'
      + d.columns.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>';
    d.rows.forEach(r=>{ h += '<tr>'+r.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>'; });
    h += '</tbody></table></div>';
  } else { h += '<p class="muted">(no result set)</p>'; }
  h += '<h3>SQL executed</h3><pre>'+esc(d.sql)+'</pre></div>';
  $('#s_out').innerHTML = h;
}

VIEWS.figures = async () => {
  const d = await jget('figures');
  let h = '<div class="card"><h2>Report figures</h2><p class="muted">'
    + 'Figures are produced by <code>src/make_figures.py</code>; if one is missing, '
    + 'regenerate it from the Pipeline page.</p></div>'
    + '<div class="grid g2">';
  d.items.forEach(f=>{
    h += '<div class="card"><figure>'
      + (f.exists ? '<img src="/figures/'+encodeURIComponent(f.file)
          +'" alt="'+esc(f.title)+'" loading="lazy">'
        : '<div class="err">Figure not generated yet</div>')
      + '<figcaption>'+esc(f.title)+(f.exists?' &middot; '+num(f.kb)+' KB':'')
      + '</figcaption></figure></div>';
  });
  $('#view').innerHTML = h+'</div>';
};

VIEWS.ops = async () => {
  const jobs = [
    ['rebuild','Rebuild database','Replace all stored grades and plans with freshly generated records'],
    ['engine','Generate all plans','Run the six-rule engine for all 1000 students and persist'],
    ['validate','Validate engine','Invariant checks + shuffled-label control + R3 precision/recall'],
    ['verify','Verify persisted output','Check StudyPlan / Recommendation consistency'],
    ['queries','Run query library','Execute all 38 queries and confirm none fail'],
    ['figures','Regenerate figures','Redraw the seven report figures'],
    ['csv','Export CSV','Export student / course / enrolment / recommendation tables'],
    ['all','Full pipeline','Recompute plans on existing records, run checks, export data and redraw figures']
  ];
  $('#view').innerHTML = '<div class="card"><h2>Data pipeline</h2>'
    + '<p class="muted">One task runs at a time. Full pipeline uses the current grades. '
    + 'Rebuild database replaces the academic records and their saved plans.</p>'
    + '<div class="grid g2">'+jobs.map(([k,t,d])=>
      '<div class="kpi" style="border-left-color:#6b7a89"><div style="font-weight:600">'
      +t+'</div><div class="l" style="margin:4px 0 8px">'+d+'</div>'
      +'<button class="btn'+(k==='rebuild'||k==='all'?' sec':'')+'" data-job="'+k+'">Run</button>'
      +'</div>').join('')+'</div></div>'
    + '<div class="card"><h2>Task output</h2><div id="t_state" class="muted">'
    + 'No task has been run yet</div><pre id="t_log">(no output)</pre></div>';
  $('#view').querySelectorAll('button[data-job]').forEach(b=>{
    b.onclick = async ()=>{
      const k = b.dataset.job;
      if(k==='rebuild' && !confirm('Replace all stored grades and plans with new simulated records?')) return;
      const r = await jpost('run',{which:k});
      $('#t_state').textContent = r.message || r.error;
      pollTask();
    };
  });
  pollTask();
};
let taskTimer = null;
async function pollTask(){
  if(taskTimer){ clearTimeout(taskTimer); taskTimer=null; }
  if(cur!=='ops') return;
  const t = await jget('task');
  const st = $('#t_state'), lg = $('#t_log');
  if(!st) return;
  if(t.running){ st.innerHTML = '<span class="tag mid">running</span> '+esc(t.name); }
  else if(t.name){ st.innerHTML = (t.rc===0?'<span class="tag lo">succeeded</span>'
    :'<span class="tag hi">failed (exit code '+esc(t.rc)+')</span>')+' '+esc(t.name); }
  lg.textContent = t.log || '(no output)';
  lg.scrollTop = lg.scrollHeight;
  if(t.running) taskTimer = setTimeout(pollTask, 1500);
}

VIEWS.about = async () => {
  $('#view').innerHTML = '<div class="card"><h2>About this system</h2>'
    + '<p>Course project for DSC5003 Storing and Retrieving Data: a student information '
    + 'management system and a next-semester study plan engine. The web and command-line '
    + 'interfaces share the student records, planning engine and saved course selections.</p>'
    + '<h3>Where the data comes from</h3><ul>'
    + '<li><b>Real</b>: course codes, titles and offering semesters come from the HKU '
    + '2026-27 public course list.</li>'
    + '<li><b>Simulated</b>: prerequisite chains follow the 1xxx -&gt; 2xxx -&gt; 3xxx -&gt; '
    + '4xxx level convention and were not checked against official requirements; '
    + 'all courses are worth 6 credits.</li>'
    + '<li><b>Synthetic</b>: all 1000 students and their grades are generated by a latent '
    + 'ability model. No real student data is involved.</li>'
    + '<li>Programme labels and requirements describe the simulated cohorts.</li>'
    + '</ul><h3>Design notes</h3><ul>'
    + '<li>3NF: <code>grade_point</code> is looked up from GradeScale and <code>age</code> is '
    + 'derived from the date of birth at query time.</li>'
    + '<li>Foreign keys: always <code>PRAGMA foreign_keys=ON</code> after connecting. '
    + 'Recomputing a plan replaces its previous rows inside a transaction, '
    + 'so that its saved course list and reasons are replaced together.</li>'
    + '<li>The engine is rules-first with the model as a tie-breaker. Model AUC must always '
    + 'be interpreted on the held-out synthetic term alongside its shuffled-label control. '
    + 'Performance on real students has not been measured.</li>'
    + '<li>When the candidate pool is too small the engine falls back to the open-elective '
    + 'pool. The plan records when electives filled a slot or too few eligible courses were available.</li>'
    + '</ul><h3>How to run</h3>'
    + '<pre>python web_app.py             # start the web UI (opens a browser)\n'
    + 'python web_app.py --port 8765 # fixed port\n'
    + 'python web_app.py --rebuild   # rebuild the database before serving\n'
    + 'python src/run_all.py         # command-line pipeline only</pre>'
    + '<p class="muted">The server is built on the Python standard library http.server, '
    + 'so no Flask / Streamlit install is needed. The optional statistical model '
    + 'requires scikit-learn; without it the engine degrades to rules-only mode.</p></div>';
};

nav(); go(location.hash.slice(1) || 'overview', true);
"""

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DSC5003 Student Information Management System</title><style>__CSS__</style></head>
<body>
<header><h1>DSC5003 Student Information Management System</h1>
<span class="sub">Web Edition &middot; SQLite &middot; rules-first recommendation engine</span>
</header>
<nav id="nav"></nav>
<main id="view"></main>
<footer>All student data is synthetic and for course-project demonstration only &middot; Generated by AI</footer>
<script>__JS__</script>
</body></html>
"""


def page_html():
    return PAGE.replace("__CSS__", CSS).replace("__JS__", JS)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "DSC5003-SIMS/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):      # silence the default access log
        pass

    def handle_one_request(self):
        # Browsers routinely close pre-connected / idle keep-alive sockets, and the
        # standard library turns that into a wall of ConnectionResetError tracebacks.
        # Swallow connection-level noise here; real application errors are still
        # caught inside do_GET / do_POST and returned as HTTP 500.
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                socket.timeout):
            self.close_connection = True

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if path in ("/", "/index.html"):
            return self._send(200, page_html(), "text/html; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(200, b"", "image/x-icon")
        if path.startswith("/figures/"):
            name = urllib.parse.unquote(path[len("/figures/"):])
            if "/" in name or "\\" in name or ".." in name:
                return self._json({"error": "Invalid path"}, 400)
            f = FIGURE_DIR / name
            if not f.is_file():
                return self._json({"error": "Figure not found"}, 404)
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            return self._send(200, f.read_bytes(), ctype)
        if path.startswith("/api/"):
            route = path[len("/api/"):]
            try:
                return self._json(api(route, params, {}))
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not u.path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            return self._json({"error": "Request body too large"}, 413)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return self._json({"error": "Request body is not valid JSON"}, 400)
        if not isinstance(body, dict):
            return self._json({"error": "Request body must be an object"}, 400)
        route = u.path[len("/api/"):]
        params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            return self._json(api(route, params, body))
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)


def free_port(preferred=None):
    if preferred:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                print("Port %d is already in use; picking another one" % preferred)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ensure_db(rebuild=False):
    if DB_PATH.exists() and not rebuild:
        return True
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    print("Building the database (1000 synthetic students + enrolments + assertions)...")
    args = ["--generate"] if rebuild else []
    rc = subprocess.call([sys.executable, "-X", "utf8", "build_database.py", *args],
                         cwd=str(SRC), env=env)
    if rc != 0:
        print("Database build failed (exit code %d)." % rc)
        return False
    # A freshly built database has empty StudyPlan / Recommendation tables, so the
    # "Study Plan" page would be blank out of the box. Run the engine once here so
    # the first launch already has complete data.
    print("\nGenerating study plans for all students (six-rule engine + model)...")
    rc = subprocess.call([sys.executable, "-X", "utf8", "recommendation_engine.py"],
                         cwd=str(SRC), env=env)
    if rc != 0:
        print("Plan generation failed (exit code %d). The web UI still starts; "
              "run 'Generate all plans' from the Pipeline page." % rc)
    print("\nDatabase ready: %s" % DB_PATH)
    return True


def main():
    ap = argparse.ArgumentParser(
        description="DSC5003 Student Information Management System - Web Edition")
    ap.add_argument("--port", type=int, default=None, help="listen on this port")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open a browser automatically")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild the database before serving (deletes the existing db)")
    a = ap.parse_args()

    if not SRC.is_dir():
        sys.exit("src/ not found; keep web_app.py next to src/: %s" % ROOT)
    if not ensure_db(a.rebuild):
        sys.exit(1)

    port = free_port(a.port)
    url = "http://127.0.0.1:%d/" % port
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True

    print("=" * 68)
    print("DSC5003 Student Information Management System - Web Edition")
    print("URL      : %s" % url)
    print("Database : %s" % DB_PATH)
    print("Stop     : press Ctrl+C in this window")
    print("=" * 68)
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
