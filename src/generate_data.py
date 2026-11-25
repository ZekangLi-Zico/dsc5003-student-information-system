"""Synthetic enrolment generator driven by a latent ability model.

WHY A LATENT MODEL RATHER THAN RANDOM GRADES
--------------------------------------------
If grades were drawn independently at random, the recommendation engine would
have nothing real to find: retake advice, prerequisite gaps and risk scores
would all be noise, and no validation would be possible. Instead every grade
is produced by an explicit generative process

    z(student, course, term) =
          ability                     student's underlying academic strength
        + year_effect                 improvement (or decline) as they progress
        + prereq_transfer             performance carried over from prerequisites
        - difficulty                  intrinsic hardness of the course
        + noise                       irreducible randomness

and z is then mapped onto the HKU letter-grade scale. The model has a known
ground truth (each student's latent ability), so Section 8 of the report can
measure whether the engine's risk flags actually correlate with real outcomes
instead of merely asserting that they do.

The seed reproduces the synthetic student and enrolment rows.
"""
import math
import random

import config as C
from course_catalogue import CATALOGUE, BY_CODE

# --- programme curriculum mapping -----------------------------------------
# requirement_type: CORE / FOUNDATION / ELECTIVE.
# FOUNDATION = compulsory maths/stat service courses taken by all four
# programmes; CORE = compulsory for that major; ELECTIVE = counts towards
# major electives. recommended_year is derived from the course level.

FOUNDATION = {
    "6999": ["MATH1013", "MATH1853", "MATH2014", "MATH2101", "SDST2601",
             "SDST2602", "COMP2121", "MATH3600"],
    "6200": ["MATH1013", "MATH1851", "MATH2014", "MATH2101", "SDST2601",
             "SDST2602", "COMP2121", "MATH3900"],
    "6729": ["MATH1821", "MATH2822", "MATH1851", "MATH2211", "MATH3906",
             "MATH2014", "SDST1600"],
    "6779": ["MATH1013", "MATH2014", "MATH2101", "COMP1117", "SDST1018",
             "MATH3900", "MATH2211"],
}

CORE = {
    "6999": ["COMP1110", "COMP1117", "COMP2113", "COMP2119", "COMP2120",
             "COMP3230", "COMP3234", "COMP3251", "COMP3278", "COMP3297",
             "COMP3314", "COMP4502", "COMP3312", "COMP3522"],
    "6200": ["COMP1110", "COMP1117", "COMP2119", "COMP2501", "COMP3270",
             "COMP3314", "COMP3340", "ASAI1001", "ASAI3010", "ASAI4011",
             "ASAI4013", "COMP3522", "COMP4501", "COMP3312"],
    "6729": ["SDST1603", "SDST2901", "SDST2902", "SDST3901", "SDST3905",
             "SDST3906", "SDST3908", "SDST3909", "SDST3910", "SDST3911",
             "SDST3953", "SDST3956", "SDST4711", "SDST3902"],
    "6779": ["SDST1016", "SDST1018", "SDST1603", "SDST2601", "SDST2602",
             "SDST3600", "SDST3602", "SDST3612", "SDST3621", "SDST3622",
             "SDST4601", "SDST4602", "SDST4710", "SDST3902"],
}

ELECTIVE = {
    "6999": ["COMP2396", "COMP3231", "COMP3235", "COMP3258", "COMP3259",
             "COMP3271", "COMP3317", "COMP3322", "COMP3323", "COMP3329",
             "COMP3330", "COMP3355", "COMP3356", "COMP3357", "COMP3358",
             "COMP3513", "COMP3524", "COMP2118", "COMP3252", "FITE2010"],
    "6200": ["COMP3231", "COMP3317", "COMP3322", "COMP3323", "COMP3340",
             "COMP3353", "COMP3354", "COMP3356", "COMP3358", "COMP3360",
             "COMP3361", "COMP3513", "COMP3516", "COMP3524", "APAI4012",
             "APAI4099", "ASAI3021", "ASAI4022", "SDST3612", "COMP2396"],
    "6729": ["SDST3603", "SDST3609", "SDST3610", "SDST3615", "SDST3618",
             "SDST3620", "SDST3655", "SDST3903", "SDST3904", "SDST3907",
             "SDST3951", "SDST3954", "SDST4603", "SDST4607", "SDST4608",
             "SDST4610", "SDST4614", "SDST4903", "SDST4904", "MATH3405"],
    "6779": ["SDST3603", "SDST3606", "SDST3613", "SDST3617", "SDST3620",
             "SDST3655", "SDST3903", "SDST3907", "SDST4609", "SDST4610",
             "SDST4602", "COMP2501", "COMP3314", "COMP3278", "MATH3901",
             "MATH3904", "MATH3911", "MATH3943", "MATH4902", "SDST3799"],
}

