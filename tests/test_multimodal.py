"""多模态输入集成测试（M2.3.5）

覆盖 VisionService + UploadService 的集成场景。
"""
import unittest
import base64
import tempfile
import shutil
from pathlib import Path
from backend.services.vision_service import VisionService, VisionResult
from backend.services.upload_service import UploadService, UploadResult


class TestVisionServiceIntegration(unittest.TestCase):
    """VisionService 集成测试"""
    
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
    
    def test_analyze_local_image(self):
        """分析本地图片文件"""
        # 创建测试图片（最小 PNG）
        img_path = Path(self._tmp) / "test.png"
        # 最小有效 PNG（1x1 像素）
        png_data = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        ]) + b"\x00" * 100
        img_path.write_bytes(png_data)
        
        svc = VisionService(allowed_root=self._tmp)
        result = svc.analyze_image(img_path)
        self.assertIsNotNone(result)
        self.assertEqual(result.content_type, "image/png")
    
    def test_analyze_base64_image(self):
        """分析 base64 编码图片"""
        # 最小 PNG base64
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        b64 = base64.b64encode(png_data).decode()
        
        svc = VisionService()
        result = svc.analyze_base64(b64, "image/png")
        self.assertIsNotNone(result)
        self.assertEqual(result.content_type, "image/png")
    
    def test_vision_rejects_sensitive_file(self):
        """拒绝敏感文件"""
        env_path = Path(self._tmp) / ".env"
        env_path.write_text("SECRET=value")
        
        svc = VisionService(allowed_root=self._tmp)
        result = svc.analyze_image(env_path)
        self.assertIsNone(result)
    
    def test_vision_rejects_non_image(self):
        """拒绝非图片文件"""
        txt_path = Path(self._tmp) / "test.txt"
        txt_path.write_text("hello world")
        
        svc = VisionService(allowed_root=self._tmp)
        result = svc.analyze_image(txt_path)
        self.assertIsNone(result)


class TestUploadServiceIntegration(unittest.TestCase):
    """UploadService 集成测试"""
    
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._upload_dir = Path(self._tmp) / "uploads"
        self._upload_dir.mkdir()
    
    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
    
    def _make_svc_with_upload_dir(self):
        """创建以上传目录配置好的 UploadService"""
        svc = UploadService()
        # 直接 patch _get_upload_dir 返回临时目录
        svc._get_upload_dir = lambda: self._upload_dir
        return svc
    
    def test_upload_image(self):
        """上传图片文件"""
        svc = self._make_svc_with_upload_dir()
        # 最小 PNG（含正确 magic bytes）
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = svc.save_upload("test.png", png_data)
        self.assertIsInstance(result, UploadResult)
        self.assertEqual(result.file_type, "image")
    
    def test_upload_document(self):
        """上传文档文件"""
        svc = self._make_svc_with_upload_dir()
        md_data = b"# Hello\n\nThis is a test document."
        result = svc.save_upload("test.md", md_data)
        self.assertIsInstance(result, UploadResult)
        self.assertEqual(result.file_type, "document")
    
    def test_upload_rejects_binary_as_text(self):
        """拒绝二进制伪装为文本"""
        svc = self._make_svc_with_upload_dir()
        binary_data = b"\x00\x01\x02\x03" * 100
        result = svc.save_upload("fake.txt", binary_data)
        # 应该返回错误字符串
        self.assertIsInstance(result, str)


class TestVisionResultDataclass(unittest.TestCase):
    def test_vision_result_fields(self):
        r = VisionResult(
            description="test prompt",
            content_type="image/png",
            file_size=1024,
            analysis="A test image"
        )
        self.assertEqual(r.description, "test prompt")
        self.assertEqual(r.analysis, "A test image")


if __name__ == "__main__":
    unittest.main()
