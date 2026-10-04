import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from cockpit.db import Store
from cockpit.models import CheckConfig, DemoControl, Policy
from cockpit.reliability import summary, timestamp

PolicyName = Literal["demo", "thirty_day"]


def create_app(db_path=None, dashboard_dir=None):
    store = Store(db_path)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="SRE Operations Cockpit", version="0.1.0", lifespan=lifespan)
    app.state.store = store

    def require_check(check_id):
        if not any(check["id"] == check_id for check in store.checks()):
            raise HTTPException(404, "Check not found")

    @app.get("/health")
    def health():
        with store.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/checks")
    def checks():
        return store.checks()

    @app.post("/api/checks", status_code=201)
    def create_check(config: CheckConfig):
        return dict(id=store.create_check(config), **config.model_dump())

    @app.put("/api/checks/{check_id}")
    def update_check(check_id: int, config: CheckConfig):
        require_check(check_id)
        store.update_check(check_id, config)
        return dict(id=check_id, **config.model_dump())

    @app.get("/api/checks/{check_id}/results")
    def results(check_id: int, limit: int = Query(100, ge=1, le=1000)):
        require_check(check_id)
        rows = store.recent(check_id, limit)
        for row in rows:
            row["scheduled_at"] = timestamp(row["scheduled_at"])
            row["completed_at"] = timestamp(row["completed_at"])
        return rows

    @app.get("/api/checks/{check_id}/summary")
    def reliability(check_id: int, policy: PolicyName = "demo"):
        require_check(check_id)
        return summary(store, check_id, policy, time.time())

    @app.get("/api/policies")
    def policies():
        return {name: store.policy(name) for name in ("demo", "thirty_day")}

    @app.put("/api/policies/{name}")
    def update_policy(name: PolicyName, policy: Policy):
        if name == "thirty_day" and policy.window_seconds != 2592000:
            raise HTTPException(422, "The thirty_day reporting window must remain thirty days")
        store.set_policy(name, policy)
        return policy

    async def demo_request(method, control=None):
        try:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=2) as client:
                response = await client.request(method, "http://127.0.0.1:8001/mode",
                                                json=control.model_dump() if control else None)
                response.raise_for_status()
                return DemoControl.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Local demo service unavailable") from exc

    @app.get("/api/demo", response_model=DemoControl)
    async def demo_mode():
        return await demo_request("GET")

    @app.put("/api/demo", response_model=DemoControl)
    async def demo_control(control: DemoControl):
        return await demo_request("PUT", control)

    dashboard = Path(dashboard_dir) if dashboard_dir is not None else Path(__file__).resolve().parent / "static" / "dashboard"
    if (dashboard / "index.html").is_file():
        # Registered last so API, /docs, and OpenAPI keep their existing routes.
        app.mount("/", StaticFiles(directory=dashboard, html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def missing_dashboard():
            return HTMLResponse("<h1>Dashboard build missing</h1><p>See README: run npm ci "
                                "and npm run build in frontend, then restart.</p>", status_code=503)
    return app


app = create_app()
