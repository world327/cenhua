# -*- coding: utf-8 -*-
"""Jinja2 + HTMX 四页（M3b 任务 2/3/4/5）— 契约 §3.6。

薄适配：页面 = service 函数调用 + 模板渲染，零业务逻辑。
鉴权：与 API 同一 security.check_token（fail-closed）；通过后落
httpOnly cookie（EventSource 无法带 header，API 侧同源 cookie 回退）。
创造页**只读 digest**（F4；草稿编辑移 M4）。
"""
import html
import io
import os
import re
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import List

from cenhua_service import core
from cenhua_service.webui import security

COOKIE = "cenhua_token"
VSWITCH_COOKIE = "cenhua_vault"     # 多库切换 cookie（M5-3）
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "templates")
MAX_TEXT_PREVIEW = 200_000          # 全文页预览上限（字符）


@dataclass
class UrlIngestResult:
    """ingest_url 的 service 面包装：stdout/stderr 捕获成 lines，
    供 channel_job 逐行 emit -> SSE。"""
    status: str = "failed"
    lines: List[str] = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    rc: int = 1
    error: str = ""


def ingest_url_job(vault, url, use_render=True):
    """长任务体：捕获 CLI 面输出，返回带 lines 的 dataclass。"""
    import m_web_cli

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        status = m_web_cli.ingest_url(vault, url, use_render=use_render)
    lines = (buf_out.getvalue() + buf_err.getvalue()).splitlines()
    return UrlIngestResult(
        status=status, lines=lines, rc=0 if status != "failed" else 1,
        error="" if status != "failed" else "ingest failed")


# ------------------------------------------------------------ 页面工具 --
def _env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR),
                      autoescape=select_autoescape(["html"]))
    env.filters["mermaid_label"] = _mermaid_label
    import json as _json

    def _tojson(v):
        """脚本内嵌 JSON（Markup 免二次转义；</ 转义防提前闭合 script）。"""
        from markupsafe import Markup
        return Markup(_json.dumps(v, ensure_ascii=False)
                      .replace("</", "<\\/"))

    env.filters["tojson"] = _tojson
    return env


def _mermaid_label(text):
    """Mermaid 节点标签清洗：去破坏语法的字符。"""
    return re.sub(r'["\[\]{}()<>`|]', "", str(text))[:40]


def _rv(base, request):
    """请求级 vault（M5-3 多库）：?vault= > cookie > 启动库。

    页面侧非法名安全回落启动库（cookie 仅由 /vault/switch 校验后写入，
    正常情况恒合法；库被删等残留场景回落保证页面可用）。
    API 侧 ?vault= 非法名由 api._rv 报 400。
    """
    name = (request.query_params.get("vault")
            or request.cookies.get(VSWITCH_COOKIE, "")).strip()
    if not name or name == base.name:
        return base
    import m_lib as L
    return L.Vault(name) if name in L.list_vaults() else base


def _authed(vault, request):
    return security.check_token(vault, request.cookies.get(COOKIE, ""))


def _redirect_login():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/login", status_code=303)


def _md_to_html(text):
    """digest markdown -> 受限 HTML（去 script / on* 属性，本地模型产出仍消毒）。"""
    import markdown as md
    body = md.markdown(text, extensions=["tables", "fenced_code"])
    body = re.sub(r"(?is)<script.*?</script>", "", body)
    body = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", body)
    return body


