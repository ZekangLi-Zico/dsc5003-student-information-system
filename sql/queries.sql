-- =====================================================================
--  DSC5003 — SQL query library
--  Student Information Management System (SQLite dialect)
--  Run with:  python src/run_queries.py
-- =====================================================================
--  Organised by increasing sophistication so the query set demonstrates the
--  full retrieval range the course examines:
--    Q01-Q06  single-table selection, projection, ordering
--    Q07-Q12  joins and aggregation
--    Q13-Q18  subqueries and set operations
--    Q19-Q26  window functions
--    Q27-Q33  the queries that actually drive the recommendation engine
--    Q34-Q38  data-quality and constraint audits
--
--  Each query is named with -- [Qnn] so run_queries.py can execute them one
--  by one and print a labelled result set.
-- =====================================================================

-- =====================================================================
--  SECTION A — BASIC RETRIEVAL (selection, projection, ordering)
-- =====================================================================

-- [Q01] All Year-3 Computer Science students, youngest first.
--       Demonstrates: equi-join on a lookup table, WHERE on two predicates,
--       ORDER BY with a named column alias.
SELECT s.student_id, s.name_en, s.name_zh, s.year_of_study, p.programme_name
  FROM Student s
  JOIN Programme p ON p.programme_code = s.programme_code
 WHERE s.programme_code = '6999' AND s.year_of_study = 3
 ORDER BY s.date_of_birth DESC;

-- [Q02] Students whose HK mobile number begins with 9.
--       Demonstrates: LIKE pattern matching and a derived count column.
SELECT student_id, name_en, phone_hk, email
  FROM Student
 WHERE phone_hk LIKE '9%'
 ORDER BY student_id
 LIMIT 20;

-- [Q03] Courses offered in the first semester at level 3 or above.
--       semester_offered = 0 means "both semesters", so it also qualifies.
SELECT course_code, course_title, department, credits, course_level
  FROM Course
 WHERE course_level >= 3 AND semester_offered IN (0, 1)
 ORDER BY course_level DESC, course_code;

-- [Q04] The official grade scale, best to worst.
--       Demonstrates: reading a lookup table that removes the
--       grade -> grade_point transitive dependency.
SELECT grade, grade_point, grade_order,
       CASE is_passing WHEN 1 THEN 'PASS' ELSE 'FAIL' END AS outcome,
       description
  FROM GradeScale
 ORDER BY grade_order DESC;

-- [Q05] Students admitted in 2024 who are still in Year 1 (held back)
--       or already in Year 2 (on track). Shows a computed progress column.
SELECT student_id, name_en, admission_year, year_of_study,
       (2026 - admission_year) AS years_since_admission,
       CASE WHEN year_of_study >= (2026 - admission_year) + 1
            THEN 'ON TRACK' ELSE 'BEHIND' END AS progress
  FROM Student
 WHERE admission_year = 2024
 ORDER BY year_of_study DESC, student_id;

-- [Q06] Course catalogue grouped by department and level — how wide is
--       the curriculum? Pure aggregation over a single table.
SELECT department, course_level, COUNT(*) AS n_courses,
       SUM(credits) AS total_credits,
       SUM(is_core) AS n_core
  FROM Course
 GROUP BY department, course_level
 ORDER BY department, course_level;

-- =====================================================================
--  SECTION B — JOINS AND AGGREGATION
-- =====================================================================

-- [Q07] Every enrolment with student name, course title and grade point.
--       Three-table join; the grade point comes from the lookup table,
--       never from a duplicated column on Enrolment.
SELECT e.student_id, s.name_en, e.course_code, c.course_title,
       e.academic_year, e.semester, e.grade, g.grade_point
  FROM Enrolment e
  JOIN Student    s ON s.student_id  = e.student_id
  JOIN Course     c ON c.course_code = e.course_code
  JOIN GradeScale g ON g.grade       = e.grade
 WHERE e.grade IS NOT NULL
 ORDER BY e.student_id, e.academic_year, e.semester
 LIMIT 25;

-- [Q08] Per-programme summary: cohort size, mean GPA and historical failed attempts.
--       Aggregation over a join, with a conditional average.
SELECT p.programme_code, p.programme_name,
       COUNT(DISTINCT s.student_id)                       AS n_students,
       ROUND(AVG(g.cumulative_gpa), 3)                    AS mean_gpa,
       ROUND(MIN(g.cumulative_gpa), 2)                    AS min_gpa,
       ROUND(MAX(g.cumulative_gpa), 2)                    AS max_gpa,
       SUM(g.n_failed)                                    AS failed_attempts,
       ROUND(AVG(g.courses_taken), 1)                     AS mean_courses
  FROM Programme p
  JOIN Student      s ON s.programme_code = p.programme_code
  JOIN v_student_gpa g ON g.student_id    = s.student_id
 GROUP BY p.programme_code, p.programme_name
 ORDER BY mean_gpa DESC;

