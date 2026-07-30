"""VisionService 测试"""
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


class TestVisionResult(unittest.TestCase):
    def test_default_values(self):
        r = VisionResult(description="test", content_type="image/png", file_size=100)
        self.assertEqual(r.analysis, "")
    
    def test_with_analysis(self):
        r = VisionResult(description="test", content_type="image/png", file_size=100, analysis="A red dot")
        self.assertEqual(r.analysis, "A red dot")


if __name__ == "__main__":
    unittest.main()
