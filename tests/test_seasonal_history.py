import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]/"skills/naver-seasonal-blog-writer/scripts"
sys.path.insert(0, str(SCRIPTS))
import catalog as seasonal_catalog
import history as seasonal_history


class RecommendationDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 19)


class RecommendationHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys, cls.topics, _ = seasonal_catalog.load()
        kid = next(k for k in cls.keys if k["keyword"] == "한파 수도관 동파 예방")
        cls.topic = next(t for t in cls.topics if t["id"] == kid["topic_id"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.occ = seasonal_catalog.occurrence(self.topic, 2026, 11)

    def rec(self, **kwargs):
        return seasonal_catalog.recommend(2026, 11, "2026-10-19", count=1000, workspace=self.work, blog="alpha", **kwargs)

    def cli_recommend(self, *args):
        output = io.StringIO()
        with patch.object(seasonal_catalog, "date", RecommendationDate), patch.object(sys, "argv", ["catalog.py", *args]), redirect_stdout(output):
            self.assertEqual(seasonal_catalog.main(), 0)
        return json.loads(output.getvalue())

    def test_default_month_uses_today_without_date_arguments(self):
        result = self.cli_recommend("recommend", "--workspace", str(self.work), "--blog", "alpha")
        self.assertEqual((result["year"], result["month"], result["as_of"]), (2026, 10, "2026-10-19"))
        self.assertEqual(result["requested_count"], 8)
        self.assertEqual(len(result["candidates"]), 8)
        self.assertFalse((self.work/".seasonal-writer").exists())
        self.assertFalse((self.work/"articles").exists())

    def test_month_only_and_explicit_year_preserve_target_month(self):
        march = self.cli_recommend("recommend", "--month", "3")
        self.assertEqual((march["year"], march["month"], march["as_of"]), (2026, 3, "2026-10-19"))
        january = self.cli_recommend("recommend", "--year", "2027", "--month", "1")
        self.assertEqual((january["year"], january["month"], january["as_of"]), (2027, 1, "2026-10-19"))
        self.assertTrue(march["candidates"] and january["candidates"])

    def test_explicit_reference_date_keeps_reproducible_plan(self):
        result = self.cli_recommend("plan", "--as-of", "2027-12-30", "--month", "11", "--count", "3")
        self.assertEqual((result["year"], result["month"], result["as_of"]), (2027, 11, "2027-12-30"))
        self.assertEqual([c["sequence"] for c in result["candidates"]], [1, 2, 3])

    def draft(self, event="draft-1", revision=0):
        p = self.work/"article.md"; p.write_text("# 제목\n\n실제 초안 파일", encoding="utf-8")
        artifact = {"path": "article.md", "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        payload = {"artifact": artifact}
        return seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "drafted", payload, event, revision), payload

    def test_all_months_unique_and_no_fabricated_metrics(self):
        for month in range(1, 13):
            r = seasonal_catalog.recommend(2026, month, "2026-10-19", 8)
            ids = [c["topic_id"] for c in r["candidates"]]
            self.assertTrue(ids); self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(c["search_volume"] is None and c["facts_status"] == "unverified" for c in r["candidates"]))
            self.assertFalse(r["history_checked"])

    def test_domains_shortfall_invalid_inputs(self):
        r = seasonal_catalog.recommend(2026, 11, "2026-10-19", 1000, "세금")
        self.assertTrue(all("세금·연금" in c["domains"] for c in r["candidates"]))
        self.assertGreater(r["shortfall"], 0)
        for month, count in [(0, 8), (13, 8), (1, 0), (1, -1)]:
            with self.assertRaises(ValueError): seasonal_catalog.recommend(2026, month, "2026-10-19", count)
        with self.assertRaises(ValueError): seasonal_catalog.recommend(2026, 11, "bad-date")
        with self.assertRaises(ValueError): seasonal_catalog.recommend(2026, 11, "2026-10-19", domain_filter="없는분야")
        with self.assertRaises(ValueError): seasonal_catalog.recommend(2026, 11, "2026-10-19", workspace=self.work)

    def test_periods_do_not_erase_income_year_term_or_round(self):
        def topic(keyword):
            key = next(k for k in self.keys if k["keyword"] == keyword)
            return next(t for t in self.topics if t["id"] == key["topic_id"])
        half = topic("근로장려금 반기 신청기간")
        self.assertNotEqual(seasonal_catalog.occurrence(half, 2026, 3), seasonal_catalog.occurrence(half, 2026, 9))
        settle = topic("연말정산 필요서류")
        self.assertEqual(seasonal_catalog.occurrence(settle, 2026, 12), seasonal_catalog.occurrence(settle, 2027, 1))
        scholarship = topic("국가장학금 가구원 동의 방법")
        self.assertEqual(seasonal_catalog.occurrence(scholarship, 2026, 11), seasonal_catalog.occurrence(scholarship, 2027, 2))
        self.assertNotEqual(seasonal_catalog.occurrence(scholarship, 2026, 2), seasonal_catalog.occurrence(scholarship, 2026, 7))
        self.assertEqual(seasonal_catalog.occurrence(self.topic, 2026, 11), seasonal_catalog.occurrence(self.topic, 2027, 1))

    def test_year_specific_and_expired_notice_not_rolled_forward(self):
        now = seasonal_catalog.recommend(2026, 10, "2026-10-19", 1000)
        future = seasonal_catalog.recommend(2027, 10, "2027-10-19", 1000)
        self.assertFalse(any("10월 1일 2일 신청" in c["keyword"] for c in now["candidates"]))
        self.assertFalse(any("2026년" in c["keyword"] for c in future["candidates"]))
        self.assertGreater(future["exclusions"].get("연도/과거 공지 조건 불일치", 0), 0)

    def test_recommended_not_permanent_exclusion(self):
        seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "recommended", {}, "rec-1", 0)
        self.assertIn(self.topic["id"], [c["topic_id"] for c in self.rec()["candidates"]])
        self.assertFalse((self.work/"article.md").exists())

    def test_draft_requery_and_blog_isolation(self):
        self.draft()
        self.assertNotIn(self.topic["id"], [c["topic_id"] for c in self.rec()["candidates"]])
        other = seasonal_catalog.recommend(2026, 11, "2026-10-19", 1000, workspace=self.work, blog="other")
        self.assertIn(self.topic["id"], [c["topic_id"] for c in other["candidates"]])

    def test_needs_update_is_separate(self):
        self.draft()
        seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "needs_update", {"reason": "지역 수도사업소 신고 경로 변경 확인"}, "update-1", 1)
        result = self.rec()
        self.assertNotIn(self.topic["id"], [c["topic_id"] for c in result["candidates"]])
        self.assertIn(self.topic["id"], [c["topic_id"] for c in result["updates"]])

    def test_replay_conflict_and_failed_save_preserve_history(self):
        state, payload = self.draft(); path = seasonal_history.history_path(self.work, "alpha"); before = path.read_bytes()
        same = seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "drafted", payload, "draft-1", 0)
        self.assertEqual(same["revision"], 1); self.assertEqual(before, path.read_bytes())
        with self.assertRaises(ValueError): seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "selected", {}, "draft-1", 1)
        with self.assertRaises(ValueError): seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "needs_update", {"reason": "확인"}, "wrong-rev", 0)
        with patch.object(seasonal_history.os, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError): seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "needs_update", {"reason": "실제 변경"}, "failed-save", 1)
        self.assertEqual(before, path.read_bytes()); self.assertFalse(path.with_suffix(".lock").exists())

    def test_corrupt_history_changed_artifact_and_path_boundary(self):
        self.draft(); path = seasonal_history.history_path(self.work, "alpha")
        (self.work/"article.md").write_text("수정됨")
        with self.assertRaises(ValueError): self.rec()
        path.write_text("{")
        with self.assertRaises(ValueError): seasonal_history.load(self.work, "alpha")
        self.assertEqual(path.read_text(), "{")
        with self.assertRaises(ValueError): seasonal_history.history_path(self.work, "../../outside")
        with self.assertRaises(ValueError): seasonal_history.safe_file(self.work, "../outside")
        with self.assertRaises(ValueError): seasonal_history.workspace_path(SCRIPTS)

    def test_no_publication_without_draft_and_confirmation(self):
        with self.assertRaises(ValueError): seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "published", {}, "publish-1", 0)
        _, payload = self.draft()
        with self.assertRaises(ValueError): seasonal_history.record(self.work, "alpha", self.topic["id"], self.occ, "published", payload, "publish-2", 1)


if __name__ == "__main__": unittest.main()