-- [Q09] Course difficulty league table — which courses are hardest?
--       Uses the v_course_stats view; HAVING removes thin samples.
SELECT course_code, course_title, department, n_taken,
       mean_grade_point, fail_rate_pct, weak_rate_pct
  FROM v_course_stats
 WHERE n_taken >= 30
 ORDER BY mean_grade_point ASC
 LIMIT 15;

-- [Q10] Easiest courses by the same measure (the other tail).
SELECT course_code, course_title, department, n_taken, mean_grade_point
  FROM v_course_stats
 WHERE n_taken >= 30
 ORDER BY mean_grade_point DESC
 LIMIT 10;

-- [Q11] Grade distribution for one course across all terms.
--       A frequency table: the input to any "is this course a bottleneck"
--       question. The window SUM gives each grade's share of the course.
SELECT c.course_code, c.course_title, e.grade,
       COUNT(*) AS n_students,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
  FROM Enrolment e
  JOIN Course     c ON c.course_code = e.course_code
  JOIN GradeScale g ON g.grade       = e.grade
 WHERE c.course_code = 'COMP3314' AND e.grade IS NOT NULL
 GROUP BY c.course_code, c.course_title, e.grade, g.grade_order
 ORDER BY g.grade_order DESC;

-- [Q12] Semester-by-semester load: how many courses were taken per term,
--       and how the mean grade moved. Time series over the enrolment table.
SELECT e.academic_year, e.semester,
       COUNT(*)                              AS n_enrolments,
       COUNT(DISTINCT e.student_id)          AS n_students,
       ROUND(AVG(g.grade_point), 3)          AS mean_grade_point,
       ROUND(AVG(c.course_level), 2)         AS mean_course_level
  FROM Enrolment e
  JOIN GradeScale g ON g.grade = e.grade
  JOIN Course     c ON c.course_code = e.course_code
 GROUP BY e.academic_year, e.semester
 ORDER BY e.academic_year, e.semester;

-- =====================================================================
--  SECTION C — SUBQUERIES AND SET OPERATIONS
-- =====================================================================

-- [Q13] Historical failed attempts and the number of courses still unpassed.
SELECT s.student_id, s.name_en, p.programme_name, s.year_of_study,
       COUNT(*) AS failed_attempts,
       COUNT(DISTINCT CASE WHEN latest.is_passing = 0 THEN e.course_code END)
           AS still_unpassed_courses
  FROM Enrolment e JOIN GradeScale gs ON gs.grade = e.grade
  JOIN Student s ON s.student_id = e.student_id
  JOIN Programme p ON p.programme_code = s.programme_code
  JOIN v_latest_enrolment latest
    ON latest.student_id = e.student_id AND latest.course_code = e.course_code
 WHERE gs.is_passing = 0
 GROUP BY s.student_id, s.name_en, p.programme_name, s.year_of_study
 ORDER BY failed_attempts DESC, s.student_id
 LIMIT 20;

-- [Q14] Courses that a given programme requires but a given student has
--       never taken. NOT IN against the student's own history.
SELECT pc.course_code, c.course_title, pc.requirement_type, pc.recommended_year
  FROM ProgrammeCourse pc
  JOIN Course c ON c.course_code = pc.course_code
 WHERE pc.programme_code = (SELECT programme_code FROM Student
                             WHERE student_id = '3036000001')
   AND pc.course_code NOT IN (SELECT course_code FROM Enrolment
                               WHERE student_id = '3036000001')
   AND pc.requirement_type IN ('CORE', 'FOUNDATION')
 ORDER BY pc.recommended_year, pc.course_code;

-- [Q15] Students in the top decile of their own programme.
--       A subquery supplies the per-programme cut-off.
SELECT r.student_id, s.name_en, r.programme_code, r.cumulative_gpa,
       r.gpa_rank, r.programme_size, r.gpa_percentile_top
  FROM v_programme_rank r
  JOIN Student s ON s.student_id = r.student_id
 WHERE r.gpa_percentile_top <= 10
 ORDER BY r.programme_code, r.gpa_rank
 LIMIT 25;

