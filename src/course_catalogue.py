"""HKU 2026-27 course catalogue (4 departments) with simulated prerequisites.

PROVENANCE — read this before citing numbers:
  * course_code, title, semester_offered : REAL. Scraped 2026-11-17 from the
    public HKU course lists:
      - saasweb.hku.hk/current/ug/course-list            (SDST, ASAI)
      - cs.hku.hk/programmes/course-offered              (COMP, FITE, ENGG)
      - hkumath.hku.hk/MathWWW/ucourse.php               (MATH, APAI)
  * credits : SIMULATED. HKU undergraduate courses are commonly 6 credits;
    per-course credit values were not individually verified.
  * prerequisites : SIMULATED. Derived from HKU's 1xxx -> 2xxx -> 3xxx -> 4xxx
    level convention plus department structure. Official per-course
    prerequisite lists were NOT individually fetched, so these edges are
    plausible teaching orderings, not authoritative requirements.
  * dept / level / is_core : derived mechanically from the course code.

Each row: (code, title, dept, credits, semester, is_core, prerequisites)
semester: 1, 2, 0 (both / year-long)
"""

# --- Computer Science (COMP) ----------------------------------------------
COMP = [
    ("COMP1110", "Computing and Data Science in Everyday Life", 6, 1, 1, []),
    ("COMP1117", "Computer Programming", 6, 0, 1, []),
    ("ENGG1330", "Computer Programming I", 6, 0, 0, []),
    ("FITE1010", "Introduction to Financial Technologies", 6, 1, 0, []),

    ("COMP2113", "Programming Technologies", 6, 0, 1, ["COMP1117"]),
    ("COMP2118", "Data Structures and Algorithms Essentials", 6, 2, 0, ["COMP1117"]),
    ("COMP2119", "Introduction to Data Structures and Algorithms", 6, 0, 1, ["COMP1117"]),
    ("COMP2120", "Computer Organization", 6, 2, 1, ["COMP1117"]),
    ("COMP2121", "Discrete Mathematics", 6, 0, 1, ["MATH1013"]),
    ("COMP2396", "Object-oriented Programming and Java", 6, 1, 0, ["COMP1117"]),
    ("COMP2501", "Introduction to Data Science", 6, 0, 1, ["COMP1117"]),
    ("COMP2502", "Computing Fundamentals", 6, 2, 0, ["COMP1117"]),
    ("FITE2000", "Foundations of FinTech Programming", 6, 2, 0, ["COMP1117"]),
    ("FITE2010", "Distributed Ledger and Blockchain", 6, 2, 0, ["COMP2119"]),

    ("COMP3230", "Principles of Operating Systems", 6, 1, 1, ["COMP2119", "COMP2120"]),
    ("COMP3231", "Computer Architecture", 6, 2, 0, ["COMP2120"]),
    ("COMP3234", "Computer and Communication Networks", 6, 0, 1, ["COMP2119"]),
    ("COMP3235", "Compiling Techniques", 6, 2, 0, ["COMP2119", "COMP3230"]),
    ("COMP3251", "Algorithm Design", 6, 2, 1, ["COMP2119", "COMP2121"]),
    ("COMP3252", "Algorithm Design and Analysis (Advanced)", 6, 2, 0, ["COMP2119", "COMP2121"]),
    ("COMP3258", "Functional Programming", 6, 2, 0, ["COMP2119"]),
    ("COMP3259", "Principles of Programming Languages", 6, 2, 0, ["COMP2119", "COMP2121"]),
    ("COMP3270", "Introduction to Artificial Intelligence", 6, 0, 1, ["COMP2119", "SDST2601"]),
    ("COMP3271", "Computer Graphics", 6, 1, 0, ["COMP2119", "MATH2014"]),
    ("COMP3278", "Introduction to Database Management Systems", 6, 0, 1, ["COMP2119"]),
    ("COMP3297", "Software Engineering", 6, 0, 1, ["COMP2119", "COMP2396"]),
    ("COMP3312", "Law and Ethics in Data Science", 6, 1, 1, ["COMP2501"]),
    ("COMP3314", "Introduction to Machine Learning", 6, 0, 1, ["COMP2119", "SDST2601", "MATH2101"]),
    ("COMP3316", "Quantum Information and Computation", 6, 2, 0, ["COMP2121", "MATH2101"]),
    ("COMP3317", "Introduction to Computer Vision", 6, 2, 0, ["COMP3314"]),
    ("COMP3322", "Modern Technologies on World Wide Web", 6, 1, 0, ["COMP2119"]),
    ("COMP3323", "Advanced Database Systems", 6, 1, 0, ["COMP3278"]),
    ("COMP3329", "Computer Game Design and Programming", 6, 2, 0, ["COMP2119"]),
    ("COMP3330", "Interactive Mobile Application Design and Programming", 6, 1, 0, ["COMP2396"]),
    ("COMP3340", "Introduction to Deep Learning", 6, 2, 0, ["COMP3314"]),
    ("COMP3353", "Bioinformatics", 6, 1, 0, ["COMP2119", "SDST2601"]),
    ("COMP3354", "Statistical Learning", 6, 2, 0, ["COMP3314", "SDST3600"]),
    ("COMP3355", "Cyber Security", 6, 1, 0, ["COMP2119", "COMP3234"]),
    ("COMP3356", "Robotics", 6, 2, 0, ["COMP3270", "MATH2101"]),
    ("COMP3357", "Cryptography", 6, 1, 0, ["COMP2121", "MATH3304"]),
    ("COMP3358", "Distributed and Parallel Computing", 6, 2, 0, ["COMP3230"]),
    ("COMP3360", "Data-driven Computer Animation", 6, 2, 0, ["COMP3271", "COMP3314"]),
    ("COMP3361", "Natural Language Processing", 6, 2, 0, ["COMP3314"]),
    ("COMP3366", "Quantum Algorithms and Computer Architecture", 6, 1, 0, ["COMP3316", "COMP3231"]),
    ("COMP3513", "Big Data Systems", 6, 2, 0, ["COMP3278", "COMP3230"]),
    ("COMP3516", "Data Analytics for IoT", 6, 2, 0, ["COMP2501"]),
    ("COMP3522", "Real-life Data Science", 6, 1, 1, ["COMP2501", "SDST2601"]),
    ("COMP3524", "Web Intelligence", 6, 2, 0, ["COMP3322"]),
    ("FITE3010", "Big Data and Data Mining", 6, 1, 0, ["COMP3314"]),
    ("FITE3012", "E-payment and Crypto-currency", 6, 2, 0, ["FITE2010"]),

    ("COMP4501", "Data Science in Discipline Project", 6, 2, 1, ["COMP3522"]),
    ("COMP4502", "Final Year Project", 6, 2, 1, ["COMP3297"]),
    ("COMP4801", "Final Year Project (Full Year)", 12, 0, 1, ["COMP3297"]),
]

