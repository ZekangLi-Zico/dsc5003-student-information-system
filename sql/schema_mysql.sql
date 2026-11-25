-- =====================================================================
--  DSC5003 Storing and Retrieving Data
--  Student Information Management System — MySQL 8 / InnoDB dialect
--  Same logical design as schema_sqlite.sql, in vendor syntax.
--  Porting notes are inline; see the SQLite file for the full ER rationale.
-- =====================================================================
--  HOW TO LOAD
--    mysql -u root -p -e "CREATE DATABASE student_info CHARACTER SET utf8mb4;"
--    mysql -u root -p student_info < schema_mysql.sql
--
--  DIFFERENCES FROM THE SQLITE VERSION
--   1. AUTO_INCREMENT replaces INTEGER PRIMARY KEY AUTOINCREMENT.
--   2. Explicit ENGINE=InnoDB so foreign keys are actually enforced
--      (MyISAM silently ignores them).
--   3. CHECK constraints: MySQL 8.0.16+ enforces them; earlier 8.0 parses
--      and IGNORES them. If your server is older, move these rules into
--      BEFORE INSERT triggers exactly as the SQLite file does.
--   4. GLOB '[56789][0-9]...' is SQLite-only; replaced by REGEXP_LIKE().
--      REGEXP_LIKE needs MySQL 8.0+.
--   5. strftime('%Y','now') is SQLite-only; replaced by TIMESTAMPDIFF(YEAR,...)
--      with a correction for the not-yet-reached birthday.
--   6. Window functions (RANK() OVER) need MySQL 8.0+; on 5.7 use a
--      session-variable ranking or a correlated subquery instead.
--   7. BOOLEAN is an alias for TINYINT(1) in MySQL. Values 0/1 work the same.
-- =====================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

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

SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
CREATE TABLE Department (
    dept_code   VARCHAR(10)  NOT NULL,
    dept_name   VARCHAR(140) NOT NULL,
    PRIMARY KEY (dept_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO Department (dept_code, dept_name) VALUES
 ('COMP', 'Department of Computer Science'),
 ('SDST', 'Department of Statistics and Actuarial Science'),
 ('ASAI', 'Applied Artificial Intelligence'),
 ('APAI', 'Applied Artificial Intelligence (postgraduate)'),
 ('MATH', 'Department of Mathematics');

-- ---------------------------------------------------------------------
CREATE TABLE Programme (
    programme_code  CHAR(4)      NOT NULL,
    programme_name  VARCHAR(120) NOT NULL,
    degree_title    VARCHAR(70)  NOT NULL,
    primary_dept    VARCHAR(10)  NOT NULL,
    PRIMARY KEY (programme_code),
    CONSTRAINT fk_programme_dept FOREIGN KEY (primary_dept)
        REFERENCES Department(dept_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO Programme
 (programme_code, programme_name, degree_title, primary_dept) VALUES
 ('6999', 'Computer Science',              'BEng in Computer Science',              'COMP'),
 ('6200', 'Artificial Intelligence and Data Science', 'BEng in AI and Data Science','ASAI'),
 ('6729', 'Actuarial Science',             'BSc in Actuarial Science',              'SDST'),
 ('6779', 'Statistical Decision Sciences', 'BStat in Statistical Decision Sciences','SDST');

-- ---------------------------------------------------------------------
CREATE TABLE Student (
    student_id      CHAR(10)     NOT NULL,
    name_en         VARCHAR(90)  NOT NULL,
    name_zh         VARCHAR(40)  NULL,
    gender          CHAR(1)      NOT NULL DEFAULT 'U',
    date_of_birth   DATE         NOT NULL,
    phone_hk        CHAR(8)      NOT NULL,
    email           VARCHAR(100) NOT NULL,
    admission_year  SMALLINT     NOT NULL,
    year_of_study   SMALLINT     NOT NULL,
    programme_code  CHAR(4)      NOT NULL,
    PRIMARY KEY (student_id),
    UNIQUE KEY uq_student_email (email),
    KEY idx_student_programme (programme_code),
    KEY idx_student_year (year_of_study),
    CONSTRAINT fk_student_programme FOREIGN KEY (programme_code)
        REFERENCES Programme(programme_code),
    CONSTRAINT chk_student_gender CHECK (gender IN ('M','F','U')),
    -- HK mobile numbers are 8 digits beginning 5/6/7/8/9
    CONSTRAINT chk_student_phone CHECK (REGEXP_LIKE(phone_hk, '^[56789][0-9]{7}$')),
    CONSTRAINT chk_student_email CHECK (email LIKE '%@connect.hku.hk'),
    CONSTRAINT chk_student_admit CHECK (admission_year BETWEEN 2022 AND 2026),
    CONSTRAINT chk_student_year  CHECK (year_of_study BETWEEN 1 AND 4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
CREATE TABLE Course (
    course_code       VARCHAR(10)  NOT NULL,
    course_title      VARCHAR(160) NOT NULL,
    department        VARCHAR(10)  NOT NULL,
    credits           SMALLINT     NOT NULL,
    semester_offered  SMALLINT     NOT NULL,
    course_level      SMALLINT     NOT NULL,
    is_core           BOOLEAN      NOT NULL DEFAULT 0,
    PRIMARY KEY (course_code),
    KEY idx_course_dept  (department),
    KEY idx_course_level (course_level),
    KEY idx_course_sem   (semester_offered),
    CONSTRAINT fk_course_dept FOREIGN KEY (department)
        REFERENCES Department(dept_code),
    CONSTRAINT chk_course_credits CHECK (credits > 0),
    CONSTRAINT chk_course_sem CHECK (semester_offered IN (0,1,2)),
    CONSTRAINT chk_course_level CHECK (course_level BETWEEN 1 AND 4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
CREATE TABLE Prerequisite (
    course_code  VARCHAR(10) NOT NULL,
    prereq_code  VARCHAR(10) NOT NULL,
    PRIMARY KEY (course_code, prereq_code),
    KEY idx_prereq_of (prereq_code),
    CONSTRAINT fk_prereq_course FOREIGN KEY (course_code)
        REFERENCES Course(course_code) ON DELETE CASCADE,
    CONSTRAINT fk_prereq_parent FOREIGN KEY (prereq_code)
        REFERENCES Course(course_code) ON DELETE CASCADE,
    CONSTRAINT chk_prereq_not_self CHECK (course_code <> prereq_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
CREATE TABLE ProgrammeCourse (
    programme_code    CHAR(4)      NOT NULL,
    course_code       VARCHAR(10)  NOT NULL,
    requirement_type  VARCHAR(12)  NOT NULL,
    recommended_year  SMALLINT     NOT NULL,
    PRIMARY KEY (programme_code, course_code),
    KEY idx_pc_course (course_code),
    CONSTRAINT fk_pc_programme FOREIGN KEY (programme_code)
        REFERENCES Programme(programme_code) ON DELETE CASCADE,
    CONSTRAINT fk_pc_course FOREIGN KEY (course_code)
        REFERENCES Course(course_code) ON DELETE CASCADE,
    CONSTRAINT chk_pc_reqtype CHECK (requirement_type IN ('CORE','FOUNDATION','ELECTIVE')),
    CONSTRAINT chk_pc_year CHECK (recommended_year BETWEEN 1 AND 4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
CREATE TABLE GradeScale (
    grade        CHAR(2)      NOT NULL,
    grade_point  NUMERIC(3,1) NOT NULL,
    grade_order  SMALLINT     NOT NULL,
    is_passing   BOOLEAN      NOT NULL,
    description  VARCHAR(40)  NOT NULL,
    PRIMARY KEY (grade),
    UNIQUE KEY uq_grade_order (grade_order),
    CONSTRAINT chk_grade_point CHECK (grade_point BETWEEN 0 AND 4.3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO GradeScale (grade, grade_point, grade_order, is_passing, description) VALUES
 ('A+', 4.3, 13, 1, 'Excellent'), ('A', 4.0, 12, 1, 'Excellent'),
 ('A-', 3.7, 11, 1, 'Excellent'), ('B+', 3.3, 10, 1, 'Good'),
 ('B',  3.0,  9, 1, 'Good'),      ('B-', 2.7,  8, 1, 'Good'),
 ('C+', 2.3,  7, 1, 'Satisfactory'),('C', 2.0, 6, 1, 'Satisfactory'),
 ('C-', 1.7,  5, 1, 'Satisfactory'),('D+',1.3,  4, 1, 'Pass'),
 ('D',  1.0,  3, 1, 'Pass'),
 ('F',  0.0,  1, 0, 'Fail');

-- ---------------------------------------------------------------------
CREATE TABLE Enrolment (
    student_id     CHAR(10)    NOT NULL,
    course_code    VARCHAR(10) NOT NULL,
    academic_year  CHAR(9)     NOT NULL,
    semester       SMALLINT    NOT NULL,
    grade          CHAR(2)     NULL,
    is_repeat      BOOLEAN     NOT NULL DEFAULT 0,
    PRIMARY KEY (student_id, course_code, academic_year, semester),
    KEY idx_enrol_course (course_code),
    KEY idx_enrol_term   (academic_year, semester),
    KEY idx_enrol_grade  (grade),
    CONSTRAINT fk_enrol_student FOREIGN KEY (student_id)
        REFERENCES Student(student_id) ON DELETE CASCADE,
    CONSTRAINT fk_enrol_course FOREIGN KEY (course_code)
        REFERENCES Course(course_code) ON DELETE CASCADE,
    CONSTRAINT fk_enrol_grade FOREIGN KEY (grade)
        REFERENCES GradeScale(grade),
    CONSTRAINT chk_enrol_sem CHECK (semester IN (1,2)),
    CONSTRAINT chk_enrol_year CHECK (REGEXP_LIKE(academic_year, '^[0-9]{4}-[0-9]{2}$'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- TRIGGER 1 — the "at most 6 courses per semester" business rule.
-- MySQL does not allow modifying the triggering table inside the trigger,
-- so we raise an error via SIGNAL instead of RAISE(ABORT,...).
-- Note: MySQL 8 does not support recursive triggers by default, so this
-- does not re-enter itself.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_dummy;
DELIMITER $$
CREATE TRIGGER trg_enrolment_max_sem_courses
BEFORE INSERT ON Enrolment
FOR EACH ROW
BEGIN
    DECLARE n_courses INT;
    IF NEW.grade IS NOT NULL AND TRIM(NEW.grade) = '' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'grade must be NULL or a valid GradeScale code';
    END IF;
    SELECT COUNT(*) INTO n_courses FROM Enrolment
     WHERE student_id    = NEW.student_id
       AND academic_year = NEW.academic_year
       AND semester      = NEW.semester;
    IF n_courses >= 6 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Business rule violated: more than 6 courses in one semester';
    END IF;
END$$
DELIMITER ;

-- ---------------------------------------------------------------------
CREATE TABLE StudyPlan (
    plan_id                  INT           NOT NULL AUTO_INCREMENT,
    student_id               CHAR(10)      NOT NULL,
    target_academic_year     CHAR(9)       NOT NULL,
    target_semester          SMALLINT      NOT NULL,
    generated_at             TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cumulative_gpa           NUMERIC(4,3)  NOT NULL,
    credits_completed        INT           NOT NULL DEFAULT 0,
    gpa_band                 VARCHAR(16)   NOT NULL,
    recommended_course_count SMALLINT      NOT NULL,
    recommended_credits      INT           NOT NULL DEFAULT 0,
    n_retake                 SMALLINT      NOT NULL DEFAULT 0,
    n_extra_effort           SMALLINT      NOT NULL DEFAULT 0,
    n_swap                   SMALLINT      NOT NULL DEFAULT 0,
    n_prereq_gap             SMALLINT      NOT NULL DEFAULT 0,
    need_major_adjustment    BOOLEAN       NOT NULL DEFAULT 0,
    major_adjust_reason      VARCHAR(200)  NULL,
    risk_level               VARCHAR(10)   NOT NULL DEFAULT 'LOW',
    PRIMARY KEY (plan_id),
    UNIQUE KEY uq_plan_student_term (student_id, target_academic_year, target_semester),
    KEY idx_plan_term (target_academic_year, target_semester),
    CONSTRAINT fk_plan_student FOREIGN KEY (student_id)
        REFERENCES Student(student_id) ON DELETE CASCADE,
    CONSTRAINT chk_plan_sem CHECK (target_semester IN (1,2)),
    CONSTRAINT chk_plan_count CHECK (recommended_course_count BETWEEN 0 AND 6),
    CONSTRAINT chk_plan_risk CHECK (risk_level IN ('LOW','MEDIUM','HIGH'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
CREATE TABLE PlanCourse (
    plan_id      INTEGER     NOT NULL,
    position     SMALLINT    NOT NULL CHECK (position > 0),
    course_code  VARCHAR(10) NOT NULL,
    PRIMARY KEY (plan_id, position),
    UNIQUE (plan_id, course_code),
    FOREIGN KEY (plan_id) REFERENCES StudyPlan(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (course_code) REFERENCES Course(course_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Recommendation (
    rec_id           INT           NOT NULL AUTO_INCREMENT,
    plan_id          INT           NOT NULL,
    student_id       CHAR(10)      NOT NULL,
    rec_type         VARCHAR(18)   NOT NULL,
    course_code      VARCHAR(10)   NULL,
    rule_id          VARCHAR(20)   NOT NULL,
    rationale_en     TEXT          NOT NULL,
    rationale_zh     TEXT          NOT NULL,
    priority         SMALLINT      NOT NULL DEFAULT 3,
    source           VARCHAR(6)    NOT NULL DEFAULT 'RULE',
    model_risk_score NUMERIC(5,4)  NULL,
    confidence       NUMERIC(5,4)  NULL,
    generated_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (rec_id),
    KEY idx_rec_plan    (plan_id),
    KEY idx_rec_student (student_id),
    KEY idx_rec_type    (rec_type),
    KEY idx_rec_course  (course_code),
    CONSTRAINT fk_rec_plan FOREIGN KEY (plan_id)
        REFERENCES StudyPlan(plan_id) ON DELETE CASCADE,
    CONSTRAINT fk_rec_student FOREIGN KEY (student_id)
        REFERENCES Student(student_id) ON DELETE CASCADE,
    CONSTRAINT fk_rec_course FOREIGN KEY (course_code)
        REFERENCES Course(course_code),
    CONSTRAINT chk_rec_type CHECK (rec_type IN
        ('COURSE_LOAD','RETAKES','EXTRA_EFFORT','SWAP_COURSE','MAJOR_ADJUST','PREREQ_GAP')),
    CONSTRAINT chk_rec_priority CHECK (priority BETWEEN 1 AND 5),
    CONSTRAINT chk_rec_source CHECK (source IN ('RULE','MODEL','BOTH'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
--  VIEWS
-- =====================================================================

-- Age derived at query time; the birthday-not-yet-reached correction is
-- the MySQL equivalent of the SQLite strftime comparison.
CREATE VIEW v_student_profile AS
SELECT
    s.student_id, s.name_en, s.name_zh, s.gender, s.date_of_birth,
    TIMESTAMPDIFF(YEAR, s.date_of_birth, CURDATE()) AS age,
    s.phone_hk, s.email, s.admission_year, s.year_of_study,
    s.programme_code, p.programme_name
FROM Student s
JOIN Programme p ON p.programme_code = s.programme_code;


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
    COUNT(*)                                   AS courses_taken,
    SUM(c.credits)                             AS credits_attempted,
    SUM(CASE WHEN g.is_passing = 1 THEN c.credits ELSE 0 END) AS credits_passed,
    ROUND(SUM(c.credits * g.grade_point) / NULLIF(SUM(c.credits),0), 3) AS cumulative_gpa,
    SUM(CASE WHEN g.is_passing = 0 THEN 1 ELSE 0 END) AS n_failed,
    MAX(CONCAT(e.academic_year, '-', e.semester))     AS last_term
FROM Enrolment e
JOIN Course     c ON c.course_code = e.course_code
JOIN GradeScale g ON g.grade       = e.grade
WHERE e.grade IS NOT NULL
GROUP BY e.student_id;

CREATE VIEW v_course_stats AS
SELECT
    e.course_code, c.course_title, c.department, c.course_level,
    COUNT(*)                              AS n_taken,
    ROUND(AVG(g.grade_point), 3)          AS mean_grade_point,
    ROUND(AVG(CASE WHEN g.is_passing=0 THEN 100.0 ELSE 0.0 END), 2) AS fail_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN g.grade_point <= 1.7 THEN 1 ELSE 0 END) / COUNT(*), 2)
                                          AS weak_rate_pct
FROM Enrolment e
JOIN Course     c ON c.course_code = e.course_code
JOIN GradeScale g ON g.grade       = e.grade
WHERE e.grade IS NOT NULL
GROUP BY e.course_code, c.course_title, c.department, c.course_level;

-- gpa_percentile_top = rank/size: rank 1 of 342 is the top 0.3%.
CREATE VIEW v_programme_rank AS
SELECT
    g.student_id, s.programme_code, s.year_of_study,
    g.cumulative_gpa, g.courses_taken,
    RANK() OVER (PARTITION BY s.programme_code ORDER BY g.cumulative_gpa DESC) AS gpa_rank,
    COUNT(*) OVER (PARTITION BY s.programme_code)                              AS programme_size,
    ROUND(100.0 * RANK() OVER (PARTITION BY s.programme_code
                               ORDER BY g.cumulative_gpa DESC)
          / COUNT(*) OVER (PARTITION BY s.programme_code), 2)                  AS gpa_percentile_top
FROM v_student_gpa g
JOIN Student s ON s.student_id = g.student_id;

CREATE VIEW v_prereq_gap AS
SELECT
    s.student_id, s.programme_code,
    pc.course_code   AS blocked_course,
    c.course_title   AS blocked_title,
    pr.prereq_code   AS missing_prereq,
    pc2.course_title AS missing_prereq_title,
    pc.requirement_type, pc.recommended_year
FROM Student s
JOIN ProgrammeCourse pc  ON pc.programme_code = s.programme_code
JOIN Course c            ON c.course_code      = pc.course_code
JOIN Prerequisite pr     ON pr.course_code     = pc.course_code
JOIN Course pc2          ON pc2.course_code    = pr.prereq_code
WHERE NOT EXISTS (
    SELECT 1 FROM v_latest_enrolment current_grade
    WHERE current_grade.student_id = s.student_id
      AND current_grade.course_code = pr.prereq_code AND current_grade.is_passing = 1
)
AND NOT EXISTS (
    SELECT 1 FROM Enrolment target
    WHERE target.student_id = s.student_id AND target.course_code = pc.course_code
);

-- Validate new enrolments and preserve eligibility when historical grades change.
DELIMITER $$
CREATE TRIGGER trg_enrolment_rules_insert
AFTER INSERT ON Enrolment
FOR EACH ROW
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code = NEW.course_code
          AND c.semester_offered IN (0, NEW.semester)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Course is not offered in this semester';
    END IF;
    IF EXISTS (
        SELECT 1 FROM Enrolment earlier JOIN GradeScale g ON g.grade = earlier.grade
        JOIN Enrolment later ON later.student_id = earlier.student_id
                            AND later.course_code = earlier.course_code
        WHERE earlier.student_id = NEW.student_id AND earlier.course_code = NEW.course_code
          AND g.is_passing = 1
          AND (earlier.academic_year, earlier.semester) < (later.academic_year, later.semester)
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A passed course cannot be selected again';
    END IF;
    IF EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = NEW.student_id
          AND (v.course_code = NEW.course_code OR v.prereq_code = NEW.course_code)
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An enrolment requires a passing prerequisite from an earlier semester';
    END IF;
END$$

CREATE TRIGGER trg_enrolment_rules_update
AFTER UPDATE ON Enrolment
FOR EACH ROW
BEGIN
    IF (SELECT COUNT(*) FROM Enrolment e WHERE e.student_id = NEW.student_id
       AND e.academic_year = NEW.academic_year AND e.semester = NEW.semester) > 6 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Business rule violated: more than 6 courses in one semester';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code = NEW.course_code
          AND c.semester_offered IN (0, NEW.semester)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Course is not offered in this semester';
    END IF;
    IF EXISTS (
        SELECT 1 FROM Enrolment earlier JOIN GradeScale g ON g.grade = earlier.grade
        JOIN Enrolment later ON later.student_id = earlier.student_id
                            AND later.course_code = earlier.course_code
        WHERE earlier.student_id = NEW.student_id AND earlier.course_code = NEW.course_code
          AND g.is_passing = 1
          AND (earlier.academic_year, earlier.semester) < (later.academic_year, later.semester)
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A passed course cannot be selected again';
    END IF;
    IF EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = NEW.student_id
          AND (v.course_code = NEW.course_code OR v.prereq_code = NEW.course_code)
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An enrolment requires a passing prerequisite from an earlier semester';
    END IF;
    IF EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = OLD.student_id AND v.prereq_code = OLD.course_code
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This change would invalidate a later enrolment prerequisite';
    END IF;
END$$

CREATE TRIGGER trg_enrolment_rules_delete
AFTER DELETE ON Enrolment
FOR EACH ROW
BEGIN
    IF EXISTS (
        SELECT 1 FROM v_enrolment_prereq_violation v
        WHERE v.student_id = OLD.student_id AND v.prereq_code = OLD.course_code
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This change would invalidate a later enrolment prerequisite';
    END IF;
END$$
DELIMITER ;
