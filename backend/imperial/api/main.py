"""FastAPI app — wires bootstrap + routes + SSE stream.

Run:  uvicorn imperial.api.main:app --reload
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from imperial.api.bootstrap import AppContext, build_context
from imperial.api.env import load_env
from imperial.api.events import EventBroadcaster
from imperial.api import routes


def create_app(
    *,
    db_path: Path | str | None = None,
    institution_path: Path | str | None = None,
    seed_posts: bool = True,
    enable_scheduler: bool | None = None,
    load_env_file: bool = True,
) -> FastAPI:
    if load_env_file:
        load_env()  # backend/.env → os.environ (no-op if absent)
    backend_root = Path(__file__).resolve().parent.parent.parent  # backend/
    ctx = build_context(
        db_path=db_path,
        institution_path=institution_path or backend_root / "institutions" / "sanguan-jiuqing.yaml",
        seed_posts=seed_posts,
        enable_scheduler=enable_scheduler,
    )
    broadcaster = EventBroadcaster()
    routes.bind(ctx, broadcaster)
    # agent-produced memorials (auto-submitted by the scheduler) must reach
    # the frontend via SSE — wire the broadcaster into MemorialService
    if ctx.memorials.on_submit is None:
        ctx.memorials.on_submit = lambda row: asyncio.get_event_loop().create_task(
            broadcaster.broadcast("memorial", row)
        )

    app = FastAPI(title="Imperial Court", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local single-machine dev
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.ctx = ctx
    app.include_router(routes.router)

    # ── agent network lifecycle ────────────────────────────
    _pump_task: asyncio.Task | None = None

    @app.on_event("startup")
    async def _start_scheduler() -> None:
        nonlocal _pump_task
        if ctx.scheduler is not None:
            await ctx.scheduler.start()
            _pump_task = asyncio.create_task(ctx.scheduler.pump())
        # give every office a persona (background; template fallback if no LLM)
        await asyncio.to_thread(ctx.ensure_personas)

    @app.on_event("shutdown")
    async def _stop_scheduler() -> None:
        nonlocal _pump_task
        if _pump_task is not None:
            _pump_task.cancel()
            _pump_task = None

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
        return {
            "status": "ok",
            "institution": ctx.institution.id,
            "posts": len(ctx.institution.posts),
            "scheduler": ctx.scheduler is not None,
        }

    return app


app = create_app()