-- [Q16] Retakes that cleared a failure on the next graded attempt.
WITH attempts AS (
    SELECT e.student_id, e.course_code, e.academic_year, e.semester, e.grade,
           gs.grade_point, gs.is_passing,
           LAG(e.grade) OVER w AS previous_grade,
           LAG(gs.grade_point) OVER w AS previous_point,
           LAG(gs.is_passing) OVER w AS previously_passed
      FROM Enrolment e JOIN GradeScale gs ON gs.grade = e.grade
    WINDOW w AS (PARTITION BY e.student_id, e.course_code ORDER BY e.academic_year, e.semester)
)
SELECT student_id, course_code, previous_grade, grade, academic_year, semester,
       ROUND(grade_point - previous_point, 1) AS improvement
  FROM attempts WHERE previously_passed = 0 AND is_passing = 1
 ORDER BY improvement DESC, student_id, course_code
 LIMIT 20;

-- [Q17] Set difference: level-1 courses that NO student has ever failed.
--       EXCEPT requires identical column counts and compatible types on both
--       sides, so only course_code is projected; the title is recovered by a
--       final join instead of being carried through the set operation.
SELECT c.course_code, c.course_title
  FROM Course c
 WHERE c.course_level = 1
   AND c.course_code IN (
        SELECT course_code FROM Course WHERE course_level = 1
        EXCEPT
        SELECT e.course_code FROM Enrolment e JOIN GradeScale gs ON gs.grade = e.grade
         WHERE gs.is_passing = 0)
 ORDER BY c.course_code;

-- [Q18] Union across programmes: each programme's single best and single
--       worst student, in one result set.
SELECT programme_code, 'TOP' AS slot, student_id, cumulative_gpa FROM (
    SELECT programme_code, student_id, cumulative_gpa,
           ROW_NUMBER() OVER (PARTITION BY programme_code
                              ORDER BY cumulative_gpa DESC) AS rn
      FROM v_programme_rank) WHERE rn = 1
UNION ALL
SELECT programme_code, 'BOTTOM', student_id, cumulative_gpa FROM (
    SELECT programme_code, student_id, cumulative_gpa,
           ROW_NUMBER() OVER (PARTITION BY programme_code
                              ORDER BY cumulative_gpa ASC) AS rn
      FROM v_programme_rank) WHERE rn = 1
ORDER BY programme_code, slot DESC;

-- =====================================================================
--  SECTION D — WINDOW FUNCTIONS
-- =====================================================================

-- [Q19] Rank every student inside their programme by cumulative GPA.
SELECT student_id, programme_code, cumulative_gpa, gpa_rank, programme_size,
       gpa_percentile_top
  FROM v_programme_rank
 ORDER BY programme_code, gpa_rank
 LIMIT 25;

-- [Q20] Each student's grade trend across terms: is the mean grade point
--       rising or falling? LAG over an ordered term sequence.
WITH term_avg AS (
    SELECT e.student_id, e.academic_year, e.semester,
           ROUND(SUM(c.credits * g.grade_point) / (1.0 * SUM(c.credits)), 3) AS term_gpa
      FROM Enrolment e
      JOIN GradeScale g ON g.grade = e.grade
      JOIN Course c ON c.course_code = e.course_code
     GROUP BY e.student_id, e.academic_year, e.semester)
SELECT student_id, academic_year, semester, term_gpa,
       LAG(term_gpa) OVER w AS prev_term_gpa,
       ROUND(term_gpa - LAG(term_gpa) OVER w, 3) AS delta,
       ROW_NUMBER() OVER w AS term_index
  FROM term_avg
WINDOW w AS (PARTITION BY student_id ORDER BY academic_year, semester)
 ORDER BY student_id, academic_year, semester
 LIMIT 30;

-- [Q21] Per-course percentile of each grade: how does a student compare
--       with peers who took the SAME course? NTILE(4) gives quartiles.
SELECT course_code, student_id, grade, grade_point, quartile
  FROM (SELECT e.course_code, e.student_id, e.grade, g.grade_point,
               NTILE(4) OVER (PARTITION BY e.course_code
                              ORDER BY g.grade_point DESC) AS quartile
          FROM Enrolment e
          JOIN GradeScale g ON g.grade = e.grade)
 WHERE course_code = 'COMP2119'
 ORDER BY quartile, grade_point DESC;

