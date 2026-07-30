"""M2.2 文件上传服务测试。

覆盖：
- UploadService 文件验证（类型/大小）
- 文件保存与读取
- UploadResult 数据结构
- 容错处理
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.upload_service import (
    UploadService, UploadResult, ALLOWED_TYPES, DEFAULT_MAX_SIZE_MB,
)


class TestUploadService(unittest.TestCase):
    """UploadService 核心测试。"""

    def setUp(self):
        """创建临时目录。"""
        self.tmpdir = tempfile.mkdtemp()
        self.docx_dir = Path(self.tmpdir) / "docx"
        self.docx_dir.mkdir()

    def tearDown(self):
        """清理临时目录。"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_config(self):
        config = MagicMock()
        ws = MagicMock()
        ws.docx_dir = str(self.docx_dir)
        config.workspace = ws
        config.get.return_value = {}  # upload cfg as dict
        return config

    def test_allowed_types_defined(self):
        """允许的文件类型已定义。"""
        self.assertIn(".jpg", ALLOWED_TYPES)
        self.assertIn(".png", ALLOWED_TYPES)
        self.assertIn(".pdf", ALLOWED_TYPES)
        self.assertIn(".md", ALLOWED_TYPES)

    def test_validate_file_valid_image(self):
        """验证合法图片文件。"""
        svc = UploadService(config=self._make_config())
        error = svc._validate_file("test.png", b"\x89PNG" + b"\x00" * 100, 1024)
        self.assertIsNone(error)

    def test_validate_file_valid_doc(self):
        """验证合法文档文件。"""
        svc = UploadService(config=self._make_config())
        error = svc._validate_file("test.md", b"hello world", 1024)
        self.assertIsNone(error)

    def test_validate_file_magic_bytes_mismatch(self):
        """magic bytes 与扩展名不匹配时应报错。"""
        svc = UploadService()
        error = svc._validate_file("fake.jpg", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, 1024)
        self.assertIsNotNone(error)
        self.assertIn("不匹配", error)

    def test_validate_file_invalid_type(self):
        """验证非法文件类型。"""
        svc = UploadService(config=self._make_config())
        error = svc._validate_file("test.exe", b"content", 1024)
        self.assertIsNotNone(error)
        self.assertIn("不支持的文件类型", error)

    def test_validate_file_too_large(self):
        """验证文件过大。"""
        svc = UploadService(config=self._make_config(), max_size_mb=1)
        # 2MB 文件
        error = svc._validate_file("test.png", b"\x89PNG" + b"\x00" * 100, 2 * 1024 * 1024)
        self.assertIsNotNone(error)
        self.assertIn("文件过大", error)

    def test_get_file_type_image(self):
        """图片文件类型识别。"""
        svc = UploadService()
        self.assertEqual(svc._get_file_type("test.png"), "image")
        self.assertEqual(svc._get_file_type("test.jpg"), "image")
        self.assertEqual(svc._get_file_type("test.webp"), "image")

    def test_get_file_type_document(self):
        """文档文件类型识别。"""
        svc = UploadService()
        self.assertEqual(svc._get_file_type("test.md"), "document")
        self.assertEqual(svc._get_file_type("test.pdf"), "document")
        self.assertEqual(svc._get_file_type("test.txt"), "document")

    def test_save_upload_success(self):
        """成功保存上传文件。"""
        svc = UploadService(config=self._make_config())
        content = b"\x89PNG\r\n\x1a\n" + b"test image content"
        result = svc.save_upload("test.png", content)

        self.assertIsInstance(result, UploadResult)
        self.assertEqual(result.filename, "test.png")
        self.assertEqual(result.file_type, "image")
        self.assertEqual(result.size_bytes, len(content))
        self.assertTrue(result.url.startswith("/uploads/"))
        # 文件实际写入
        self.assertTrue(Path(result.path).exists())

    def test_save_upload_invalid_type(self):
        """保存非法类型返回错误字符串。"""
        svc = UploadService(config=self._make_config())
        result = svc.save_upload("test.exe", b"content")
        self.assertIsInstance(result, str)
        self.assertIn("不支持的文件类型", result)

    def test_save_upload_too_large(self):
        """保存过大文件返回错误字符串。"""
        svc = UploadService(config=self._make_config(), max_size_mb=1)
        result = svc.save_upload("test.png", b"x" * 2 * 1024 * 1024)
        self.assertIsInstance(result, str)
        self.assertIn("文件过大", result)

    def test_get_file_path_found(self):
        """根据 file_id 找到文件。"""
        svc = UploadService(config=self._make_config())
        content = b"\x89PNG\r\n\x1a\n" + b"content"
        result = svc.save_upload("test.png", content)
        self.assertIsInstance(result, UploadResult)

        # 从 URL 提取 file_id
        file_id = result.file_id
        path = svc.get_file_path(file_id)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

    def test_get_file_path_not_found(self):
        """不存在的 file_id 返回 None。"""
        svc = UploadService(config=self._make_config())
        path = svc.get_file_path("nonexistent")
        self.assertIsNone(path)

    def test_upload_dir_created(self):
        """上传目录自动创建。"""
        svc = UploadService(config=self._make_config())
        upload_dir = svc._get_upload_dir()
        self.assertTrue(upload_dir.exists())
        self.assertEqual(upload_dir.name, "uploads")

    def test_unique_file_id(self):
        """每次上传生成唯一 file_id。"""
        svc = UploadService(config=self._make_config())
        r1 = svc.save_upload("test1.md", b"content1")
        r2 = svc.save_upload("test2.md", b"content2")
        self.assertIsInstance(r1, UploadResult)
        self.assertIsInstance(r2, UploadResult)
        self.assertNotEqual(r1.file_id, r2.file_id)


class TestUploadResult(unittest.TestCase):
    """UploadResult 数据类测试。"""

    def test_dataclass_fields(self):
        """字段完整。"""
        r = UploadResult(
            file_id="abc123",
            filename="test.png",
            file_type="image",
            path="/tmp/test.png",
            size_bytes=1024,
            url="/uploads/abc123.png",
        )
        self.assertEqual(r.file_id, "abc123")
        self.assertEqual(r.filename, "test.png")
        self.assertEqual(r.file_type, "image")
        self.assertEqual(r.size_bytes, 1024)


class TestUploadServiceNoConfig(unittest.TestCase):
    """无配置时的默认行为。"""

    def test_no_config_uses_cwd(self):
        """无 config 时使用当前目录。"""
        svc = UploadService()
        upload_dir = svc._get_upload_dir()
        self.assertEqual(upload_dir, Path("./uploads"))


if __name__ == "__main__":
    unittest.main()
