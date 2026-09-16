"""Production entrypoint that keeps the existing ClipVideo API and adds Social Hub."""
import os
from fastapi.responses import RedirectResponse
from main import app
from social_api import router as social_router

app.include_router(social_router)

@app.get("/social/", include_in_schema=False)
def social_ui_redirect():
    return RedirectResponse(os.getenv("PUBLIC_FRONTEND_BASE_URL", "https://clipvideo.site.je").rstrip("/") + "/social/")
