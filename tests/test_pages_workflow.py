"""公開 (GitHub Pages) の設定と導線のテスト。

公開まわりは**壊れても手元では気づけない**。CI が失敗するか、
静かに古いページが出続けるだけになる。そこで yml をテキストとして読み、
「公開するものを両方作っているか」「テストの後に公開しているか」
「権限を渡しているか」を機械で押さえる。

yaml ライブラリは使わない (標準ライブラリに無く、依存を増やしたくない)。
代わりに行単位で読み、必要な要素の**存在と前後関係**だけを確かめる。
"""

import re
import unittest
from pathlib import Path

from tools.build_site import APP_PATH, REPO_URL, build

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
PAGES = WORKFLOWS / "pages.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class PagesWorkflowTest(unittest.TestCase):
    """pages.yml が公開に必要な形をしているか。"""

    def setUp(self):
        self.body = _text(PAGES)

    def test_the_workflow_file_exists(self):
        self.assertTrue(PAGES.is_file())

    def test_it_runs_on_main_pushes_and_by_hand(self):
        self.assertIn("branches: [main]", self.body)
        self.assertIn("workflow_dispatch:", self.body)

    def test_it_asks_for_the_permissions_pages_needs(self):
        # この 2 つが無いと deploy-pages が認証できず失敗する
        self.assertIn("pages: write", self.body)
        self.assertIn("id-token: write", self.body)

    def test_it_does_not_ask_for_write_access_to_the_repository(self):
        # 公開に書き込み権限は不要。余分な権限は渡さない。
        self.assertIn("contents: read", self.body)
        self.assertNotIn("contents: write", self.body)

    def test_only_one_deploy_runs_at_a_time(self):
        self.assertIn("concurrency:", self.body)
        self.assertIn("group: pages", self.body)

    def test_it_does_not_cancel_a_deploy_in_flight(self):
        # 途中で切ると Pages が中途半端な状態で残ることがある
        self.assertIn("cancel-in-progress: false", self.body)

    def test_it_builds_both_the_demo_and_the_app(self):
        self.assertIn("tools/build_site.py", self.body)
        self.assertIn("tools/build_web.py", self.body)

    def test_the_app_is_built_inside_the_demo_folder(self):
        # site/app に置くから、デモページの相対リンク app/ が届く
        self.assertIn(f"site/{APP_PATH.rstrip('/')}", self.body)

    def test_tests_run_before_anything_is_built(self):
        run_tests = self.body.index("python -m unittest")
        build_site = self.body.index("tools/build_site.py")
        self.assertLess(run_tests, build_site,
                        "テストが通る前にページを作ってはいけない")

    def test_it_checks_the_output_before_uploading(self):
        check = self.body.index("site/app/picoseq-core.zip")
        upload = self.body.index("upload-pages-artifact")
        self.assertLess(check, upload)

    def test_it_uploads_and_deploys_with_the_official_actions(self):
        for action in ("actions/checkout@v4", "actions/configure-pages@v5",
                       "actions/setup-python@v5",
                       "actions/upload-pages-artifact@v3",
                       "actions/deploy-pages@v4"):
            self.assertIn(action, self.body, action)

    def test_it_turns_pages_on_by_itself(self):
        """Pages が無効なリポジトリでも自力で有効化すること。

        これが無いと、初回だけ画面 (Settings > Pages) を触らないと
        「Failed to create deployment (status: 404)」で最後だけ落ちる。
        フォークやクローンでも同じ罠を踏むので、ワークフロー側で面倒を見る。
        """
        self.assertRegex(
            self.body,
            r"actions/configure-pages@v5\s*\n\s*with:\s*\n\s*enablement: true")

    def test_pages_is_configured_before_the_artifact_is_uploaded(self):
        configure = self.body.index("configure-pages@v5")
        upload = self.body.index("upload-pages-artifact")
        self.assertLess(configure, upload)

    def test_the_uploaded_folder_is_the_demo_folder(self):
        self.assertRegex(self.body, r"upload-pages-artifact@v3\s*\n\s*with:\s*\n\s*path: site")

    def test_deploy_waits_for_the_build(self):
        self.assertIn("needs: build", self.body)

    def test_deploy_reports_the_published_url(self):
        # Actions の画面から公開先へ飛べるようにしておく
        self.assertIn("github-pages", self.body)
        self.assertIn("steps.deploy.outputs.page_url", self.body)

    def test_it_pins_a_python_version(self):
        self.assertRegex(self.body, r'python-version: "3\.\d+"')

    def test_it_does_not_leave_a_placeholder_behind(self):
        for bad in ("TODO", "FIXME", "<your", "example.com"):
            self.assertNotIn(bad, self.body, bad)


