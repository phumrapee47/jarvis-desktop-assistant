"""Regression tests สำหรับ issue #1 (memory/reminder ลบเกิน) และ #2 (git worktree/submodule)

รัน:  python -m unittest discover tests -v
ไม่แตะ memory.json จริง (ใช้ไฟล์ชั่วคราว) และไม่เรียก Claude Code จริง (ตรวจแค่ด่านตรวจก่อนขอยืนยัน)
"""
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools_dev
import tools_memory


def sh(*cmd, cwd=None, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd} -> {r.stderr}")
    return r.stdout.strip()


# ---------------------------------------------------------------- Issue #1
class MemorySafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = tools_memory.PATH
        tools_memory.PATH = os.path.join(self.tmp, "mem.json")

    def tearDown(self):
        tools_memory.PATH = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def snapshot(self):
        return json.dumps(tools_memory._load(), sort_keys=True)

    def notes(self, *texts):
        for t in texts:
            tools_memory.remember(t)

    def reminders(self, *texts):
        for t in texts:
            tools_memory.set_reminder(t, minutes_from_now=60)

    def test_tc01_match_empty_query(self):
        items = [{"id": 1, "text": "ชอบ TypeScript"}, {"id": 2, "text": "จ่ายค่าไฟ"}]
        self.assertEqual(tools_memory._match("", items), [])

    def test_tc02_match_whitespace_query(self):
        items = [{"id": 1, "text": "ชอบ TypeScript"}]
        self.assertEqual(tools_memory._match("   ", items), [])

    def test_tc03_cancel_reminder_empty(self):
        self.reminders("ยืดเส้น", "push โค้ด", "ประชุม")
        before = self.snapshot()
        tools_memory.cancel_reminder("")
        self.assertEqual(self.snapshot(), before)

    def test_tc04_cancel_reminder_short_query_not_mass_delete(self):
        self.reminders("pay rent a", "call a friend", "buy a gift")
        tools_memory.cancel_reminder("a")
        self.assertEqual(len(tools_memory._load()["reminders"]), 3)

    def test_tc05_forget_empty_with_1_to_3_notes(self):
        for n in (1, 2, 3):
            with self.subTest(notes=n):
                if os.path.exists(tools_memory.PATH):
                    os.remove(tools_memory.PATH)
                self.notes(*[f"โน้ตทดสอบ {i}" for i in range(n)])
                tools_memory.forget("")
                self.assertEqual(len(tools_memory._load()["notes"]), n)

    def test_tc06_forget_whitespace(self):
        self.notes("โน้ต A", "โน้ต B")
        tools_memory.forget("   ")
        self.assertEqual(len(tools_memory._load()["notes"]), 2)

    def test_tc07_single_match_deletes_only_that(self):
        self.notes("ผมชอบ TypeScript", "ผมกินข้าวเช้า")
        self.reminders("ยืดเส้น", "ส่งรายงาน")
        tools_memory.forget("TypeScript")
        tools_memory.cancel_reminder("ยืดเส้น")
        self.assertEqual([n["text"] for n in tools_memory._load()["notes"]], ["ผมกินข้าวเช้า"])
        self.assertEqual([r["text"] for r in tools_memory._load()["reminders"]], ["ส่งรายงาน"])

    def test_tc08_multiple_matches_refused(self):
        self.notes("โปรเจกต์ alpha ใช้ Flutter", "โปรเจกต์ beta ใช้ Flutter")
        self.reminders("ประชุมทีม A", "ประชุมทีม B")
        before = self.snapshot()
        r1, r2 = tools_memory.forget("Flutter"), tools_memory.cancel_reminder("ประชุม")
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("ลืมแล้ว", r1)
        self.assertNotIn("ยกเลิกเตือนแล้ว", r2)

    def test_tc09_no_match_keeps_everything(self):
        self.notes("โน้ต A"); self.reminders("เตือน A")
        before = self.snapshot()
        tools_memory.forget("zzzไม่มีคำนี้"); tools_memory.cancel_reminder("zzzไม่มีคำนี้")
        self.assertEqual(self.snapshot(), before)

    def test_tc10_data_unchanged_after_refused_commands(self):
        self.notes("โน้ต 1", "โน้ต 2", "โน้ต 3"); self.reminders("เตือน 1", "เตือน 2")
        before = self.snapshot()
        for q in ("", "   ", "\t\n", "โ", "เ"):
            tools_memory.forget(q); tools_memory.cancel_reminder(q)
        self.assertEqual(self.snapshot(), before)

    def test_exact_text_still_works_when_it_is_substring_of_another(self):
        # regression: ข้อความตรงเป๊ะต้องลบได้ แม้เป็นส่วนหนึ่งของโน้ตอื่น (ไม่ถูกบล็อกเพราะ "ตรงหลายอัน")
        self.notes("ใช้ vim", "ใช้ vim กับ tmux")
        tools_memory.forget("ใช้ vim")
        self.assertEqual([n["text"] for n in tools_memory._load()["notes"]], ["ใช้ vim กับ tmux"])

    def test_delete_by_id(self):
        self.notes("โน้ต X", "โน้ต Y")
        nid = tools_memory._load()["notes"][1]["id"]
        tools_memory.forget(f"#{nid}")
        self.assertEqual([n["text"] for n in tools_memory._load()["notes"]], ["โน้ต X"])


