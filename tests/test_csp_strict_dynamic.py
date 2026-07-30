"""M-S4: CSP script-src 使用 strict-dynamic 替代 unsafe-inline"""
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api.security_headers import SecurityHeadersMiddleware, SECURITY_HEADERS


class TestCSPStrictDynamic(unittest.TestCase):
    """验证 CSP 头中 script-src 使用 strict-dynamic 而非 unsafe-inline。"""

    def setUp(self):
        app = FastAPI()

        @app.get("/html")
        def html_page():
            from fastapi.responses import HTMLResponse
            return HTMLResponse("<html><body>ok</body></html>")

        @app.get("/json")
        def json_resp():
            return {"status": "ok"}

        app.add_middleware(SecurityHeadersMiddleware, enabled=True)
        self.client = TestClient(app)

    def test_csp_script_src_has_strict_dynamic(self):
        """script-src 包含 'strict-dynamic'"""
        resp = self.client.get("/html")
        csp = resp.headers["content-security-policy"]
        self.assertIn("'strict-dynamic'", csp)

    def test_csp_script_src_no_unsafe_inline(self):
        """script-src 不包含 'unsafe-inline'"""
        resp = self.client.get("/html")
        csp = resp.headers["content-security-policy"]
        # 提取 script-src 指令（到下一个 ; 为止）
        script_src = [d.strip() for d in csp.split(";") if "script-src" in d][0]
        self.assertNotIn("'unsafe-inline'", script_src)

    def test_csp_style_src_keeps_unsafe_inline(self):
        """style-src 保留 'unsafe-inline'（Monaco 依赖）"""
        resp = self.client.get("/html")
        csp = resp.headers["content-security-policy"]
        style_src = [d.strip() for d in csp.split(";") if "style-src" in d][0]
        self.assertIn("'unsafe-inline'", style_src)

    def test_security_headers_present_on_all_responses(self):
        """所有响应都包含安全头"""
        for path in ("/html", "/json"):
            resp = self.client.get(path)
            for header in SECURITY_HEADERS:
                self.assertIn(header, resp.headers, f"{header} missing on {path}")

    def test_disabled_middleware_no_headers(self):
        """enabled=False 时不注入安全头"""
        app = FastAPI()

        @app.get("/")
        def root():
            return {"ok": True}

        app.add_middleware(SecurityHeadersMiddleware, enabled=False)
        client = TestClient(app)
        resp = client.get("/")
        self.assertNotIn("content-security-policy", resp.headers)


if __name__ == "__main__":
    unittest.main()
