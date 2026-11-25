-- =====================================================================
--  DSC5003 Storing and Retrieving Data
--  Student Information Management System — SQLite schema
--  Target DBMS : SQLite 3.x  (portable, zero-install; see schema_mysql.sql
--                  for the MySQL/InnoDB dialect of the same design)
--  Generated   : 2026-11-17
-- =====================================================================
--
--  DESIGN NOTE — why these tables and not fewer
--  --------------------------------------------
--  The schema is normalised to 3NF. Two normalisation decisions are worth
--  calling out because they are the kind of thing this course examines:
--
--  1. GRADEPOINT IS NOT STORED ON Enrolment.
--     grade_point is functionally determined by grade alone
--     (grade -> grade_point), so keeping it beside the grade in the
--     enrolment row would create the transitive dependency
--         (student_id, course_code, academic_year, semester)
--             -> grade -> grade_point
--     and violate 3NF. It would also allow contradictory rows
--     (grade='A' with grade_point=2.0). The lookup table GradeScale
--     removes both problems; grade_point is recovered by JOIN.
--
--  2. AGE IS NOT STORED ON Student.
--     Age is a function of date_of_birth AND of today's date, so a stored
--     age column goes stale silently. Student stores date_of_birth and the
--     view v_student_profile derives age at query time. This is a
--     derived-attribute decision, not a normal-form violation, but it is
--     the same principle: store facts, derive consequences.
--
--  DESIGN NOTE — the 4-to-6-courses-per-semester rule
--  ---------------------------------------------------
--  This is a CROSS-ROW (aggregate) constraint. It cannot be written as a
--  table-level CHECK, because CHECK sees one row at a time. Two options:
--    (a) enforce it in the application / generator layer, or
--    (b) enforce it with a trigger.
--  This schema does BOTH: triggers trg_enrolment_max_sem_courses and
--  trg_enrolment_min_checked are the declarative guard rails, and
--  build_database.py asserts the final counts after loading. The query
--  q_constraint_audit.sql re-verifies it against the stored data.
--
--  PROVENANCE — what is real and what is simulated
--  -------------------------------------------------
--  course_code / course_title / semester_offered : REAL, scraped 2026-11-17
--      from public HKU 2026-27 course lists (saasweb.hku.hk, cs.hku.hk,
--      hkumath.hku.hk).
--  programme_code : 6999, 6200, 6729, 6779 VERIFIED from HKU admissions /
--      programme pages.
--  prerequisites, credits : SIMULATED from HKU's 1xxx->4xxx level convention
--      and department structure. Official per-course prerequisite lists were
--      NOT individually fetched.
--  students, grades : SYNTHETIC. No real personal data is used.
-- =====================================================================

PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_prereq_gap;
DROP VIEW   IF EXISTS v_enrolment_prereq_violation;
DROP VIEW   IF EXISTS v_latest_enrolment;
DROP VIEW   IF EXISTS v_programme_rank;
DROP VIEW   IF EXISTS v_course_stats;
DROP VIEW   IF EXISTS v_student_gpa;
DROP VIEW   IF EXISTS v_student_profile;
DROP TRIGGER IF EXISTS trg_enrolment_min_checked;
DROP TRIGGER IF EXISTS trg_enrolment_max_sem_courses;
DROP TABLE  IF EXISTS PlanCourse;
DROP TABLE  IF EXISTS Recommendation;
DROP TABLE  IF EXISTS StudyPlan;
DROP TABLE  IF EXISTS Enrolment;
DROP TABLE  IF EXISTS GradeScale;
DROP TABLE  IF EXISTS ProgrammeCourse;
DROP TABLE  IF EXISTS Prerequisite;
DROP TABLE  IF EXISTS Course;
DROP TABLE  IF EXISTS Student;
DROP TABLE  IF EXISTS Programme;
DROP TABLE  IF EXISTS Department;

-- ---------------------------------------------------------------------
-- Department — small lookup table. Kept separate so that Course and
-- Programme can both reference it instead of repeating full names.
-- ---------------------------------------------------------------------
CREATE TABLE Department (
    dept_code   VARCHAR(10)  PRIMARY KEY,
    dept_name   VARCHAR(140) NOT NULL
);

