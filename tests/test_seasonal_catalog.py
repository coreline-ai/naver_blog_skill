import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills/naver-seasonal-blog-writer/scripts/catalog.py"
spec = importlib.util.spec_from_file_location("seasonal_catalog", SCRIPT)
cat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cat)


class CatalogTests(unittest.TestCase):
    def test_packaged_baseline_and_lineage(self):
        keys, topics, manifest = cat.load()
        self.assertEqual(manifest["stats"]["source_rows"], 3109)
        self.assertEqual(manifest["stats"]["by_source"], {"A": 2586, "B": 523})
        self.assertEqual(len(keys), 2793)
        self.assertEqual(manifest["stats"]["exact_unique"], 2796)
        self.assertEqual(sum(len(k["sources"]) for k in keys), 3109)
        self.assertFalse(manifest["original_workbook_bytes_verified"])
        self.assertLess(len(topics), len(keys))

    def test_normalization_preserves_meaning(self):
        self.assertEqual(cat.normalized("자료 제공 동의"), cat.normalized("자료제공동의"))
        self.assertEqual(cat.normalized("3.3% 1차 2027 상반기"), "3.3%1차2027상반기")
        self.assertNotEqual(cat.normalized("1차"), cat.normalized("2차"))
        self.assertNotEqual(cat.normalized("3.3%"), cat.normalized("33%"))
        self.assertEqual(cat.normalized("월세"), cat.normalized("월세"))

    def test_conservative_groups_and_distinct_procedures(self):
        self.assertEqual(cat.editorial_key("연말정산 환급금 언제")[0], cat.editorial_key("연말정산 환급금 지급일")[0])
        self.assertNotEqual(cat.editorial_key("회사 환급금 지급일")[0], cat.editorial_key("국세 환급금 지급일")[0])
        self.assertNotEqual(cat.editorial_key("국가장학금 신청방법")[0], cat.editorial_key("국가장학금 가구원 동의 방법")[0])
        self.assertNotEqual(cat.editorial_key("2026 축제 일정")[0], cat.editorial_key("2027 축제 일정")[0])

    def test_months_aliases_and_quarantine(self):
        keys, _, _ = cat.load()
        winter = next(k for k in keys if k["keyword"] == "한파 수도관 동파 예방")
        self.assertEqual(winter["months"], [1, 11, 12])
        consent = next(k for k in keys if k["normalized"] == "연말정산부양가족자료제공동의")
        self.assertEqual(len(consent["aliases"]), 2)
        for phrase in ["IRP IRP 차이", "재산세 중고차", "지원금 신용카드 신청방법", "벚꽃축제 주차"]:
            self.assertEqual(next(k for k in keys if k["keyword"] == phrase)["status"], "needs_review")

    def test_ids_corruption_and_no_overwrite(self):
        keys, topics, manifest = cat.load()
        self.assertEqual(cat.validate_data(list(reversed(keys)), list(reversed(topics)), manifest), manifest["stats"])
        bad = copy.deepcopy(keys); bad[0]["months"] = []
        with self.assertRaises(cat.CatalogError): cat.validate_data(bad, topics, manifest)
        badtopics = copy.deepcopy(topics); badtopics[0]["keyword_ids"] = []
        with self.assertRaises(cat.CatalogError): cat.validate_data(keys, badtopics, manifest)
        badtopics = copy.deepcopy(topics); badtopics[0]["question"] += "changed"
        with self.assertRaises(cat.CatalogError): cat.validate_data(keys, badtopics, manifest)
        with tempfile.TemporaryDirectory() as temp:
            cat.save_build({"keywords": keys, "topics": topics, "manifest": manifest}, temp)
            before = hashlib.sha256((Path(temp)/"keywords.jsonl").read_bytes()).hexdigest()
            with self.assertRaises(cat.CatalogError): cat.save_build({"keywords": keys, "topics": topics, "manifest": manifest}, temp)
            self.assertEqual(before, hashlib.sha256((Path(temp)/"keywords.jsonl").read_bytes()).hexdigest())

    def test_rebuild_is_read_only_and_order_independent(self):
        snapshot = [{"name": name, "sheets": [{"name": "1월" if source == "A" else "전체 키워드", "rows": [{"row": 1, "cells": {"C1": "키워드"}}, {"row": 2, "cells": {"A2": 1, "B2": "한파 생활 대비", "C2": "한파 수도관 동파 예방"}}]}]} for name, source in cat.NAMES.items()]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"snapshot.json"; path.write_text(json.dumps(snapshot, ensure_ascii=False))
            before = path.read_bytes(); first = cat.build(path)
            self.assertEqual(before, path.read_bytes())
            path.write_text(json.dumps(list(reversed(snapshot)), ensure_ascii=False)); second = cat.build(path)
            self.assertEqual(first["keywords"], second["keywords"])
            self.assertEqual(first["topics"], second["topics"])
            self.assertEqual(first["manifest"]["stats"]["source_rows"], 2)


if __name__ == "__main__": unittest.main()
