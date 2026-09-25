import socket
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.proxy import (
    MAX_BYTES,
    ERRORS,
    error_document,
    ProxyError,
    content_type,
    normalize_url,
    public_ip,
    proxied,
    proxy,
    rewrite_css,
    rewrite_html,
    validate_target,
)
from app.terminal_server import server


class RawStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes):
        self.body = body

    async def __aiter__(self):
        yield self.body


class RewriteTests(unittest.TestCase):
    def test_nonpublic_addresses(self):
        for address in [
            "127.0.0.1",
            "0.0.0.0",
            "10.1.1.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "192.0.2.1",
            "224.0.0.1",
            "240.0.0.1",
            "::",
            "::1",
            "fe80::1",
            "fc00::1",
            "ff02::1",
            "::ffff:8.8.8.8",
            "2002:0808:0808::1",
        ]:
            with self.subTest(address=address):
                self.assertFalse(public_ip(address))
        self.assertTrue(public_ip("8.8.8.8"))
        self.assertTrue(public_ip("2606:4700:4700::1111"))

    def test_invalid_urls(self):
        for url in [
            "",
            "http:///x",
            "ftp://example.com",
            "http://u:p@example.com",
            "http://example.com:8080",
            "http://example.com:0",
            "http://localhost.",
            "http://a.localhost",
            "http://localhost.localdomain",
            "http://printer.local",
            "http://intranet",
            "http://x.home.arpa",
            "http://[fe80::1%25eth0]",
            "http://example.com\\@127.0.0.1",
            "http://example.com\n/",
        ]:
            with self.subTest(url=url), self.assertRaises(ProxyError):
                normalize_url(url)

    def test_html(self):
        source = """<base href="https://evil.example/"><meta http-equiv="refresh" content="0;url=/login"><script>alert(1)</script><iframe src="/x"></iframe><object></object><embed><form method="post"><input name="password"></form><form action="search"><input name="q"></form><a href="../next?a=1&b=2" onclick="evil()" integrity="x" crossorigin="anonymous">Next</a><img src="/a.png" srcset="a.png 1x, /b.png 2x"><video poster="/p.jpg"></video><p style="background:url('/bg.png')"></p><style>@import 'theme.css';</style>"""
        soup = BeautifulSoup(
            rewrite_html(source, "https://example.com/dir/page"), "html.parser"
        )
        self.assertEqual(
            len(soup.select('script[src="/terminal/static/controls.js"]')), 1
        )
        self.assertEqual(len(soup.find_all("script")), 1)
        self.assertEqual(soup.body.find(recursive=False)["id"], "terminal")
        self.assertEqual(
            soup.select_one("#url")["value"], "https://example.com/dir/page"
        )
        soup = soup.select_one("#remote-content")
        self.assertFalse(
            soup.select("base, meta, script, iframe, object, embed")
        )
        self.assertEqual(len(soup.find_all("form")), 1)
        self.assertTrue(soup.form["action"].startswith("/proxy?url="))
        self.assertEqual(
            parse_qs(urlsplit(soup.a["href"]).query)["url"],
            ["https://example.com:443/next?a=1&b=2"],
        )
        for attr in ["onclick", "integrity", "crossorigin"]:
            self.assertNotIn(attr, soup.a.attrs)
        self.assertEqual(soup.img["srcset"].count("/proxy?url="), 2)
        self.assertIn("/proxy?url=", soup.video["poster"])
        self.assertIn("/proxy?url=", soup.p["style"])
        self.assertIn("/proxy?url=", soup.style.text)
        self.assertEqual(
            BeautifulSoup(
                rewrite_html(
                    '<a href="javascript:alert(1)">x</a>', "https://example.com"
                ),
                "html.parser",
            ).select_one("#remote-content a")["href"],
            "#",
        )

    def test_head_styles_are_preserved_and_rewritten(self):
        source = """<html><head><title>Remote</title>
<link rel="stylesheet" href="theme.css">
<style>@import "extra.css"; p { background: url(/head.png); }</style>
<script src="https://example.com/remote.js"></script></head>
<body><p style="background:url(/inline.png)">Content</p></body></html>"""
        soup = BeautifulSoup(
            rewrite_html(source, "https://example.com/dir/page"), "html.parser"
        )
        remote = soup.select_one("#remote-content")
        self.assertEqual(remote.link["rel"], ["stylesheet"])
        self.assertEqual(
            parse_qs(urlsplit(remote.link["href"]).query)["url"],
            ["https://example.com:443/dir/theme.css"],
        )
        self.assertEqual(remote.style.text.count("/proxy?url="), 2)
        self.assertIn("/proxy?url=", remote.p["style"])
        self.assertFalse(remote.select("script, title, meta"))

    def test_error_documents(self):
        for code, (status, message) in ERRORS.items():
            response = error_document(code, 'https://example.com/?q="<script>')
            self.assertEqual(response.status_code, status)
            soup = BeautifulSoup(response.body, "html.parser")
            self.assertEqual(soup.select_one(".error-status").text, str(status))
            self.assertEqual(soup.select_one(".error-message").text, message)
            self.assertEqual(
                soup.select_one("#url")["value"],
                'https://example.com/?q="<script>',
            )
            self.assertEqual(len(soup.find_all("script")), 1)
            self.assertEqual(
                soup.select_one("#address-form")["action"], "/proxy"
            )
            self.assertIsNotNone(soup.select_one("#retry"))
            self.assertIsNotNone(soup.select_one("#error-home"))
            directives = response.headers["content-security-policy"].split("; ")
            self.assertIn("style-src 'self' 'unsafe-inline'", directives)
            self.assertIn("script-src 'self'", directives)
            self.assertIn("default-src 'none'", directives)

    def test_css_and_types(self):
        css = rewrite_css(
            '/* url(no) */ @import "a.css" screen; @import url(b.css); p {background:URL(../x.png)}',
            "https://example.com/dir/p",
        )
        self.assertEqual(css.count("/proxy?url="), 3)
        self.assertNotIn("url(no)", css)
        self.assertEqual(
            content_type('text/plain; charset="windows-1250"'),
            ("text/plain", "cp1250"),
        )
        for media in [
            "application/javascript",
            "application/json",
            "image/svg+xml",
            "text/html; charset=utf-7",
            "",
        ]:
            with self.assertRaises(ProxyError):
                content_type(media)


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def request_proxy(
        self, handler, url="https://example.com/start", **kwargs
    ):
        real_client = httpx.AsyncClient
        calls = []

        def factory(**options):
            calls.append(options)
            return real_client(
                transport=httpx.MockTransport(handler), **options
            )

        records = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ]
        async with real_client(
            transport=httpx.ASGITransport(app=server), base_url="http://test"
        ) as client:
            with (
                patch("app.proxy.httpx.AsyncClient", side_effect=factory),
                patch(
                    "asyncio.BaseEventLoop.getaddrinfo",
                    new=AsyncMock(return_value=records),
                ),
            ):
                response = await client.get(
                    "/proxy", params={"url": url}, **kwargs
                )
        for options in calls:
            self.assertFalse(options["trust_env"])
            self.assertFalse(options["follow_redirects"])
        for name, value in [
            ("cache-control", "no-store"),
            ("referrer-policy", "no-referrer"),
            ("x-content-type-options", "nosniff"),
        ]:
            self.assertEqual(response.headers[name], value)
        self.assertIn(
            "script-src 'self'", response.headers["content-security-policy"]
        )
        return response

    async def test_native_link_flow(self):
        response = await self.request_proxy(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                stream=RawStream(
                    b'<a href="/next?a=1&b=2">Next</a><script>bad()</script>'
                ),
            )
        )
        soup = BeautifulSoup(response.text, "html.parser")
        link = soup.select_one("#remote-content a")["href"]
        self.assertTrue(link.startswith("/proxy?url="))
        target = parse_qs(urlsplit(link).query)["url"][0]
        next_response = await self.request_proxy(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                stream=RawStream(b"<p>Next</p>"),
            ),
            url=target,
        )
        next_page = BeautifulSoup(next_response.text, "html.parser")
        self.assertEqual(next_page.select_one("#url")["value"], target)
        self.assertEqual(next_page.select_one("#remote-content p").text, "Next")

    async def test_unexpected_failure_is_logged(self):
        with (
            patch(
                "app.proxy.fetch",
                new=AsyncMock(side_effect=RuntimeError("bug")),
            ),
            patch("app.proxy.logging.exception") as log,
        ):
            response = await proxy("https://example.com")
        self.assertEqual(response.status_code, 502)
        log.assert_called_once()
        self.assertNotIn("bug", response.body.decode())

    async def test_dns_all_results(self):
        records = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ["8.8.8.8", "127.0.0.1"]
        ]
        with (
            patch(
                "asyncio.BaseEventLoop.getaddrinfo",
                new=AsyncMock(return_value=records),
            ),
            self.assertRaises(ProxyError) as error,
        ):
            await validate_target("https://example.com")
        self.assertEqual(error.exception.code, "blocked_address")

    async def test_pinning_and_no_session_forwarding(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, "8.8.8.8")
            self.assertEqual(request.headers["host"], "example.com")
            self.assertEqual(request.extensions["sni_hostname"], "example.com")
            for header in ["cookie", "authorization", "referer", "x-secret"]:
                self.assertNotIn(header, request.headers)
            if len(requests) == 1:
                return httpx.Response(
                    302,
                    headers={
                        "location": "/final",
                        "set-cookie": "secret=upstream",
                    },
                )
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/plain; charset=windows-1250",
                    "set-cookie": "secret=again",
                },
                stream=RawStream(b"hello"),
            )

        response = await self.request_proxy(
            handler,
            headers={
                "Cookie": "session=secret",
                "Authorization": "Bearer secret",
                "X-Secret": "private",
                "Referer": "https://private.example",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"hello")
        self.assertNotIn("set-cookie", response.headers)
        self.assertIn("cp1250", response.headers["content-type"])
        self.assertEqual(len(requests), 2)

    async def test_redirect_security(self):
        for location, code in [
            ("http://127.0.0.1/", "blocked_address"),
            ("https://example.com/start", "redirect_loop"),
            ("file:///etc/passwd", "invalid_url"),
        ]:
            response = await self.request_proxy(
                lambda request: httpx.Response(
                    302, headers={"location": location}
                )
            )
            self.assertEqual(response.status_code, ERRORS[code][0])
            self.assertIn(ERRORS[code][1], response.text)
        counter = 0

        def chain(request):
            nonlocal counter
            counter += 1
            return httpx.Response(302, headers={"location": f"/hop{counter}"})

        response = await self.request_proxy(chain)
        self.assertIn(ERRORS["redirect_limit"][1], response.text)
        self.assertEqual(counter, 6)

    async def test_limits_and_errors(self):
        cases = [
            (
                {
                    "content-type": "text/plain",
                    "content-length": str(MAX_BYTES + 1),
                },
                b"",
                413,
            ),
            ({"content-type": "text/plain"}, b"x" * (MAX_BYTES + 1), 413),
            ({"content-type": "application/javascript"}, b"", 415),
            (
                {"content-type": "text/html", "content-encoding": "gzip"},
                b"",
                415,
            ),
        ]
        for headers, body, status in cases:
            response = await self.request_proxy(
                lambda request: httpx.Response(
                    200, headers=headers, stream=RawStream(body)
                )
            )
            self.assertEqual(response.status_code, status)
        response = await self.request_proxy(lambda request: httpx.Response(401))
        self.assertIn(ERRORS["login_required"][1], response.text)

        def timeout(request):
            raise httpx.ReadTimeout("sensitive diagnostic")

        response = await self.request_proxy(timeout)
        self.assertEqual(response.status_code, 504)
        self.assertNotIn("sensitive", response.text)

    async def test_redirect_rechecks_dns(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        private = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))
        ]
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "/next"})
        )
        async with real_client(
            transport=httpx.ASGITransport(app=server), base_url="http://test"
        ) as client:
            with (
                patch(
                    "app.proxy.httpx.AsyncClient",
                    side_effect=lambda **kwargs: real_client(
                        transport=transport, **kwargs
                    ),
                ),
                patch(
                    "asyncio.BaseEventLoop.getaddrinfo",
                    new=AsyncMock(side_effect=[public, private]),
                ) as dns,
            ):
                response = await client.get(
                    "/proxy", params={"url": "https://example.com"}
                )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dns.await_count, 2)


if __name__ == "__main__":
    unittest.main()
