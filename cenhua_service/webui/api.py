# -*- coding: utf-8 -*-
"""/api/v1/* 局域网 API（M3b 任务 6/9/10）。

薄适配：端点 = service 函数调用 + dataclass 序列化，零业务逻辑。
长任务（query/ask/digest）走 M3a 任务通道：POST 返回 JobHandle，
进度经 SSE（job_status 增量协议的另一适配）或 JSON 轮询获取。
鉴权/限流依赖由 app.py 注入（security.check_token / RateLimiter）。
"""
import asyncio
import dataclasses
import json
import os

from cenhua_service import core
from cenhua_service import jobs as J
from cenhua_service.webui import security


def to_json(obj):
    """dataclass / list[dataclass] / 原值 -> JSON 可序列化对象。"""
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [to_json(o) for o in obj]
    return obj


def err(status, message, detail=""):
    """统一错误响应形态（契约 §3.6）。"""
    return {"error": message, "detail": detail, "schema_version": 1}


def build_router(vault):
    """组装 /api/v1 路由。只挂 service 函数；fastapi 延迟导入。"""
    from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
    from fastapi.responses import StreamingResponse

    router = APIRouter(prefix="/api/v1")

    # ---- 鉴权依赖：X-Cenhua-Token / Bearer / 同源 cookie（fail-closed） --
    def require_token(request: Request):
        provided = request.headers.get("x-cenhua-token", "")
        if not provided:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()
        if not provided:
            # EventSource 不能带自定义 header：页面登录后走同源 cookie 回退
            provided = request.cookies.get("cenhua_token", "")
        if not security.check_token(vault, provided):
            raise HTTPException(status_code=401,
                                detail=err(401, "invalid or missing token",
                                           "set CENHUA_API_TOKEN and send "
                                           "X-Cenhua-Token header"))
        return provided

    # ---- 限流依赖：滑动窗口，超限 429 ----------------------------------
    def require_rate(request: Request):
        limiter = getattr(request.app.state, "limiter", None)
        if limiter is not None:
            key = request.client.host if request.client else "local"
            if not limiter.allow(key):
                raise HTTPException(
                    status_code=429,
                    detail=err(429, "rate limit exceeded",
                               "retry after %ds" % limiter.retry_after(key)),
                    headers={"Retry-After": str(limiter.retry_after(key))})
        return True

    guard = [Depends(require_token), Depends(require_rate)]

    # ---------------------------------------------------------- ingest --
    @router.post("/ingest", dependencies=guard)
    def api_ingest(file: UploadFile = File(...)):
        """multipart 落 inbox（唯一用户可见入口）再走标准摄取。"""
        safe = os.path.basename(file.filename or "upload.bin")
        dest = os.path.join(vault.inbox, safe)
        if os.path.exists(dest):        # inbox 同名会覆盖原件，加时间戳避让
            root, ext = os.path.splitext(safe)
            dest = os.path.join(vault.inbox,
                                "%s.%d%s" % (root, int(__import__("time").time()), ext))
        data = file.file.read()
        with open(dest, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())       # agent/引擎读前文件可见性（flush+fsync）
        res = core.ingest(vault, dest)
        body = to_json(res)
        if res.status == "failed":
            raise HTTPException(status_code=422,
                                detail=err(422, res.error or "ingest failed",
                                           json.dumps(body, ensure_ascii=False)))
        return body

    # ------------------------------------------------------- documents --
    @router.get("/documents", dependencies=guard)
    def api_documents():
        import m_lib as L
        from cenhua_service import tier as T
        docs = L.store_docs(vault)
        have, _missing, _empty = L.text_status(vault)
        out = []
        for doc_id, d in sorted(docs.items(),
                                key=lambda kv: kv[1].get("name", "")):
            out.append({"doc_id": doc_id, "name": d.get("name", ""),
                        "stored_as": d.get("stored_as", ""),
                        "text_layer": doc_id in have,
                        "tier": T.record_tier(vault, doc_id)})
        return {"documents": out, "total": len(out), "schema_version": 1}

    @router.get("/stats", dependencies=guard)
    def api_stats():
        return to_json(core.stats(vault))

    # ----------------------------------------------------------- find --
    @router.post("/find", dependencies=guard)
    async def api_find(request: Request):
        body = await request.json()
        terms = body.get("terms") or []
        if isinstance(terms, str):
            terms = [terms]
        if not terms:
            raise HTTPException(status_code=422,
                                detail=err(422, "terms required"))
        hits = core.find(vault, terms,
                         docs_selector=body.get("docs"),
                         regex=bool(body.get("regex")),
                         ignore_case=bool(body.get("ignore_case", True)))
        return {"hits": to_json(hits), "total": len(hits),
                "schema_version": 1}

    # ------------------------------------------- 长任务三兄弟 -> handle --
    def _submit(spec):
        handle = J.submit(spec)
        return {"job": handle.to_dict(),
                "events_url": "/api/v1/jobs/%s" % handle.job_id,
                "status_url": "/api/v1/jobs/%s/status" % handle.job_id,
                "schema_version": 1}

    @router.post("/query", dependencies=guard)
    async def api_query(request: Request):
        body = await request.json()
        q = (body.get("question") or "").strip()
        if not q:
            raise HTTPException(status_code=422,
                                detail=err(422, "question required"))
        spec = core.channel_job("query", core.query, vault, q,
                                include_derived=bool(body.get("include_derived")),
                                dry=bool(body.get("dry_run")),
                                force=bool(body.get("force")))
        return _submit(spec)

    @router.post("/ask", dependencies=guard)
    async def api_ask(request: Request):
        body = await request.json()
        q = (body.get("question") or "").strip()
        if not q:
            raise HTTPException(status_code=422,
                                detail=err(422, "question required"))
        spec = core.channel_job("ask", core.ask, vault, q,
                                doc=body.get("doc"),
                                all_docs=bool(body.get("all_docs")),
                                limit=int(body.get("limit", 10)),
                                dry_run=bool(body.get("dry_run")),
                                force=bool(body.get("force")))
        return _submit(spec)

    @router.post("/digest", dependencies=guard)
    async def api_digest(request: Request):
        from cenhua_service import digest as D
        body = await request.json()
        # API JSON 面 -> digest_flow kwargs（与 digest.parse_cli 同语义）
        kw = {"weekly": bool(body.get("weekly")),
              "monthly": bool(body.get("monthly")),
              "quarterly": bool(body.get("quarterly")),
              "dry_run": bool(body.get("dry_run")),
              "force": bool(body.get("force")),
              "since": body.get("since"),
              "max_cost": body.get("max_cost")}
        spec = core.channel_job("digest", D.digest_flow, vault, **kw)
        return _submit(spec)

    # ------------------------------------------------------- relations --
    @router.get("/relations", dependencies=guard)
    def api_relations(doc: str = Query(..., min_length=1)):
        rels = core.related(vault, doc)
        return {"doc": doc, "relations": to_json(rels),
                "total": len(rels), "schema_version": 1}

    # ------------------------------------------------- docmeta（编织页） --
    @router.get("/docmeta", dependencies=guard)
    def api_docmeta_get(doc: str = Query(..., min_length=1)):
        from cenhua_service import docmeta as DM
        return to_json(DM.get(vault, doc)) | {"schema_version": 1}

    @router.post("/docmeta", dependencies=guard)
    async def api_docmeta_post(request: Request):
        from cenhua_service import docmeta as DM
        body = await request.json()
        doc = (body.get("doc") or "").strip()
        if not doc:
            raise HTTPException(status_code=422, detail=err(422, "doc required"))
        meta = DM.update(vault, doc, tags=body.get("tags"),
                         note=body.get("note"))
        return to_json(meta) | {"schema_version": 1}

    # ----------------------------------------------- 任务通道：轮询面 --
    def _handle_or_404(job_id):
        try:
            return J.JobHandle(job_id=job_id, kind="")
        except KeyError:
            raise HTTPException(status_code=404,
                                detail=err(404, "unknown job"))

    @router.get("/jobs/{job_id}/status", dependencies=guard)
    def api_job_status(job_id: str, cursor: int = Query(0, ge=0)):
        st = J.job_status(_handle_or_404(job_id), cursor)
        return to_json(st)

    @router.get("/jobs/{job_id}/result", dependencies=guard)
    def api_job_result(job_id: str):
        handle = _handle_or_404(job_id)
        try:
            result = J.job_result(handle)
        except J.JobNotDone:
            raise HTTPException(status_code=409,
                                detail=err(409, "job not finished"))
        except (J.JobFailed, J.JobStale) as exc:
            raise HTTPException(status_code=410 if isinstance(exc, J.JobStale)
                                else 500,
                                detail=err(500, str(exc)))
        return to_json(result)

    # ------------------------------------------- SSE 薄适配（任务 9） --
    @router.get("/jobs/{job_id}", dependencies=guard)
    async def api_job_events(request: Request, job_id: str,
                             cursor: int = Query(0, ge=0)):
        """job_status 增量协议 -> SSE 事件流。

        事件：chunk / progress / done / failed / aborted / heartbeat。
        断线重连：客户端带 Last-Event-ID 或 ?cursor= 重订阅，幂等重放。
        空闲 heartbeat_s 发心跳注释行（SSE 长连接防挂起三件套之一）。
        """
        handle = _handle_or_404(job_id)
        heartbeat_s = float(getattr(request.app.state, "heartbeat_s", 10.0))

        def _sse(event, data):
            return "event: %s\ndata: %s\n\n" % (
                event, json.dumps(data, ensure_ascii=False))

        async def _stream():
            cur = cursor
            idle = 0.0
            while True:
                if await request.is_disconnected():
                    return
                st = J.job_status(handle, cur)
                for chunk in st.chunks:
                    yield _sse("chunk", {"cursor": cur, "text": chunk})
                    cur += 1
                if st.chunks or st.state in (J.DONE, J.FAILED, J.ABORTED):
                    idle = 0.0
                    yield _sse("progress", {"state": st.state,
                                            "progress": st.progress,
                                            "cursor": cur, "cost": st.cost})
                if st.state == J.DONE:
                    yield _sse("done", {"cursor": cur, "cost": st.cost})
                    return
                if st.state == J.FAILED:
                    yield _sse("failed", {"error": st.error})
                    return
                if st.state == J.ABORTED:
                    yield _sse("aborted", {"reason": st.reason})
                    return
                await asyncio.sleep(0.25)
                idle += 0.25
                if idle >= heartbeat_s:
                    idle = 0.0
                    yield ": heartbeat\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # ------------------------------------------- 图谱（M4b 任务 6/16） --
    @router.get("/graph", dependencies=guard)
    def api_graph(entity: str = Query("", max_length=80),
                  max_nodes: int = Query(80, ge=1, le=500)):
        from cenhua_service import graph as G
        return G.view(vault, entity_kw=entity or None, max_nodes=max_nodes)

    # ------------------------------------------- 草稿（M4a-7 / M4b-16） --
    @router.post("/draft", dependencies=guard)
    async def api_draft(request: Request):
        from cenhua_service import draft as D
        body = await request.json()
        topic = (body.get("topic") or "").strip()
        if not topic:
            raise HTTPException(status_code=422,
                                detail=err(422, "topic required"))
        mode = body.get("mode") or "new"
        if mode not in ("new", "extend", "rewrite"):
            raise HTTPException(status_code=422,
                                detail=err(422, "mode must be new/extend/"
                                               "rewrite"))
        spec = core.channel_job("draft", D.draft_flow, vault, topic=topic,
                                mode=mode,
                                section=str(body.get("section") or ""),
                                version=str(body.get("version") or ""),
                                top=int(body.get("top", D.MAX_DOCS)),
                                dry_run=bool(body.get("dry_run")),
                                force=bool(body.get("force")),
                                max_cost=body.get("max_cost"),
                                rid=str(body.get("rid") or ""))
        return _submit(spec)

    # ---------------------------- 草稿编辑三件套（M4b 任务 11 数据面） --
    @router.get("/drafts", dependencies=guard)
    def api_drafts(topic: str = Query("", max_length=120)):
        from cenhua_service import draft as D
        rows = D.list_drafts(vault, topic=topic)
        return {"drafts": [{k: r[k] for k in
                            ("file", "slug", "topic", "version", "date",
                             "mode", "rid")} for r in rows],
                "total": len(rows), "schema_version": 1}

    @router.get("/drafts/{fname}", dependencies=guard)
    def api_draft_detail(fname: str):
        from cenhua_service import draft as D
        out = D.detail(vault, fname)
        if out.get("rc") != 0:
            raise HTTPException(status_code=404,
                                detail=err(404, "draft not found", fname))
        return out

    @router.put("/drafts/{fname}", dependencies=guard)
    async def api_draft_save(request: Request, fname: str):
        from cenhua_service import draft as D
        body = await request.json()
        text = body.get("text")
        if not isinstance(text, str):
            raise HTTPException(status_code=422,
                                detail=err(422, "text required"))
        out = D.save_draft(vault, fname, text,
                           do_verify=bool(body.get("verify", True)))
        if out["rc"] == 2:
            raise HTTPException(status_code=404,
                                detail=err(404, "draft not found", fname))
        return out | {"schema_version": 1}

    @router.get("/drafts/{fname}/excerpt", dependencies=guard)
    def api_draft_excerpt(fname: str, doc: str = Query("", max_length=80),
                          page: str = Query(..., min_length=1),
                          snippet: str = Query(..., min_length=1)):
        """引文穿透预览：doc 缺省用 fname（detail 里 doc 已是补全后的完整 id）。"""
        from cenhua_service import draft as D
        return D.page_excerpt(vault, doc or fname, page, snippet)

    @router.get("/drafts/-/diff", dependencies=guard)
    def api_draft_diff(a: str = Query(..., min_length=1),
                       b: str = Query(..., min_length=1)):
        from cenhua_service import draft as D
        out = D.diff_files(vault, a, b)
        if out["rc"] == 2:
            raise HTTPException(status_code=404,
                                detail=err(404, "draft not found",
                                           "%s / %s" % (a, b)))
        return out

    return router