# ------------------------------------------------------------ 路由组装 --
def build_pages(vault):
    from fastapi import APIRouter, Form, Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    from cenhua_service import docmeta as DM
    from cenhua_service import jobs as J
    from cenhua_service import tier as T

    router = APIRouter()
    env = _env()

    def render(tpl_name, request, **ctx):
        if not _authed(vault, request):
            return _redirect_login()
        tpl = env.get_template(tpl_name)
        rv = _rv(vault, request)
        st = core.stats(rv)
        import m_lib as L
        return HTMLResponse(tpl.render(
            stats=st, page=tpl_name.split(".")[0], version=_version(),
            vault_name=rv.name, vaults=L.list_vaults(),
            request=request, **ctx))

    def _version():
        import m_lib as L
        return L.VERSION

    # ------------------------------------------------------ 登录 / 登出 --
    @router.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, bad: int = 0):
        if _authed(vault, request):
            return RedirectResponse("/ingest", status_code=303)
        has_token = bool(security.resolve_token(vault))
        return HTMLResponse(env.get_template("login.html").render(
            bad=bad, has_token=has_token, version=_version()))

    @router.post("/login")
    def login(token: str = Form(""), next: str = Form("/ingest")):
        resp = RedirectResponse(next if next.startswith("/") else "/ingest",
                                status_code=303)
        if security.check_token(vault, token):
            resp.set_cookie(COOKIE, token, httponly=True, samesite="lax")
            return resp
        return RedirectResponse("/login?bad=1", status_code=303)

    @router.get("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    # ------------------------------- 多库切换（M5-3）：cookie 持久化 --
    @router.post("/vault/switch")
    async def vault_switch(request: Request):
        """校验白名单后写 cenhua_vault cookie（非法名不写，静默回落）。"""
        if not _authed(vault, request):
            return _redirect_login()
        form = await request.form()
        name = (form.get("vault") or "").strip()
        nxt = form.get("next") or "/ingest"
        import m_lib as L
        nxt = nxt if nxt.startswith("/") else "/ingest"
        if name in L.list_vaults():
            resp = RedirectResponse(nxt, status_code=303)
            resp.set_cookie(VSWITCH_COOKIE, name, httponly=True,
                            samesite="lax")
            return resp
        return RedirectResponse(nxt, status_code=303)

    # ------------------------------------------------ 摄取页（任务 2） --
    @router.get("/ingest", response_class=HTMLResponse)
    def page_ingest(request: Request):
        return render("ingest.html", request)

    @router.post("/ingest/file")
    async def page_ingest_file(request: Request):
        if not _authed(vault, request):
            return _redirect_login()
        from fastapi.responses import HTMLResponse as H
        form = await request.form()
        up = form.get("file")
        if not up:
            return H("<p class='bad'>no file</p>", status_code=422)
        import m_lib as L
        safe = os.path.basename(getattr(up, "filename", "") or "upload.bin")
        rv = _rv(vault, request)
        dest = os.path.join(rv.inbox, safe)
        if os.path.exists(dest):
            root, ext = os.path.splitext(safe)
            dest = os.path.join(vault.inbox,
                                "%s.%d%s" % (root, int(time.time()), ext))
        data = await up.read()
        with open(dest, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        res = core.ingest(rv, dest)
        cls = "ok" if res.status in ("added", "dupe") else "bad"
        return H("<p class='%s'>%s: %s%s</p>" % (
            cls, html.escape(res.status), html.escape(res.name or safe),
            "" if res.status != "failed"
            else " — " + html.escape(res.error or "")))

    @router.post("/ingest/url")
    async def page_ingest_url(request: Request):
        """URL 摄取走任务通道，页面用 SSE 订阅进度（任务 2/9）。"""
        if not _authed(vault, request):
            return _redirect_login()
        from fastapi.responses import HTMLResponse as H
        form = await request.form()
        url = (form.get("url") or "").strip()
        render_flag = form.get("render") in (None, "on", "true")
        if not url:
            return H("<p class='bad'>url required</p>", status_code=422)
        spec = core.channel_job("ingest_url", ingest_url_job,
                                _rv(vault, request), url,
                                use_render=render_flag)
        handle = J.submit(spec)
        return H('<div id="log" data-job="%s" data-status-url="/api/v1/jobs/%s"'
                 ' class="joblog"></div>'
                 '<script src="/static/joblog.js"></script>'
                 % (handle.job_id, handle.job_id))

    # ------------------------------------------------ 检索页（任务 3） --
    @router.get("/search", response_class=HTMLResponse)
    def page_search(request: Request, q: str = "", mode: str = "find",
                    regex: str = "", ic: str = "on", docs: str = "",
                    derived: str = "", alldocs: str = "", limit: int = 10,
                    dry: str = "", force: str = ""):
        """检索页（M5-3 补齐 CLI 面：正则/大小写/docs 过滤 + LLM 高级参数）。"""
        rv = _rv(vault, request)
        ctx = {"q": q, "mode": mode, "hits": [], "groups": {},
               "job": "", "asked": False, "regex": regex, "ic": ic,
               "docs": docs, "derived": derived, "alldocs": alldocs,
               "limit": limit, "dry": dry, "force": force}
        if q and mode == "find":
            docsel = re.sub(r"[,\uFF0C\s]+", ",", docs.strip()).strip(",") or None
            hits = core.find(rv, [t for t in q.split() if t],
                             docs_selector=docsel, regex=bool(regex),
                             ignore_case=bool(ic))
            groups = {}
            for h in hits:                      # 按文档分组=命中+位置
                groups.setdefault((h.doc, h.name), []).append(h)
            ctx["hits"] = hits
            ctx["groups"] = groups
        if q and mode in ("query", "ask"):      # 长任务 -> handle -> SSE
            if mode == "query":
                spec = core.channel_job("query", core.query, rv, q,
                                        include_derived=bool(derived),
                                        dry=bool(dry), force=bool(force))
            else:
                spec = core.channel_job("ask", core.ask, rv, q,
                                        all_docs=bool(alldocs),
                                        limit=max(1, min(limit, 50)),
                                        dry_run=bool(dry),
                                        force=bool(force))
            handle = J.submit(spec)
            ctx["job"] = handle.job_id
            ctx["asked"] = True
        return render("search.html", request, **ctx)

    # ------------------------------------------------ 编织页（任务 4） --
    @router.get("/weave", response_class=HTMLResponse)
    def page_weave(request: Request, doc: str = ""):
        import m_lib as L
        rv = _rv(vault, request)
        docs = L.store_docs(rv)
        metas = DM.load(rv)
        rows = []
        for doc_id, d in sorted(docs.items(),
                                key=lambda kv: kv[1].get("name", "")):
            m = metas.get(doc_id) or {}
            rows.append({"doc_id": doc_id, "name": d.get("name", ""),
                         "tier": T.record_tier(vault, doc_id),
                         "tags": m.get("tags", []),
                         "note": m.get("note", "")})
        sel = None
        if doc and doc in docs:
            meta = DM.get(rv, doc)
            sel = {"doc_id": doc, "name": docs[doc].get("name", ""),
                   "tags": meta.tags, "note": meta.note}
        return render("weave.html", request, rows=rows, sel=sel)

    @router.post("/weave/meta")
    async def page_weave_meta(request: Request):
        if not _authed(vault, request):
            return _redirect_login()
        from fastapi.responses import HTMLResponse as H
        form = await request.form()
        doc = (form.get("doc") or "").strip()
        if not doc:
            return H("<p class='bad'>doc required</p>", status_code=422)
        tags = [t for t in re.split(r"[,，;；\s]+", form.get("tags") or "") if t]
        meta = DM.update(_rv(vault, request), doc, tags=tags,
                         note=form.get("note") or "")
        return H("<p class='ok'>saved: %s [%s]</p>" % (
            html.escape(doc), html.escape(", ".join(meta.tags))))

    @router.get("/relations.part", response_class=HTMLResponse)
    def relations_part(request: Request, doc: str = ""):
        """Mermaid 关联图部件（HTMX 注入）。"""
        if not _authed(vault, request):
            return _redirect_login()
        from fastapi.responses import HTMLResponse as H
        rels = core.related(_rv(vault, request), doc) if doc else []
        if not rels:
            return H("<p class='muted'>(no relations)</p>")
        lines = ["graph LR"]
        seen = set()
        for r in rels:
            a = _mermaid_label(doc)
            b = _mermaid_label(r.to_doc)
            w = "" if not r.weight else " -. %s .-" % ("%.2f" % r.weight)
            lines.append('  %s["%s"]%s--> %s["%s"]' % (a, a, w, b, b))
            if (a, b) not in seen:
                seen.add((a, b))
        return H('<pre class="mermaid">%s</pre>'
                 '<script>if(window.mermaid)mermaid.run();</script>'
                 % html.escape("\n".join(lines)))

    @router.get("/doc/{doc_id}", response_class=HTMLResponse)
    def page_doc(request: Request, doc_id: str):
        import m_lib as L
        docs = L.store_docs(_rv(vault, request))
        if doc_id not in docs:
            return render("doc.html", request, doc_id=doc_id,
                          name="", body="(not found)")
        path = os.path.join(vault.textdir, doc_id + ".txt")
        body = ""
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                body = fh.read(MAX_TEXT_PREVIEW)
        except OSError:
            body = "(text layer not available)"
        return render("doc.html", request, doc_id=doc_id,
                      name=docs[doc_id].get("name", ""), body=body)

    # ------------------------------------------- 创造页（任务 5，只读） --
    @router.get("/insights", response_class=HTMLResponse)
    def page_insights(request: Request):
        ddir = os.path.join(_rv(vault, request).works, "digests")
        files = []
        if os.path.isdir(ddir):
            for f in sorted(os.listdir(ddir), reverse=True):
                if f.endswith(".md"):
                    files.append({"name": f,
                                  "mtime": time.strftime(
                                      "%F %H:%M",
                                      time.localtime(
                                          os.path.getmtime(
                                              os.path.join(ddir, f))))})
        return render("insights.html", request, files=files)

    @router.get("/insights/{fname}", response_class=HTMLResponse)
    def page_digest(request: Request, fname: str):
        if "/" in fname or ".." in fname or not fname.endswith(".md"):
            return HTMLResponse("(bad name)", status_code=400)
        path = os.path.join(_rv(vault, request).works, "digests", fname)
        if not os.path.isfile(path):
            return HTMLResponse("(not found)", status_code=404)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        return render("digest_view.html", request, fname=fname,
                      body=_md_to_html(raw))

    # --------------------------- digest 触发（M5-3 洞察页补齐 CLI 面） --
    @router.post("/insights/generate")
    async def page_insights_generate(request: Request):
        """洞察页 digest 生成入口：走任务通道，回 SSE joblog 部件。"""
        if not _authed(vault, request):
            return _redirect_login()
        from fastapi.responses import HTMLResponse as H
        from cenhua_service import digest as DG
        form = await request.form()
        kind = form.get("kind") or "weekly"
        if kind not in ("weekly", "monthly", "quarterly"):
            return H("<p class='bad'>kind must be weekly/monthly/quarterly"
                     "</p>", status_code=422)
        spec = core.channel_job("digest", DG.digest_flow,
                                _rv(vault, request),
                                **{kind: True,
                                   "dry_run": form.get("dry_run") in
                                   ("on", "true"),
                                   "force": form.get("force") in
                                   ("on", "true")})
        handle = J.submit(spec)
        return H('<div id="log" data-job="%s" data-status-url="/api/v1/jobs/%s"'
                 ' class="joblog"></div>'
                 '<script src="/static/joblog.js"></script>'
                 % (handle.job_id, handle.job_id))

    # ------------------------------------------- 图谱页（M4b 任务 6） --
    @router.get("/graph", response_class=HTMLResponse)
    def page_graph(request: Request, entity: str = "",
                   max_nodes: int = 80):
        """力导向图画布；数据走 GET /api/v1/graph（同 cookie 鉴权）。"""
        return render("graph.html", request, entity=entity,
                      max_nodes=min(max(1, max_nodes), 300))

    # ---------------------------------------- 草稿页（M4b 任务 11） ----
    @router.get("/drafts", response_class=HTMLResponse)
    def page_drafts(request: Request):
        from cenhua_service import draft as D
        groups, cur = [], None
        for r in D.list_drafts(_rv(vault, request)):
            if not cur or cur["slug"] != r["slug"]:
                cur = {"slug": r["slug"], "topic": r["topic"], "rows": []}
                groups.append(cur)
            cur["rows"].append(r)
        for g in groups:                       # 最新版在前（编辑入口用）
            g["latest"] = g["rows"][-1]
        return render("drafts.html", request, groups=groups)

    @router.post("/drafts/generate")
    async def page_draft_generate(request: Request):
        """草稿列表页的生成入口：走任务通道，回 SSE joblog 部件。"""
        if not _authed(vault, request):
            return _redirect_login()
        from fastapi.responses import HTMLResponse as H
        from cenhua_service import draft as D
        form = await request.form()
        topic = (form.get("topic") or "").strip()
        if not topic:
            return H("<p class='bad'>topic required</p>", status_code=422)
        spec = core.channel_job("draft", D.draft_flow,
                                _rv(vault, request), topic=topic,
                                dry_run=form.get("dry_run") in
                                ("on", "true"),
                                force=form.get("force") in ("on", "true"))
        handle = J.submit(spec)
        return H('<div id="log" data-job="%s" data-status-url="/api/v1/jobs/%s"'
                 ' class="joblog"></div>'
                 '<script src="/static/joblog.js"></script>'
                 % (handle.job_id, handle.job_id))

    @router.get("/drafts/{fname}", response_class=HTMLResponse)
    def page_draft_edit(request: Request, fname: str):
        from cenhua_service import draft as D
        out = D.detail(_rv(vault, request), fname)
        if out.get("rc") != 0:
            return HTMLResponse("(draft not found)", status_code=404)
        return render("draft_edit.html", request, d=out)

    # ------------------------------------------------------------ 首页 --
    @router.get("/")
    def home():
        return RedirectResponse("/ingest", status_code=303)

    return router
