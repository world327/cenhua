#!/usr/bin/env python3
"""m_lib.py — CENHUA shared library.

Owns: vault layout, vault config, gateway/env resolution, the bridge to the
bundled PageIndex engine (scripts/engine/), and the citation format every
query command prints.

Design rules (do not break):
  * The engine in scripts/engine/ stays byte-identical to upstream
    pageindex-rag so it can be diffed/upgraded. All integration happens HERE,
    via subprocess + PI_* env vars, never by editing engine modules.
  * No secrets are ever written to disk. vault.yaml may hold base URLs and
    model names; API keys come from the process environment only.
  * Offline commands (find/read/status/doctor) must never import or require
    the LLM stack.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "engine")
SKILL_DIR = os.path.dirname(HERE)          # <skill>/scripts -> <skill>
VERSION = "0.5.0"

# ---------------------------------------------------------- storage root ----
# Where vaults (documents, indexes, archived originals) live is a USER
# decision made once at install time — never taken silently, because the
# corpus outlives the skill install. Resolution order:
#   1. CENHUA_HOME env var            (wins; use it for ephemeral/test homes)
#   2. pointer file                   (written by `cenhua setup --home ...`)
#   3. ~/.cenhua                      (default, survives skill updates)
# Only the one-line pointer lives under the config dir, so the data can sit
# anywhere (external disk, iCloud-less path, per-project folder).
def config_dir():
    d = os.environ.get("CENHUA_CONFIG_DIR")
    if not d:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        d = os.path.join(xdg, "cenhua")
    return d


POINTER = os.path.join(config_dir(), "location")
DEFAULT_HOME = os.path.expanduser("~/.cenhua")
# "put everything in the install dir" choice: pin the SKILL root itself
# so vaults land at <skill>/vaults/<name> (no double nesting).
INSTALL_HOME = SKILL_DIR


def read_pointer():
    try:
        with open(POINTER, encoding="utf-8") as f:
            p = f.read().strip()
        return os.path.abspath(os.path.expanduser(p)) if p else ""
    except OSError:
        return ""


def resolve_home():
    """(path, source) for the storage root. Never creates anything."""
    env = os.environ.get("CENHUA_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env)), "env CENHUA_HOME"
    ptr = read_pointer()
    if ptr:
        return ptr, f"pointer {POINTER}"
    return DEFAULT_HOME, "default (not chosen yet)"


HOME, HOME_SOURCE = resolve_home()
CONFIG = os.path.join(HOME, "config.json")


def location_decided():
    """True when the user (or env) explicitly picked a storage root."""
    return bool(os.environ.get("CENHUA_HOME") or read_pointer())


def usable_dir(path):
    """Expand, create, and prove writability. Returns abspath or raises OSError."""
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(path, exist_ok=True)
    probe = os.path.join(path, ".cenhua-write-test")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    return path


def relocate(path, move_existing=True):
    """Pin the storage root and point this process at it. Existing vaults are
    carried over; on any failure nothing is destroyed."""
    global HOME, HOME_SOURCE, CONFIG
    old = HOME
    new = usable_dir(path)
    if move_existing and os.path.abspath(old) != new \
            and os.path.isdir(os.path.join(old, "vaults")):
        dst = os.path.join(new, "vaults")
        if not os.path.exists(dst):
            shutil.move(os.path.join(old, "vaults"), dst)
        # if the destination already had vaults, we keep both (no overwrite)
    os.makedirs(config_dir(), exist_ok=True)
    with open(POINTER, "w", encoding="utf-8") as f:
        f.write(new + "\n")
    HOME, HOME_SOURCE = new, f"pointer {POINTER}"
    CONFIG = os.path.join(HOME, "config.json")
    return old, new


def storage_size(root=None):
    total = 0
    for base, _, files in os.walk(root or HOME):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(base, fn))
            except OSError:
                pass
    return total

# Formats accepted by the bundled engine (pi_ingest.py).
EXTS = {
    ".pdf", ".md", ".markdown", ".txt", ".html", ".htm", ".csv",
    ".docx", ".pptx", ".xlsx", ".xls",
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
    ".eml", ".msg",               # 邮件（M1b §4.4，m_mail 展开后进引擎）
}

PAGE_RE = re.compile(r"^=== (?:PAGE (\d+)|第(\d+)页) ===$")


# ---------------------------------------------------------------- terminal --
def say(msg=""):
    print(msg, flush=True)


def err(msg):
    print(msg, file=sys.stderr, flush=True)


def die(msg, code=2):
    err(f"x {msg}")
    sys.exit(code)


def ask_user(prompt, default=""):
    try:
        raw = input(f"{prompt}{' [' + default + ']' if default else ''}: ").strip()
    except EOFError:
        raw = ""
    return raw or default


# ------------------------------------------------------------------ config --
def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(HOME, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def default_vault():
    cfg = load_config()
    name = os.environ.get("CENHUA_VAULT") or cfg.get("default_vault")
    if not name:
        known = list_vaults()
        name = "default" if "default" in known else (known[0] if known else "default")
    return name


def list_vaults():
    root = os.path.join(HOME, "vaults")
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root)
                  if os.path.isfile(os.path.join(root, d, "vault.yaml")))


# ------------------------------------------------------------ vault layout --
def vault_dir(name):
    return os.path.join(HOME, "vaults", name)


class Vault:
    """A vault = one project/domain knowledge base.

    ~/.cenhua/vaults/<name>/
      vault.yaml      config (no secrets)
      inbox/          drop zone — the only dir the user must remember
      inbox/.processed/   ingested, kept for audit
      inbox/.failed/      ingest failed, kept with the reason in logs
      engine/         PI_STORE: sources/ pdf/ docs/ text/ manifest.json ...
      works/          user/agent output (drafts, exports)
      logs/           ingest + query logs
      meta/           CENHUA-only state: dedupe index, vectors, cost ledger
    """

    def __init__(self, name=None, must_exist=True):
        self.name = name or default_vault()
        self.root = vault_dir(self.name)
        self.yaml = os.path.join(self.root, "vault.yaml")
        self.inbox = os.path.join(self.root, "inbox")
        self.processed = os.path.join(self.inbox, ".processed")
        self.failed = os.path.join(self.inbox, ".failed")
        self.store = os.path.join(self.root, "engine")
        self.sources = os.path.join(self.store, "sources")
        self.textdir = os.path.join(self.store, "text")
        self.docsdir = os.path.join(self.store, "docs")
        self.works = os.path.join(self.root, "works")
        self.logs = os.path.join(self.root, "logs")
        self.meta = os.path.join(self.root, "meta")
        self.vectors = os.path.join(self.meta, "vectors")
        if must_exist and not os.path.isfile(self.yaml):
            known = list_vaults()
            hint = (" create one with `cenhua init --vault %s`"
                    % (self.name if "default" not in known else "default"))
            die(f"vault '{self.name}' not found at {self.root};{hint}")

    def create_dirs(self):
        for d in (self.inbox, self.processed, self.failed, self.store,
                  self.works, self.logs, self.meta, self.vectors):
            os.makedirs(d, exist_ok=True)

    # ---- vault.yaml: flat "key: value" (parsed here; readable by humans) --
    def cfg(self):
        data = {}
        if os.path.isfile(self.yaml):
            for line in open(self.yaml, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()
        return data

    def save_cfg(self, data):
        os.makedirs(self.root, exist_ok=True)
        with open(self.yaml, "w", encoding="utf-8") as f:
            f.write("# CENHUA vault config — API keys are NEVER stored here.\n")
            for k, v in data.items():
                f.write(f"{k}: {v}\n")

    def setting(self, key, fallback_env=None, default=""):
        """Config resolution order: env var > vault.yaml > default."""
        if fallback_env and os.environ.get(fallback_env):
            return os.environ[fallback_env]
        return self.cfg().get(key, default)

    def max_llm_calls(self):
        try:
            return int(self.cfg().get("max_llm_calls", "8"))
        except ValueError:
            return 8

    # ------------------------------------------------------------- logging --
    def log(self, stream, text):
        os.makedirs(self.logs, exist_ok=True)
        path = os.path.join(self.logs, f"{stream}-{time.strftime('%Y%m')}.log")
        with open(path, "a", encoding="utf-8") as f:
            for line in (text if isinstance(text, list) else [text]):
                f.write(f"{time.strftime('%F %T')}\t{line}\n")


# --------------------------------------------------------- gateway / env ----
# Keys live only in the environment OR in a gateway the user explicitly chose
# (e.g. a reference to OpenClaw's own model config). CENHUA never copies a key
# to its own files: an OpenClaw gateway is RESOLVED FROM ~/.openclaw/openclaw.json
# at runtime, so one rotation updates every consumer.
CHAT_KEYS = ("PI_BASE", "PI_KEY", "PI_MODEL",
             "PI_BASE2", "PI_KEY2", "PI_MODEL2",
             "PI_VISION_BASE", "PI_VISION_KEY", "PI_VISION_MODEL",
             "PI_TIMEOUT", "PI_RETRIES", "PI_WORKERS")


def openclaw_home():
    """State dir of a local OpenClaw install, or '' when absent."""
    d = os.environ.get("OPENCLAW_STATE_DIR") or os.path.expanduser("~/.openclaw")
    return d if os.path.isfile(os.path.join(d, "openclaw.json")) else ""


def openclaw_config():
    """Parsed openclaw.json, or {} (never raises, never logs secrets)."""
    d = openclaw_home()
    if not d:
        return {}
    return read_json(os.path.join(d, "openclaw.json"), {}) or {}


def openclaw_providers(cfg=None):
    """name -> {base, key, api, models[], vision_hint}. Values come from the
    user's own OpenClaw config; `key` is returned for runtime use only and is
    never written anywhere by CENHUA."""
    cfg = cfg if cfg is not None else openclaw_config()
    out = {}
    provs = ((cfg.get("models") or {}).get("providers")) or {}
    for name, p in provs.items():
        if not isinstance(p, dict) or not p.get("baseUrl"):
            continue
        out[name] = {
            "base": p["baseUrl"],
            "key": p.get("apiKey") or "",
            "api": p.get("api") or "openai-completions",
            "models": [m.get("id") for m in (p.get("models") or [])
                       if isinstance(m, dict) and m.get("id")],
            "vision_hint": "",
        }
    # OpenClaw's own image model, when configured, is a vision-capable pick
    img = ((cfg.get("agents") or {}).get("defaults") or {}).get("imageModel") or ""
    if "/" in img:
        prov, model = img.split("/", 1)
        if prov in out:
            out[prov]["vision_hint"] = model
    return out


def openclaw_primary(cfg=None):
    """agents.defaults.model.primary as 'provider/model', or ''."""
    cfg = cfg if cfg is not None else openclaw_config()
    return (((cfg.get("agents") or {}).get("defaults") or {})
            .get("model") or {}).get("primary") or ""


def openclaw_reference(vault):
    """(provider, model, vision) when vault.yaml opts into the OpenClaw gateway."""
    cfg = vault.cfg()
    if cfg.get("gateway") != "openclaw":
        return None
    prov = cfg.get("openclaw_provider", "")
    if not prov:
        return None
    return prov, cfg.get("openclaw_model", ""), cfg.get("openclaw_vision", "")


def resolve_gateway(vault):
    """Full effective gateway for a vault WITHOUT ever printing keys:
    returns dict(base, key, model, vision, source) or None."""
    env = os.environ
    if env.get("PI_BASE") and env.get("PI_KEY"):
        return {"base": env["PI_BASE"], "key": env["PI_KEY"],
                "model": env.get("PI_MODEL", ""), "source": "env"}
    if vault is None:
        return None
    ref = openclaw_reference(vault)
    if ref:
        prov, model, vision = ref
        p = openclaw_providers().get(prov)
        if p:
            return {"base": p["base"], "key": p["key"],
                    "model": model or (p["models"][0] if p["models"] else ""),
                    "vision": vision or p.get("vision_hint", ""),
                    "api": p["api"],
                    "source": f"openclaw:{prov} (from {openclaw_home()}/openclaw.json)"}
    cfg = vault.cfg()
    if cfg.get("base"):
        return {"base": cfg["base"], "key": env.get("PI_KEY", ""),
                "model": cfg.get("model", ""), "source": "vault.yaml + env PI_KEY"}
    return None


def build_env(vault=None):
    """Environment for engine subprocesses. Resolution order:
    process env  >  vault's OpenClaw gateway reference (read live)  >
    vault.yaml non-secret defaults."""
    env = dict(os.environ)
    if vault is None:
        return env
    env["PI_STORE"] = vault.store
    cfg = vault.cfg()
    gw = resolve_gateway(vault)
    if gw and gw["source"].startswith("openclaw"):
        env.setdefault("PI_BASE", gw["base"])
        if gw["key"]:
            env.setdefault("PI_KEY", gw["key"])
        if gw.get("model"):
            # LiteLLM routing needs the openai/ prefix; vision stays bare
            m_ = gw["model"]
            env.setdefault("PI_MODEL", m_ if m_.startswith("openai/") else f"openai/{m_}")
        if gw.get("vision"):
            env.setdefault("PI_VISION_MODEL", gw["vision"])
    mapping = {
        "PI_BASE": "base", "PI_BASE2": "base2",
        "PI_MODEL": "model", "PI_MODEL2": "model2",
        "PI_VISION_BASE": "vision_base", "PI_VISION_MODEL": "vision_model",
    }
    for env_key, cfg_key in mapping.items():
        if not env.get(env_key) and cfg.get(cfg_key):
            env[env_key] = cfg[cfg_key]
    return env


def chat_ready(env=None):
    env = env or os.environ
    return bool(env.get("PI_BASE") and env.get("PI_KEY"))


def probe_models(base, key=None, timeout=8):
    """Probe an OpenAI-compatible endpoint for reachable + model list.
    Returns (ok, detail). Never raises."""
    import urllib.error
    import urllib.request
    url = base.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(4000).decode("utf-8", "replace")
        ids = re.findall(r'"id"\s*:\s*"([^"]+)"', body)
        return True, (", ".join(ids[:8]) + (" ..." if len(ids) > 8 else "")
                      if ids else "reachable")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


# --------------------------------------------------------- engine bridge ----
def run_engine(script, args, vault, capture=False, timeout=None):
    """Run a bundled engine script with this vault's PI_STORE.
    Returns (rc, stdout). Prints stdout live unless capture=True."""
    path = os.path.join(ENGINE, script)
    if not os.path.isfile(path):
        die(f"engine script missing: {path} (broken install — re-run install.sh)")
    cmd = [sys.executable, path, *[str(a) for a in args]]
    proc = subprocess.run(cmd, env=build_env(vault), cwd=ENGINE,
                          capture_output=capture, text=True, timeout=timeout)
    if capture:
        if proc.stderr:
            err(proc.stderr.rstrip())
        return proc.returncode, proc.stdout
    if proc.stderr:
        err(proc.stderr.rstrip())
    return proc.returncode, ""


# ------------------------------------------------------- index inspection --
def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def store_docs(vault):
    """doc_id -> {name, source, stored_as, sha1, ts}.

    PageIndex's manifest.json is authoritative for WHAT is indexed; the
    ingest ledger is authoritative for names + provenance. Union of both.
    """
    docs = {}
    man = read_json(os.path.join(vault.store, "manifest.json"), {}) or {}
    for doc_id, meta in (man.get("docs") or {}).items():
        docs[doc_id] = {"name": meta.get("name", ""), "doc_id": doc_id}
    led = read_json(os.path.join(vault.store, "ingest_manifest.json"), {}) or {}
    for doc_id, rec in led.items():
        docs.setdefault(doc_id, {"doc_id": doc_id})
        docs[doc_id].update({k: rec.get(k, "") for k in
                             ("name", "source", "stored_as", "sha1", "ts")})
    # server-side names carry a _<12hex>.pdf dedupe suffix — strip it
    for d in docs.values():
        d["name"] = re.sub(r"_[0-9a-f]{12}\.pdf$", "", d.get("name", ""))
    return docs


def text_pages(vault, doc_id):
    """[(page_no, text)] for a doc's flattened text layer; [] if absent."""
    path = os.path.join(vault.textdir, f"{doc_id}.txt")
    if not os.path.isfile(path):
        return []
    pages, cur, buf = [], "?", []
    for line in open(path, encoding="utf-8", errors="ignore"):
        m = PAGE_RE.match(line.strip())
        if m:
            if buf:
                pages.append((cur, "\n".join(buf).rstrip()))
            cur, buf = (m.group(1) or m.group(2)), []
        else:
            buf.append(line.rstrip("\n"))
    if buf:
        pages.append((cur, "\n".join(buf).rstrip()))
    return pages