INSERT INTO Department (dept_code, dept_name) VALUES
 ('COMP', 'Department of Computer Science'),
 ('SDST', 'Department of Statistics and Actuarial Science'),
 ('ASAI', 'Applied Artificial Intelligence'),
 ('APAI', 'Applied Artificial Intelligence (postgraduate)'),
 ('MATH', 'Department of Mathematics');

-- ---------------------------------------------------------------------
-- Programme — the four undergraduate programmes in scope.
-- programme_code values are the real HKU admissions codes.
-- ---------------------------------------------------------------------
CREATE TABLE Programme (
    programme_code  CHAR(4)      PRIMARY KEY,
    programme_name  VARCHAR(120) NOT NULL,
    degree_title    VARCHAR(70)  NOT NULL,
    primary_dept    VARCHAR(10)  NOT NULL,
    FOREIGN KEY (primary_dept) REFERENCES Department(dept_code)
);

INSERT INTO Programme
 (programme_code, programme_name, degree_title, primary_dept) VALUES
 ('6999', 'Computer Science',               'BEng in Computer Science',
                                                        'COMP'),
 ('6200', 'Artificial Intelligence and Data Science',
                                            'BEng in AI and Data Science',
                                                        'ASAI'),
 ('6729', 'Actuarial Science',              'BSc in Actuarial Science',
                                                        'SDST'),
 ('6779', 'Statistical Decision Sciences',  'BStat in Statistical Decision Sciences',
                                                        'SDST');