class WorkflowSetTest(unittest.TestCase):
    """ワークフロー全体としての整合。"""

    def test_ci_and_pages_agree_on_the_python_version(self):
        # 片方だけ上げるとテストが通るのに公開が落ちる、という食い違いになる
        def version(path):
            return re.findall(r'python-version: "([^"]+)"', _text(path))

        self.assertTrue(version(PAGES))
        self.assertEqual(set(version(PAGES)),
                         set(version(WORKFLOWS / "ci.yml")))

    def test_only_pages_deploys(self):
        # 公開経路は 1 本だけ。ci.yml が勝手に上書きしないこと。
        deploying = [p.name for p in WORKFLOWS.glob("*.yml")
                     if "deploy-pages" in _text(p)]
        self.assertEqual(deploying, ["pages.yml"])

    def test_the_two_jobs_cover_both_render_paths(self):
        """numpy 有り (pages) と無し (ci) の両方でテストが回ること。

        numpy 経路と純 Python 経路は**ビット一致が要件**なのに、両方が
        揃った環境でしか比較できない。片方の環境しか無いと、一致テストが
        黙ってスキップされたまま気づけなくなる。
        """
        pages = _text(PAGES)
        ci = _text(WORKFLOWS / "ci.yml")
        self.assertIn("pip install numpy", pages, "pages 側に numpy が要る")
        self.assertNotIn("pip install numpy", ci,
                         "ci 側は numpy 無しで純 Python 経路を見る役")

    def test_every_workflow_is_valid_utf8_without_a_bom(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            head = path.read_bytes()[:3]
            self.assertNotEqual(head, b"\xef\xbb\xbf", f"{path.name} に BOM")
            path.read_text(encoding="utf-8")

    def test_no_workflow_uses_tabs(self):
        # yaml はタブを字下げに使えない。混ぜると読み込み時に落ちる。
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for number, line in enumerate(_text(path).splitlines(), 1):
                self.assertNotIn("\t", line, f"{path.name}:{number}")


class DemoLinksToTheAppTest(unittest.TestCase):
    """試聴デモ → ブラウザ版の導線。"""

    @classmethod
    def setUpClass(cls):
        from tempfile import TemporaryDirectory
        cls._tmp = TemporaryDirectory()
        build(Path(cls._tmp.name))
        cls.page = (Path(cls._tmp.name) / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_demo_page_links_to_the_app(self):
        self.assertIn(f'href="{APP_PATH}"', self.page)

    def test_the_link_is_relative(self):
        # 絶対 URL にするとリポジトリ名付きのサブパス公開で 404 になる
        self.assertFalse(APP_PATH.startswith(("/", "http")))

    def test_the_call_to_action_is_above_the_samples(self):
        cta = self.page.index(f'href="{APP_PATH}"')
        first_sample = self.page.index("<audio")
        self.assertLess(cta, first_sample)

    def test_it_no_longer_claims_the_browser_can_only_listen(self):
        # ブラウザ版が出来た時点で嘘になった文
        self.assertNotIn("ブラウザで動くのは", self.page)

    def test_it_says_what_the_browser_version_cannot_do(self):
        for missing in ("DJ", "MIDI"):
            self.assertIn(missing, self.page, missing)

    def test_it_warns_that_the_first_load_is_slow(self):
        # Pyodide の初回読み込みは十数秒かかる。黙っていると壊れて見える。
        self.assertRegex(self.page, r"初回だけ.*かかり")

    def test_the_repository_link_points_at_the_real_repository(self):
        self.assertIn(REPO_URL, self.page)
        self.assertNotIn('href="https://github.com/"', self.page)


class AppLinksBackTest(unittest.TestCase):
    """ブラウザ版 → 試聴デモ・リポジトリの導線。"""

    def setUp(self):
        self.page = _text(ROOT / "web" / "index.html")

    def test_the_app_links_back_to_the_demo(self):
        self.assertIn('href="../"', self.page)

    def test_the_app_links_to_the_repository(self):
        self.assertIn(REPO_URL, self.page)


if __name__ == "__main__":
    unittest.main()