# --- Statistics & Actuarial Science (SDST) --------------------------------
SDST = [
    ("SDST1016", "Data Science 101", 6, 1, 1, []),
    ("SDST1018", "Foundations of Data Science", 6, 1, 1, []),
    ("SDST1600", "Statistics: Ideas and Concepts", 6, 0, 1, []),
    ("SDST1603", "Introductory Statistics", 6, 0, 1, []),

    ("SDST2601", "Probability and Statistics I", 6, 0, 1, ["MATH1013"]),
    ("SDST2602", "Probability and Statistics II", 6, 0, 1, ["SDST2601"]),
    ("SDST2901", "Probability and Statistics: Foundations of Actuarial Science", 6, 2, 1, ["MATH1821"]),
    ("SDST2902", "Financial Mathematics", 6, 2, 1, ["SDST2901"]),

    ("SDST3600", "Linear Statistical Analysis", 6, 0, 1, ["SDST2602", "MATH2101"]),
    ("SDST3602", "Statistical Inference", 6, 1, 1, ["SDST2602"]),
    ("SDST3603", "Stochastic Processes", 6, 1, 0, ["SDST2602", "MATH2211"]),
    ("SDST3606", "Business Logistics", 6, 1, 0, ["SDST2601"]),
    ("SDST3609", "The Statistics of Investment Risk", 6, 1, 0, ["SDST2602"]),
    ("SDST3610", "Risk Management and Insurance", 6, 2, 0, ["SDST2902"]),
    ("SDST3612", "Statistical Machine Learning", 6, 0, 1, ["SDST3600", "COMP2501"]),
    ("SDST3613", "Marketing Analytics", 6, 1, 0, ["SDST2601"]),
    ("SDST3615", "Practical Mathematics for Investment", 6, 2, 0, ["SDST2902"]),
    ("SDST3617", "Sample Survey Methods", 6, 2, 0, ["SDST3600"]),
    ("SDST3618", "Derivatives and Risk Management", 6, 1, 0, ["SDST3905"]),
    ("SDST3620", "Modern Nonparametric Statistics", 6, 1, 0, ["SDST3602"]),
    ("SDST3621", "Statistical Data Analysis", 6, 2, 1, ["SDST3600"]),
    ("SDST3622", "Data Visualization", 6, 2, 1, ["SDST1018"]),
    ("SDST3655", "Survival Analysis", 6, 2, 0, ["SDST3602"]),
    ("SDST3901", "Life Contingencies I", 6, 1, 1, ["SDST2901"]),
    ("SDST3902", "Mathematical Statistics", 6, 1, 1, ["SDST2602", "MATH2211"]),
    ("SDST3903", "Stochastic Models", 6, 2, 0, ["SDST3603"]),
    ("SDST3904", "Corporate Finance for Actuarial Science", 6, 1, 0, ["SDST2902"]),
    ("SDST3905", "Introduction to Financial Derivatives", 6, 2, 1, ["SDST2902", "MATH3906"]),
    ("SDST3906", "Risk Theory I", 6, 1, 1, ["SDST2901"]),
    ("SDST3907", "Linear Models and Forecasting", 6, 2, 1, ["SDST3600"]),
    ("SDST3908", "Credibility Theory and Loss Modelling", 6, 2, 1, ["SDST3906"]),
    ("SDST3909", "Life Contingencies II", 6, 1, 1, ["SDST3901"]),
    ("SDST3910", "Financial Economics I", 6, 1, 1, ["SDST2902"]),
    ("SDST3911", "Financial Economics II", 6, 2, 1, ["SDST3910"]),
    ("SDST3951", "Topics on Advanced Actuarial Modelling", 6, 2, 0, ["SDST3908"]),
    ("SDST3953", "Fundamentals of Actuarial Practice", 6, 1, 1, ["SDST3909"]),
    ("SDST3954", "Current Topics in Actuarial Science", 6, 1, 0, ["SDST3909"]),
    ("SDST3956", "Life Contingencies III", 6, 1, 1, ["SDST3909"]),
    ("SDST4601", "Time-Series Analysis", 6, 1, 1, ["SDST3600", "MATH2101"]),
    ("SDST4602", "Multivariate Data Analysis", 6, 2, 1, ["SDST3600"]),
    ("SDST4603", "Current Topics in Risk Management", 6, 1, 0, ["SDST3610"]),
    ("SDST4607", "Credit Risk Analysis", 6, 2, 0, ["SDST3618"]),
    ("SDST4608", "Market Risk Analysis", 6, 2, 0, ["SDST3618"]),
    ("SDST4609", "Big Data Analytics", 6, 2, 1, ["SDST3612", "COMP3513"]),
    ("SDST4610", "Bayesian Learning", 6, 1, 0, ["SDST3902"]),
    ("SDST4614", "Quantitative Risk Management", 6, 2, 1, ["SDST3618", "SDST3906"]),
    ("SDST4710", "Capstone Experience for Statistics Undergraduates", 6, 0, 1, ["SDST3621"]),
    ("SDST4711", "Capstone Experience for Actuarial Science Undergraduates", 6, 0, 1, ["SDST3953"]),
    ("SDST4798", "Statistics and Actuarial Science Project", 6, 0, 1, ["SDST4710"]),
    ("SDST4903", "Actuarial Techniques for General Insurance", 6, 1, 1, ["SDST3906"]),
    ("SDST4904", "Statistical Learning for Risk Modelling", 6, 2, 0, ["SDST3612", "SDST3906"]),
]

