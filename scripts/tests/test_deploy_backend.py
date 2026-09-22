from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.deploy_backend import build_source_archive, replace_service_images


class DeployBackendTests(unittest.TestCase):
    def test_archive_contains_only_backend_runtime_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend/app").mkdir(parents=True)
            (root / "backend/app/main.py").write_text("app = 1")
            (root / "backend/app/private.env").write_text("SECRET=do-not-package")
            (root / "backend/.env").write_text("SECRET=do-not-package")
            (root / "backend/app/__pycache__").mkdir()
            (root / "backend/app/__pycache__/main.pyc").write_bytes(b"secret")
            archive = root / "source.tar.gz"

            build_source_archive(root, archive)

            with tarfile.open(archive, "r:gz") as bundle:
                names = set(bundle.getnames())
                self.assertEqual(
                    names,
                    {"app/main.py"},
                )

    def test_replaces_only_api_and_worker_images(self) -> None:
        compose = (
            "services:\n"
            "  frontend:\n    image: portfolio-frontend:old\n"
            "  api:\n    image: portfolio-api:old\n"
            "  worker:\n    image: portfolio-api:old\n"
            "  db:\n    image: postgres:17-alpine\n"
        )

        result = replace_service_images(
            compose, "portfolio-api:old", "portfolio-api:new"
        )

        self.assertIn("frontend:old", result)
        self.assertIn("postgres:17-alpine", result)
        self.assertEqual(result.count("portfolio-api:new"), 2)
        self.assertNotIn("portfolio-api:old", result)

    def test_refuses_unexpected_current_image(self) -> None:
        compose = "services:\n  api:\n    image: changed\n  worker:\n    image: old\n"
        with self.assertRaisesRegex(ValueError, "api image"):
            replace_service_images(compose, "old", "new")

    def test_refuses_symlinked_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend/app").mkdir(parents=True)
            outside = root / "outside.py"
            outside.write_text("secret")
            try:
                (root / "backend/app/main.py").symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are unavailable on this system")
            with self.assertRaisesRegex(ValueError, "symlink"):
                build_source_archive(root, root / "source.tar.gz")


if __name__ == "__main__":
    unittest.main()
