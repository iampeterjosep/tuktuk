from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, monitor, driver, queue, lines, drivers

app = FastAPI(
    title="Tuktuk Queue API",
    description=(
        "Privileged business-logic layer sitting alongside Supabase. "
        "Flutter reads queue state and subscribes to realtime updates "
        "directly via Supabase; it calls this API only for the actions "
        "that need server-side rules enforced (join, reorder, overtake, "
        "status changes, void, and line/driver management)."
    ),
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(monitor.router)
app.include_router(driver.router)
app.include_router(queue.router)
app.include_router(lines.router)
app.include_router(drivers.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
