"""AuthProvider 接口测试"""
import unittest
from unittest.mock import MagicMock
from backend.services.auth_provider import AuthProvider, LocalAuthProvider, OAuthProvider


class TestAuthProviderInterface(unittest.TestCase):
    def test_auth_provider_is_abstract(self):
        with self.assertRaises(TypeError):
            AuthProvider()


class TestLocalAuthProvider(unittest.TestCase):
    def _make_provider(self, hash_value=""):
        config = MagicMock()
        config.env.return_value = hash_value
        provider = LocalAuthProvider(config)
        return provider

    def test_enabled_no_password(self):
        provider = self._make_provider("")
        self.assertFalse(provider.enabled())
    
    def test_verify_empty_password(self):
        provider = self._make_provider("")
        # 哈希为空时 verify 应返回 False
        self.assertFalse(provider.verify_password("anything"))


class TestOAuthProvider(unittest.TestCase):
    def test_verify_password_raises(self):
        provider = OAuthProvider()
        with self.assertRaises(NotImplementedError):
            provider.verify_password("test")
    
    def test_set_password_raises(self):
        provider = OAuthProvider()
        with self.assertRaises(NotImplementedError):
            provider.set_password("test")
    
    def test_clear_password_raises(self):
        provider = OAuthProvider()
        with self.assertRaises(NotImplementedError):
            provider.clear_password()
    
    def test_enabled_returns_false(self):
        provider = OAuthProvider()
        self.assertFalse(provider.enabled())


if __name__ == "__main__":
    unittest.main()
