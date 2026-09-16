"""Production entrypoint that keeps the existing ClipVideo API and adds Social Hub."""
from main import app
from social_api import router as social_router

app.include_router(social_router)