-- [Q22] Running attempted credits per student over time, including repeats and failures.
SELECT student_id, academic_year, semester, credits AS term_attempted_credits,
       SUM(credits) OVER w AS running_attempted_credits
  FROM (SELECT e.student_id, e.academic_year, e.semester,
               SUM(c.credits) AS credits
          FROM Enrolment e
          JOIN Course c ON c.course_code = e.course_code
         GROUP BY e.student_id, e.academic_year, e.semester)
WINDOW w AS (PARTITION BY student_id ORDER BY academic_year, semester)
 ORDER BY student_id, academic_year, semester
 LIMIT 30;

-- [Q23] Students whose GPA is more than 0.5 grade points below their programme mean.
WITH z AS (
    SELECT r.student_id, r.programme_code, r.cumulative_gpa,
           AVG(r.cumulative_gpa)    OVER (PARTITION BY r.programme_code) AS prog_mean,
           COUNT(*)                 OVER (PARTITION BY r.programme_code) AS prog_n
      FROM v_programme_rank r)
SELECT z.student_id, s.name_en, z.programme_code,
       ROUND(z.cumulative_gpa, 2) AS gpa, ROUND(z.prog_mean, 2) AS prog_mean
  FROM z JOIN Student s ON s.student_id = z.student_id
 WHERE z.cumulative_gpa < z.prog_mean - 0.5
 ORDER BY (z.prog_mean - z.cumulative_gpa) DESC
 LIMIT 20;

-- [Q24] Most common course combination per term — which courses travel
--       together? Dense rank over pair counts.
SELECT academic_year, semester, course_code, n_students, rnk
  FROM (SELECT e.academic_year, e.semester, e.course_code,
               COUNT(*) AS n_students,
               DENSE_RANK() OVER (PARTITION BY e.academic_year, e.semester
                                  ORDER BY COUNT(*) DESC) AS rnk
          FROM Enrolment e
         GROUP BY e.academic_year, e.semester, e.course_code)
 WHERE rnk <= 3
 ORDER BY academic_year, semester, rnk;

-- [Q25] Grade inflation check: mean grade point per academic year, with
--       the change from the previous year.
SELECT academic_year,
       ROUND(mean_gp, 3)                                  AS mean_grade_point,
       ROUND(mean_gp - LAG(mean_gp) OVER (ORDER BY academic_year), 3)
                                                          AS change_from_prev_year,
       n_enrolments
  FROM (SELECT e.academic_year, AVG(g.grade_point) AS mean_gp,
               COUNT(*) AS n_enrolments
          FROM Enrolment e JOIN GradeScale g ON g.grade = e.grade
         GROUP BY e.academic_year)
 ORDER BY academic_year;

-- [Q26] For each student, their best and worst course side by side,
--       plus the spread. MAX/MIN as window aggregates over the full
--       partition.
SELECT DISTINCT student_id, best_course, worst_course,
       best_point, worst_point, (best_point - worst_point) AS spread
  FROM (SELECT e.student_id,
               FIRST_VALUE(e.course_code) OVER w_best  AS best_course,
               FIRST_VALUE(e.course_code) OVER w_worst AS worst_course,
               MAX(g.grade_point)  OVER (PARTITION BY e.student_id) AS best_point,
               MIN(g.grade_point)  OVER (PARTITION BY e.student_id) AS worst_point
          FROM Enrolment e JOIN GradeScale g ON g.grade = e.grade
        WINDOW w_best  AS (PARTITION BY e.student_id ORDER BY g.grade_point DESC,
                                                            e.course_code),
               w_worst AS (PARTITION BY e.student_id ORDER BY g.grade_point ASC,
                                                            e.course_code))
 ORDER BY spread DESC, student_id
 LIMIT 20;

-- =====================================================================
--  SECTION E — QUERIES THAT DRIVE THE RECOMMENDATION ENGINE
-- =====================================================================

-- [Q27] Currently unpassed courses: one latest graded attempt per student and course.
SELECT s.student_id, s.programme_code, e.course_code, c.course_title,
       e.grade AS failed_grade, e.academic_year, e.semester,
       pc.requirement_type, c.semester_offered
  FROM v_latest_enrolment e
  JOIN Student s ON s.student_id = e.student_id
  JOIN Course c ON c.course_code = e.course_code
  LEFT JOIN ProgrammeCourse pc
    ON pc.programme_code = s.programme_code AND pc.course_code = e.course_code
 WHERE e.is_passing = 0
 ORDER BY s.student_id, e.course_code;