-- ---------------------------------------------------------------------
-- Student — one row per person.
--   * date_of_birth stored, age derived in v_student_profile
--   * phone_hk is exactly 8 digits and must start 5/6/7/8/9 (HK mobile)
--   * email is unique and must sit in the student domain
--   * year_of_study 1..4 for a four-year curriculum
-- ---------------------------------------------------------------------
CREATE TABLE Student (
    student_id      CHAR(10)     PRIMARY KEY,
    name_en         VARCHAR(90)  NOT NULL,
    name_zh         VARCHAR(40),
    gender          CHAR(1)      NOT NULL DEFAULT 'U'
                    CHECK (gender IN ('M','F','U')),
    date_of_birth   DATE         NOT NULL,
    phone_hk        CHAR(8)      NOT NULL
                    CHECK (phone_hk GLOB '[56789][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    email           VARCHAR(100) NOT NULL UNIQUE
                    CHECK (email LIKE '%@connect.hku.hk'),
    admission_year  SMALLINT     NOT NULL
                    CHECK (admission_year BETWEEN 2022 AND 2026),
    year_of_study   SMALLINT     NOT NULL
                    CHECK (year_of_study BETWEEN 1 AND 4),
    programme_code  CHAR(4)      NOT NULL,
    FOREIGN KEY (programme_code) REFERENCES Programme(programme_code)
);

CREATE INDEX idx_student_programme ON Student(programme_code);
CREATE INDEX idx_student_year      ON Student(year_of_study);

-- ---------------------------------------------------------------------
-- Course — the 2026-27 catalogue.
--   semester_offered: 1 = first semester, 2 = second, 0 = both / year-long
--   course_level    : derived from the code (COMP3278 -> 3)
-- ---------------------------------------------------------------------
CREATE TABLE Course (
    course_code       VARCHAR(10)  PRIMARY KEY,
    course_title      VARCHAR(160) NOT NULL,
    department        VARCHAR(10)  NOT NULL,
    credits           SMALLINT     NOT NULL CHECK (credits > 0),
    semester_offered  SMALLINT     NOT NULL CHECK (semester_offered IN (0,1,2)),
    course_level      SMALLINT     NOT NULL CHECK (course_level BETWEEN 1 AND 4),
    is_core           BOOLEAN      NOT NULL DEFAULT 0,
    FOREIGN KEY (department) REFERENCES Department(dept_code)
);

CREATE INDEX idx_course_dept   ON Course(department);
CREATE INDEX idx_course_level  ON Course(course_level);
CREATE INDEX idx_course_sem    ON Course(semester_offered);

-- ---------------------------------------------------------------------
-- Prerequisite — self-referencing many-to-many on Course.
--   "course_code requires prereq_code to be completed and passed first".
--   The CHECK rules out a course being its own prerequisite; acyclicity
--   cannot be expressed declaratively and is asserted by the loader and
--   by q_constraint_audit.sql.
-- ---------------------------------------------------------------------
CREATE TABLE Prerequisite (
    course_code  VARCHAR(10) NOT NULL,
    prereq_code  VARCHAR(10) NOT NULL,
    PRIMARY KEY (course_code, prereq_code),
    CHECK (course_code <> prereq_code),
    FOREIGN KEY (course_code) REFERENCES Course(course_code) ON DELETE CASCADE,
    FOREIGN KEY (prereq_code) REFERENCES Course(course_code) ON DELETE CASCADE
);

CREATE INDEX idx_prereq_of ON Prerequisite(prereq_code);

-- ---------------------------------------------------------------------
-- ProgrammeCourse — which courses belong to which curriculum, and how.
--   requirement_type : CORE    = compulsory for the major
--                      FOUNDATION = compulsory maths/stat service course
--                      ELECTIVE   = counts towards major electives
--   recommended_year : the year the programme suggests taking it
-- Without this table the engine cannot tell "course this student has not
-- taken" from "course this student's programme does not require".
-- ---------------------------------------------------------------------
CREATE TABLE ProgrammeCourse (
    programme_code    CHAR(4)      NOT NULL,
    course_code       VARCHAR(10)  NOT NULL,
    requirement_type  VARCHAR(12)  NOT NULL
                      CHECK (requirement_type IN ('CORE','FOUNDATION','ELECTIVE')),
    recommended_year  SMALLINT     NOT NULL
                      CHECK (recommended_year BETWEEN 1 AND 4),
    PRIMARY KEY (programme_code, course_code),
    FOREIGN KEY (programme_code) REFERENCES Programme(programme_code) ON DELETE CASCADE,
    FOREIGN KEY (course_code)    REFERENCES Course(course_code)       ON DELETE CASCADE
);

CREATE INDEX idx_pc_course ON ProgrammeCourse(course_code);

-- ---------------------------------------------------------------------
-- GradeScale — lookup table that breaks the grade -> grade_point
-- transitive dependency (see DESIGN NOTE 1 above).
--   grade_order gives a total ordering for MIN/MAX/window comparisons.
-- ---------------------------------------------------------------------
CREATE TABLE GradeScale (
    grade        CHAR(2)     PRIMARY KEY,
    grade_point  NUMERIC(3,1) NOT NULL CHECK (grade_point BETWEEN 0 AND 4.3),
    grade_order  SMALLINT    NOT NULL UNIQUE,
    is_passing   BOOLEAN     NOT NULL,
    description  VARCHAR(40) NOT NULL
);

INSERT INTO GradeScale (grade, grade_point, grade_order, is_passing, description) VALUES
 ('A+', 4.3, 13, 1, 'Excellent'),
 ('A',  4.0, 12, 1, 'Excellent'),
 ('A-', 3.7, 11, 1, 'Excellent'),
 ('B+', 3.3, 10, 1, 'Good'),
 ('B',  3.0,  9, 1, 'Good'),
 ('B-', 2.7,  8, 1, 'Good'),
 ('C+', 2.3,  7, 1, 'Satisfactory'),
 ('C',  2.0,  6, 1, 'Satisfactory'),
 ('C-', 1.7,  5, 1, 'Satisfactory'),
 ('D+', 1.3,  4, 1, 'Pass'),
 ('D',  1.0,  3, 1, 'Pass'),
 ('F',  0.0,  1, 0, 'Fail');

-- ---------------------------------------------------------------------
-- Enrolment — the many-to-many association between Student and Course,
-- resolved per (academic_year, semester). Carries the grade.
--   PK is the full candidate key, so every non-key attribute
--   (grade, is_repeat) depends on the WHOLE key -> 2NF satisfied.
--   grade is nullable: a row can exist for a course in progress.
--   is_repeat flags a retake, which lets the engine tell a first attempt
--   from a second without inferring it from duplicate course rows.
-- ---------------------------------------------------------------------
CREATE TABLE Enrolment (
    student_id     CHAR(10)     NOT NULL,
    course_code    VARCHAR(10)  NOT NULL,
    academic_year  CHAR(9)      NOT NULL,      -- e.g. '2025-26'
    semester       SMALLINT     NOT NULL CHECK (semester IN (1,2)),
    grade          CHAR(2),
    is_repeat      BOOLEAN      NOT NULL DEFAULT 0,
    PRIMARY KEY (student_id, course_code, academic_year, semester),
    CHECK (academic_year GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    FOREIGN KEY (student_id)  REFERENCES Student(student_id)   ON DELETE CASCADE,
    FOREIGN KEY (course_code) REFERENCES Course(course_code)   ON DELETE CASCADE,
    FOREIGN KEY (grade)       REFERENCES GradeScale(grade)
);

CREATE INDEX idx_enrol_course  ON Enrolment(course_code);
CREATE INDEX idx_enrol_term    ON Enrolment(academic_year, semester);
CREATE INDEX idx_enrol_grade   ON Enrolment(grade);

-- ---------------------------------------------------------------------
-- TRIGGER 1 — hard cap of 6 courses per student per semester.
-- Fires after an insert and aborts the statement if that student's
-- course count for the term would exceed 6. This is the declarative
-- half of the "at most 6 courses" business rule.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_enrolment_max_sem_courses
AFTER INSERT ON Enrolment
BEGIN
    SELECT CASE
        WHEN (SELECT COUNT(*) FROM Enrolment
               WHERE student_id    = NEW.student_id
                 AND academic_year = NEW.academic_year
                 AND semester      = NEW.semester) > 6
        THEN RAISE(ABORT,
             'Business rule violated: more than 6 courses in one semester')
    END;
END;

-- ---------------------------------------------------------------------
-- TRIGGER 2 — grade validity guard.
-- Rejects a grade that is not on the official scale, in case a row is
-- inserted by hand rather than through the generator (the FK already
-- blocks unknown grades; this gives a clearer message and also blocks
-- a blank/whitespace string that some clients send instead of NULL).
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_enrolment_min_checked
BEFORE INSERT ON Enrolment
WHEN NEW.grade IS NOT NULL AND TRIM(NEW.grade) = ''
BEGIN
    SELECT RAISE(ABORT,
        'grade must be NULL or a valid GradeScale code, not an empty string');
END;

-- ---------------------------------------------------------------------
-- StudyPlan — one planning summary per student per target semester.
-- This is the "header" of the recommendation; Recommendation rows are
-- its line items. Splitting them keeps each Recommendation atomic (one
-- action, one rule id, one rationale) instead of stuffing a list into
-- a single column, which would break 1NF.
-- ---------------------------------------------------------------------
CREATE TABLE StudyPlan (
    plan_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id               CHAR(10)     NOT NULL,
    target_academic_year     CHAR(9)      NOT NULL,
    target_semester          SMALLINT     NOT NULL CHECK (target_semester IN (1,2)),
    generated_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cumulative_gpa           NUMERIC(4,3) NOT NULL,
    credits_completed        INTEGER      NOT NULL DEFAULT 0,
    gpa_band                 VARCHAR(16)  NOT NULL,
    recommended_course_count SMALLINT     NOT NULL
                             CHECK (recommended_course_count BETWEEN 0 AND 6),
    recommended_credits      INTEGER      NOT NULL DEFAULT 0,
    n_retake                 SMALLINT     NOT NULL DEFAULT 0,
    n_extra_effort           SMALLINT     NOT NULL DEFAULT 0,
    n_swap                   SMALLINT     NOT NULL DEFAULT 0,
    n_prereq_gap             SMALLINT     NOT NULL DEFAULT 0,
    need_major_adjustment    BOOLEAN      NOT NULL DEFAULT 0,
    major_adjust_reason      VARCHAR(200),
    risk_level               VARCHAR(10)  NOT NULL DEFAULT 'LOW'
                             CHECK (risk_level IN ('LOW','MEDIUM','HIGH')),
    UNIQUE (student_id, target_academic_year, target_semester),
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE INDEX idx_plan_term ON StudyPlan(target_academic_year, target_semester);

-- ---------------------------------------------------------------------
-- Recommendation — one actionable line item.
--   rec_type  : the kind of advice (see CHECK list)
--   rule_id   : which engine rule produced it, so every recommendation
--               is traceable to a written rule (requirement from the brief)
--   rationale_en / rationale_zh : bilingual because the report is bilingual
--   source    : 'RULE' for deterministic rules, 'MODEL' for the
--               statistical model, 'BOTH' when they agree
--   model_risk_score : the auxiliary statistical model's output; NULL for
--               pure-rule recommendations. The model ADVISES, it never
--               decides on its own.
--   confidence : model probability when source involves the model
-- ---------------------------------------------------------------------
CREATE TABLE PlanCourse (
    plan_id      INTEGER     NOT NULL,
    position     SMALLINT    NOT NULL CHECK (position > 0),
    course_code  VARCHAR(10) NOT NULL,
    PRIMARY KEY (plan_id, position),
    UNIQUE (plan_id, course_code),
    FOREIGN KEY (plan_id) REFERENCES StudyPlan(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (course_code) REFERENCES Course(course_code)
);

CREATE TABLE Recommendation (
    rec_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id          INTEGER      NOT NULL,
    student_id       CHAR(10)     NOT NULL,
    rec_type         VARCHAR(18)  NOT NULL
                     CHECK (rec_type IN (
                         'COURSE_LOAD','RETAKES','EXTRA_EFFORT',
                         'SWAP_COURSE','MAJOR_ADJUST','PREREQ_GAP')),
    course_code      VARCHAR(10),
    rule_id          VARCHAR(20)  NOT NULL,
    rationale_en     TEXT         NOT NULL,
    rationale_zh     TEXT         NOT NULL,
    priority         SMALLINT     NOT NULL DEFAULT 3
                     CHECK (priority BETWEEN 1 AND 5),
    source           VARCHAR(6)   NOT NULL DEFAULT 'RULE'
                     CHECK (source IN ('RULE','MODEL','BOTH')),
    model_risk_score NUMERIC(5,4),
    confidence       NUMERIC(5,4),
    generated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id)      REFERENCES StudyPlan(plan_id)     ON DELETE CASCADE,
    FOREIGN KEY (student_id)   REFERENCES Student(student_id)    ON DELETE CASCADE,
    FOREIGN KEY (course_code)  REFERENCES Course(course_code)
);

CREATE INDEX idx_rec_plan    ON Recommendation(plan_id);
CREATE INDEX idx_rec_student ON Recommendation(student_id);
CREATE INDEX idx_rec_type    ON Recommendation(rec_type);
CREATE INDEX idx_rec_course  ON Recommendation(course_code);

-- =====================================================================
--  VIEWS — derived facts, so no attribute is stored twice.
-- =====================================================================

-- v_student_profile : Student plus the derived age and programme name.
-- This is what the management system shows; age is always current.
CREATE VIEW v_student_profile AS
SELECT
    s.student_id,
    s.name_en,
    s.name_zh,
    s.gender,
    s.date_of_birth,
    CAST(
        (strftime('%Y','now') - strftime('%Y', s.date_of_birth))
        - (CASE WHEN strftime('%m-%d','now') < strftime('%m-%d', s.date_of_birth)
                THEN 1 ELSE 0 END)
    AS INTEGER)                              AS age,
    s.phone_hk,
    s.email,
    s.admission_year,
    s.year_of_study,
    s.programme_code,
    p.programme_name
FROM Student s
JOIN Programme p ON p.programme_code = s.programme_code;

-- v_student_gpa : cumulative GPA and credit totals per student.
-- grade_point comes from the GradeScale lookup, never from a stored copy.

-- Current standing uses the most recent graded attempt. An in-progress
-- enrolment with NULL grade does not replace a completed result.
CREATE VIEW v_latest_enrolment AS
SELECT e.student_id, e.course_code, e.academic_year, e.semester, e.grade,
       e.is_repeat, g.grade_point, g.is_passing
FROM Enrolment e JOIN GradeScale g ON g.grade = e.grade
WHERE NOT EXISTS (
    SELECT 1 FROM Enrolment newer
    WHERE newer.student_id = e.student_id AND newer.course_code = e.course_code
      AND newer.grade IS NOT NULL
      AND (newer.academic_year, newer.semester) > (e.academic_year, e.semester)
);

-- Historical eligibility uses the latest graded result strictly before the
-- dependent term. Later passes and passes during that same term do not qualify.
CREATE VIEW v_enrolment_prereq_violation AS
SELECT e.student_id, e.course_code, e.academic_year, e.semester, pr.prereq_code
FROM Enrolment e JOIN Prerequisite pr ON pr.course_code = e.course_code
WHERE COALESCE((
    SELECT g.is_passing
    FROM Enrolment h JOIN GradeScale g ON g.grade = h.grade
    WHERE h.student_id = e.student_id AND h.course_code = pr.prereq_code
      AND (h.academic_year, h.semester) < (e.academic_year, e.semester)
    ORDER BY h.academic_year DESC, h.semester DESC
    LIMIT 1
), 0) = 0;

-- CGPA includes the credit weight of every graded attempt, including F.
CREATE VIEW v_student_gpa AS
SELECT
    e.student_id,
    COUNT(*)                                        AS courses_taken,
    SUM(c.credits)                                  AS credits_attempted,
    SUM(CASE WHEN g.is_passing = 1 THEN c.credits ELSE 0 END)
                                                    AS credits_passed,
    ROUND(SUM(c.credits * g.grade_point) * 1.0 / NULLIF(SUM(c.credits),0), 3)
                                                    AS cumulative_gpa,
    SUM(CASE WHEN g.is_passing = 0 THEN 1 ELSE 0 END)
                                                    AS n_failed,
    MAX(e.academic_year || '-' || e.semester)       AS last_term
FROM Enrolment e
JOIN Course      c ON c.course_code = e.course_code
JOIN GradeScale  g ON g.grade       = e.grade
WHERE e.grade IS NOT NULL
GROUP BY e.student_id;

-- v_course_stats : per-course difficulty profile used by the engine to
-- compare a student against peers taking the SAME course (fairer than
-- comparing a student's raw mark across courses of different difficulty).
CREATE VIEW v_course_stats AS
SELECT
    e.course_code,
    c.course_title,
    c.department,
    c.course_level,
    COUNT(*)                                  AS n_taken,
    ROUND(AVG(g.grade_point), 3)              AS mean_grade_point,
    ROUND(AVG(CASE WHEN g.is_passing=0 THEN 100.0 ELSE 0.0 END), 2)
                                              AS fail_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN g.grade_point <= 1.7 THEN 1 ELSE 0 END)
                / COUNT(*), 2)                AS weak_rate_pct
FROM Enrolment e
JOIN Course     c ON c.course_code = e.course_code
JOIN GradeScale g ON g.grade       = e.grade
WHERE e.grade IS NOT NULL
GROUP BY e.course_code, c.course_title, c.department, c.course_level;

-- v_programme_rank : rank of each student inside their own programme.
-- Window functions are the point here; a correlated subquery would be
-- far more expensive on 1000 students x several thousand enrolments.
--
-- gpa_percentile_top means "the student sits in the top N% of the programme".
-- It must be rank/size, NOT (size-rank+1)/size: rank 1 of 342 is the top
-- 0.3%, and rank 342 of 342 is the top 100%. An earlier version had this
-- inverted, so the strongest students were labelled "top 100%" and the
-- weakest "top 0.3%".
CREATE VIEW v_programme_rank AS
SELECT
    g.student_id,
    s.programme_code,
    s.year_of_study,
    g.cumulative_gpa,
    g.courses_taken,
    RANK() OVER (PARTITION BY s.programme_code
                 ORDER BY g.cumulative_gpa DESC)          AS gpa_rank,
    COUNT(*) OVER (PARTITION BY s.programme_code)         AS programme_size,
    ROUND(100.0 * RANK() OVER (PARTITION BY s.programme_code
                               ORDER BY g.cumulative_gpa DESC)
          / COUNT(*) OVER (PARTITION BY s.programme_code), 2)
                                                          AS gpa_percentile_top
FROM v_student_gpa g
JOIN Student s ON s.student_id = g.student_id;

-- v_prereq_gap : for each student, the required courses whose
-- prerequisites are not yet passed. This drives the PREREQ_GAP
-- recommendation and is a pure relational query — no application logic.
CREATE VIEW v_prereq_gap AS
SELECT
    s.student_id,
    s.programme_code,
    pc.course_code            AS blocked_course,
    c.course_title            AS blocked_title,
    pr.prereq_code            AS missing_prereq,
    pc2.course_title          AS missing_prereq_title,
    pc.requirement_type,
    pc.recommended_year
FROM Student s
JOIN ProgrammeCourse pc ON pc.programme_code = s.programme_code
JOIN Course c           ON c.course_code      = pc.course_code
JOIN Prerequisite pr    ON pr.course_code     = pc.course_code
JOIN Course pc2         ON pc2.course_code    = pr.prereq_code
WHERE NOT EXISTS (
    SELECT 1 FROM v_latest_enrolment current_grade
    WHERE current_grade.student_id = s.student_id
      AND current_grade.course_code = pr.prereq_code AND current_grade.is_passing = 1
)
AND NOT EXISTS (
    SELECT 1 FROM Enrolment target
    WHERE target.student_id = s.student_id AND target.course_code = pc.course_code
);

-- =====================================================================
--  Post-load integrity assertions. Run these after building the DB;
--  every query must return 0 rows / the expected value.
-- =====================================================================
-- 1000 students:
--   SELECT COUNT(*) FROM Student;                                   -> 1000
-- No orphan enrolments:
--   SELECT COUNT(*) FROM Enrolment e
--    WHERE NOT EXISTS (SELECT 1 FROM Student s WHERE s.student_id=e.student_id);  -> 0
-- Every student has 4..6 courses in every enrolled semester:
--   SELECT student_id, academic_year, semester, COUNT(*) n FROM Enrolment
--    GROUP BY student_id, academic_year, semester
--   HAVING n < 4 OR n > 6;                                          -> 0 rows
-- No student retakes a course in the same term they first took it:
--   SELECT student_id, course_code, academic_year, semester, COUNT(*) n
--     FROM Enrolment GROUP BY student_id, course_code, academic_year, semester
--    HAVING n > 1;                                                  -> 0 rows
-- =====================================================================

-- Validate new enrolments and preserve eligibility when historical grades change.
CREATE TRIGGER trg_enrolment_rules_insert
AFTER INSERT ON Enrolment
BEGIN
    SELECT RAISE(ABORT, 'Course is not offered in this semester')
    WHERE NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code = NEW.course_code
          AND c.semester_offered IN (0, NEW.semester));
    SELECT RAISE(ABORT, 'A passed course cannot be selected again')
    WHERE EXISTS (
        SELECT 1 FROM Enrolment earlier JOIN GradeScale g ON g.grade = earlier.grade
        JOIN Enrolment later ON later.student_id = earlier.student_id
                            AND later.course_code = earlier.course_code
        WHERE earlier.student_id = NEW.student_id AND earlier.course_code = NEW.course_code
          AND g.is_passing = 1
          AND (earlier.academic_year, earlier.semester) < (later.academic_year, later.semester)
    );
    SELECT RAISE(ABORT, 'An enrolment requires a passing prerequisite from an earlier semester')
    WHERE EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = NEW.student_id
          AND (v.course_code = NEW.course_code OR v.prereq_code = NEW.course_code)
    );
