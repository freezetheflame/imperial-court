"""FastAPI app — wires bootstrap + routes + SSE stream.

Run:  uvicorn imperial.api.main:app --reload
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from imperial.api.bootstrap import AppContext, build_context
from imperial.api.events import EventBroadcaster
from imperial.api import routes


def create_app(
    *,
    db_path: Path | str | None = None,
    institution_path: Path | str | None = None,
    seed_posts: bool = True,
) -> FastAPI:
    backend_root = Path(__file__).resolve().parent.parent.parent  # backend/
    ctx = build_context(
        db_path=db_path,
        institution_path=institution_path or backend_root / "institutions" / "sanguan-jiuqing.yaml",
        seed_posts=seed_posts,
    )
    broadcaster = EventBroadcaster()
    routes.bind(ctx, broadcaster)

    app = FastAPI(title="Imperial Court", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local single-machine dev
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.ctx = ctx
    app.include_router(routes.router)

    @app.get("/api/events/stream")
    async def event_stream(request: Request) -> StreamingResponse:
        async def gen():
            async for payload in broadcaster.subscribe():
                if await request.is_disconnected():
                    break
                yield broadcaster.format_sse(payload)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "institution": ctx.institution.id, "posts": len(ctx.institution.posts)}

    return app


app = create_app()
