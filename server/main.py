"""Max WheyTV — Main application."""
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.catalog import router as catalog_router
from server.routes import router as routes_router
from server.manifest import get_manifest
from server.config import HOST, PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(15),
        limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
        follow_redirects=True,
    )
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="Max WheyTV", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_router)
app.include_router(catalog_router)


@app.get("/")
async def root():
    return RedirectResponse(url="/configure/")


@app.get("/manifest.json")
async def manifest_no_config(request):
    manifest = get_manifest()
    base = str(request.base_url)
    manifest.logo = base + "logo.png"
    return manifest


@app.get("/{config}/manifest.json")
async def manifest_with_config(request, config: str):
    from server.catalog import parse_config
    cfg = parse_config(config)
    manifest = get_manifest(cfg)
    base = str(request.base_url)
    manifest.logo = base + "logo.png"
    return manifest


app.mount("/configure", StaticFiles(directory="web", html=True), name="web")


@app.get("/logo.png")
async def get_logo():
    return FileResponse("assets/logo.png", media_type="image/png")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host=HOST, port=PORT, reload=True)
