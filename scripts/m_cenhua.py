#!/usr/bin/env python3
"""cenhua — personal second-brain CLI (OpenClaw / Hermes skill entry point).

Cen-hua 岑华: the昆仑 tree of the classic Mountain Classic (Shanhaijing) that
marks the seasons and records all things — a time-aware memory tree. That is
what this tool builds: one tree index per document, one searchable text layer
per vault, originals archived so every answer stays verifiable.

One CLI, one rule set (grep for existence, LLM for meaning):
    exact question        -> cenhua find        (offline, ms, free)
    meaning / summary     -> cenhua ask --doc   (LLM, cost-checked)
    fuzzy rephrasing      -> cenhua seek        (optional embeddings)
    verification          -> cenhua read / sources

Agent contract: call THIS command. Never invoke scripts/engine/pi_*.py
directly — the engine needs PI_STORE wiring, post-ingest flatten and cost
ceilings that only this CLI provides.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402

USAGE = __doc__ + """
USAGE
  cenhua <command> [args] [--vault NAME]

BOOTSTRAP
  setup [name] [--openclaw]         install python deps + create vault;
                                    prints agent env/config hints

VAULTS
  init [name] [--title T] [--yes]   create a vault (project/domain per vault)
  list                              all vaults, doc counts, inbox backlog
  status [name]                     what is indexed, searchable, pending
  doctor [name]                     env/store self-check (run this when lost)
  use <name>                        switch default vault
  rm <name> [--yes]                 delete a vault
  config <key> [value] [--vault N]  read/write vault.yaml (never secrets)
  sources [kw]                      provenance: origin file + archived copy