PROGRAMMES = ["6999", "6200", "6729", "6779"]
# Realistic HKU cohort split: CS largest, then AI&DS, SDS, Actuarial.
PROGRAMME_WEIGHTS = [0.34, 0.24, 0.22, 0.20]

# Mean latent ability per programme. These were tuned so that the generated
# grade distribution resembles a real HKU cohort:
#   roughly A 20% / B 38% / C 30% / D 10% / F 1%, mean GPA near 3.0.
# An earlier setting (0.18..0.34, sd 0.62) produced only 0.24% F grades, which
# left the RETAKES recommendation with almost no data to act on.
PROGRAMME_MEAN_ABILITY = {"6999": 0.15, "6200": 0.22, "6729": 0.05, "6779": 0.10}
ABILITY_SD = 0.75


def build_programme_courses():
    """Flatten the curriculum maps into ProgrammeCourse rows."""
    rows = []
    for prog in PROGRAMMES:
        for ctype, codes in (("FOUNDATION", FOUNDATION[prog]),
                             ("CORE", CORE[prog]),
                             ("ELECTIVE", ELECTIVE[prog])):
            for code in codes:
                if code not in BY_CODE:
                    continue          # catalogue is authoritative
                rec = BY_CODE[code]
                rows.append({
                    "programme_code": prog,
                    "course_code": code,
                    "requirement_type": ctype,
                    "recommended_year": min(4, max(1, rec["course_level"])),
                })
    # de-duplicate (a course could appear in two lists by mistake)
    seen, out = set(), []
    for r in rows:
        k = (r["programme_code"], r["course_code"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# --- deterministic course difficulty --------------------------------------
def course_difficulty(code):
    """Stable difficulty offset in [-0.6, +0.7], derived from the code.

    Derived deterministically from the course code rather than drawn from a
    random stream, so difficulty is a property of the course (shared by every
    student and every term) and survives re-seeding.
    """
    h = 0
    for ch in code:
        h = (h * 131 + ord(ch)) % 100003
    base = (h % 1000) / 1000.0            # 0..1
    level = BY_CODE[code]["course_level"] if code in BY_CODE else 3
    # higher-level courses are systematically harder, with per-course spread
    return -0.6 + base * 0.9 + 0.09 * (level - 1)


DIFFICULTY = {c["course_code"]: course_difficulty(c["course_code"]) for c in CATALOGUE}

# --- grade mapping ---------------------------------------------------------
GRADE_CUTS = [
    (2.00, "A+"), (1.60, "A"), (1.20, "A-"),
    (0.85, "B+"), (0.50, "B"), (0.20, "B-"),
    (-0.10, "C+"), (-0.40, "C"), (-0.75, "C-"),
    (-1.10, "D+"), (-1.45, "D"),
]


def z_to_grade(z):
    for cut, g in GRADE_CUTS:
        if z >= cut:
            return g
    return "F"


def generate_students(rng, n):
    """Student rows: identity (from persona) + latent ability + enrolment plan."""
    from persona import make_people
    people = make_people(rng, n)

    students = []
    for i, p in enumerate(people):
        prog = rng.choices(PROGRAMMES, weights=PROGRAMME_WEIGHTS)[0]
        # year_of_study spread: roughly even across 1..4
        year = rng.choices([1, 2, 3, 4], weights=[0.27, 0.25, 0.25, 0.23])[0]
        admission = C.ADMISSION_YEAR_BY_YEAR[year]
        # date of birth consistent with year_of_study: Year 1 ~18-19, Year 4 ~21-23
        age_at_2026 = 18 + (4 - year) + rng.randint(0, 2)
        birth_year = C.NEXT_YEAR - age_at_2026
        dob = "%04d-%02d-%02d" % (birth_year, rng.randint(1, 12), rng.randint(1, 28))

        ability = max(-2.4, min(2.4, rng.gauss(PROGRAMME_MEAN_ABILITY[prog], ABILITY_SD)))
        # per-student work ethic multiplies how much they improve each year
        diligence = rng.uniform(0.7, 1.35)

        students.append({
            **p,
            "date_of_birth": dob,
            "admission_year": admission,
            "year_of_study": year,
            "programme_code": prog,
            "_ability": ability,
            "_diligence": diligence,
        })
    return students


def _allowed_courses(prog, level_max):
    """Courses this programme may schedule, filtered by level ceiling."""
    allowed = []
    for r in PROGRAMME_COURSE_ROWS:
        if r["programme_code"] != prog:
            continue
        c = BY_CODE[r["course_code"]]
        if c["course_level"] <= level_max:
            allowed.append(r["course_code"])
    return allowed


def _prereqs_passed(code, passed):
    """True when every prerequisite of `code` is in the passed set."""
    for p in BY_CODE[code]["prerequisites"]:
        if p not in passed:
            return False
    return True


def _offered_in(code, semester):
    s = BY_CODE[code]["semester_offered"]
    return s == 0 or s == semester


def generate_enrolments(rng, students):
    """Walk each student term by term, respecting prerequisites, retakes and
    the 4-6 courses per semester rule. Returns enrolment rows.

    Retake handling: a course that was attempted but not passed stays
    eligible (up to MAX_RETAKES extra attempts) and is scheduled with
    priority, so the is_repeat flag and the RETAKES recommendation have a
    real basis in the data.
    """
    MAX_RETAKES = 2
    rows = []
    for st in students:
        ability = st["_ability"]
        diligence = st["_diligence"]
        prog = st["programme_code"]
        year = st["year_of_study"]
        terms = C.completed_terms(year)
        passed = set()          # course codes passed so far
        attempts = {}           # course_code -> number of attempts so far
        z_of = {}               # course_code -> latest completed attempt's latent z

        for t_i, (ay, sem) in enumerate(terms):
            # year_effect: students generally improve, scaled by diligence
            year_effect = 0.10 * t_i * diligence - 0.12 * (1.0 - diligence)

            # Level ceiling starts at 2: once level-1 prerequisites are
            # cleared, first-year students may already take level-2 courses.
            # Starting at 1 made the eligible pool too small, so nearly every
            # term collapsed to the 4-course minimum.
            level_max = min(4, 2 + t_i // 2 + (1 if year >= 3 else 0))

            def eligible(code):
                if code in passed:
                    return False
                if not _offered_in(code, sem):
                    return False
                if not _prereqs_passed(code, passed):
                    return False
                if attempts.get(code, 0) >= 1 + MAX_RETAKES:
                    return False
                return True

            # programme courses first, then any eligible catalogue course
            prog_pool = [r["course_code"] for r in PROGRAMME_COURSE_ROWS
                         if r["programme_code"] == prog
                         and BY_CODE[r["course_code"]]["course_level"] <= level_max
                         and eligible(r["course_code"])]

            req_rank = {}
            for r in PROGRAMME_COURSE_ROWS:
                if r["programme_code"] == prog:
                    req_rank[r["course_code"]] = {
                        "CORE": 0, "FOUNDATION": 1, "ELECTIVE": 2}[r["requirement_type"]]

            def rank_key(code):
                # retakes go first (clear the failure), then by requirement type
                first_attempt = attempts.get(code, 0) == 0
                return (first_attempt, req_rank.get(code, 3),
                        BY_CODE[code]["course_level"], code)

            prog_pool.sort(key=rank_key)

            # target course count for this term
            if t_i == 0:
                k = rng.choices([4, 5, 6], weights=[0.22, 0.44, 0.34])[0]
            else:
                k = rng.choices([4, 5, 6], weights=[0.30, 0.42, 0.28])[0]

            chosen = prog_pool[:k]
            # Top up whenever we are below the term's target k, not merely
            # below the 4-course floor. Previously the top-up only fired when
            # len(chosen) < MIN, so a programme pool of exactly 4 left every
            # term at 4 courses and the 5/6 counts collapsed.
            if len(chosen) < k:
                others = [c["course_code"] for c in CATALOGUE
                          if c["course_code"] not in chosen
                          and c["course_level"] <= level_max
                          and eligible(c["course_code"])]
                others.sort(key=rank_key)
                for code in others:
                    if len(chosen) >= k:
                        break
                    chosen.append(code)
            chosen = chosen[:C.MAX_COURSES_PER_SEM]

            for code in chosen:
                pre_z = [z_of[p] for p in BY_CODE[code]["prerequisites"] if p in z_of]
                prereq_transfer = (0.22 * sum(pre_z) / len(pre_z)) if pre_z else 0.0
                is_repeat = 1 if attempts.get(code, 0) > 0 else 0
                # a retake means the student struggled before; small penalty,
                # partly offset by having had a term to recover
                retake_adj = -0.18 if is_repeat else 0.0

                z = (ability
                     + year_effect
                     + prereq_transfer
                     - DIFFICULTY[code]
                     + retake_adj
                     + rng.gauss(0, 0.52))
                grade = z_to_grade(z)

                rows.append({
                    "student_id": st["student_id"],
                    "course_code": code,
                    "academic_year": ay,
                    "semester": sem,
                    "grade": grade,
                    "is_repeat": is_repeat,
                })

                attempts[code] = attempts.get(code, 0) + 1
                if grade in C.PASSING_GRADES:
                    passed.add(code)
                else:
                    passed.discard(code)
                z_of[code] = z

    return rows


PROGRAMME_COURSE_ROWS = build_programme_courses()


def generate_all(seed=C.RANDOM_SEED, n=C.N_STUDENTS):
    """Return (students, enrolments, programme_courses) ready for insertion."""
    rng = random.Random(seed)
    students = generate_students(rng, n)
    enrolments = generate_enrolments(rng, students)
    return students, enrolments, PROGRAMME_COURSE_ROWS


if __name__ == "__main__":
    students, enrolments, pc = generate_all()
    from collections import Counter, defaultdict

    print("students   :", len(students))
    print("enrolments :", len(enrolments))
    print("prog courses:", len(pc))

    print("\nby programme:", dict(Counter(s["programme_code"] for s in students)))
    print("by year     :", dict(sorted(Counter(s["year_of_study"] for s in students).items())))
    print("grade dist  :", dict(sorted(Counter(e["grade"] for e in enrolments).items(),
                                       key=lambda kv: -C.GRADE_SCALE[kv[0]])))

    # the 4..6 rule
    per = defaultdict(int)
    for e in enrolments:
        per[(e["student_id"], e["academic_year"], e["semester"])] += 1
    counts = Counter(per.values())
    print("\ncourses per student-semester:", dict(sorted(counts.items())))
    bad = {k: v for k, v in per.items() if v < C.MIN_COURSES_PER_SEM or v > C.MAX_COURSES_PER_SEM}
    print("terms violating the 4..6 rule:", len(bad))
    for k, v in list(bad.items())[:5]:
        print("   ", k, v)

    # no duplicate enrolment keys
    keys = Counter((e["student_id"], e["course_code"], e["academic_year"], e["semester"])
                   for e in enrolments)
    print("duplicate enrolment keys:", sum(1 for v in keys.values() if v > 1))

    # mean grade point
    tot = sum(C.GRADE_SCALE[e["grade"]] * BY_CODE[e["course_code"]]["credits"]
              for e in enrolments)
    cr = sum(BY_CODE[e["course_code"]]["credits"] for e in enrolments)
    print("overall weighted mean GPA: %.3f" % (tot / cr))