END;

CREATE TRIGGER trg_enrolment_rules_update
AFTER UPDATE ON Enrolment
BEGIN
    SELECT RAISE(ABORT, 'Business rule violated: more than 6 courses in one semester')
    WHERE (SELECT COUNT(*) FROM Enrolment e WHERE e.student_id = NEW.student_id
       AND e.academic_year = NEW.academic_year AND e.semester = NEW.semester) > 6;
    SELECT RAISE(ABORT, 'Course is not offered in this semester')
    WHERE NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code = NEW.course_code
          AND c.semester_offered IN (0, NEW.semester));
    SELECT RAISE(ABORT, 'A passed course cannot be selected again')
    WHERE EXISTS (
        SELECT 1 FROM Enrolment earlier JOIN GradeScale g ON g.grade = earlier.grade
        JOIN Enrolment later ON later.student_id = earlier.student_id
                            AND later.course_code = earlier.course_code
        WHERE earlier.student_id = NEW.student_id AND earlier.course_code = NEW.course_code
          AND g.is_passing = 1
          AND (earlier.academic_year, earlier.semester) < (later.academic_year, later.semester)
    );
    SELECT RAISE(ABORT, 'An enrolment requires a passing prerequisite from an earlier semester')
    WHERE EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = NEW.student_id
          AND (v.course_code = NEW.course_code OR v.prereq_code = NEW.course_code)
    );
    SELECT RAISE(ABORT, 'This change would invalidate a later enrolment prerequisite')
    WHERE EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = OLD.student_id AND v.prereq_code = OLD.course_code
    );
END;

CREATE TRIGGER trg_enrolment_rules_delete
AFTER DELETE ON Enrolment
BEGIN
    SELECT RAISE(ABORT, 'This change would invalidate a later enrolment prerequisite')
    WHERE EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = OLD.student_id AND v.prereq_code = OLD.course_code
    );
END;
