"""VisionService 测试"""
import os
import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock
from backend.services.vision_service import VisionService, VisionResult


class TestVisionService(unittest.TestCase):
    def test_init_default(self):
        svc = VisionService()
        self.assertEqual(svc._max_size, 10 * 1024 * 1024)
    
    def test_analyze_nonexistent_file(self):
        svc = VisionService()
        result = svc.analyze_image(Path("/nonexistent.png"))
        self.assertIsNone(result)
    
    def test_detect_content_type(self):
        svc = VisionService()
        self.assertEqual(svc._detect_content_type(Path("test.png")), "image/png")
        self.assertEqual(svc._detect_content_type(Path("test.jpg")), "image/jpeg")
        self.assertEqual(svc._detect_content_type(Path("test.webp")), "image/webp")
    
    def test_analyze_base64_invalid(self):
        svc = VisionService()
        result = svc.analyze_base64("not-valid-base64!!!", "image/png")
        self.assertIsNone(result)
    
    def test_analyze_base64_valid(self):
        svc = VisionService()
        # 1x1 red pixel PNG (tiny)
        tiny_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
        result = svc.analyze_base64(tiny_png, "image/png")
        self.assertIsNotNone(result)
        self.assertEqual(result.content_type, "image/png")
    
    def test_vision_api_unconfigured(self):
        svc = VisionService()
        result = svc._call_vision_api("abc", "image/png", "test")
        self.assertEqual(result, "[Vision API 未配置]")


class TestVisionSecurity(unittest.TestCase):
    """安全检查测试"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_analyze_rejects_sensitive_file(self):
        svc = VisionService(allowed_root=self._tmp)
        env_path = Path(self._tmp) / ".env"
        env_path.write_text("SECRET=value")
        result = svc.analyze_image(env_path)
        self.assertIsNone(result)

    def test_analyze_rejects_outside_root(self):
        svc = VisionService(allowed_root=self._tmp)
        # 创建一个在 root 之外的文件
        outside = tempfile.mkdtemp()
        try:
            outside_file = Path(outside) / "test.png"
            outside_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
            result = svc.analyze_image(outside_file)
            self.assertIsNone(result)
        finally:
            import shutil
            shutil.rmtree(outside, ignore_errors=True)

    def test_analyze_rejects_non_image_ext(self):
        svc = VisionService(allowed_root=self._tmp)
        txt_path = Path(self._tmp) / "test.txt"
        txt_path.write_text("hello")
        result = svc.analyze_image(txt_path)
        self.assertIsNone(result)

    def test_analyze_rejects_directory(self):
        svc = VisionService(allowed_root=self._tmp)
        # 传入一个目录而非文件
        result = svc.analyze_image(Path(self._tmp))
        self.assertIsNone(result)

    def test_analyze_allows_valid_image_in_root(self):
        svc = VisionService(allowed_root=self._tmp)
        img_path = Path(self._tmp) / "photo.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        result = svc.analyze_image(img_path)
        self.assertIsNotNone(result)

    def test_analyze_no_root_allows_all(self):
        svc = VisionService()
        img_path = Path(self._tmp) / "photo.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        result = svc.analyze_image(img_path)
        self.assertIsNotNone(result)

    def test_init_with_config(self):
        config = {
            "active_workspace": "myws",
            "workspaces": [
                {"slug": "myws", "docx_dir": self._tmp}
            ]
        }
        svc = VisionService(config=config)
        self.assertEqual(svc._allowed_root, self._tmp)


class TestVisionResult(unittest.TestCase):
    def test_default_values(self):
        r = VisionResult(description="test", content_type="image/png", file_size=100)
        self.assertEqual(r.analysis, "")
    
    def test_with_analysis(self):
        r = VisionResult(description="test", content_type="image/png", file_size=100, analysis="A red dot")
        self.assertEqual(r.analysis, "A red dot")


if __name__ == "__main__":
    unittest.main()
