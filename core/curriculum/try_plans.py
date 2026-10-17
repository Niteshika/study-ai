"""
Phase 1 task: "Test on 5 different topics and fix bad plans."

Needs a real key in .env (OPENAI_API_KEY or GEMINI_API_KEY) and LLM_PROVIDER set.
Run from the repo root:  python -m core.curriculum.try_plans
Uses the database in DATABASE_URL, under the test user 'tester'. The plans are
deleted again at the end, so nothing is left behind in your real database.
Read each plan and note anything wrong (bad order, too broad, missing basics).

This is a manual check script. The app never imports it.
"""
from core import db

from . import store
from .service import delete_plan, generate_plan
from .validate import PlanError

TOPICS = [
    ("Dynamic programming", "I know the basics", "Crack interviews", "2 weeks"),
    ("Photosynthesis", "Complete beginner", "Pass an exam", "3 days"),
    ("SQL joins", "Complete beginner", "Build a project", "1 week"),
    ("Transformers in deep learning", "Intermediate", "Just understand it", "2 weeks"),
    ("Supply and demand", "Complete beginner", "Pass an exam", "1 week"),
]

TEST_USER = "tester"

if __name__ == "__main__":
    made = []
    with db.connect() as conn:
        try:
            for topic, level, goal, time in TOPICS:  # one test user, many plans
                print(f"\n=== {topic} ({level}, {goal}, {time}) ===")
                try:
                    result = generate_plan(TEST_USER, topic, level, goal, time, conn=conn)
                except PlanError as e:
                    print("FAILED:", e)
                    continue
                made.append(result["plan_id"])
                plan = store.get_plan(conn, result["plan_id"])
                names = {c["id"]: c["name"] for c in plan}
                for c in plan:
                    needs = ", ".join(names[p] for p in c["prerequisites"]) or "-"
                    print(f"{c['order'] + 1}. {c['name']}  (needs: {needs})")
                    print(f"   {c['definition']}")
        finally:
            for plan_id in made:  # clean up, even if something crashed
                delete_plan(TEST_USER, plan_id, conn=conn)
            print(f"\nCleaned up {len(made)} test plan(s).")
    db.close_pool()