INTAKE
  add <file|dir>... [--no-flatten]  ingest now (any format, sha1-deduped)
  add --inbox                       ingest everything sitting in the inbox
  add --url <url>... [--url-file F] ingest web pages (render -> PDF + HTML)
                                    [--no-render] force static HTML fetch
                                    [--force] ignore robots.txt disallow
  watch [--interval S] [--once]     keep the inbox ingested in the background
  watch --urls [--once] [--force]   watch inbox/urls/*.url for web ingestion

RETRIEVAL
  find <term>... [-d kw] [-i] [-r]  exact text-layer grep, page numbers   [OFFLINE]
  read <doc> [-p N] [-g regex]      print raw pages for verification      [OFFLINE]
  list                              documents in the vault                [OFFLINE]
  flatten [--force]                 rebuild the text layer                [OFFLINE]
  ask [--doc kw | --all] "q" [--limit N] [--dry-run] [--yes] [--force]
                                    tree-navigation deep read (LLM; cost guard)
  index [build|status]              optional semantic (embedding) layer
  seek "question" [--top N]         semantic recall — a net, not the answer

COST & QUALITY
  cost [--month YYYY-MM]            cost ledger summary, grouped by command
                                    (ingest cost listed first)
  bench [--corpus]                  quality gate: fixture (blocking) or
                                    user-vault QA (report mode)

Examples
  cenhua init contracts --title "Client contracts"
  cp ~/Downloads/*.pdf ~/.cenhua/vaults/contracts/inbox/
  cenhua watch --once
  cenhua find 违约金 penalty
  cenhua ask --doc contract "what are the termination penalties?" --dry-run
"""


VALUE_OPTS = {"--title", "--gateway", "--home", "--vault", "-d", "--doc",
              "-p", "--page", "-g", "--grep", "--limit", "--workers", "--top",
              "--set", "--interval", "-n", "--max"}


def positional(rest):
    """Positional args only: skip flags AND the values they consume, so
    `init x --home /path` does not mistake /path for a vault name."""
    out, skip = [], False
    for a in rest:
        if skip:
            skip = False
            continue
        if a in VALUE_OPTS:
            skip = True
            continue
        if a.startswith("-") and len(a) > 1:
            continue
        out.append(a)
    return out


def split_argv(argv):
    """Pull --vault out of anywhere in the argv."""
    vault, out, i = None, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--vault" and i + 1 < len(argv):
            vault = argv[i + 1]
            i += 2
            continue
        if a.startswith("--vault="):
            vault = a.split("=", 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1
    return vault, out


def flag(args, name):
    return name in args


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"cenhua {L.VERSION}")
        return 0

    vname, args = split_argv(argv)
    if not args:
        print(USAGE)
        return 0
    cmd, rest = args[0], args[1:]
    pos = positional(rest)

    # ---- bootstrap ----------------------------------------------------------
    if cmd == "setup":
        import shutil
        import m_setup
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        auto_oc = ".openclaw" in skill_dir or shutil.which("openclaw") is not None
        gw = rest[rest.index("--gateway") + 1] if "--gateway" in rest else None
        home = rest[rest.index("--home") + 1] if "--home" in rest else None
        return m_setup.setup(vname or (pos[0] if pos else None),
                             for_openclaw=flag(rest, "--openclaw") or auto_oc,
                             gateway=gw, home=home,
                             skip_deps=flag(rest, "--skip-deps"))
    if cmd == "home":
        import m_setup
        if pos and pos[0] == "set" and len(pos) > 1:
            try:
                m_setup.apply_home(None, pos[1])
            except OSError as e:
                L.die(f"storage path not usable: {e}")
            return 0
        if pos and pos[0] == "default":
            return m_setup.apply_home(None, L.DEFAULT_HOME)
        L.say(m_setup.location_line())
        if not L.location_decided():
            L.say("  ! not decided yet — run `cenhua setup --home <path>` or "
                  "accept the default with `cenhua home default`")
        L.say(f"  vaults: {os.path.join(L.HOME, 'vaults')}"
              + (f"  ({', '.join(L.list_vaults())})" if L.list_vaults() else "  (none)"))
        return 0
    if cmd == "gateway":
        import m_setup
        v = L.Vault(vname)
        if pos and pos[0] == "list":
            provs = L.openclaw_providers()
            if not provs:
                L.say("(no local OpenClaw config at ~/.openclaw/openclaw.json)")
            for line in m_setup.gw_table(provs, L.openclaw_primary()):
                L.say(line)
            return 0
        choice = rest[rest.index("--set") + 1] if "--set" in rest \
            else (pos[0] if pos else "")
        if choice == "env":
            cfg = v.cfg()
            for k in ("gateway", "openclaw_provider", "openclaw_model",
                      "openclaw_vision"):
                cfg.pop(k, None)
            v.save_cfg(cfg)
            L.say("+ gateway -> env (unset vault reference; export PI_BASE/PI_KEY)")
            return 0
        if choice == "openclaw" or choice.startswith("openclaw:"):
            sel = choice.split(":", 1)[1] if ":" in choice else ""
            provs = L.openclaw_providers()
            sel = sel or (m_setup.primary_provider(L.openclaw_primary())
                          or (sorted(provs)[0] if provs else ""))
            ok, msg = m_setup.apply_openclaw(v, provs, sel)
            (L.say if ok else L.die)(("+ " + msg) if ok else msg)
            return 0
        gw = L.resolve_gateway(v)
        if gw:
            L.say(f"gateway : {gw['source']}")
            L.say(f"  base  : {gw['base']}")
            L.say(f"  model : {gw.get('model') or '(unset)'}   key: ***")
        else:
            L.say("gateway : none (offline only). Set one:")
            L.say("  cenhua gateway openclaw:<provider>[/<model>]   (reuse OpenClaw)")
            L.say("  export PI_BASE=... PI_KEY=***               (own endpoint)")
        return 0

    # ---- vaults (name can be positional) ----------------------------------
    if cmd == "init":
        title = ""
        if "--title" in rest:
            i = rest.index("--title")
            if i + 1 < len(rest):
                title = rest[i + 1]
        name = pos[0] if pos else (vname or "default")
        import m_setup
        import m_vault
        # storage-location decision first (exit 6 for the agent to relay)
        home = rest[rest.index("--home") + 1] if "--home" in rest else None
        if not L.location_decided():
            if home:
                try:
                    m_setup.apply_home(name, home)
                except OSError as e:
                    L.die(f"storage path not usable: {e}")
            elif flag(rest, "--yes"):
                # --yes = accept documented defaults, no questions asked
                m_setup.apply_home(name, L.DEFAULT_HOME)
                L.say(f"= storage: {L.HOME} (default, accepted via --yes)")
            else:   # tty -> interactive prompt; agent (no tty) -> exit 6
                rc = m_setup.confirm_location(name, choice=None)
                if rc:
                    return rc
        m_vault.init(name, title=title, interactive=True,
                     defaults=flag(rest, "--yes"))
        # the one-time LLM decision: reuse OpenClaw's gateway or own endpoint
        gw = rest[rest.index("--gateway") + 1] if "--gateway" in rest else None
        if flag(rest, "--yes") and gw is None:
            L.say("~ gateway not decided yet — run `cenhua setup` when ready")
            return 0
        return m_setup.configure_gateway(L.Vault(name), choice=gw)
    if cmd == "list" and not flag(rest, "--all-vaults"):
        # bare `cenhua list` = documents of current vault (matches docs)
        import m_search
        return m_search.list_docs(L.Vault(vname))
    if cmd == "vaults":
        import m_vault
        m_vault.listing()
        return 0
    if cmd == "use":
        if not pos:
            L.die("usage: cenhua use <vault>")
        import m_vault
        m_vault.use(pos[0])
        return 0
    if cmd == "rm":
        import m_vault
        m_vault.rm(pos[0] if pos else vname, yes=flag(rest, "--yes"))
        return 0
    if cmd == "config":
        v = L.Vault(vname)
        cfg = v.cfg()
        if not pos:
            for k, val in cfg.items():
                shown = "***" if "key" in k.lower() else val
                L.say(f"{k}: {shown}")
            return 0
        if len(pos) == 1:
            L.say(f"{pos[0]}: {cfg.get(pos[0], '(unset)')}")
            return 0
        key = pos[0]
        if any(t in key.lower() for t in ("key", "token", "secret")):
            L.die("API keys are never stored in vault.yaml — export them in your "
                  "shell/secret manager (PI_KEY, PI_VISION_KEY, PI_EMBED_KEY)")
        cfg[key] = " ".join(pos[1:])
        v.save_cfg(cfg)
        L.say(f"+ {key} = {cfg[key]}")
        return 0

    v = L.Vault(vname)

    if cmd == "cost":
        import m_cost
        month = rest[rest.index("--month") + 1] if "--month" in rest else None
        return m_cost.cost_cmd(v, month=month)
    if cmd == "bench":
        import m_cost
        return m_cost.bench_cmd(v, corpus=flag(rest, "--corpus"))

    if cmd == "status":
        import m_vault
        m_vault.status(v)
        return 0
    if cmd == "doctor":
        import m_vault
        return m_vault.doctor(v)
    if cmd == "sources":
        import m_vault
        m_vault.sources(v, pos[0] if pos else "")
        return 0

    # ---- intake ------------------------------------------------------------
    if cmd == "add":
        import m_ingest
        # 网页收录（M2a）：--url / --url-file
        urls = []
        i = 0
        while i < len(rest):
            if rest[i] == "--url" and i + 1 < len(rest):
                urls.append(rest[i + 1])
                i += 2
                continue
            if rest[i].startswith("--url="):
                urls.append(rest[i].split("=", 1)[1])
                i += 1
                continue
            i += 1
        url_file = rest[rest.index("--url-file") + 1] if "--url-file" in rest else None
        if urls or url_file:
            import m_web_cli
            return m_web_cli.add_url_cmd(v, urls, url_file=url_file,
                                         use_render=not flag(rest, "--no-render"),
                                         force=flag(rest, "--force"))
        paths = [a for a in rest if not a.startswith("-")]
        return m_ingest.add(v, paths, use_inbox=flag(rest, "--inbox"),
                            flatten=not flag(rest, "--no-flatten"))
    if cmd == "watch":
        import m_ingest
        interval = 5.0
        if "--interval" in rest:
            try:
                interval = float(rest[rest.index("--interval") + 1])
            except (ValueError, IndexError):
                L.die("--interval needs a number of seconds")
        # 网页收录（M2a）：watch 同时监听 inbox/urls/*.url
        if flag(rest, "--urls"):
            import m_web_cli
            return m_web_cli.watch_urls(v, interval=interval,
                                        once=flag(rest, "--once"),
                                        force=flag(rest, "--force"))
        return m_ingest.watch(v, interval=interval, once=flag(rest, "--once"))
    if cmd == "flatten":
        import m_ask
        return m_ask.flatten(v, force=flag(rest, "--force"))

    # ---- retrieval ---------------------------------------------------------
    if cmd == "find":
        import argparse
        import m_search
        ap = argparse.ArgumentParser(prog="cenhua find", add_help=False)
        ap.add_argument("terms", nargs="+")
        ap.add_argument("-d", "--doc", dest="doc")
        ap.add_argument("-i", "--ignore-case", action="store_true")
        ap.add_argument("-r", "--regex", action="store_true")
        ap.add_argument("-n", "--max", type=int, default=15)
        a = ap.parse_args(rest)
        return m_search.find(v, a.terms, docs_selector=a.doc,
                             ignore_case=a.ignore_case, regex=a.regex,
                             max_per_doc=a.max)
    if cmd == "read":
        import m_search
        if not pos:
            L.die("usage: cenhua read <doc keyword|doc_id> [-p N] [-g regex]")
        page = rest[rest.index("-p") + 1] if "-p" in rest else None
        gre = rest[rest.index("-g") + 1] if "-g" in rest else None
        return m_search.read(v, pos[0], page=page, grep=gre)
    if cmd == "ask":
        import argparse
        import m_ask
        ap = argparse.ArgumentParser(prog="cenhua ask", add_help=False)
        ap.add_argument("--doc")
        ap.add_argument("--all", action="store_true")
        ap.add_argument("--limit", type=int, default=10)
        ap.add_argument("--workers", type=int, default=None)
        ap.add_argument("--dry-run", action="store_true")
        ap.add_argument("--yes", action="store_true")
        ap.add_argument("--force", action="store_true")
        ap.add_argument("question", nargs="?")
        a = ap.parse_args(rest)
        return m_ask.ask(v, a.question, doc=a.doc, all_docs=a.all,
                         limit=a.limit, workers=a.workers,
                         dry_run=a.dry_run, yes=a.yes, force=a.force)
    if cmd in ("index", "seek"):
        import m_vectors
        if cmd == "seek":
            query = " ".join(a for a in rest if not a.startswith("-"))
            if not query:
                L.die('usage: cenhua seek "question" [--top N]')
            top = _int(rest, "--top", 6)
            m_vectors.build(v) if _needs_build(v) else None
            m_vectors.search(v, query, top)
            return 0
        mode = pos[0] if pos else "status"
        if mode == "build":
            m_vectors.build(v, force=flag(rest, "--force"))
        elif mode == "status":
            m_vectors.status(v)
        else:
            L.die("usage: cenhua index [build|status] [--force]")
        return 0

    L.die(f"unknown command: {cmd}\n\n{USAGE}", code=64)


def _needs_build(v):
    """True when the vector index is missing or any doc changed since build."""
    import m_vectors
    base, key, model = m_vectors.embed_config(v)
    if not (base and model):
        return False
    state = m_vectors.load_state(v)
    have, _, _ = L.text_status(v)
    for doc_id in have:
        p = os.path.join(v.textdir, f"{doc_id}.txt")
        if not os.path.isfile(p) or not os.path.getsize(p):
            continue
        rec = state.get(doc_id)
        if not rec or rec.get("sha1") != L.sha1(p) or rec.get("model") != model:
            return True
    return False


def _int(args, name, default):
    if name in args:
        try:
            return int(args[args.index(name) + 1])
        except (ValueError, IndexError):
            L.die(f"{name} needs an integer")
    return default


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        L.err("\ninterrupted")
        sys.exit(130)
    except BrokenPipeError:  # output cut short by `| head` etc.
        os._exit(0)
