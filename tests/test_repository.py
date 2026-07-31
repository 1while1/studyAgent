"""Repository 抽象测试"""
import unittest
import tempfile
import shutil
from pathlib import Path
from backend.services.repository import (
    Repository, JsonRepository, SqliteRepository
)


class RepositoryTestMixin:
    """Repository 通用测试（Mixin）"""

    def _make_repo(self, tmp_dir: str) -> Repository:
        raise NotImplementedError

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._repo = self._make_repo(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_load_nonexistent(self):
        self.assertIsNone(self._repo.load("nonexistent"))

    def test_save_and_load(self):
        data = {"key": "value", "nested": {"a": 1}}
        self._repo.save("test", data)
        loaded = self._repo.load("test")
        self.assertEqual(loaded, data)

    def test_exists(self):
        self.assertFalse(self._repo.exists("test"))
        self._repo.save("test", {"a": 1})
        self.assertTrue(self._repo.exists("test"))

    def test_delete(self):
        self._repo.save("test", {"a": 1})
        self._repo.delete("test")
        self.assertFalse(self._repo.exists("test"))

    def test_list_keys(self):
        self._repo.save("a", {"x": 1})
        self._repo.save("b", {"x": 2})
        keys = self._repo.list_keys()
        self.assertEqual(sorted(keys), ["a", "b"])

    def test_overwrite(self):
        self._repo.save("test", {"v": 1})
        self._repo.save("test", {"v": 2})
        self.assertEqual(self._repo.load("test"), {"v": 2})

    def test_unicode_data(self):
        data = {"name": "测试", "emoji": "🎓"}
        self._repo.save("unicode", data)
        self.assertEqual(self._repo.load("unicode"), data)


class TestJsonRepository(RepositoryTestMixin, unittest.TestCase):
    def _make_repo(self, tmp_dir):
        return JsonRepository(Path(tmp_dir))


class TestSqliteRepository(RepositoryTestMixin, unittest.TestCase):
    def _make_repo(self, tmp_dir):
        return SqliteRepository(Path(tmp_dir) / "test.db")

    def tearDown(self):
        self._repo.close()
        super().tearDown()

    def test_wal_mode(self):
        cursor = self._repo._conn.execute("PRAGMA journal_mode")
        self.assertEqual(cursor.fetchone()[0], "wal")


if __name__ == "__main__":
    unittest.main()
