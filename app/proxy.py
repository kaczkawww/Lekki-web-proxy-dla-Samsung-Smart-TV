import asyncio
import codecs
import ipaddress
import logging
import re
import socket
from html import escape
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter
from starlette.responses import Response

router = APIRouter()
MAX_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 5
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox allow-forms allow-scripts allow-same-origin; default-src 'none'; script-src 'self'; img-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-src 'none'; object-src 'none'; frame-ancestors 'self'",
}
ERRORS = {
    "invalid_url": (400, "Nieprawidłowy adres HTTP/HTTPS."),
    "blocked_address": (403, "Adres nie jest publicznym adresem internetowym."),
    "dns_failed": (502, "Nie można rozwiązać nazwy strony."),
    "redirect_loop": (502, "Wykryto pętlę przekierowań."),
    "redirect_limit": (502, "Przekroczono limit przekierowań."),
    "timeout": (504, "Upłynął czas oczekiwania na stronę."),
    "too_large": (413, "Zasób przekracza dozwolony rozmiar."),
    "unsupported_type": (
        415,
        "Ten typ zasobu lub kodowanie nie jest obsługiwane.",
    ),
    "login_required": (
        403,
        "Strona wymaga autoryzacji. Proxy nie przenosi sesji logowania.",
    ),
    "upstream_error": (502, "Nie można pobrać zasobu."),
}
TEXT_TYPES = {"text/html", "application/xhtml+xml", "text/css", "text/plain"}
IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/bmp",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}


class ProxyError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return bool(
        address.is_global
        and not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
        and not (
            isinstance(address, ipaddress.IPv6Address)
            and (address.ipv4_mapped or address.sixtofour or address.teredo)
        )
    )


def normalize_url(value: str) -> tuple[str, str, int]:
    try:
        if (
            not value
            or len(value) > 8192
            or re.search(r"[\s\\\x00-\x1f\x7f]", value)
        ):
            raise ProxyError("invalid_url")
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ProxyError("invalid_url")
        host = (
            parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        )
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        if (
            port not in {80, 443}
            or parsed.netloc.endswith(":")
            or parsed.port == 0
        ):
            raise ProxyError("blocked_address")
        if (
            "%" in host
            or host == "localhost"
            or host.startswith("localhost.")
            or host.endswith(
                (
                    ".localhost",
                    ".local",
                    ".localdomain",
                    ".internal",
                    ".lan",
                    ".home",
                    ".home.arpa",
                    ".test",
                    ".invalid",
                )
            )
        ):
            raise ProxyError("blocked_address")
        if ":" not in host and (
            not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host
        ):
            raise ProxyError("invalid_url")
        if "." not in host and ":" not in host:
            raise ProxyError("blocked_address")
        authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        return (
            urlunsplit(
                (
                    parsed.scheme.lower(),
                    authority,
                    parsed.path or "/",
                    parsed.query,
                    "",
                )
            ),
            host,
            port,
        )
    except (ValueError, UnicodeError):
        logging.exception("Unexpected error")
        logging.debug("Controlled proxy rejection")
        raise ProxyError("invalid_url") from None


async def validate_target(value: str) -> tuple[str, str, int, str]:
    normalized, host, port = normalize_url(value)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            results = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                ),
                timeout=3,
            )
            addresses = list({result[4][0] for result in results})
        except (OSError, TimeoutError):
            logging.exception("Unexpected error")
            raise ProxyError("dns_failed") from None
    if not addresses or not all(public_ip(address) for address in addresses):
        raise ProxyError("blocked_address")
    return normalized, host, port, addresses[0]


def proxied(value: str, base: str) -> str:
    value = value.strip()
    if value.startswith("#"):
        return value
    try:
        target = urljoin(base, value)
        normalized, _, _ = normalize_url(target)
        fragment = urlsplit(target).fragment
        return f"/proxy?url={quote(normalized, safe='')}{f'#{quote(fragment)}' if fragment else ''}"
    except (ProxyError, ValueError):
        logging.exception("Unexpected error")
        return "#"