# --- AI & Data Science (ASAI / APAI) --------------------------------------
ASAI = [
    ("ASAI1001", "Artificial Intelligence: Foundation, Philosophy and Ethics", 6, 1, 1, []),
    ("ASAI3010", "Image Processing and Computer Vision", 6, 2, 1, ["COMP3314"]),
    ("ASAI3021", "Modern Biostatistics", 6, 1, 0, ["SDST2602"]),
    ("ASAI4011", "Natural Language Processing", 6, 1, 1, ["COMP3340"]),
    ("ASAI4013", "Applied High-Performance Computing and Parallel Programming", 6, 2, 1, ["COMP3358"]),
    ("ASAI4022", "Omics Data Analysis", 6, 2, 0, ["COMP3353"]),
    ("APAI4012", "High-performance Computing: Algorithms and Applications", 6, 1, 0, ["COMP3358"]),
    ("APAI4099", "Special Topics in Applied AI", 6, 1, 0, ["COMP3314"]),
]

# --- Mathematics (MATH) ----------------------------------------------------
MATH = [
    ("MATH1011", "University Mathematics I", 6, 0, 1, []),
    ("MATH1013", "University Mathematics II", 6, 0, 1, ["MATH1011"]),
    ("MATH1821", "Mathematical Methods for Actuarial Science I", 6, 1, 1, []),
    ("MATH1851", "Calculus and Ordinary Differential Equations", 6, 0, 1, []),
    ("MATH1853", "Linear Algebra, Probability and Statistics", 6, 0, 1, []),

    ("MATH2012", "Fundamental Concepts of Mathematics", 6, 0, 1, ["MATH1013"]),
    ("MATH2014", "Multivariable Calculus and Linear Algebra", 6, 0, 1, ["MATH1013"]),
    ("MATH2101", "Linear Algebra I", 6, 0, 1, ["MATH1853"]),
    ("MATH2102", "Linear Algebra II", 6, 0, 0, ["MATH2101"]),
    ("MATH2211", "Multivariable Calculus", 6, 0, 1, ["MATH1851"]),
    ("MATH2241", "Introduction to Mathematical Analysis", 6, 0, 0, ["MATH2012"]),
    ("MATH2822", "Mathematical Methods for Actuarial Science II", 6, 2, 1, ["MATH1821"]),

    ("MATH3303", "Matrix Theory and Its Applications", 6, 2, 0, ["MATH2101"]),
    ("MATH3304", "Introduction to Number Theory", 6, 2, 0, ["MATH2012"]),
    ("MATH3401", "Analysis I", 6, 1, 0, ["MATH2241"]),
    ("MATH3403", "Functions of a Complex Variable", 6, 2, 0, ["MATH2211"]),
    ("MATH3405", "Differential Equations", 6, 2, 0, ["MATH1851"]),
    ("MATH3600", "Discrete Mathematics", 6, 1, 1, ["COMP2121"]),
    ("MATH3601", "Numerical Analysis", 6, 1, 0, ["MATH2014", "COMP1117"]),
    ("MATH3603", "Probability Theory", 6, 1, 1, ["SDST2602", "MATH2211"]),
    ("MATH3604", "Measure Theoretic Probability", 6, 2, 0, ["MATH3603"]),
    ("MATH3900", "Optimization for AI and Data Analysis", 6, 1, 1, ["MATH2014", "COMP2501"]),
    ("MATH3901", "Operations Research I", 6, 2, 1, ["MATH2014"]),
    ("MATH3904", "Introduction to Optimization", 6, 2, 0, ["MATH3901"]),
    ("MATH3906", "Financial Calculus", 6, 2, 1, ["MATH2211"]),
    ("MATH3911", "Game Theory and Strategy", 6, 2, 0, ["SDST2601"]),
    ("MATH3943", "Network Models in Operations Research", 6, 1, 0, ["MATH3901"]),

    ("MATH4602", "Scientific Computing", 6, 2, 0, ["MATH3601"]),
    ("MATH4902", "Operations Research II", 6, 2, 0, ["MATH3901"]),
    ("MATH4907", "Numerical Methods for Financial Calculus", 6, 1, 0, ["MATH3906", "MATH3601"]),
]

