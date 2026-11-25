"""Project-wide configuration and constants.

DSC5003 Storing and Retrieving Data — Student Information Management System
Course catalogue simulated from HKU 2026-27 public course lists.

Nothing here touches the network; all paths resolve relative to the project
root so the pipeline is portable.
"""
from pathlib import Path

# --- locations ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SQL_DIR = PROJECT_ROOT / "sql"
OUTPUT_DIR = PROJECT_ROOT / "output"
FIGURE_DIR = OUTPUT_DIR / "figures"
REPORT_DIR = PROJECT_ROOT / "report"

DB_PATH = DATA_DIR / "student_info.db"

for _d in (DATA_DIR, SQL_DIR, OUTPUT_DIR, FIGURE_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- domain constants -----------------------------------------------------
N_STUDENTS = 1000
MIN_COURSES_PER_SEM = 4
MAX_COURSES_PER_SEM = 6

# Simulated semester history. Every student must have at least one COMPLETED
# term, otherwise the recommendation engine has no grades to reason about —
# so Year 1 students have a grade history in 2025-26 semester 2 and we plan for
# 2026-27 semester 1.
SEMESTERS = [
    ("2023-24", 1), ("2023-24", 2),
    ("2024-25", 1), ("2024-25", 2),
    ("2025-26", 1), ("2025-26", 2),
]

# How many past terms each year-of-study has already completed.
#   Year 4 (admitted 2022) -> all 6 terms
#   Year 3 (admitted 2023) -> 4 terms
#   Year 2 (admitted 2024) -> 2 terms
#   Year 1 (admitted 2025) -> 1 term  (2025-26 sem 2, already graded)
TERMS_DONE_BY_YEAR = {4: 6, 3: 4, 2: 2, 1: 1}
ADMISSION_YEAR_BY_YEAR = {4: 2022, 3: 2023, 2: 2024, 1: 2025}


def completed_terms(year_of_study):
    """Return the list of (academic_year, semester) a student has finished."""
    n = TERMS_DONE_BY_YEAR.get(year_of_study, 0)
    return SEMESTERS[len(SEMESTERS) - n:] if n else []


CURRENT_YEAR = 2025
CURRENT_SEM = 2
NEXT_YEAR = 2026
NEXT_SEM = 1          # the semester we plan for
NEXT_TERM = ("2026-27", 1)

# Numerical letter grades from HKU Undergraduate Regulation UG8.
GRADE_SCALE = {
    "A+": 4.3, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D+": 1.3, "D": 1.0,
    "F":  0.0,
}
PASSING_GRADES = {g for g, p in GRADE_SCALE.items() if p >= 1.0}
FAIL_GRADE = "F"

# --- reproducibility ------------------------------------------------------
RANDOM_SEED = 2026005003   # DSC5003 → memorable, fixed for reproducibility

# --- provenance flags (honesty: what is real vs. simulated) ---------------
PROVENANCE = {
    "course_code_title_semester":
        "Catalogue entries draw on the HKU course lists cited in course_catalogue.py "
        "(saasweb.hku.hk, cs.hku.hk, hkumath.hku.hk)",
    "prerequisite_chain":
        "SIMULATED — built from HKU's 1xxx→2xxx→3xxx→4xxx level convention "
        "and department structure; official per-course prerequisites were NOT "
        "individually fetched",
    "programme_code":
        "The project uses four cohort identifiers: 6999 (Computer Science), "
        "6200 (AI and Data Science), 6729 (Actuarial Science), and "
        "6779 (Statistical Decision Sciences). Curriculum mappings are simulated.",
    "credits":
        "SIMULATED — HKU undergraduate courses are commonly 6 credits; not "
        "verified per course",
    "students_grades":
        "SYNTHETIC — no real student data is used; generated with a latent "
        "ability model so that recommendations can be validated",
}
