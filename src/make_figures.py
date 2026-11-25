"""Generate database and advising figures in output/figures from the current SQLite data."""
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False
OUT = C.FIGURE_DIR

INK = "#1c3d52"
ACCENT = "#22506b"
MUTED = "#8a9aa6"
GOLD = "#c9a227"
RED = "#b03a2e"


def conn():
    c = sqlite3.connect(str(C.DB_PATH))
    c.row_factory = sqlite3.Row
    return c


# ==========================================================================
# 1. ER DIAGRAM
# ==========================================================================
def fig_er(cn):
    """Show core associations with key fields and relationship cardinalities."""
    fig, ax = plt.subplots(figsize=(12.5, 8.0))
    ax.set_xlim(0, 12.5)
    ax.set_ylim(0, 8.0)
    ax.axis("off")
    ax.text(.15, 7.69, "Student records and study plans", fontsize=18, weight="bold", color=INK)
    ax.text(.15, 7.34, "Lines run from a single parent to its child rows. Repeated boxes refer to the same table.",
            color=INK, fontsize=10)
    def box(x,y,w,table,body,fill):
        ax.add_patch(FancyBboxPatch((x,y),w,.84,boxstyle="round,pad=.06",edgecolor=MUTED,facecolor=fill))
        ax.text(x+.13,y+.57,table,fontsize=11.6,color=INK,weight="bold",va="center")
        ax.text(x+.13,y+.23,body,fontsize=8.5,color=INK,va="center")
    def rel(x,xx,y,reverse=False):
        ax.annotate("", xy=(x if reverse else xx,y), xytext=(xx if reverse else x,y),
                    arrowprops=dict(arrowstyle="->",lw=1.4,color=ACCENT))
        ax.text(x+.05,y+.10,"N" if reverse else "1",fontsize=8.4,color=ACCENT)
        ax.text(xx-.19,y+.10,"1" if reverse else "N",fontsize=8.4,color=ACCENT)
    pale, junction, output = "#e9f2f3", "#f7f0df", "#e9f2e6"
    triples = [
        (6.12, ("Student","student_id"), ("Enrolment","student · course · year · semester"), ("Course","course_code")),
        (4.98, ("Programme","programme_code"), ("ProgrammeCourse","programme · course"), ("Course","course_code")),
        (3.84, ("Course","the dependent course"), ("Prerequisite","course_code · prereq_code"), ("Course","the prerequisite course")),
        (2.43, ("StudyPlan","plan_id; one per student and term"), ("PlanCourse","plan · position; unique plan · course"), ("Course","selected course")),
        (1.29, ("StudyPlan","plan_id"), ("Recommendation","rec_id; rule and rationale"), ("Course","optional course reference")),
    ]
    for y,left,mid,right in triples:
        box(.21,y,2.85,*left,pale)
        box(4.52,y,3.46,*mid,output if y < 3 else junction)
        box(9.43,y,2.75,*right,pale)
        rel(3.18,4.42,y+.44)
        rel(8.07,9.31,y+.44,True)
    ax.text(.22,.76,"Other parent tables",color=ACCENT,weight="bold",fontsize=10)
    ax.text(.22,.46,"GradeScale → Enrolment (grade)      Department → Programme and Course      Programme → Student",fontsize=10,color=INK)
    ax.text(.22,.16,"Student → StudyPlan and Recommendation      A course reference is optional on term-wide recommendations.",fontsize=10,color=INK)
    fig.savefig(OUT / "fig_er_diagram.png", dpi=170, bbox_inches="tight", pad_inches=.10)
    plt.close(fig)