-- [Q28] Extra effort: weak latest passes at or below a tie-consistent quartile.
WITH ranked AS (
    SELECT e.course_code, g.grade_point,
           NTILE(4) OVER (PARTITION BY e.course_code ORDER BY g.grade_point) AS quartile,
           COUNT(*) OVER (PARTITION BY e.course_code) AS n_attempts
      FROM Enrolment e JOIN GradeScale g ON g.grade = e.grade
), cutoffs AS (
    SELECT course_code, MAX(grade_point) AS cutoff, MAX(n_attempts) AS n_attempts
      FROM ranked WHERE quartile = 1 AND n_attempts >= 20 GROUP BY course_code
)
SELECT e.student_id, s.programme_code, e.course_code, c.course_title,
       e.grade, e.grade_point, q.cutoff, q.n_attempts
  FROM v_latest_enrolment e
  JOIN Student s ON s.student_id = e.student_id
  JOIN Course c ON c.course_code = e.course_code
  JOIN cutoffs q ON q.course_code = e.course_code
 WHERE e.is_passing = 1 AND e.grade_point <= 1.7 AND e.grade_point <= q.cutoff
 ORDER BY e.student_id, e.course_code;

-- [Q29] PREREQ GAP: required courses blocked by an unpassed prerequisite.
--       Reads the view built for exactly this purpose.
SELECT student_id, programme_code, blocked_course, blocked_title,
       missing_prereq, missing_prereq_title, requirement_type, recommended_year
  FROM v_prereq_gap
 WHERE requirement_type IN ('CORE', 'FOUNDATION')
 ORDER BY student_id, recommended_year, blocked_course
 LIMIT 30;

-- [Q30] COURSE LOAD: the GPA band that decides next semester's load.
SELECT s.student_id, s.name_en, s.programme_code, s.year_of_study,
       g.cumulative_gpa, g.credits_passed, g.n_failed AS failed_attempts,
       CASE
         WHEN g.cumulative_gpa >= 3.7 THEN 'EXCELLENT'
         WHEN g.cumulative_gpa >= 3.0 THEN 'GOOD'
         WHEN g.cumulative_gpa >= 2.5 THEN 'SATISFACTORY'
         WHEN g.cumulative_gpa >= 2.0 THEN 'AT RISK'
         ELSE 'CRITICAL'
       END AS gpa_band,
       CASE
         WHEN g.cumulative_gpa >= 3.7 THEN 6
         WHEN g.cumulative_gpa >= 3.0 THEN 5
         WHEN g.cumulative_gpa >= 2.5 THEN 5
         WHEN g.cumulative_gpa >= 2.0 THEN 4
         ELSE 4
       END AS suggested_courses
  FROM Student s
  JOIN v_student_gpa g ON g.student_id = s.student_id
 ORDER BY g.cumulative_gpa DESC
 LIMIT 25;

-- [Q31] Weak latest passes outside core and foundation requirements.
SELECT e.student_id, s.programme_code, e.course_code, c.course_title,
       e.grade, e.grade_point, c.department
  FROM v_latest_enrolment e
  JOIN Student s ON s.student_id = e.student_id
  JOIN Course c ON c.course_code = e.course_code
 WHERE e.is_passing = 1 AND e.grade_point <= 1.7
   AND NOT EXISTS (SELECT 1 FROM ProgrammeCourse pc
                    WHERE pc.programme_code = s.programme_code AND pc.course_code = e.course_code
                      AND pc.requirement_type IN ('CORE','FOUNDATION'))
 ORDER BY e.student_id, e.grade_point, e.course_code
 LIMIT 30;

-- [Q32] MAJOR ADJUSTMENT evidence: a student's mean grade point inside
--       their own department versus outside it. A large negative gap
--       suggests the major may not be the right fit.
SELECT s.student_id, s.programme_code, p.primary_dept,
       ROUND(AVG(CASE WHEN c.department = p.primary_dept
                      THEN g.grade_point END), 3) AS mean_in_dept,
       ROUND(AVG(CASE WHEN c.department <> p.primary_dept
                      THEN g.grade_point END), 3) AS mean_out_of_dept,
       ROUND(AVG(CASE WHEN c.department = p.primary_dept
                      THEN g.grade_point END)
           - AVG(CASE WHEN c.department <> p.primary_dept
                      THEN g.grade_point END), 3) AS dept_gap,
       SUM(CASE WHEN c.department = p.primary_dept THEN 1 ELSE 0 END) AS n_in_dept
  FROM Enrolment e
  JOIN Student    s ON s.student_id  = e.student_id
  JOIN Programme  p ON p.programme_code = s.programme_code
  JOIN Course     c ON c.course_code = e.course_code
  JOIN GradeScale g ON g.grade       = e.grade
 GROUP BY s.student_id, s.programme_code, p.primary_dept
