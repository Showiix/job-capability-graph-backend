from fastapi import FastAPI


def create_app() -> FastAPI:
    application = FastAPI(title="岗位能力图谱系统 API", version="0.1.0")

    @application.get("/health/live", tags=["system"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
