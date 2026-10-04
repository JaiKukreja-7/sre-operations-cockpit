import asyncio
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from cockpit.models import DemoControl


def create_app():
    app = FastAPI(title="Local Synthetic Demo", version="0.1.0")
    app.state.control = DemoControl()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/mode", response_model=DemoControl)
    def mode():
        return app.state.control

    @app.put("/mode", response_model=DemoControl)
    def change_mode(control: DemoControl):
        app.state.control = control
        return control

    @app.get("/probe", response_class=PlainTextResponse)
    async def target():
        control = app.state.control.model_copy()
        if control.mode == "Slow":
            await asyncio.sleep(control.delay_seconds)
        if control.mode == "Failing":
            return PlainTextResponse("synthetic demo failure", status_code=500)
        return PlainTextResponse("synthetic demo OK", status_code=200)

    return app


app = create_app()
