"""Run the domestic payroll preview on loopback without an interactive login.

Start with: python3 -m scripts.domestic_labor_local_preview
This launcher keeps its identity and data separate from the normal application.
"""
import argparse
from http.cookies import SimpleCookie
import os
from pathlib import Path
from urllib.parse import urlsplit


class LocalDomesticIdentity:
    def __init__(self, app, session_token, port=8002):
        self.app = app
        self.session_token = session_token
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = list(scope.get("headers", []))
            host = next((value.decode("latin-1") for key, value in headers if key.lower() == b"host"), "")
            client = scope.get("client") or ("", 0)
            path = scope.get("path", "")
            domestic = path in {"/domestic-labor.html", "/labor.html", "/domestic-labor-skillhub.html", "/api/me"} or path.startswith("/api/domestic-labor/")
            referer = next((value.decode("latin-1") for key, value in headers if key.lower() == b"referer"), "")
            try:
                source = urlsplit(referer)
                from_domestic = source.scheme == "http" and source.netloc == host and source.path in {"/domestic-labor.html", "/labor.html", "/domestic-labor-skillhub.html"}
            except ValueError:
                from_domestic = False
            widget = path == "/api/workbench/announcements" or path == "/api/workbench/feedback" or path.startswith("/api/workbench/feedback/")
            domestic = domestic or (widget and from_domestic)
            if domestic and client[0] in {"127.0.0.1", "::1"} and host in self.allowed_hosts:
                cookies = SimpleCookie()
                for key, value in headers:
                    if key.lower() == b"cookie":
                        cookies.load(value.decode("latin-1"))
                cookies["sigma_session"] = self.session_token
                scope = {**scope, "headers": [
                    (key, value) for key, value in headers if key.lower() != b"cookie"
                ] + [(b"cookie", cookies.output(header="", sep=";").strip().encode("latin-1"))]}
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if any(os.environ.get(key) for key in ("VERCEL", "VERCEL_ENV", "VERCEL_URL")):
        raise RuntimeError("Local preview cannot run in a Vercel environment")
    root = Path(__file__).resolve().parents[1]
    data = root / "outputs" / "domestic-local-preview"
    # Explicit process settings take precedence over .env without editing it.
    os.environ.update({
        "SIGMA_WORKBENCH_HOME": str(data),
        "ADMIN_DATABASE_URL": f"sqlite:///{data / 'sigma_workbench.db'}",
        "DATABASE_URL": "",
        "SIGMA_DOMESTIC_LABOR_STORAGE_BACKEND": "local",
        "SIGMA_FBU_STORAGE_BACKEND": "local",
        "SIGMA_LABOR_STORAGE_BACKEND": "local",
        "SIGMA_LABOR_AUTH_REQUIRED": "1",
        "SIGMA_ENABLE_MOCK_LOGIN": "0",
        "SIGMA_HIDE_DEVELOPING_MODULES": "0",
    })
    import uvicorn
    from bonus_platform.app import app
    from bonus_platform.engine.admin_store import create_session

    token = create_session("cnPayrollAdminUser", action="local_domestic_preview")
    app.add_middleware(LocalDomesticIdentity, session_token=token, port=args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, lifespan="off")


if __name__ == "__main__":
    main()
