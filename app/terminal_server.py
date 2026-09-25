import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import Response

from app.proxy import router as proxy_router


STATIC_DIR = Path(__file__).parent / "static"
server = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
server.include_router(proxy_router)


def asset_response(filename: str, media_type: str) -> Response:
    try:
        content = (STATIC_DIR / filename).read_bytes()
    except OSError as e:
        logging.exception(f"Error: {e}")
        return Response(
            "Interfejs jest chwilowo niedostępny.",
            status_code=503,
            media_type="text/plain",
        )
    return Response(
        content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; form-action 'self'; base-uri 'none'",
        },
    )


@server.get("/", include_in_schema=False)
@server.get("/terminal/", include_in_schema=False)
def terminal() -> Response:
    return asset_response("terminal.txt", "text/html")


@server.get("/terminal/static/styles.css", include_in_schema=False)
def stylesheet() -> Response:
    return asset_response("styles.txt", "text/css")


@server.get("/terminal/static/controls.js", include_in_schema=False)
def controls() -> Response:
    return asset_response("controls.txt", "application/javascript")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(server, host="0.0.0.0", port=8080, access_log=False)
