"""Guard the repository's local-only site configuration boundary."""

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "AGENTS.local.md"


def git(*args):
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class LocalSitePrivacyTests(unittest.TestCase):
    def test_local_configuration_is_ignored_and_not_tracked(self):
        self.assertEqual(git("check-ignore", "--no-index", "-q", LOCAL.name).returncode, 0)
        self.assertEqual(git("ls-files", "--", LOCAL.name).stdout, b"")

    def test_project_instructions_load_local_configuration(self):
        self.assertIn(LOCAL.name, (ROOT / "AGENTS.md").read_text(encoding="utf-8"))

    def test_local_site_addresses_are_absent_from_tracked_files(self):
        if not LOCAL.is_file():
            self.skipTest("Local configuration is intentionally absent")
        content = LOCAL.read_text(encoding="utf-8")
        urls = set(re.findall(r"https://(?:blog|cshop)\.naver\.com/[A-Za-z0-9_-]+", content))
        self.assertTrue(urls, "Local configuration contains no site addresses to check")
        tracked = git("ls-files", "-z")
        self.assertEqual(tracked.returncode, 0)
        for name in tracked.stdout.decode("utf-8").split("\0"):
            if not name:
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for url in urls:
                self.assertFalse(url in text, f"Local site address found in tracked file: {name}")


if __name__ == "__main__":
    unittest.main()
