import asyncio
import unittest

import httpx

from app.terminal_server import controls, server, stylesheet, terminal


class TerminalTests(unittest.TestCase):
    def test_native_document(self):
        response = terminal()
        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/proxy" method="get"', html)
        self.assertIn('name="url"', html)
        self.assertNotIn("<iframe", html)
        self.assertNotIn("/_next/", html)
        self.assertNotIn("stage-note", html)
        self.assertNotIn("nie jest jeszcze dostępne", html)
        self.assertIn("text/html", response.headers["content-type"])

    def test_old_browser_assets(self):
        script = controls().body.decode("utf-8")
        for forbidden in (
            "fetch(",
            "Promise",
            "=>",
            "const ",
            "let ",
            "localStorage",
            "sessionStorage",
        ):
            self.assertNotIn(forbidden, script)
        self.assertIn("attachEvent", script)
        self.assertIn("if (!element)", script)
        self.assertIn("window.history.back()", script)
        self.assertIn("window.history.forward()", script)
        self.assertIn("window.location.reload()", script)
        self.assertIn("selectionStart", script)
        self.assertIn("address.setAttribute('aria-invalid', 'true');", script)
        self.assertIn("address.removeAttribute('aria-invalid');", script)
        css = stylesheet().body.decode("utf-8")
        for forbidden in (
            "@import",
            "animation:",
            "transition:",
            "gradient(",
            "display: grid",
            "display: flex",
        ):
            self.assertNotIn(forbidden, css)
        self.assertIn("Arial", css)

    def test_proxy_registered(self):
        paths = [
            route.path for route in server.routes if hasattr(route, "path")
        ]
        self.assertIn("/terminal/static/controls.js", paths)

        async def check_proxy():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://test",
            ) as client:
                response = await client.get("/proxy")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Nieprawidłowy adres HTTP/HTTPS.", response.text)

        asyncio.run(check_proxy())


if __name__ == "__main__":
    unittest.main()