HAVING SUM(CASE WHEN c.department = p.primary_dept THEN 1 ELSE 0 END) >= 4
   AND AVG(CASE WHEN c.department <> p.primary_dept
                THEN g.grade_point END) IS NOT NULL
 ORDER BY dept_gap ASC
 LIMIT 20;

-- [Q33] Additional programme courses eligible for 2026-27 S1, including retakes.
SELECT s.student_id, s.programme_code, pc.course_code, c.course_title,
       pc.requirement_type, c.course_level, c.credits,
       CASE WHEN latest.is_passing = 0 THEN 'RETAKE' ELSE 'NEW' END AS course_status
  FROM Student s
  JOIN ProgrammeCourse pc ON pc.programme_code = s.programme_code
  JOIN Course c ON c.course_code = pc.course_code
  LEFT JOIN v_latest_enrolment latest
    ON latest.student_id = s.student_id AND latest.course_code = c.course_code
 WHERE c.semester_offered IN (0, 1)
   AND c.course_level <= s.year_of_study + 1
   AND COALESCE(latest.is_passing, 0) = 0
   AND NOT EXISTS (SELECT 1 FROM Enrolment registered
                    WHERE registered.student_id = s.student_id AND registered.course_code = c.course_code
                      AND registered.academic_year = '2026-27' AND registered.semester = 1)
   AND NOT EXISTS (SELECT 1 FROM Prerequisite pr
                    WHERE pr.course_code = pc.course_code AND NOT EXISTS (
                          SELECT 1 FROM v_latest_enrolment previous
                           WHERE previous.student_id = s.student_id
                             AND previous.course_code = pr.prereq_code AND previous.is_passing = 1))
 ORDER BY s.student_id, CASE pc.requirement_type WHEN 'CORE' THEN 0
                   WHEN 'FOUNDATION' THEN 1 ELSE 2 END, c.course_level, c.course_code
 LIMIT 30;

-- =====================================================================
--  SECTION F — DATA-QUALITY AND CONSTRAINT AUDITS
--  Every one of these must return zero rows / a zero count.
-- =====================================================================

-- [Q34] Business-rule audit: any term outside the 4..6 course window?
SELECT student_id, academic_year, semester, COUNT(*) AS n_courses
  FROM Enrolment
 GROUP BY student_id, academic_year, semester
HAVING COUNT(*) < 4 OR COUNT(*) > 6;

-- [Q35] Duplicate enrolment audit (primary-key sanity).
SELECT student_id, course_code, academic_year, semester, COUNT(*) AS n
  FROM Enrolment
 GROUP BY student_id, course_code, academic_year, semester
HAVING COUNT(*) > 1;

-- [Q36] Enrolments without a passing prerequisite in a strictly earlier term.
SELECT student_id, course_code, academic_year, semester, prereq_code
  FROM v_enrolment_prereq_violation
 ORDER BY student_id, academic_year, semester, course_code, prereq_code
 LIMIT 20;

-- [Q37] Orphan counts for five selected foreign keys.
SELECT 'Enrolment.student_id'  AS fk, COUNT(*) AS orphans FROM Enrolment e
 WHERE NOT EXISTS (SELECT 1 FROM Student s WHERE s.student_id = e.student_id)
UNION ALL
SELECT 'Enrolment.course_code', COUNT(*) FROM Enrolment e
 WHERE NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code = e.course_code)
UNION ALL
SELECT 'Student.programme_code', COUNT(*) FROM Student s
 WHERE NOT EXISTS (SELECT 1 FROM Programme p WHERE p.programme_code = s.programme_code)
UNION ALL
SELECT 'Prerequisite.prereq_code', COUNT(*) FROM Prerequisite p
 WHERE NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code = p.prereq_code)
UNION ALL
SELECT 'ProgrammeCourse.course_code', COUNT(*) FROM ProgrammeCourse pc
 WHERE NOT EXISTS (SELECT 1 FROM Course c WHERE c.course_code = pc.course_code);

-- [Q38] Contact-detail audit: malformed email or phone values.
SELECT student_id, email, phone_hk FROM Student
 WHERE email NOT LIKE '%@connect.hku.hk'
    OR LENGTH(phone_hk) <> 8
    OR phone_hk NOT GLOB '[56789][0-9][0-9][0-9][0-9][0-9][0-9][0-9]';