# ==========================================================================
# 2. GRADE DISTRIBUTION
# ==========================================================================
def fig_grades(cn):
    order = list(C.GRADE_SCALE.keys())
    rows = cn.execute("""SELECT e.grade, COUNT(*) n FROM Enrolment e
                          WHERE e.grade IS NOT NULL GROUP BY e.grade""").fetchall()
    counts = {r["grade"]: r["n"] for r in rows}
    vals = [counts.get(g, 0) for g in order]
    tot = sum(vals)
    pct = [100.0 * v / tot for v in vals]
    colors = ["#1e7a46" if C.GRADE_SCALE[g] >= 3.0 else
              ("#c9a227" if C.GRADE_SCALE[g] >= 2.0 else RED) for g in order]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.2, 4.6))
    b = a1.bar(order, pct, color=colors, edgecolor="white", linewidth=0.8)
    for r, v in zip(b, pct):
        a1.text(r.get_x() + r.get_width() / 2, v + 0.25, "%.1f" % v,
                ha="center", fontsize=8.4, color=INK)
    a1.set_ylabel("share of all graded enrolments (%)")
    a1.set_xlabel("HKU letter grade")
    a1.set_title(f"Grade distribution across {tot:,} graded attempts",
                 fontsize=11, fontweight="bold", color=INK)
    a1.set_ylim(0, max(pct) * 1.18)
    a1.spines[["top", "right"]].set_visible(False)
    a1.grid(axis="y", alpha=0.25, linewidth=0.6)

    # cumulative share, best-to-worst
    cum = np.cumsum(pct)
    a2.plot(order, cum, marker="o", color=ACCENT, linewidth=2.0, markersize=5)
    a2.axhline(50, color=GOLD, linestyle="--", linewidth=1.2)
    a2.text(len(order) - 0.4, 52, "median", color="#7a6410", fontsize=8.6, ha="right")
    a2.set_ylabel("cumulative share (%)")
    a2.set_xlabel("HKU letter grade (best → worst)")
    a2.set_title("Cumulative distribution", fontsize=11, fontweight="bold", color=INK)
    a2.set_ylim(0, 105)
    a2.spines[["top", "right"]].set_visible(False)
    a2.grid(alpha=0.25, linewidth=0.6)
    a2.tick_params(axis="x", labelsize=8.6)

    fig.suptitle("Generated grade distribution (synthetic, latent-ability model)",
                 fontsize=11.5, color="#5d6d7e", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig_grade_distribution.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("  fig_grade_distribution.png")


# ==========================================================================
# 3. PROGRAMME / YEAR GPA
# ==========================================================================
def fig_programme(cn):
    prog = cn.execute("""SELECT p.programme_code, p.programme_name,
                                AVG(g.cumulative_gpa) m,
                                MIN(g.cumulative_gpa) lo, MAX(g.cumulative_gpa) hi,
                                COUNT(*) n
                           FROM Programme p JOIN Student s ON s.programme_code=p.programme_code
                           JOIN v_student_gpa g ON g.student_id=s.student_id
                       GROUP BY p.programme_code ORDER BY m DESC""").fetchall()
    yr = cn.execute("""SELECT s.year_of_study, AVG(g.cumulative_gpa) m, COUNT(*) n
                         FROM Student s JOIN v_student_gpa g ON g.student_id=s.student_id
                     GROUP BY s.year_of_study ORDER BY s.year_of_study""").fetchall()

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.2, 4.8))

    labels = ["%s\n(%s, n=%d)" % (r["programme_name"][:26], r["programme_code"], r["n"])
              for r in prog]
    means = [r["m"] for r in prog]
    errs = [[r["m"] - r["lo"] for r in prog], [r["hi"] - r["m"] for r in prog]]
    b = a1.barh(range(len(prog)), means, xerr=errs, color=ACCENT, alpha=0.85,
                edgecolor="white", capsize=4, error_kw=dict(ecolor=MUTED, linewidth=1.1))
    for i, r in enumerate(prog):
        a1.text(r["m"] + 0.06, i, "%.3f" % r["m"], va="center", fontsize=9, color=INK)
    a1.set_yticks(range(len(prog)))
    a1.set_yticklabels(labels, fontsize=8.4)
    a1.invert_yaxis()
    a1.set_xlabel("cumulative GPA (mean, whiskers = min/max)")
    a1.set_title("GPA by programme", fontsize=11, fontweight="bold", color=INK)
    a1.set_xlim(0, 4.5)
    a1.axvline(3.0, color=GOLD, linestyle="--", linewidth=1.1)
    a1.text(3.03, len(prog) - 0.35, "3.0", color="#7a6410", fontsize=8.4)
    a1.spines[["top", "right"]].set_visible(False)
    a1.grid(axis="x", alpha=0.25, linewidth=0.6)

    xs = [r["year_of_study"] for r in yr]
    ms = [r["m"] for r in yr]
    a2.bar(xs, ms, color=[GOLD, ACCENT, "#4f8fa8", "#7fb3c8"], edgecolor="white")
    for x, m, r in zip(xs, ms, yr):
        a2.text(x, m + 0.05, "%.3f\n(n=%d)" % (m, r["n"]), ha="center",
                fontsize=8.6, color=INK)
    a2.set_xticks(xs)
    a2.set_xticklabels(["Year %d" % x for x in xs])
    a2.set_ylabel("mean cumulative GPA")
    a2.set_title("GPA by year of study", fontsize=11, fontweight="bold", color=INK)
    a2.set_ylim(0, max(ms) * 1.30)
    a2.spines[["top", "right"]].set_visible(False)
    a2.grid(axis="y", alpha=0.25, linewidth=0.6)

    fig.suptitle("Academic standing by programme and by year (synthetic data)",
                 fontsize=11.5, color="#5d6d7e", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig_programme_gpa.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("  fig_programme_gpa.png")


# ==========================================================================
# 4. RECOMMENDATION TYPES
# ==========================================================================
def fig_recs(cn):
    rows = cn.execute("""SELECT rec_type, COUNT(*) n, COUNT(DISTINCT student_id) s
                           FROM Recommendation GROUP BY rec_type
                          ORDER BY n DESC""").fetchall()
    rules = cn.execute("""SELECT rule_id, COUNT(*) n FROM Recommendation
                          GROUP BY rule_id ORDER BY n DESC""").fetchall()

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.6, 4.9))

    labels = [r["rec_type"] for r in rows]
    ns = [r["n"] for r in rows]
    ss = [r["s"] for r in rows]
    x = np.arange(len(labels))
    a1.bar(x - 0.19, ns, 0.38, label="recommendation rows", color=ACCENT)
    a1.bar(x + 0.19, ss, 0.38, label="distinct students affected", color=GOLD)
    for i, (n, s) in enumerate(zip(ns, ss)):
        a1.text(i - 0.19, n + 40, str(n), ha="center", fontsize=8.2, color=INK)
        a1.text(i + 0.19, s + 40, str(s), ha="center", fontsize=8.2, color="#7a6410")
    a1.set_xticks(x)
    a1.set_xticklabels(labels, rotation=18, ha="right", fontsize=8.8)
    a1.set_ylabel("count")
    a1.set_title(f"Recommendations by type ({sum(ns):,} rows)",
                 fontsize=11, fontweight="bold", color=INK)
    a1.legend(fontsize=8.6, frameon=False)
    a1.spines[["top", "right"]].set_visible(False)
    a1.grid(axis="y", alpha=0.25, linewidth=0.6)
    a1.set_ylim(0, max(ns) * 1.20)

    rl = [r["rule_id"] for r in rules]
    rn = [r["n"] for r in rules]
    cols = [RED if "FALLBACK" in r or "SHORTFALL" in r else
            (GOLD if "MODEL" in r else ACCENT) for r in rl]
    a2.barh(range(len(rl)), rn, color=cols, edgecolor="white")
    for i, v in enumerate(rn):
        a2.text(v + 40, i, str(v), va="center", fontsize=8.4, color=INK)
    a2.set_yticks(range(len(rl)))
    a2.set_yticklabels(rl, fontsize=8.6)
    a2.invert_yaxis()
    a2.set_xlabel("rows emitted")
    a2.set_title("Rows by rule id (traceability)",
                 fontsize=11, fontweight="bold", color=INK)
    a2.spines[["top", "right"]].set_visible(False)
    a2.grid(axis="x", alpha=0.25, linewidth=0.6)
    a2.set_xlim(0, max(rn) * 1.16)
    a2.text(0.98, 0.04, "gold = model-sourced (advisory only)\nred = fallback / shortfall disclosure",
            transform=a2.transAxes, ha="right", va="bottom", fontsize=8.0, color="#5d6d7e")

    fig.suptitle("Recommendation engine output, every row traceable to a rule id",
                 fontsize=11.5, color="#5d6d7e", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig_rec_types.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("  fig_rec_types.png")


# ==========================================================================
# 5. GPA BANDS AND RISK
# ==========================================================================
def fig_bands(cn):
    band_rows = cn.execute("""SELECT gpa_band, COUNT(*) n, AVG(recommended_course_count) c
                                FROM StudyPlan GROUP BY gpa_band""").fetchall()
    order = ["EXCELLENT", "GOOD", "SATISFACTORY", "AT RISK", "CRITICAL"]
    bm = {r["gpa_band"]: r for r in band_rows}
    ns = [bm[b]["n"] if b in bm else 0 for b in order]
    cs = [bm[b]["c"] if b in bm else 0 for b in order]
    risk = cn.execute("""SELECT risk_level, COUNT(*) n FROM StudyPlan GROUP BY risk_level""").fetchall()
    rm = {r["risk_level"]: r["n"] for r in risk}

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.2, 4.7),
                                 gridspec_kw={"width_ratios": [1.5, 1]})
    x = np.arange(len(order))
    cols = ["#1e7a46", "#4f9d69", GOLD, "#d98324", RED]
    a1.bar(x - 0.2, ns, 0.4, color=cols, edgecolor="white", label="students")
    for i, v in enumerate(ns):
        a1.text(i - 0.2, v + 6, str(v), ha="center", fontsize=8.6, color=INK)
    a1.set_xticks(x)
    a1.set_xticklabels(order, fontsize=9)
    a1.set_ylabel("number of students")
    a1.set_ylim(0, max(ns) * 1.25)
    a1.set_title("Rule R1: GPA band → suggested course load",
                 fontsize=11, fontweight="bold", color=INK)
    a1.spines[["top", "right"]].set_visible(False)
    a1.grid(axis="y", alpha=0.25, linewidth=0.6)

    a1b = a1.twinx()
    a1b.plot(x, cs, marker="D", color=ACCENT, linewidth=2.0, markersize=6,
             label="mean suggested courses")
    for i, v in enumerate(cs):
        a1b.text(i + 0.13, v + 0.06, "%.1f" % v, fontsize=8.4, color=ACCENT)
    a1b.set_ylim(0, 7)
    a1b.set_ylabel("mean suggested courses", color=ACCENT)
    a1b.tick_params(axis="y", labelcolor=ACCENT)
    a1b.spines["top"].set_visible(False)
    h1, l1 = a1.get_legend_handles_labels()
    h2, l2 = a1b.get_legend_handles_labels()
    a1.legend(h1 + h2, l1 + l2, fontsize=8.4, frameon=False, loc="upper right")

    ro = ["HIGH", "MEDIUM", "LOW"]
    rv = [rm.get(k, 0) for k in ro]
    rc = [RED, GOLD, "#1e7a46"]
    wedges, _, auto = a2.pie(rv, colors=rc, autopct=lambda p: "%d\n(%.1f%%)" % (round(p * sum(rv) / 100), p),
                             startangle=90, textprops=dict(fontsize=8.6, color="white"),
                             wedgeprops=dict(edgecolor="white", linewidth=1.6))
    a2.legend(wedges, ro, fontsize=8.8, frameon=False, loc="lower center",
              ncol=3, bbox_to_anchor=(0.5, -0.10))
    a2.set_title("Overall risk level", fontsize=11, fontweight="bold", color=INK)

    fig.suptitle("Course-load planning bands and risk triage",
                 fontsize=11.5, color="#5d6d7e", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig_gpa_bands.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("  fig_gpa_bands.png")


# ==========================================================================
# 6. MODEL VALIDATION (real vs shuffled)
# ==========================================================================
def fig_model(cn, eng):
    """Use the same chronological holdout and controls as the advising engine."""
    metrics = eng.fit_model()
    fig, ax = plt.subplots(figsize=(7.4, 4.5))
    if not metrics or metrics.get("roc") is None:
        ax.axis("off")
        ax.text(.5,.5,"No chronological evaluation available for this run.",
                transform=ax.transAxes, ha="center", color=INK)
    else:
        for key, auc, title, color in [
            ("roc", "auc", "Held-out grades", ACCENT),
            ("control_roc", "control_auc", "Shuffled-label control", GOLD),
        ]:
            fpr, tpr = metrics[key][:2]
            ax.plot(fpr, tpr, color=color, lw=2, label=f"{title}   AUC {metrics[auc]:.3f}")
        ax.plot([0,1],[0,1], "--", color=MUTED, lw=1)
        ax.set(xlim=(0,1), ylim=(0,1.02), xlabel="False positive rate", ylabel="True positive rate")
        term = metrics["holdout_term"]
        ax.set_title(f"Predicting weak grades in a later term   |   {term[0]} S{term[1]}", color=INK)
        ax.legend(loc="lower right", frameon=False)
        ax.spines[["right","top"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "fig_model_validation.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


# ==========================================================================
# 7. PREREQUISITE CHAIN DEPTH
# ==========================================================================
def fig_prereq(cn, eng):
    memo = {}

    def depth(code):
        if code in memo:
            return memo[code]
        ps = [p for p in eng.prereq.get(code, []) if p in eng.course]
        d = 0 if not ps else 1 + max(depth(p) for p in ps)
        memo[code] = d
        return d

    rows = cn.execute("""SELECT cs.course_code, cs.mean_grade_point, cs.n_taken,
                                cs.fail_rate_pct FROM v_course_stats cs
                          WHERE cs.n_taken >= 30""").fetchall()
    ds, ms, fs, sizes, labels = [], [], [], [], []
    for r in rows:
        d = depth(r["course_code"])
        ds.append(d)
        ms.append(r["mean_grade_point"])
        fs.append(r["fail_rate_pct"])
        sizes.append(r["n_taken"])
        labels.append(r["course_code"])

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.2, 4.8))
    sc = a1.scatter(ds, ms, s=[max(18, min(320, n / 3)) for n in sizes],
                    c=fs, cmap="RdYlGn_r", alpha=0.82, edgecolor="white", linewidth=0.9)
    a1.set_xlabel("prerequisite chain depth (0 = no prerequisite)")
    a1.set_ylabel("mean grade point")
    a1.set_title("Does chain depth predict difficulty?", fontsize=11,
                 fontweight="bold", color=INK)
    a1.grid(alpha=0.25, linewidth=0.6)
    a1.spines[["top", "right"]].set_visible(False)
    cb = fig.colorbar(sc, ax=a1, pad=0.02)
    cb.set_label("fail rate (%)", fontsize=8.6)
    cb.ax.tick_params(labelsize=8)
    # annotate the extremes
    if ms:
        i_min = int(np.argmin(ms))
        i_max = int(np.argmax(ms))
        for i, dy in ((i_min, -0.22), (i_max, 0.20)):
            a1.annotate(labels[i], (ds[i], ms[i]), textcoords="offset points",
                        xytext=(0, 14 if dy > 0 else -20), ha="center",
                        fontsize=8.0, color=INK)
    if len(ds) > 2:
        z = np.polyfit(ds, ms, 1)
        xs = np.linspace(min(ds), max(ds), 50)
        a1.plot(xs, np.polyval(z, xs), color=ACCENT, linewidth=1.8, linestyle="--",
                label="linear fit  r=%.2f" % np.corrcoef(ds, ms)[0, 1])
        a1.legend(fontsize=8.4, frameon=False, loc="lower left")

    # how many required courses are blocked, by programme
    rows2 = cn.execute("""SELECT s.programme_code, p.programme_name,
                                 1.0 * COUNT(DISTINCT v.student_id || char(31) || v.blocked_course) / COUNT(DISTINCT s.student_id) AS mean_blocked
                            FROM Student s JOIN Programme p ON p.programme_code=s.programme_code
                       LEFT JOIN v_prereq_gap v ON v.student_id=s.student_id
                             AND v.requirement_type IN ('CORE','FOUNDATION')
                        GROUP BY s.programme_code, p.programme_name
                        ORDER BY mean_blocked DESC""").fetchall()
    if rows2:
        yv = range(len(rows2))
        a2.barh(list(yv), [r["mean_blocked"] for r in rows2], color=ACCENT,
                edgecolor="white")
        for i, r in enumerate(rows2):
            a2.text(r["mean_blocked"] + 0.4, i, "%.1f" % r["mean_blocked"],
                    va="center", fontsize=8.8, color=INK)
        a2.set_yticks(list(yv))
        a2.set_yticklabels(["%s (%s)" % (r["programme_name"][:24], r["programme_code"])
                            for r in rows2], fontsize=8.4)
        a2.invert_yaxis()
        a2.set_xlabel("mean blocked required courses per student")
        a2.set_title("Curriculum blockage by programme", fontsize=11,
                     fontweight="bold", color=INK)
        a2.spines[["top", "right"]].set_visible(False)
        a2.grid(axis="x", alpha=0.25, linewidth=0.6)
        a2.set_xlim(0, max(r["mean_blocked"] for r in rows2) * 1.18)

    fig.suptitle("Prerequisite structure: depth vs difficulty, and blockage by programme",
                 fontsize=11.5, color="#5d6d7e", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig_prereq_chain.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("  fig_prereq_chain.png")


def main():
    if not C.DB_PATH.exists():
        sys.exit("database missing — run build_database.py first")
    print("generating figures into %s" % OUT)
    cn = conn()
    from recommendation_engine import Engine
    eng = Engine()
    fig_er(cn)
    fig_grades(cn)
    fig_programme(cn)
    fig_recs(cn)
    fig_bands(cn)
    fig_model(cn, eng)
    fig_prereq(cn, eng)
    eng.close()
    cn.close()
    print("done — %d files" % len(list(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
