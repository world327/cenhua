#!/usr/bin/env python3
"""m_setup.py — first-run bootstrap so a git/URL skill install is USE-ready.

An agent that just installed CENHUA from a GitHub link should only ever run:

    <skill-dir>/bin/cenhua setup [--vault NAME]

which (idempotently):
  1. installs the python dependencies (with the measured mirror/pypi.org split:
     pageindex ships on official PyPI only, its litellm dep stalls on mirrors),
  2. creates the default (or named) vault if none exists,
  3. prints the env-var checklist + doctor summary.

Non-interactive safe: never prompts, exits 0 when the vault is usable offline
even if the LLM stack could not be installed (find/read still work).
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402

ROOT = os.path.dirname(L.ENGINE)          # <skill>/scripts
REQ = os.path.join(os.path.dirname(ROOT), "requirements.txt")

PIP_TRIES = [
    ["-m", "pip", "install", "-q", "-r"],
    ["-m", "pip", "install", "-q", "--user", "--break-system-packages", "-r"],
]


def pip_install(args_extra=None, req=REQ):
    """Try pip with and without --user/--break-system-packages. Returns ok."""
    for base in PIP_TRIES:
        cmd = [sys.executable, *base, req, *(args_extra or [])]
        L.say("$ " + " ".join(cmd))
        if subprocess.run(cmd).returncode == 0:
            return True
        L.err("  (failed, trying next strategy...)")
    return False


def ensure_deps():
    import importlib.util
    need = {"pymupdf": "fitz", "markdown": "markdown", "pageindex": "pageindex",
            "openai": "openai", "numpy": "numpy"}
    missing = [name for name, mod in need.items() if not importlib.util.find_spec(mod)]
    if not missing:
        L.say("= python deps already present")
        return True
    L.say(f"~ installing missing deps: {', '.join(missing)}")
    if pip_install():
        return True
    # measured fallback: deps from the configured mirror, pageindex from pypi.org
    L.say("~ retry split: deps from default index, then pageindex --no-deps from pypi.org")
    deps = os.path.join(os.environ.get("TMPDIR", "/tmp"), "cenhua-deps.txt")
    if os.path.isfile(REQ):
        with open(REQ, encoding="utf-8") as f, open(deps, "w", encoding="utf-8") as g:
            for line in f:
                if not line.strip().startswith("pageindex"):
                    g.write(line)
        ok1 = pip_install(req=deps)
        ok2 = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps",
                              "--index-url", "https://pypi.org/simple", "pageindex"]
                             ).returncode == 0 \
            or subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps",
                               "--user", "--break-system-packages",
                               "--index-url", "https://pypi.org/simple", "pageindex"]
                              ).returncode == 0
        return ok1 and ok2
    return False


ENV_SNIPPET = """
  // ~/.openclaw/openclaw.json  ->  skills.entries  (add; keep existing keys)
  "cenhua": {
    "enabled": true,
    "env": {
      "PI_BASE": "https://api.example.com/v1",
      "PI_KEY": "sk-...",
      "PI_MODEL": "openai/gpt-4o-mini",
      "PI_VISION_MODEL": "",
      "PI_EMBED_MODEL": ""
    }
  }
