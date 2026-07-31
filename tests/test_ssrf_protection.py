"""C-4 SSRF 防护：_validate_base_url 单元测试。"""

import unittest

from backend.services.llm_config_service import validate_base_url as _validate_base_url


class TestValidateBaseUrl(unittest.TestCase):
    """_validate_base_url 校验逻辑测试。"""

    def test_rejects_file_protocol(self):
        """file:// 协议必须被拒绝。"""
        error = _validate_base_url("file:///etc/passwd")
        self.assertIsNotNone(error)

    def test_rejects_localhost(self):
        """localhost / 127.0.0.1 必须被拒绝。"""
        error = _validate_base_url("http://127.0.0.1:8080/")
        self.assertIsNotNone(error)

    def test_rejects_localhost_name(self):
        """localhost 主机名必须被拒绝。"""
        error = _validate_base_url("http://localhost:8080/")
        self.assertIsNotNone(error)

    def test_rejects_cloud_metadata(self):
        """169.254.169.254（云元数据）必须被拒绝。"""
        error = _validate_base_url("http://169.254.169.254/")
        self.assertIsNotNone(error)

    def test_accepts_public_https(self):
        """公网 HTTPS 地址必须通过。"""
        error = _validate_base_url("https://api.openai.com/v1")
        self.assertIsNone(error)

    def test_accepts_public_http(self):
        """公网 HTTP 地址必须通过。"""
        error = _validate_base_url("http://api.example.com/v1")
        self.assertIsNone(error)

    def test_allow_private_flag(self):
        """allow_private=True 时内网地址必须通过。"""
        error = _validate_base_url("http://192.168.1.100:11434/v1", allow_private=True)
        self.assertIsNone(error)

    def test_rejects_private_ip_without_flag(self):
        """allow_private=False 时内网 IP 必须被拒绝。"""
        error = _validate_base_url("http://192.168.1.100:11434/v1")
        self.assertIsNotNone(error)

    def test_rejects_ipv6_loopback(self):
        """IPv6 回环地址必须被拒绝。"""
        error = _validate_base_url("http://[::1]:8080/")
        self.assertIsNotNone(error)

    def test_empty_url_allowed(self):
        """空 URL 必须允许（可选字段）。"""
        error = _validate_base_url("")
        self.assertIsNone(error)

    def test_rejects_ftp_protocol(self):
        """ftp:// 协议必须被拒绝。"""
        error = _validate_base_url("ftp://example.com/file")
        self.assertIsNotNone(error)

    def test_rejects_zero_address(self):
        """0.0.0.0 必须被拒绝。"""
        error = _validate_base_url("http://0.0.0.0:8080/")
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
