"""Refresh plans, query checks, validation, exports and figures for the current cohort.

Every stage stops the chain on a non-zero exit code, so a failing check can
never be silently swallowed by a later stage. Usage:

    python run_all.py            # full pipeline
    python run_all.py --no-fig   # skip figure regeneration
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

STAGES = [
    ("recommendation_engine.py", "plan the current cohort and persist course selections and advice"),
    ("run_queries.py", "execute the SQL library against the current plans"),
    ("validate_engine.py",     "engine invariants, shuffled-label control, R3 precision/recall"),
    ("verify_engine_output.py", "persistence checks"),
    ("export_csv.py",          "flat CSV extracts"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fig", action="store_true", help="skip make_figures.py")
    ap.add_argument("--fresh-rebuild", action="store_true", help="replace the database with a newly generated synthetic cohort before planning")
    a = ap.parse_args()

    stages = list(STAGES)
    if a.fresh_rebuild or not (HERE.parent / "data" / "student_info.db").is_file():
        source = "generate new synthetic enrolments" if a.fresh_rebuild else "restore the report cohort"
        stages.insert(0, ("build_database.py", source))
    if not a.no_fig:
        stages.append(("make_figures.py", "regenerate the seven report figures"))

    for script, desc in stages:
        print("\n" + "#" * 78)
        print("# %s  (%s)" % (script, desc))
        print("#" * 78)
        args = ["--generate"] if script == "build_database.py" and a.fresh_rebuild else []
        rc = subprocess.call([sys.executable, "-X", "utf8", str(HERE / script), *args])
        if rc != 0:
            print("\nSTAGE FAILED: %s (exit %d) — stopping the chain." % (script, rc))
            sys.exit(rc)
    print("\n" + "=" * 78)
    print("PIPELINE COMPLETE — every stage exited 0.")
    print("database : %s" % (HERE.parent / "data" / "student_info.db"))
    print("outputs  : %s" % (HERE.parent / "output"))


if __name__ == "__main__":
    main()
