"""访问密码门（services/auth_service + api/middleware）测试。"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.auth_service import AUTH_COOKIE, AuthService
from backend.services.config_service import ConfigService

_KEY = "AUTH_PASSWORD_HASH"


class AuthTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="auth_"))
        self.env_path = self.tmp / ".env"
        settings = self.tmp / "settings.toml"
        settings.write_text("", encoding="utf-8")
        self.config = ConfigService(settings)
        self.auth = AuthService(self.config, env_path=self.env_path)
        os.environ.pop(_KEY, None)

    def tearDown(self):
        os.environ.pop(_KEY, None)
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestPassword(AuthTestBase):
    def test_gate_off_when_no_hash(self):
        self.assertFalse(self.auth.enabled())

    def test_set_and_verify(self):
        self.auth.set_password("secret123")
        self.assertTrue(self.auth.enabled())
        self.assertTrue(self.auth.verify_password("secret123"))
        self.assertFalse(self.auth.verify_password("wrong"))
        self.assertFalse(self.auth.verify_password(""))

    def test_hash_written_to_env_file_not_plaintext(self):
        self.auth.set_password("secret123")
        content = self.env_path.read_text(encoding="utf-8")
        self.assertIn(_KEY, content)
        self.assertNotIn("secret123", content)

    def test_clear_restores_open(self):
        self.auth.set_password("secret123")
        self.auth.clear_password()
        self.assertFalse(self.auth.enabled())


class TestToken(AuthTestBase):
    def test_roundtrip(self):
        token = self.auth.make_token()
        self.assertTrue(self.auth.verify_token(token))

    def test_tampered_rejected(self):
        token = self.auth.make_token()
        exp, _, sig = token.partition(".")
        self.assertFalse(self.auth.verify_token(f"{exp}.{'0' * len(sig)}"))
        self.assertFalse(self.auth.verify_token("garbage"))
        self.assertFalse(self.auth.verify_token(""))

    def test_expired_rejected(self):
        import hashlib
        import hmac
        exp = str(int(time.time() - 10))
        sig = hmac.new(self.auth._secret(), exp.encode(),
                       hashlib.sha256).hexdigest()
        self.assertFalse(self.auth.verify_token(f"{exp}.{sig}"))


class TestRateLimit(AuthTestBase):
    def test_lockout_and_recovery(self):
        self.config._data["auth_login_max_attempts"] = 3
        self.config._data["auth_login_window_s"] = 300
        ip = "1.2.3.4"
        for _ in range(3):
            self.assertFalse(self.auth.rate_limited(ip))
            self.auth.record_fail(ip)
        self.assertTrue(self.auth.rate_limited(ip))
        self.auth.record_success(ip)
        self.assertFalse(self.auth.rate_limited(ip))

    def test_window_expiry(self):
        self.config._data["auth_login_max_attempts"] = 2
        self.config._data["auth_login_window_s"] = 1
        ip = "1.2.3.4"
        self.auth.record_fail(ip)
        self.auth.record_fail(ip)
        self.assertTrue(self.auth.rate_limited(ip))
        time.sleep(1.1)
        self.assertFalse(self.auth.rate_limited(ip))


class TestMiddleware(AuthTestBase):
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.api.middleware import make_auth_gate
        from backend.services import auth_service as auth_mod

        # 单例按配置路径缓存：换注入 env_path 的实例
        auth_mod._AUTH[str(self.config.path)] = self.auth
        app = FastAPI()
        app.middleware("http")(make_auth_gate(self.config))

        @app.get("/api/x")
        def x():
            return {"ok": True}

        @app.get("/api/auth/status")
        def status():
            return {"ok": True}

        @app.get("/static.js")
        def static():
            return {"ok": True}

        return TestClient(app)

    def test_gate_off_passes(self):
        c = self._client()
        self.assertEqual(c.get("/api/x").status_code, 200)

    def test_gate_on_blocks_and_admits(self):
        self.auth.set_password("secret123")
        c = self._client()
        self.assertEqual(c.get("/api/x").status_code, 401)  # 无 cookie
        # 篡改 cookie 也拒
        c.cookies.set(AUTH_COOKIE, "bad.token")
        self.assertEqual(c.get("/api/x").status_code, 401)
        # 正确 token 放行
        c.cookies.set(AUTH_COOKIE, self.auth.make_token())
        self.assertEqual(c.get("/api/x").status_code, 200)

    def test_exempt_and_static_pass(self):
        self.auth.set_password("secret123")
        c = self._client()
        self.assertEqual(c.get("/api/auth/status").status_code, 200)  # 豁免
        self.assertEqual(c.get("/static.js").status_code, 200)  # 非 /api


if __name__ == "__main__":
    unittest.main()
