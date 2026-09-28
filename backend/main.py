from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, serving
from .live import scheduler
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    serving.state()  # load the current data version before the first request
    db.init()
    tasks = scheduler.start()  # inbox watcher + news scout; LIVE_JOBS=0 turns them off
    yield
    await scheduler.stop(tasks)


app = FastAPI(title="PAIMANA Radar backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