def rewrite_css(text: str, base: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(
        r"\\([0-9a-fA-F]{1,6})\s?|\\([^\r\n])",
        lambda m: chr(min(int(m[1], 16), 0x10FFFF) or 0xFFFD) if m[1] else m[2],
        text,
    )
    text = re.sub(
        r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)",
        lambda m: (
            f'url("{proxied(next(group for group in m.groups() if group is not None).strip(), base)}")'
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(@import\s+)([\"'])(.*?)\2",
        lambda m: f'{m[1]}"{proxied(m[3], base)}"',
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"(?:expression\s*\(|-moz-binding\s*:|behavior\s*:)",
        "blocked:",
        text,
        flags=re.I,
    )
    return text


def rewrite_srcset(text: str, base: str) -> str:
    candidates = []
    # Data URLs and comma-containing candidates are deliberately unsupported.
    for candidate in text.split(","):
        parts = candidate.split()
        if (
            parts
            and len(parts) <= 2
            and (
                len(parts) == 1
                or re.fullmatch(r"(?:\d+w|\d+(?:\.\d+)?x)", parts[1])
            )
        ):
            if parts[0].lower().startswith("data:"):
                continue
            candidates.append(" ".join([proxied(parts[0], base), *parts[1:]]))
    return ", ".join(candidates)


def document(
    content: str, url: str, title: str = "ORSAY — przeglądanie"
) -> str:
    address = escape(url, quote=True)
    return f'''<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><link rel="stylesheet" href="/terminal/static/styles.css">
</head><body class="proxy-view"><div id="terminal">
<div id="navigation" role="navigation" aria-label="Nawigacja przeglądarki">
<button id="back" type="button" class="nav-control">← Wstecz</button>
<button id="forward" type="button" class="nav-control">→ Dalej</button>
<button id="reload" type="button" class="nav-control">↻ Odśwież</button>
<a id="home" class="nav-control" href="/terminal/">Strona główna</a>
</div><form id="address-form" action="/proxy" method="get">
<label for="url">ADRES STRONY</label><div class="address-row">
<input id="url" name="url" type="text" value="{address}" autocomplete="off" autocapitalize="off" spellcheck="false" aria-describedby="address-error">
<button id="open" type="submit">OTWÓRZ →</button></div>
<p id="address-error" role="alert" aria-live="polite"></p></form>
<noscript><p class="noscript">Wpisz pełny adres HTTP/HTTPS. Wstecz, Dalej i Odśwież wymagają JavaScript; możesz użyć przycisków przeglądarki.</p></noscript>
<div id="remote-content" role="main">{content}</div></div>
<script src="/terminal/static/controls.js"></script></body></html>'''


def error_document(code: str, url: str) -> Response:
    status, message = ERRORS[code]
    retry = escape(f"/proxy?url={quote(url, safe='')}", quote=True)
    content = f'''<div class="error-page"><p class="eyebrow">NIE MOŻNA OTWORZYĆ STRONY</p>
<h1 class="error-status">{status}</h1><p class="error-message">{escape(message)}</p>
<p class="hint">Sprawdź adres lub spróbuj ponownie za chwilę.</p>
<p><a id="retry" class="nav-control" href="{retry}">Spróbuj ponownie</a>
<a id="error-home" class="nav-control" href="/terminal/">Strona główna</a></p></div>'''
    return Response(
        document(content, url, f"ORSAY — błąd {status}"),
        status_code=status,
        headers=HEADERS,
        media_type="text/html",
    )


def rewrite_html(text: str, base: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    for tag in list(
        soup.find_all(
            [
                "base",
                "iframe",
                "frame",
                "frameset",
                "object",
                "embed",
                "script",
                "svg",
                "math",
                "applet",
                "template",
            ]
        )
    ):
        tag.decompose()
    for tag in list(soup.find_all("meta")):
        if tag.get("http-equiv"):
            tag.decompose()
        elif tag.get("charset"):
            tag["charset"] = "utf-8"
    for tag in list(soup.find_all("form")):
        if str(tag.get("method", "get")).lower() != "get":
            tag.decompose()
        else:
            tag["action"] = proxied(tag.get("action", base), base)
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on") or attr.lower() in {
                "integrity",
                "crossorigin",
                "nonce",
                "srcdoc",
                "ping",
                "formaction",
                "formmethod",
                "target",
                "download",
                "background",
                "manifest",
                "profile",
                "codebase",
                "archive",
                "data",
                "autofocus",
            }:
                del tag[attr]
        for attr in ("href", "src", "poster"):
            if tag.has_attr(attr):
                tag[attr] = proxied(tag[attr], base)
        if tag.has_attr("srcset"):
            tag["srcset"] = rewrite_srcset(tag["srcset"], base)
        if tag.has_attr("style"):
            tag["style"] = rewrite_css(tag["style"], base)
        if tag.name == "style":
            tag.string = rewrite_css(tag.get_text(), base)
        if tag.name == "link":
            tag["rel"] = (
                ["stylesheet"] if "stylesheet" in tag.get("rel", []) else []
            )
    for tag in soup.find_all(True):
        if tag.get("id") in {
            "terminal",
            "navigation",
            "address-form",
            "url",
            "open",
            "back",
            "forward",
            "reload",
            "home",
            "address-error",
            "remote-content",
            "retry",
            "error-home",
        }:
            del tag["id"]
    for tag in list(soup.find_all(["title", "meta"])):
        tag.decompose()
    for tag in list(soup.find_all(["html", "head", "body"])):
        tag.unwrap()
    return document(soup, base)


def content_type(value: str) -> tuple[str, str]:
    media = value.split(";", 1)[0].strip().lower()
    if media not in TEXT_TYPES | IMAGE_TYPES:
        raise ProxyError("unsupported_type")
    match = re.search(r";\s*charset\s*=\s*[\"']?([a-zA-Z0-9._-]+)", value, re.I)
    charset = match[1] if match else "utf-8"
    try:
        charset = codecs.lookup(charset).name
        if charset not in {
            "utf-8",
            "ascii",
            "iso8859-1",
            "iso8859-2",
            "cp1250",
            "cp1251",
            "cp1252",
            "shift_jis",
            "euc_jp",
            "gb2312",
            "gbk",
            "gb18030",
            "big5",
            "koi8-r",
            "utf-16",
            "utf-16-le",
            "utf-16-be",
        }:
            raise ProxyError("unsupported_type")
    except LookupError:
        logging.exception("Unexpected error")
        raise ProxyError("unsupported_type") from None
    return media, charset


async def fetch(value: str) -> Response:
    visited: set[str] = set()
    for hop in range(MAX_REDIRECTS + 1):
        normalized, host, port, address = await validate_target(value)
        if normalized in visited:
            raise ProxyError("redirect_loop")
        visited.add(normalized)
        original = httpx.URL(normalized)
        pinned = original.copy_with(host=address)
        # Connect only to an already checked IP; retain original TLS SNI and Host.
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(6, connect=3),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        ) as client:
            async with client.stream(
                "GET",
                pinned,
                headers={
                    "Host": original.netloc.decode("ascii"),
                    "Accept": "text/html,application/xhtml+xml,text/css,text/plain,image/*",
                    "Accept-Encoding": "identity",
                    "User-Agent": "OrsayPublicProxy/1.0",
                },
                extensions={"sni_hostname": host},
            ) as upstream:
                if upstream.status_code in {301, 302, 303, 307, 308}:
                    location = upstream.headers.get("location")
                    if not location:
                        raise ProxyError("upstream_error")
                    if hop == MAX_REDIRECTS:
                        raise ProxyError("redirect_limit")
                    value = urljoin(normalized, location)
                    continue
                if upstream.status_code in {401, 403, 407}:
                    raise ProxyError("login_required")
                if upstream.status_code != 200:
                    raise ProxyError("upstream_error")
                media, charset = content_type(
                    upstream.headers.get("content-type", "")
                )
                if upstream.headers.get(
                    "content-encoding", "identity"
                ).lower() not in {"identity", ""}:
                    raise ProxyError("unsupported_type")
                length = upstream.headers.get("content-length", "")
                if length.isdigit() and int(length) > MAX_BYTES:
                    raise ProxyError("too_large")
                body = bytearray()
                async for chunk in upstream.aiter_raw(chunk_size=65536):
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise ProxyError("too_large")
                    body.extend(chunk)
        if media in {"text/html", "application/xhtml+xml", "text/css"}:
            text = bytes(body).decode(charset, errors="replace")
            if media == "text/css":
                text = rewrite_css(text, normalized)
            else:
                text = rewrite_html(text, normalized)
                media = "text/html"
            result = text.encode("utf-8")
            safe_type = f"{media}; charset=utf-8"
        else:
            result = bytes(body)
            safe_type = (
                f"{media}; charset={charset}"
                if media == "text/plain"
                else media
            )
        return Response(result, headers={**HEADERS, "Content-Type": safe_type})
    raise ProxyError("redirect_limit")


@router.get("/proxy")
async def proxy(url: str = "") -> Response:
    try:
        async with asyncio.timeout(20):
            return await fetch(url)
    except ProxyError as e:
        logging.exception("Unexpected error")
        code = e.code
    except (TimeoutError, httpx.TimeoutException):
        logging.exception("Unexpected error")
        code = "timeout"
    except socket.gaierror:
        logging.exception("Unexpected error")
        code = "dns_failed"
    except httpx.HTTPError:
        logging.exception("Unexpected error")
        code = "upstream_error"
    except Exception:
        logging.exception("Unexpected proxy failure")
        code = "upstream_error"
    return error_document(code, url)