def text_status(vault):
    """(docs_with_text, missing_ids, empty_ids)."""
    docs = store_docs(vault)
    have = {f[:-4] for f in os.listdir(vault.textdir)
            if f.endswith(".txt")} if os.path.isdir(vault.textdir) else set()
    missing = sorted(set(docs) - have)
    empty = sorted(i for i in have & set(docs)
                   if os.path.getsize(os.path.join(vault.textdir, f"{i}.txt")) == 0)
    return have, missing, empty


def resolve_docs(vault, selector, limit=None):
    """selector: comma-separated name keywords / doc_id prefixes -> [(id, name)]."""
    docs = store_docs(vault)
    if not selector or selector in ("*", "all"):
        out = sorted(docs.items(), key=lambda kv: kv[1].get("name", ""))
        return [(k, v.get("name", k)) for k, v in out]
    kws = [k.strip().lower() for k in selector.split(",") if k.strip()]
    hits = [(d, v.get("name", d)) for d, v in docs.items()
            if any(k in v.get("name", "").lower() or d.startswith(k) for k in kws)]
    hits.sort(key=lambda x: x[1])
    return hits[:limit] if limit else hits


# ------------------------------------------------------------- citation -----
def provenance(vault, doc_id, name=""):
    """One-line, user-verifiable origin of every answer (engine v1.2 rule)."""
    rec = (read_json(os.path.join(vault.store, "ingest_manifest.json"), {}) or {}).get(doc_id)
    if not rec:
        return f"Source: {name or doc_id} | no ledger row (indexed before CENHUA?)"
    stored = rec.get("stored_as", "")
    if stored and os.path.exists(stored):
        loc = f"original archived at {stored}"
    elif rec.get("source") and os.path.exists(rec["source"]):
        loc = f"original at {rec['source']} (not archived in-vault)"
    else:
        loc = "original deleted and not archived; text layer only"
    return f"Source: {rec.get('name', name) or doc_id} | {loc}"