"""


def openclaw_hint():
    L.say("\nFor OpenClaw agents, inject the gateway through the config so the")
    L.say("skill's LLM features work in every session (keys stay out of the repo):")
    L.say(ENV_SNIPPET)
    L.say("verify with:  openclaw skills check   (cenhua should be 'ready')")


# ------------------------------------------------------------- gateway -----
# PageIndex needs an LLM. The user is asked ONCE, at setup/init, which gateway
# CENHUA should use — this decision is never taken silently:
#   openclaw : reuse the local OpenClaw model config (keys stay in
#              openclaw.json, resolved live at every call, one rotation
#              updates everything)
#   env      : bring your own PI_BASE/PI_KEY/PI_MODEL
NEED_DECISION = 5


def gw_table(provs, primary):
    """Human summary of candidate gateways. Keys are NEVER shown."""
    lines = []
    prim_prov, prim_model = "", ""
    if "/" in primary:
        prim_prov, prim_model = primary.split("/", 1)
    for i, (name, p) in enumerate(sorted(provs.items()), 1):
        host = p["base"].split("//")[-1].split("/")[0]
        marks = []
        if name == prim_prov:
            marks.append(f"primary:{prim_model}")
        if p.get("vision_hint"):
            marks.append(f"vision:{p['vision_hint']}")
        models = ", ".join(p["models"][:3]) + (" ..." if len(p["models"]) > 3 else "")
        lines.append(f"    {i:>2}. {name:<14} {host:<38} [{models}]"
                     + (("  <- " + ", ".join(marks)) if marks else ""))
    return lines


def apply_openclaw(vault, provs, choice):
    """Persist `gateway: openclaw` + provider/model into vault.yaml.
    `choice` may be 'provider' or 'provider/model'. Returns (ok, message)."""
    prov, _, model = choice.partition("/")
    if prov not in provs:
        return False, f"unknown OpenClaw provider '{prov}' (see list above)"
    p = provs[prov]
    if model and model not in p["models"]:
        return False, (f"'{model}' is not listed under provider '{prov}' "
                       f"(models: {', '.join(p['models'])})")
    if not model:
        model = p["models"][0] if p["models"] else ""
    if not p["key"]:
        return False, f"provider '{prov}' has no apiKey in openclaw.json"
    cfg = vault.cfg()
    cfg.update(gateway="openclaw", openclaw_provider=prov, openclaw_model=model)
    if p.get("vision_hint"):
        cfg.setdefault("openclaw_vision", p["vision_hint"])
    vault.save_cfg(cfg)
    return True, (f"gateway = openclaw:{prov} model={model}"
                  + (f" vision={p['vision_hint']}" if p.get("vision_hint") else "")
                  + f"  (key read live from {L.openclaw_home()}/openclaw.json,"
                    " never copied)")


def confirm_required(vault, provs, primary):
    """Agent path: no decision made silently — print the exact question and
    exit NEED_DECISION so the agent relays it to the user."""
    L.err("CONFIRM REQUIRED — which LLM should CENHUA use?")
    L.err("Ingest (tree indexing) and `ask` need an LLM. Ask the user to choose:")
    L.err("")
    L.err("  1) REUSE the OpenClaw gateway found on this machine (recommended:")
    L.err("     keys stay in openclaw.json and are read live, never copied)")
    for line in gw_table(provs, primary):
        L.err(line)
    L.err("     apply:  cenhua setup --gateway openclaw:<provider>[/<model>]")
    L.err("             (default model = first listed; OpenClaw's own primary")
    L.err("              model is marked; a configured image model becomes the")
    L.err("              vision model for images/scans)")
    L.err("")
    L.err("  2) BRING YOUR OWN endpoint (CENHUA-specific gateway, env vars):")
    L.err("             export PI_BASE=... PI_KEY=*** PI_MODEL=openai/<name>")
    L.err("             cenhua setup --gateway env")
    L.err("")
    L.err(f"Nothing was changed. vault '{vault.name}' stays offline-searchable.")
    return NEED_DECISION


def pick_interactive(vault, provs, primary):
    L.say("Which LLM should CENHUA use for ingest/ask?")
    for line in gw_table(provs, primary):
        L.say(line)
    L.say("     0. none for now — I will export PI_BASE/PI_KEY myself (env)")
    raw = L.ask_user("number [1]", "1")
    if raw in ("0", "env", "manual"):
        L.say("= gateway left to environment variables")
        return 0
    try:
        name = sorted(provs)[int(raw) - 1]
    except (ValueError, IndexError):
        L.die(f"invalid choice: {raw}", code=1)
    default_model = ""
    if primary.startswith(name + "/"):
        default_model = primary.split("/", 1)[1]
    model = L.ask_user(f"model under '{name}'",
                       default_model or (provs[name]["models"][0]
                                         if provs[name]["models"] else ""))
    ok, msg = apply_openclaw(vault, provs, f"{name}/{model}" if model else name)
    if not ok:
        L.die(msg)
    L.say(f"+ {msg}")
    return 0


def configure_gateway(vault, choice=None):
    """The one-time gateway decision. Returns exit code.
    Skips when: env already provides PI_BASE+PI_KEY, or vault already decided."""
    if L.chat_ready(os.environ):
        L.say(f"= gateway from environment (PI_MODEL={os.environ.get('PI_MODEL', '?')})"
              " — env wins over any vault setting")
        return 0
    existing = vault.cfg().get("gateway", "")
    if existing:
        gw = L.resolve_gateway(vault)
        L.say(f"= gateway already decided: {existing}"
              + (f" ({gw['source']})" if gw else " (not currently resolvable)"))
        return 0

    provs = L.openclaw_providers()
    if not provs:
        L.say("~ no local OpenClaw config found (~/.openclaw/openclaw.json)")
        L.say("  gateway must come from PI_BASE/PI_KEY/PI_MODEL (offline mode")
        L.say("  keeps working without them). Re-run after exporting, or add")
        L.say("  skills.entries.cenhua.env in openclaw.json if you install it.")
        return 0

    if choice:                                   # explicit, non-interactive
        if choice in ("env", "manual", "none"):
            L.say("= gateway left to environment variables (user's choice)")
            return 0
        if not choice.startswith("openclaw"):
            L.die("--gateway expects 'env' or 'openclaw:<provider>[/<model>]'")
        choice = choice.split(":", 1)[1] if ":" in choice else ""
        ok, msg = apply_openclaw(vault, provs, choice or
                                 (primary_provider(L.openclaw_primary())
                                  or sorted(provs)[0]))
        if not ok:
            L.die(msg)
        L.say(f"+ {msg}")
        return 0

    if sys.stdin.isatty():
        return pick_interactive(vault, provs, L.openclaw_primary())
    return confirm_required(vault, provs, L.openclaw_primary())


def primary_provider(primary):
    return primary.split("/", 1)[0] if "/" in primary else ""


# ------------------------------------------------------------- location ----
# Second install-time decision, also never taken silently: WHERE the personal
# corpus lives. Data outlives the skill (updates/reinstalls must not touch it),
# so the default is ~/.cenhua, but the user may pin any writable path —
# including the skill directory itself for a fully self-contained install.
LOC_EXIT = 6


def location_line():
    return (f"storage : {L.HOME}   (source: {L.HOME_SOURCE}"
            f", {L.human_size(L.storage_size())} in use)")


def apply_home(vault_name, path):
    old, new = L.relocate(path)
    L.say(f"+ storage root = {new}  (pointer: {L.POINTER})")
    if old != new and os.path.isdir(os.path.join(old, "vaults")):
        L.say(f"  moved existing vaults from {old}/vaults"
              if os.path.isdir(os.path.join(new, "vaults")) else
              f"  (previous root {old} had vaults; merge was skipped — "
              f"destination already has a vaults/)")
    return 0


def confirm_location(vault_name, choice):
    """Returns 0 when decided, LOC_EXIT when the agent must ask the user.
    An explicit --home doubles as the relocation command: it always wins."""
    if choice:
        try:
            return apply_home(vault_name, choice)
        except OSError as e:
            L.die(f"storage path not usable: {e}")
    if L.location_decided():
        L.say(f"= storage already decided: {L.HOME} ({L.HOME_SOURCE})")
        return 0
    if sys.stdin.isatty():
        L.say("Where should CENHUA store your knowledge base?")
        L.say(f"  1. {L.DEFAULT_HOME}   (default; survives skill updates)")
        L.say(f"  2. {L.INSTALL_HOME}   (everything inside the install dir —")
        L.say("     vaults land at <install>/vaults/<name>; self-contained, but an")
        L.say("     agent skill update/reinstall may delete this tree)")
        L.say("  3. type a custom path (external disk / per-project folder...)")
        raw = L.ask_user("choice [1]", "1")
        if raw in ("2", L.INSTALL_HOME):
            path = L.INSTALL_HOME
        elif raw in ("1", ""):
            path = L.DEFAULT_HOME
        else:
            path = raw
        try:
            return apply_home(vault_name, path)
        except OSError as e:
            L.die(f"storage path not usable: {e}")
        return 0
    # agent path: explicit confirmation required, nothing written
    L.err("CONFIRM REQUIRED — where should the personal knowledge base live?")
    L.err("Ask the user to choose (this stores documents + indexes + archived")
    L.err("originals; the corpus outlives skill updates):")
    L.err("")
    L.err(f"  1) {L.DEFAULT_HOME}  (recommended default)")
    L.err(f"  2) {L.INSTALL_HOME}  (everything under the INSTALL DIR — vaults go")
    L.err("     to <install>/vaults/<name>; self-contained, but a skill update or")
    L.err("     reinstall may wipe it — only choose if the user asks for one folder)")
    L.err("  3) a custom path the user provides (external drive, synced-out folder...)")
    L.err("")
    L.err("apply with:  cenhua setup --home <path>   [--vault NAME]")
    L.err("Nothing was created yet.")
    return LOC_EXIT


def ensure_ocr():
    """Verify the local OCR backend (RapidOCR) is installed. It is a REQUIRED
    dependency for image/scan intake (see requirements.txt); if missing, tell
    the user how to install it and keep going — the vision model still works
    as a fallback, so setup never hard-fails on this."""
    import importlib.util
    for mod in ("rapidocr_onnxruntime", "rapidocr"):
        if importlib.util.find_spec(mod):
            return True
    L.say("! RapidOCR not installed — images/scans will use the vision model")
    L.say("  install it with:  pip install rapidocr-onnxruntime")
    L.say("  (it is a required dependency in requirements.txt)")
    return False


def ensure_chromium():
    """Install the Playwright chromium browser binary (M2a web ingestion).

    With root/sudo: `playwright install --with-deps chromium` (also installs
    the system libs libnss3/libatk etc. that WSL2 needs). Without permission:
    fall back to `playwright install chromium` and warn that system libs are
    missing. Idempotent: skips when chromium is already present.
    """
    import importlib.util
    if not importlib.util.find_spec("playwright"):
        L.say("! playwright not installed — `cenhua add --url` disabled")
        L.say("  install it with:  pip install playwright")
        return False
    import m_web
    if m_web.chromium_available():
        L.say("= chromium already installed")
        return True
    L.say("~ installing chromium browser binary (~150 MB, one-time)...")
    has_sudo = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
    if has_sudo:
        L.say("$ python -m playwright install --with-deps chromium")
        ok = subprocess.run([sys.executable, "-m", "playwright", "install",
                             "--with-deps", "chromium"]).returncode == 0
        if ok:
            return True
        L.err("  (--with-deps failed, trying plain install...)")
    L.say("$ python -m playwright install chromium")
    ok = subprocess.run([sys.executable, "-m", "playwright", "install",
                         "chromium"]).returncode == 0
    if not ok:
        L.err("! chromium install failed — `cenhua add --url` will fall back to")
        L.err("  static HTML fetch. Fix later with: sudo playwright install-deps chromium")
        return False
    if not has_sudo:
        L.say("! chromium installed WITHOUT system libs (no root). On WSL2 the")
        L.say("  browser may fail to launch. Fix with: sudo playwright install-deps chromium")
    return True


def feature_report(vault=None):
    env = L.build_env(vault)
    import m_ocr
    import m_web
    feats = [
        ("offline find/read/status", True),
        ("ingest + ask (needs PI_BASE/PI_KEY)",
         bool(env.get("PI_BASE") and env.get("PI_KEY"))),
        ("local OCR for images & scans (RapidOCR)", m_ocr.available()),
        ("vision fallback for images/scans (needs PI_VISION_MODEL)",
         bool(env.get("PI_VISION_MODEL"))),
        ("semantic recall (needs PI_EMBED_MODEL)", bool(env.get("PI_EMBED_MODEL"))),
        ("web rendering for add --url (chromium; static fetch fallback)",
         m_web.chromium_available()),
    ]
    L.say("\nfeatures:")
    for name, ok in feats:
        L.say(f"  {'on ' if ok else 'off'}  {name}")
    if vault is not None:
        gw = L.resolve_gateway(vault)
        if gw:
            L.say(f"\ngateway in use: {gw['source']}")
            L.say(f"  base  : {gw['base']}")
            L.say(f"  model : {gw.get('model') or '(unset)'}   key: ***")
            ok, detail = L.probe_models(gw["base"], gw.get("key") or None)
            L.say(f"  probe : {'ok — ' + detail if ok else 'UNREACHABLE: ' + detail}")
        else:
            L.say("\ngateway in use: none (offline mode only)")


def setup(vault_name=None, with_vault=True, for_openclaw=False, gateway=None,
          home=None, skip_deps=False):
    L.say(f"CENHUA {L.VERSION} setup (skill root: {os.path.dirname(ROOT)})")
    deps_ok = True if skip_deps else ensure_deps()
    if skip_deps:
        L.say("~ dependency install skipped (--skip-deps)")

    # Decision 1 of 2 at install time: WHERE the corpus lives. Must precede any
    # vault creation — the path is where everything lands.
    rc = confirm_location(vault_name, choice=home)
    if rc == LOC_EXIT:
        return rc

    v = None
    if with_vault:
        existing = L.list_vaults()
        name = vault_name or (existing[0] if existing else "default")
        if not existing:
            import m_vault
            m_vault.init(name, interactive=False, defaults=True)
        else:
            L.say(f"= vault(s) exist: {', '.join(existing)} (default: {L.default_vault()})")
        v = L.Vault(name)

    if not deps_ok:
        L.say("! LLM stack incomplete — offline mode (find/read/status) still works;")
        L.say("  fix later with: cenhua setup   (or pip install -r requirements.txt)")

    ensure_ocr()   # local OCR for images/scans; vision model stays the fallback
    ensure_chromium()  # M2a: web ingestion browser; static fetch is the fallback

    # Decision 2 of 2: which LLM gateway (never silently taken).
    if v is not None and deps_ok:
        rc = configure_gateway(v, choice=gateway)

    if for_openclaw and not (v and v.cfg().get("gateway") == "openclaw"):
        openclaw_hint()
    L.say("")
    L.say(location_line())
    feature_report(v)

    L.say(f"\ndrop files into:  {v.inbox if v else L.vault_dir('default')}/inbox")
    L.say("then:             cenhua add --inbox   &&   cenhua find <term>")
    if rc == NEED_DECISION:
        L.err("\nsetup is otherwise complete; answer the question above to")
        L.err("enable ingest/ask. Change your mind later: cenhua gateway ...")
    return rc

