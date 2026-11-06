"""Dev helper: load all snapshots once into a pickle-free session and explain questions."""
import sys, json
sys.path.insert(0, 'dev'); import load
sys.path.insert(0, 'submission')
from kb.system import KnowledgeSystem
from kb.understand import parse
from kb.match import rank

def system(selftest=False):
    ks = KnowledgeSystem()
    for s in load.snaps(selftest): ks.ingest(s)
    return ks

def top_rows(ks, question, n=8, snap=-1):
    v = ks.store.snapshots[snap]; q = parse(question)
    for s in rank(v.facts, q, ks._idf[v.snapshot_id])[:n]:
        f = s.fact
        print(round(s.score,2), f.page.tier, f.page.url[23:70], '|', f.caption, '|', f.label, '|', [x.text for x in f.values], s.why)

if __name__ == '__main__':
    ks = system()
    for qq in sys.argv[1:]:
        print('Q:', qq); print(json.dumps(ks.explain(qq), indent=1, default=str)[:1500]); top_rows(ks, qq)