# ---------------------------------------------------------------- Issue #2
class GitDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cfg = os.path.join(cls.tmp, "gitconfig")
        with open(cfg, "w") as f:
            f.write("[user]\n\tname = Test\n\temail = test@example.com\n[protocol \"file\"]\n\tallow = always\n"
                    "[init]\n\tdefaultBranch = main\n[safe]\n\tdirectory = *\n")
        cls.env = dict(os.environ, GIT_CONFIG_GLOBAL=cfg, GIT_CONFIG_NOSYSTEM="1")
        os.environ.update(GIT_CONFIG_GLOBAL=cfg, GIT_CONFIG_NOSYSTEM="1")
        cls.docs = os.path.join(cls.tmp, "docs")
        os.makedirs(cls.docs)
        g = lambda *a, cwd=None: sh("git", *a, cwd=cwd, env=cls.env)

        def commit_file(repo, name="f.txt", text="x"):
            with open(os.path.join(repo, name), "w") as f:
                f.write(text)
            g("add", "-A", cwd=repo); g("commit", "-q", "-m", f"add {name}", cwd=repo)

        cls.normal = os.path.join(cls.docs, "normal")
        os.makedirs(cls.normal); g("init", "-q", cwd=cls.normal); commit_file(cls.normal)
        os.makedirs(os.path.join(cls.normal, "src")); cls.subfolder = os.path.join(cls.normal, "src")
        cls.worktree = os.path.join(cls.docs, "wt")
        g("worktree", "add", "-q", cls.worktree, "-b", "wtbranch", cwd=cls.normal)
        commit_file(cls.worktree, "w.txt", "worktree work")  # งานใน worktree วันนี้ (ใช้ทดสอบ standup)
        origin = os.path.join(cls.tmp, "sub_origin"); os.makedirs(origin); g("init", "-q", cwd=origin); commit_file(origin)
        cls.superrepo = os.path.join(cls.docs, "super")
        os.makedirs(cls.superrepo); g("init", "-q", cwd=cls.superrepo); commit_file(cls.superrepo)
        g("submodule", "add", "-q", origin, "libsub", cwd=cls.superrepo); g("commit", "-q", "-m", "add submodule", cwd=cls.superrepo)
        cls.submodule = os.path.join(cls.superrepo, "libsub")
        cls.plain = os.path.join(cls.docs, "plain"); os.makedirs(cls.plain)
        cls.bad_file = os.path.join(cls.docs, "bad_file"); os.makedirs(cls.bad_file)
        with open(os.path.join(cls.bad_file, ".git"), "w") as f:
            f.write("this is not a gitdir pointer\n")
        cls.bad_dir = os.path.join(cls.docs, "bad_dir"); os.makedirs(os.path.join(cls.bad_dir, ".git"))

    @classmethod
    def tearDownClass(cls):
        sh_rm = lambda p: subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", p], capture_output=True)
        sh_rm(cls.tmp)

    def setUp(self):
        self._docs = mock.patch.object(tools_dev, "DOCS", self.docs); self._docs.start()
        self._which = mock.patch.object(tools_dev.shutil, "which", return_value="claude.exe"); self._which.start()
        tools_dev._pending.update(fn=None, desc="", expires=0.0)

    def tearDown(self):
        mock.patch.stopall()
        tools_dev._pending.update(fn=None, desc="", expires=0.0)

    def test_tc11_normal_repo(self):
        self.assertTrue(tools_dev.is_repo_root(self.normal))

    def test_tc12_worktree(self):
        self.assertTrue(os.path.isfile(os.path.join(self.worktree, ".git")), "ต้องเป็นไฟล์ .git (worktree)")
        self.assertTrue(tools_dev.is_repo_root(self.worktree))

    def test_tc13_submodule(self):
        self.assertTrue(os.path.isfile(os.path.join(self.submodule, ".git")), "ต้องเป็นไฟล์ .git (submodule)")
        self.assertTrue(tools_dev.is_repo_root(self.submodule))

    def test_tc14_not_a_repo(self):
        self.assertFalse(tools_dev.is_repo_root(self.plain))

    def test_tc15_invalid_dotgit(self):
        self.assertFalse(tools_dev.is_repo_root(self.bad_file))
        self.assertFalse(tools_dev.is_repo_root(self.bad_dir))

    def test_tc16_standup_includes_worktree(self):
        out = tools_dev.recent_activity(1)
        self.assertIn("wt:", out)
        self.assertIn("normal:", out)  # repo ปกติยังอยู่ (ไม่ regress); มี commit วันนี้จาก setup
        self.assertNotIn("plain:", out); self.assertNotIn("bad_file:", out); self.assertNotIn("bad_dir:", out)

    def test_tc16b_git_status_on_worktree(self):
        self.assertNotIn("ไม่ใช่ git repo", tools_dev.git_status("wt"))
        self.assertIn("wtbranch", tools_dev.git_status("wt"))

    def test_tc17_edit_on_worktree_not_refused(self):
        r = tools_dev.claude_code_edit("wt", "task")
        self.assertNotIn("ไม่ใช่ git repo", r)
        self.assertTrue(tools_dev.has_pending(), r)

    def test_tc18_edit_on_submodule_passes_git_check(self):
        with mock.patch.object(tools_dev, "find_project", return_value=(self.submodule, None)):
            r = tools_dev.claude_code_edit("libsub", "task")
        self.assertNotIn("ไม่ใช่ git repo", r)
        self.assertTrue(tools_dev.has_pending(), r)

    def test_tc19_subfolder_policy_requires_repo_root(self):
        # นโยบาย: โปรเจกต์ต้องเป็น "รากของ working tree" โฟลเดอร์ย่อยใน repo อื่นไม่นับ (กันแก้ผิดขอบเขต)
        self.assertFalse(tools_dev.is_repo_root(self.subfolder))
        top = tools_dev.git_toplevel(self.subfolder)
        self.assertEqual(top, os.path.normcase(os.path.realpath(self.normal)))

    def test_tc20_git_failure_or_timeout_does_not_crash(self):
        boom = subprocess.TimeoutExpired(cmd="git", timeout=1)
        with mock.patch.object(tools_dev, "_run", side_effect=boom):
            self.assertFalse(tools_dev.is_repo_root(self.normal))
            self.assertIsInstance(tools_dev.git_status("normal"), str)
            self.assertIsInstance(tools_dev.recent_activity(1), str)
            self.assertIsInstance(tools_dev.claude_code_edit("normal", "task"), str)
        with mock.patch.object(tools_dev, "_run", side_effect=OSError("git missing")):
            self.assertFalse(tools_dev.is_repo_root(self.normal))
            self.assertIsInstance(tools_dev.claude_code_edit("normal", "task"), str)

    def test_non_repo_still_refused_for_edit(self):
        r = tools_dev.claude_code_edit("plain", "task")
        self.assertIn("ไม่ใช่ git repo", r)
        self.assertFalse(tools_dev.has_pending())


if __name__ == "__main__":
    unittest.main(verbosity=2)