def cite(vault, doc_id, page, snippet, prefix="    "):
    return f"{prefix}[{doc_id[:8]} P{page}] {snippet}"


# ------------------------------------------------------------- misc --------
def sha1(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def is_supported(path):
    return os.path.splitext(path)[1].lower() in EXTS


def pending(inbox, min_age=0.0):
    """Files waiting in an inbox. Hidden entries (.processed/.failed staging
    dirs and dotfiles) never count as pending work.

    Ordered by creation/modification time (oldest first), NOT by name: an
    inbox filled by chat/IM tools names files by content hash or sender, so
    alphabetical order shuffles the real arrival sequence and answers can be
    retrieved in the wrong order (`create_time` sort, M1b §4.4).
    `min_age` skips files younger than N seconds (partially-copied guard).
    """
    if not os.path.isdir(inbox):
        return []
    out = []
    for f in os.listdir(inbox):
        if f.startswith("."):
            continue
        p = os.path.join(inbox, f)
        if not os.path.isfile(p):
            continue
        if min_age > 0:
            try:
                age = time.time() - os.path.getmtime(p)
            except OSError:
                continue
            if age < min_age:
                continue
        try:
            st = os.stat(p)
            key = getattr(st, "st_ctime", st.st_mtime)
        except OSError:
            key = 0
        out.append((key, f, p))
    return [p for _, _, p in sorted(out)]


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def move_into(src, dstdir, suffix=""):
    os.makedirs(dstdir, exist_ok=True)
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    dst = os.path.join(dstdir, f"{stem}{suffix}{ext}")
    n = 1
    while os.path.exists(dst):
        dst = os.path.join(dstdir, f"{stem}{suffix}-{n}{ext}")
        n += 1
    shutil.move(src, dst)
    return dst
