import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipIf(os.name == "nt", "Linux checkout permissions")
class UpdatePermissionsTests(unittest.TestCase):
    def test_private_checkout_becomes_readable_without_exposing_untracked_secrets(self):
        script = (Path(__file__).resolve().parents[1] / "deploy/update.sh").read_text()
        function = script.split("make_code_readable() {", 1)[1].split("\n}\n", 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            web = root / "web"
            web.mkdir()
            source = web / "app.js"
            source.write_text("// public code")
            secret = root / "private-token"
            secret.write_text("keep private")
            subprocess.run(["git", "add", "web/app.js"], cwd=root, check=True)
            git_mode = (root / ".git").stat().st_mode & 0o777
            source.chmod(0o600)
            secret.chmod(0o600)
            web.chmod(0o700)
            root.chmod(0o700)
            subprocess.run(["bash", "-c", function], cwd=root, check=True)
            self.assertEqual(source.stat().st_mode & 0o777, 0o644)
            self.assertEqual(web.stat().st_mode & 0o777, 0o755)
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / ".git").stat().st_mode & 0o777, git_mode)
