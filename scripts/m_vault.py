#!/usr/bin/env python3
"""m_vault.py — CENHUA vault lifecycle: init / list / status / doctor / rm.

A vault is one project or domain ("contract-vault", "reading-notes", ...).
Layout and rules live in m_lib.Vault. Nothing here ever talks to an LLM.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import m_lib as L  # noqa: E402
from cenhua_service import tier as TG  # noqa: E402

DEFAULT_CFG = {
    "name": "",
    "title": "",
    "created": "",
    "cenhua": L.VERSION,
    "store": "engine",
    "max_llm_calls": "8",
    "model": "openai/gpt-4o-mini",
    "base": "",
    "vision_model": "",
    "embed_model": "",
}


# ------------------------------------------------------------------- init ---
def init(name, title="", interactive=True, defaults=False):
    """Create the vault skeleton. The LLM gateway is NOT asked here —
    that is the single one-time decision owned by m_setup.configure_gateway
    (triggered by `cenhua setup` or a plain `cenhua init`)."""
    name = (name or "default").strip()
    if (not name or name.startswith(".") or "/" in name or os.sep in name
            or name in (".", "..")):
        L.die(f"invalid vault name: {name!r} "
              f"(letters/digits/-/_ only; use --home for paths)")
    v = L.Vault(name, must_exist=False)
    if os.path.isfile(v.yaml):
        L.say(f"= vault '{name}' already exists at {v.root}")
    else:
        cfg = dict(DEFAULT_CFG)
        cfg.update(name=name, title=title or name,
                   created=time.strftime("%F %T"))
        if interactive and not defaults and sys.stdin.isatty():
            cfg["title"] = L.ask_user("One-line description", cfg["title"])
        v.create_dirs()
        v.save_cfg(cfg)
        L.say(f"+ created vault '{name}'")
    L.say(f"  root    : {v.root}")
    L.say(f"  INBOX   : {v.inbox}   <-- drop files here")
    L.say(f"  works   : {v.works}")
    L.say(f"  store   : {v.store}")
    cfg = v.cfg()
    L.say(f"  secrets : API keys are read from env only "
          f"(PI_KEY{', PI_VISION_KEY, PI_EMBED_KEY' if cfg.get('vision_model') or cfg.get('embed_model') else ''}) "
          f"— never stored on disk")

    cfgs = L.load_config()
    cfgs.setdefault("vaults", [])
    if name not in cfgs["vaults"]:
        cfgs["vaults"].append(name)
    if not cfgs.get("default_vault"):
        cfgs["default_vault"] = name
    L.save_config(cfgs)
    L.say(f"  default : {cfgs['default_vault']}"
          f"   (switch: cenhua use <name>; one-off: --vault <name>)")


def use(name):
    L.Vault(name)  # validates existence
    cfg = L.load_config()
    cfg["default_vault"] = name
    L.save_config(cfg)
    L.say(f"+ default vault -> {name}")


def rm(name, yes=False):
    import shutil
    v = L.Vault(name)
    if not yes:
        L.say(f"about to delete vault '{name}' ({v.root}) INCLUDING all indexed "
              f"documents and archived originals.")
        if L.ask_user("Type the vault name to confirm") != name:
            L.die("aborted", code=1)
    shutil.rmtree(v.root)
    cfg = L.load_config()
    cfg["vaults"] = [x for x in cfg.get("vaults", []) if x != name]
    if cfg.get("default_vault") == name:
        cfg["default_vault"] = cfg["vaults"][0] if cfg["vaults"] else "default"
    L.save_config(cfg)
    L.say(f"- deleted vault '{name}'")


# ------------------------------------------------------------------- list ---
def listing():
    names = L.list_vaults()
    if not names:
        L.say("(no vaults — run: cenhua init)")
        return
    cur = L.default_vault()
    L.say(f"{'VAULT':<20} {'DOCS':>5} {'SIZE':>8}  {'INBOX':>5}  DESCRIPTION")
    for n in names:
        v = L.Vault(n)
        docs = L.store_docs(v)
        size = 0
        for root, _, files in os.walk(v.root):
            if os.sep + "inbox" + os.sep in root + os.sep:
                continue
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        inbox = L.pending(v.inbox)
        mark = "*" if n == cur else " "
        L.say(f"{mark}{n:<19} {len(docs):>5} {L.human_size(size):>8}  "
              f"{len(inbox):>5}  {v.cfg().get('title', '')}")
    L.say(f"\n* = default (cenhua use <name> | CENHUA_VAULT=<name> | --vault <name>)")


# ----------------------------------------------------------------- status ---
def status(v):
    cfg = v.cfg()
    docs = L.store_docs(v)
    have, missing, empty = L.text_status(v)
    inbox = [f for f in os.listdir(v.inbox) if os.path.isfile(os.path.join(v.inbox, f))] \
        if os.path.isdir(v.inbox) else []
    fail = os.listdir(v.failed) if os.path.isdir(v.failed) else []
    cost = L.read_json(os.path.join(v.meta, "llm_calls.json"), {"total": 0}) or {"total": 0}

    L.say(f"vault      : {v.name} — {cfg.get('title', '')}")
    L.say(f"root       : {v.root}")
    L.say(f"storage    : {L.HOME}  ({L.HOME_SOURCE})")
    L.say(f"inbox      : {len(inbox)} pending"
          + (f"  -> run: cenhua add --inbox" if inbox else ""))
    if fail:
        L.say(f"FAILED     : {len(fail)} file(s) in {v.failed}  -> check logs/")
    L.say(f"documents  : {len(docs)} indexed")
    for doc_id, d in sorted(docs.items(), key=lambda kv: kv[1].get("name", "")):
        text = "text✓" if doc_id in have else ("text EMPTY" if doc_id in empty else "text MISSING")
        arch = "archived✓" if d.get("stored_as") and os.path.exists(d.get("stored_as", "")) \
            else "archived✗"
        L.say(f"  {doc_id[:12]:<12} {d.get('name', '')[:44]:<46} {text:<11} {arch}")
    if missing:
        L.say(f"! {len(missing)} doc(s) without text layer -> run: cenhua flatten")
    if empty:
        L.say(f"! {len(empty)} EMPTY text layer(s) (silently-blank PDF? re-ingest): "
              + ", ".join(m[:12] for m in empty))
    L.say(f"llm calls  : {cost.get('total', 0)} charged by this CLI "
          f"(cap/run: {v.max_llm_calls()})")
    env = L.build_env(v)
    gw = L.resolve_gateway(v)
    src = gw["source"] if gw else "none"
    L.say(f"llm gateway: {'ready' if L.chat_ready(env) else 'NOT configured (find/flatten stay offline)'}"
          f"  model={env.get('PI_MODEL', '-')}  via={src}")
    if os.path.isdir(v.vectors):
        try:
            import m_vectors
            m_vectors.status(v)
        except SystemExit:
            pass


# ----------------------------------------------------------------- doctor ---
def _chromium_selfcheck(timeout=15):
    """spawn chromium 无头加载 about:blank（超时 15s）。返回 (ok, note)。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto("about:blank", timeout=timeout * 1000)
                return True, ""
            finally:
                browser.close()
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def doctor(v):
    """Environment + store self-check. Exit code 0 = usable for offline mode."""
    problems, warns = [], []
    L.say(f"CENHUA {L.VERSION} doctor — vault '{v.name}'")

    L.say(f"\n[1] python & engine")
    L.say(f"  python {sys.version.split()[0]}   engine {L.ENGINE}")
    if not os.path.isdir(L.ENGINE):
        problems.append("engine directory missing")
    for need in ("pi_ingest.py", "pi_flatten.py", "pi_query.py"):
        if not os.path.isfile(os.path.join(L.ENGINE, need)):
            problems.append(f"engine/{need} missing")
    for mod in ("pageindex", "pymupdf", "markdown", "openai"):
        try:
            __import__(mod)
            L.say(f"  ✓ {mod}")
        except ImportError:
            # offline commands (find/read/status/doctor) only need pymupdf via
            # flatten; a missing LLM stack costs features, not the vault.
            if mod == "pymupdf":
                problems.append("python module 'pymupdf' not installed — "
                                "flatten/find cannot work")
            else:
                warns.append(f"python module '{mod}' not installed — ingest/ask "
                             f"disabled (offline find/read still work); "
                             f"fix: pip install -r requirements.txt")

    L.say(f"\n[2] gateway (LLM modes; offline commands don't need this)")
    env = L.build_env(v)
    if L.chat_ready(env):
        ok, detail = L.probe_models(env["PI_BASE"], env.get("PI_KEY"))
        L.say(f"  PI_BASE {env['PI_BASE']} -> {'ok' if ok else 'FAIL'}: {detail}")
        if not ok:
            warns.append("chat endpoint unreachable (vision/embedding may also fail)")
        if not env.get("PI_MODEL", "").startswith("openai/"):
            warns.append(f"PI_MODEL '{env.get('PI_MODEL')}' needs the openai/ "
                         f"prefix for LiteLLM routing")
    else:
        warns.append("PI_BASE/PI_KEY not set -> cenhua ask disabled "
                     "(find/flatten/status still work)")

    L.say(f"\n[3] images & scanned PDFs")
    import m_ocr
    if m_ocr.available():
        L.say("  local OCR (RapidOCR): on - transcription free & offline")
    else:
        L.say("  local OCR (RapidOCR): off (pip install rapidocr-onnxruntime)")
    vm = env.get("PI_VISION_MODEL")
    if vm:
        vb = env.get("PI_VISION_BASE") or env.get("PI_BASE")
        ok, detail = L.probe_models(vb, env.get("PI_VISION_KEY") or env.get("PI_KEY"))
        L.say(f"  vision fallback {vm} @ {vb} -> {'ok' if ok else 'FAIL'}: {detail}")
        if vm.startswith("openai/"):
            warns.append("PI_VISION_MODEL must be a BARE model id "
                         "(the openai/ prefix 404s on raw endpoints)")
    elif not m_ocr.available():
        warns.append("no RapidOCR and no PI_VISION_MODEL -> images/scans "
                     "will not ingest")

    L.say(f"\n[4] embeddings (optional semantic recall)")
    import m_vectors
    eb, ek, em = m_vectors.embed_config(v)
    if em:
        ok, detail = L.probe_models(eb or env.get("PI_BASE", ""), ek or env.get("PI_KEY"))
        L.say(f"  {em} @ {eb or env.get('PI_BASE')} -> {'ok' if ok else 'FAIL'}: {detail}")
    else:
        L.say("  not configured — fine, `find` + tree-navigation cover exact recall")

    L.say(f"\n[5] store integrity ({v.store})")
    docs = L.store_docs(v)
    piman = os.path.join(v.store, "manifest.json")
    if os.path.isfile(piman):
        try:
            json.load(open(piman))
            L.say(f"  ✓ manifest.json ({len(docs)} docs)")
        except ValueError:
            problems.append("manifest.json is corrupt")
    else:
        L.say("  (store empty — nothing ingested yet)")
    have, missing, empty = L.text_status(v)
    for m_ in missing:
        warns.append(f"doc {m_[:12]} has no text layer -> run `cenhua flatten`")
    for e_ in empty:
        problems.append(f"doc {e_[:12]} text layer is EMPTY — likely a silently-blank "
                        f"PDF, re-ingest the original")
    led = L.read_json(os.path.join(v.store, "ingest_manifest.json"), {}) or {}
    for d, rec in led.items():
        if not docs.get(d):
            warns.append(f"ledger row {d[:12]} has no PageIndex index (ingest died "
                         f"mid-way); original: {rec.get('stored_as') or rec.get('source')}")
    # never shadow PageIndex's own manifest name
    if os.path.exists(os.path.join(v.store, "source_map.csv")):
        L.say("  ✓ source_map.csv ledger present")

    L.say(f"\n[6] web ingestion (M2a: `cenhua add --url`)")
    import m_web
    if m_web.chromium_available():
        # 启动自检：spawn chromium 无头加载 about:blank（超时 15s）
        ok, note = _chromium_selfcheck()
        if ok:
            L.say("  chromium: on - JS rendering available")
        else:
            problems.append(f"chromium launch self-check failed: {note}")
            L.say("  chromium: PROBLEM - `cenhua add --url` will fall back to "
                  "static HTML fetch")
            L.say("  fix: sudo playwright install-deps chromium")
    else:
        warns.append("chromium not installed - `cenhua add --url` uses static "
                     "HTML fetch only (no JS rendering); fix: "
                     "cenhua setup (installs chromium)")

    L.say("\n" + "=" * 58)
    for p in problems:
        L.say(f"PROBLEM  {p}")
    for w in warns:
        L.say(f"warn     {w}")
    if not problems and not warns:
        L.say("all good — the vault is healthy")
    return 1 if problems else 0


# ---------------------------------------------------------------- sources ---
def sources(v, kw=""):
    """Where did this content come from? 三层分组渲染在 service（tier.sources_lines）。"""
    for line in TG.sources_lines(v, kw):
        L.say(line)
