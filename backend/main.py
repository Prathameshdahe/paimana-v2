import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm import rag, router as chat_router

from . import db, serving
from .live import scheduler
from .routes import router

log = logging.getLogger(__name__)


def _warm_chat() -> None:
    """The assistant's first question should not wait: the router's vocabulary now, and (with the live jobs on) the
    search index, loaded or rebuilt in its own background thread (llm/rag.py ensure_index)."""
    try:
        chat_router.vocab()
        if scheduler.enabled():
            rag.ensure_index(background=True)
    except Exception:  # noqa: BLE001 - a failed warm-up only means a slower first question
        log.exception("chat warm-up failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    serving.state()  # load the current data version before the first request
    db.init()
    tasks = scheduler.start()  # inbox watcher + news scout; LIVE_JOBS=0 turns them off
    threading.Thread(target=_warm_chat, name="chat-warmup", daemon=True).start()
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
