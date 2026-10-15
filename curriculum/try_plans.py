"""
Phase 1 task: "Test on 5 different topics and fix bad plans."

Needs a real key in .env (OPENAI_API_KEY or GEMINI_API_KEY) and LLM_PROVIDER set.
Run from the repo root:  python -m curriculum.try_plans
Read each plan and note anything wrong (bad order, too broad, missing basics).
"""
from . import store
from .core import generate_plan
from .validate import PlanError

TOPICS = [
    ("Dynamic programming", "I know the basics", "Crack interviews", "2 weeks"),
    ("Photosynthesis", "Complete beginner", "Pass an exam", "3 days"),
    ("SQL joins", "Complete beginner", "Build a project", "1 week"),
    ("Transformers in deep learning", "Intermediate", "Just understand it", "2 weeks"),
    ("Supply and demand", "Complete beginner", "Pass an exam", "1 week"),
]

if __name__ == "__main__":
    conn = store.db("data/try_plans.db")
    for i, (topic, level, goal, time) in enumerate(TOPICS):
        user = f"tester{i}"
        print(f"\n=== {topic} ({level}, {goal}, {time}) ===")
        try:
            generate_plan(user, topic, level, goal, time, conn=conn)
        except PlanError as e:
            print("FAILED:", e)
            continue
        plan = store.get_plan(conn, user)
        names = {c["id"]: c["name"] for c in plan}
        for c in plan:
            needs = ", ".join(names[p] for p in c["prerequisites"]) or "-"
            print(f"{c['order'] + 1}. {c['name']}  (needs: {needs})")
            print(f"   {c['definition']}")