# --- assemble --------------------------------------------------------------
_RAW = (
    [("COMP", r) for r in COMP]
    + [("SDST", r) for r in SDST]
    + [("ASAI", r) for r in ASAI]
    + [("MATH", r) for r in MATH]
)


def _level(code):
    """Course level 1-4 from the numeric part of the code, e.g. COMP3278 -> 3."""
    digits = "".join(ch for ch in code if ch.isdigit())
    return int(digits[0]) if digits else 1


def build_catalogue():
    """Return a list of course dicts ready for database insertion."""
    rows = []
    for dept, (code, title, credits, sem, is_core, prereqs) in _RAW:
        rows.append({
            "course_code": code,
            "course_title": title,
            "department": dept,
            "credits": credits,
            "semester_offered": sem,       # 1, 2, or 0 = both/year-long
            "course_level": _level(code),
            "is_core": bool(is_core),
            "prerequisites": list(prereqs),
        })
    return rows


CATALOGUE = build_catalogue()
BY_CODE = {c["course_code"]: c for c in CATALOGUE}


def self_check():
    """Validate the catalogue: unique codes, prerequisites exist and are acyclic.

    Level rule: a prerequisite may sit at the SAME level as the course it leads
    to (e.g. SDST2601 -> SDST2602 are both level 2; COMP3278 -> COMP3323 are
    both level 3). That is normal university sequencing. What is NOT allowed is
    a prerequisite at a STRICTLY HIGHER level, which would mean the student has
    to finish an advanced course before its own prerequisite.
    """
    problems = []
    seen = set()
    for c in CATALOGUE:
        code = c["course_code"]
        if code in seen:
            problems.append("duplicate course_code: %s" % code)
        seen.add(code)
        if not (1 <= c["course_level"] <= 4):
            problems.append("bad level %s: %s" % (code, c["course_level"]))
        if c["semester_offered"] not in (0, 1, 2):
            problems.append("bad semester %s: %s" % (code, c["semester_offered"]))
        if c["credits"] not in (6, 12):
            problems.append("odd credits %s: %s" % (code, c["credits"]))
        if not c["course_title"].strip():
            problems.append("empty title: %s" % code)
        for p in c["prerequisites"]:
            if p == code:
                problems.append("self-prerequisite: %s" % code)
                continue
            if p not in BY_CODE:
                problems.append("dangling prerequisite %s for %s" % (p, code))
                continue
            if BY_CODE[p]["course_level"] > c["course_level"]:
                problems.append(
                    "prerequisite %s (L%d) is ABOVE %s (L%d)"
                    % (p, BY_CODE[p]["course_level"], code, c["course_level"]))

    # cycle detection over the prerequisite DAG (iterative to avoid recursion
    # limits on long chains)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {c["course_code"]: WHITE for c in CATALOGUE}

    for root in BY_CODE:
        if color[root] != WHITE:
            continue
        stack = [(root, iter([p for p in BY_CODE[root]["prerequisites"] if p in BY_CODE]))]
        color[root] = GREY
        path = [root]
        while stack:
            node, children = stack[-1]
            advanced = False
            for p in children:
                if color[p] == GREY:
                    problems.append("cycle: %s -> %s" % (" -> ".join(path), p))
                elif color[p] == WHITE:
                    color[p] = GREY
                    path.append(p)
                    stack.append((p, iter([q for q in BY_CODE[p]["prerequisites"]
                                            if q in BY_CODE])))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return problems


if __name__ == "__main__":
    print("catalogue size:", len(CATALOGUE))
    from collections import Counter
    print("by department:", dict(Counter(c["department"] for c in CATALOGUE)))
    print("by level     :", dict(sorted(Counter(c["course_level"] for c in CATALOGUE).items())))
    print("by semester  :", dict(sorted(Counter(c["semester_offered"] for c in CATALOGUE).items())))
    n_pre = sum(len(c["prerequisites"]) for c in CATALOGUE)
    print("prerequisite edges:", n_pre)
    probs = self_check()
    print("self-check problems:", len(probs))
    for p in probs[:25]:
        print("   !", p)
