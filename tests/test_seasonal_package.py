import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT/"skills/naver-seasonal-blog-writer"


class PackageTests(unittest.TestCase):
    def test_isolated_cli_end_to_end_with_original_paths_blocked(self):
        with tempfile.TemporaryDirectory(prefix="seasonal-isolated-") as tmp:
            base = Path(tmp); copied = base/"naver-seasonal-blog-writer"; work = base/"work"; work.mkdir()
            shutil.copytree(SKILL, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            # Reject reads from both the original repository and installed skills.
            guard = """import sys,runpy,os
banned=sys.argv[1:3]; script=sys.argv[3]; sys.argv=sys.argv[3:]
def audit(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)):
  path=os.path.realpath(os.fsdecode(args[0]))
  if any(path==p or path.startswith(p+os.sep) for p in banned): raise RuntimeError('Blocked development/skill path: '+path)
sys.addaudithook(audit)
sys.path.insert(0,os.path.dirname(script))
runpy.run_path(script,run_name='__main__')
"""
            def cli(script, *args, expected=0):
                run = subprocess.run([sys.executable, "-E", "-s", "-S", "-B", "-c", guard, str(ROOT), str(Path.home()/".codex/skills"), str(copied/"scripts"/script), *map(str,args)], cwd=base, env={"PATH": os.defpath, "HOME": str(base), "LANG": "en_US.UTF-8"}, capture_output=True, text=True)
                self.assertEqual(run.returncode, expected, run.stderr)
                return json.loads(run.stdout if expected == 0 else run.stderr)
            before = {str(p.relative_to(copied)):hashlib.sha256(p.read_bytes()).hexdigest() for p in copied.rglob("*") if p.is_file()}
            cli("catalog.py", "validate")
            for month in range(1,13):
                rec = cli("catalog.py", "recommend", "--as-of", "2026-10-19", "--year", 2026, "--month", month, "--workspace", work, "--blog", "alpha")
                self.assertTrue(rec["candidates"])
                self.assertEqual(len({c["topic_id"] for c in rec["candidates"]}),len(rec["candidates"]))
            rec = cli("catalog.py", "recommend", "--as-of", "2026-10-19", "--month", 11, "--count", 1000, "--workspace", work, "--blog", "alpha")
            chosen = next(c for c in rec["candidates"] if c["keyword"]=="한파 수도관 동파 예방")
            def save(name, value):
                p=work/name; p.write_text(json.dumps(value,ensure_ascii=False)); return p
            recfile=save("recommendations.json",rec)
            self.assertFalse((work/".seasonal-writer").exists())
            brief=cli("article.py","prepare","--recommendations",recfile,"--topic-id",chosen["topic_id"],"--workspace",work,"--blog","alpha")
            # Fixture verifies the protocol; the separately saved real article verifies authoring.
            from test_seasonal_article import submission
            content, editorial, review=submission(brief)
            draft=work/"draft.md";draft.write_bytes(content)
            def commit(b, body, review_data, event):
                draft.write_bytes(body)
                return cli("article.py","commit","--brief",save("brief.json",b),"--article",draft,"--editorial",save("editorial.json",editorial),"--review",save("review.json",review_data),"--workspace",work,"--blog","alpha","--event-id",event)
            first=commit(brief,content,review,"draft-1")
            self.assertEqual(commit(brief,content,review,"draft-1")["replayed"],True)
            first_path=work/first["payload"]["artifact"]["path"]
            for blog,present in (("alpha",False),("beta",True)):
                next_rec=cli("catalog.py","recommend","--as-of","2026-10-19","--month",11,"--count",1000,"--workspace",work,"--blog",blog)
                self.assertEqual(any(c["topic_id"]==chosen["topic_id"] for c in next_rec["candidates"]),present)
            brief2=cli("article.py","prepare","--action","update","--recommendations",recfile,"--topic-id",chosen["topic_id"],"--workspace",work,"--blog","alpha")
            content2=content+b"\n\n## Fixture revision\n\nCheck the local announcement again.\n"
            review["article_sha256"]=hashlib.sha256(content2).hexdigest()
            second=commit(brief2,content2,review,"draft-2")
            self.assertEqual(second["payload"]["version"],2); self.assertEqual(first_path.read_bytes(),content)
            receipt=(work/second["payload"]["artifact"]["path"]).parent/"receipt.json"
            self.assertEqual(cli("article.py","verify","--receipt",receipt,"--workspace",work,"--blog","alpha")["review_status"],"passed")
            state=cli("history.py","show","--workspace",work,"--blog","alpha");self.assertEqual(state["revision"],2)
            bad=cli("catalog.py","recommend","--as-of","2026-10-19","--month",13,expected=2);self.assertIn("error",bad)
            after = {str(p.relative_to(copied)):hashlib.sha256(p.read_bytes()).hexdigest() for p in copied.rglob("*") if p.is_file()}
            self.assertEqual(before,after)

    def test_references_and_self_contained_imports(self):
        links = 0
        for p in [SKILL/"SKILL.md", *(SKILL/"references").glob("*.md")]:
            for ref in re.findall(r"\[[^\]]+\]\(([^)]+)\)", p.read_text()):
                if "://" in ref or ref.startswith("#"): continue
                target = (p.parent/ref.split("#")[0]).resolve()
                self.assertIn(SKILL.resolve(), target.parents)
                self.assertTrue(target.is_file(), ref)
                links += 1
        self.assertGreater(links, 2)
        allowed = sys.stdlib_module_names | {"catalog", "history", "article", "__future__"}
        for p in (SKILL/"scripts").glob("*.py"):
            for node in ast.walk(ast.parse(p.read_text())):
                names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) else []
                self.assertLessEqual(set(names), allowed, str(p))

    def test_distribution_excludes_private_and_development_inputs(self):
        files = [p for p in SKILL.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        for p in files:
            self.assertNotIn(p.name, {"history.json", "article.md", "receipt.json", "source_data.json"})
            self.assertNotEqual(p.suffix, ".xlsx")
            text = p.read_text()
            for absolute in (str(ROOT), "/Users/iriver", "/Volumes/ExternalSSD"):
                self.assertNotIn(absolute, text, str(p))
        for needed in ("SKILL.md", "agents/openai.yaml", "data/keywords.jsonl", "data/topics.jsonl", "data/source-manifest.json", "scripts/catalog.py", "scripts/history.py", "scripts/article.py"):
            self.assertTrue((SKILL/needed).is_file())


if __name__ == "__main__": unittest.main()
