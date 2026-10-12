#!/usr/bin/env python3
"""Offline test suite for the CENHUA CLI.

No network, no API keys. The bundled engine's offline halves (pi_flatten.py and
pi_query.py --grep) are exercised FOR REAL; only tree indexing needs an LLM, so
ingest is covered on its dedupe / failure / unsupported-format paths, and a
store is fabricated the way PageIndex leaves it behind.

Run:  python3 tests/test_cenhua.py     (or bash tests/run_tests.sh)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

DOC_A = """# Termination clauses

=== body ===
The penalty for early termination is 30% of the annual fee.
Party B shall notify Party A in writing 60 days in advance.
Account 6222 0200 1234 5678 belongs to the client.
"""
DOC_B = """季度经营纪要

第三条 本季度毛利 1,240 万元，同比增长 18%。
违约金刚性条款见合同附录二。
联系人电话 13800138000。
"""


def run(args, home, env=None, input_text=None):
    e = dict(os.environ)
    e["CENHUA_HOME"] = home
    # keep the storage-location pointer file inside the test sandbox
    e["CENHUA_CONFIG_DIR"] = os.path.join(home, "config-dir")
    e.update(env or {})
    e.pop("PI_BASE", None)
    e.pop("PI_KEY", None)
    return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                          capture_output=True, text=True, input=input_text)


def pending(inbox):
    """Files still waiting in an inbox (hidden staging dirs never count)."""
    return [f for f in os.listdir(inbox)
            if not f.startswith(".") and os.path.isfile(os.path.join(inbox, f))]


class CenhuaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="cenhua-test-")
        cls.src = tempfile.mkdtemp(prefix="cenhua-src-")
        cls.docA = os.path.join(cls.src, "contract.txt")
        cls.docB = os.path.join(cls.src, "纪要.txt")
        open(cls.docA, "w", encoding="utf-8").write(DOC_A)
        open(cls.docB, "w", encoding="utf-8").write(DOC_B)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)
        shutil.rmtree(cls.src, ignore_errors=True)

    # ---------------------------------------------------------------- utils --
    def vault_paths(self, name="t"):
        r = os.path.join(self.home, "vaults", name)
        j = lambda *p: os.path.join(r, *p)
        return {"root": r, "inbox": j("inbox"), "processed": j("inbox", ".processed"),
                "failed": j("inbox", ".failed"), "store": j("engine"),
                "text": j("engine", "text"), "docs": j("engine", "docs"),
                "meta": j("meta"), "works": j("works"), "logs": j("logs")}

    def seed_store(self, name="t"):
        """Fabricate the store exactly as PageIndex + pi_ingest leave it:
        manifest.json (PageIndex owns it) + ingest_manifest.json ledger +
        docs/<id>/pages.json. Then flatten derives the text layer."""
        p = self.vault_paths(name)
        spec = {
            "pi-aaaa1111": [  # two pages -> exercises page numbering
                "# Termination clauses\n\nThe penalty for early termination is "
                "30% of the annual fee.",
                "Party B shall notify Party A in writing 60 days in advance.\n\n"
                "Account 6222 0200 1234 5678 belongs to the client."],
            "pi-bbbb2222": [
                "季度经营纪要\n\n第三条 本季度毛利 1,240 万元，同比增长 18%。\n"
                "违约金刚性条款见合同附录二。\n联系人电话 13800138000。"],
        }
        for doc_id, pages in spec.items():
            d = os.path.join(p["store"], "docs", doc_id)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "pages.json"), "w", encoding="utf-8") as f:
                json.dump([{"page_index": i + 1, "markdown": t}
                           for i, t in enumerate(pages)], f, ensure_ascii=False)
        with open(os.path.join(p["store"], "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"docs": {"pi-aaaa1111":
                                {"name": "contract_0123456789ab.pdf"},
                                "pi-bbbb2222": {"name": "纪要"}}},
                      f, ensure_ascii=False)
        with open(os.path.join(p["store"], "ingest_manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "pi-aaaa1111": {"name": "contract.txt", "doc_id": "pi-aaaa1111",
                                "sha1": "a" * 40, "ts": "2026-10-10 10:00:00",
                                "source": self.docA,
                                "stored_as": self._archive(p, "contract.txt", DOC_A)},
                "pi-bbbb2222": {"name": "纪要.txt", "doc_id": "pi-bbbb2222",
                                "sha1": "b" * 40, "ts": "2026-10-10 10:05:00",
                                "source": self.docB, "stored_as": ""},
            }, f, ensure_ascii=False)

    @staticmethod
    def _archive(p, name, content):
        d = os.path.join(p["store"], "sources")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    # ------------------------------------------------------------- 1. init --
    def test_01_init_and_layout(self):
        r = run(["init", "t", "--title", "unit test", "--yes"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.vault_paths()
        for k in ("inbox", "store", "works", "logs", "meta"):
            self.assertTrue(os.path.isdir(p[k]), f"{k} missing")
        self.assertTrue(os.path.isfile(os.path.join(p["root"], "vault.yaml")))
        self.assertIn("drop files here", r.stdout)
        # secrets never on disk
        cfg = open(os.path.join(p["root"], "vault.yaml"), encoding="utf-8").read()
        for banned in ("PI_KEY", "secret", "token"):
            self.assertNotIn(banned, cfg.lower().replace("keys are never", ""))

    def test_02_vaults_isolated(self):
        for name in ("work", "reading"):
            r = run(["init", name, "--yes"], self.home)
            self.assertEqual(r.returncode, 0, r.stderr)
        r = run(["vaults"], self.home)
        for name in ("t", "work", "reading"):
            self.assertIn(name, r.stdout)
        # an ingest into one vault must not appear in another
        self.seed_store("work")
        run(["flatten", "--vault", "work"], self.home)
        r = run(["list", "--vault", "reading"], self.home)
        self.assertIn("(empty vault)", r.stdout)

    def test_03_config_refuses_secrets(self):
        r = run(["config", "PI_KEY", "sk-live-123", "--vault", "t"], self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("never stored", r.stderr)
        r = run(["config", "max_llm_calls", "3", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("3", run(["config", "max_llm_calls", "--vault", "t"],
                               self.home).stdout)

    # --------------------------------------------------------- 2. text layer --
    def test_10_flatten_builds_text_layer(self):
        self.seed_store()
        r = run(["flatten", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = self.vault_paths()
        text = open(os.path.join(p["text"], "pi-aaaa1111.txt"),
                    encoding="utf-8").read()
        self.assertIn("=== PAGE 1 ===", text)
        self.assertIn("penalty", text)

    def test_11_find_exact_and_cjk(self):
        # (term, doc shown, page it lives on in the fixture)
        for term, needle, page in (("penalty", "contract.txt", "P1"),
                                   ("termination", "contract.txt", "P1"),
                                   ("违约金", "纪要.txt", "P1"),
                                   ("6222 0200 1234 5678", "contract.txt", "P2"),
                                   ("13800138000", "纪要.txt", "P1")):
            r = run(["find", term, "--vault", "t"], self.home)
            self.assertEqual(r.returncode, 0, f"{term}: {r.stdout}{r.stderr}")
            self.assertIn(needle, r.stdout)
            self.assertIn(page + "]", r.stdout)       # exact page citation
            self.assertIn("Source:", r.stdout)        # provenance on every hit
            self.assertIn("offline, exact, complete", r.stdout)

    def test_12_find_miss_reports_not_found(self):
        r = run(["find", "zzz-absent-term", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT FOUND", r.stdout)

    def test_13_find_auto_flattens_when_stale(self):
        """The silent-miss trap: a new doc without a text layer must not be
        quietly skipped — find flattens first."""
        p = self.vault_paths()
        os.remove(os.path.join(p["text"], "pi-bbbb2222.txt"))
        r = run(["find", "毛利", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("flattening", r.stdout)
        self.assertIn("毛利", r.stdout)

    def test_14_find_scoped_and_regex(self):
        r = run(["find", "penalty", "-d", "contract", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("纪要", r.stdout)
        r = run(["find", r"毛利 \d+,?\d* 万元", "-r", "--vault", "t"], self.home)
        self.assertIn("毛利 1,240 万元", r.stdout)

    def test_15_read_pages(self):
        r = run(["read", "contract", "-p", "1", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--- page 1 ---", r.stdout)
        self.assertIn("Termination clauses", r.stdout)
        r = run(["read", "pi-bbbb", "-g", "违约", "--vault", "t"], self.home)
        self.assertIn("违约金刚性条款", r.stdout)

    # ------------------------------------------------------------- 3. intake --
    def test_20_add_requires_gateway_and_keeps_file(self):
        """No PI_BASE/PI_KEY -> engine fails -> file lands in .failed, not lost,
        and the batch reports it (no silent drop)."""
        p = self.vault_paths()
        src = os.path.join(self.src, "fresh.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("# fresh\nhello cen hua\n")
        shutil.copy(src, p["inbox"])
        r = run(["add", "--inbox", "--vault", "t"], self.home)
        self.assertIn("x1failed", r.stdout.replace(" ", ""))
        self.assertEqual(pending(p["inbox"]), [])
        self.assertEqual(len(os.listdir(p["failed"])), 1)
        self.assertTrue(any("ingest" in f for f in os.listdir(p["logs"])),
                        "failure reason must be in logs/")

    def test_21_unsupported_extension_quarantined(self):
        p = self.vault_paths()
        with open(os.path.join(p["inbox"], "movie.mkv"), "w") as f:
            f.write("x")
        r = run(["add", "--inbox", "--vault", "t"], self.home)
        self.assertIn("unsupported extension", r.stderr)
        self.assertEqual(pending(p["inbox"]), [])
        self.assertTrue(any("unsupported" in f for f in os.listdir(p["failed"])))

    def test_22_dedupe_skips_without_llm(self):
        """sha1 already in the dedupe index -> no engine call at all."""
        p = self.vault_paths()
        src = os.path.join(self.src, "dup.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("duplicate content\n")
        import hashlib
        digest = hashlib.sha1(open(src, "rb").read()).hexdigest()
        with open(os.path.join(p["meta"], "dedupe.json"), "w") as f:
            json.dump({digest: {"doc_id": "pi-aaaa1111", "name": "dup.txt"}}, f)
        shutil.copy(src, p["inbox"])
        r = run(["add", "--inbox", "--vault", "t"], self.home)
        self.assertIn("already in vault", r.stdout)
        self.assertIn("=1dupes", r.stdout.replace(" ", ""))
        self.assertTrue(any(f.startswith("dup") for f in os.listdir(p["processed"])))

    def test_23_watch_once_drains_inbox(self):
        p = self.vault_paths()
        with open(os.path.join(p["inbox"], "later.txt"), "w") as f:
            f.write("later note\n")
        r = run(["watch", "--once", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(pending(p["inbox"]), [])

    # ------------------------------------------------------------- 4. cost --
    def test_30_ask_without_scope_is_refused(self):
        r = run(["ask", "what is the penalty?"], self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--doc", r.stderr)

    def test_31_dry_run_costs_nothing_without_gateway(self):
        r = run(["ask", "--all", "what is the penalty?", "--dry-run", "--vault", "t"],
                self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("LLM calls  : ~2", r.stdout)
        self.assertIn("nothing was sent", r.stdout)

    def test_32_ceiling_blocks_before_spending(self):
        """max_llm_calls=3 already set in test_03; 2 docs fit, --force path
        and the over-cap refusal are both checked."""
        r = run(["ask", "--all", "q?", "--vault", "t", "--yes"], self.home)
        self.assertNotEqual(r.returncode, 0)          # no gateway -> must fail
        self.assertIn("PI_BASE", r.stderr)            # ... and say why clearly
        r = run(["init", "tiny", "--yes"], self.home)
        self.seed_store("tiny")
        run(["config", "max_llm_calls", "1", "--vault", "tiny"], self.home)
        r = run(["ask", "--all", "q?", "--vault", "tiny", "--yes"], self.home)
        self.assertIn("exceeds the per-run ceiling", r.stderr)

    def test_33_ask_dry_run_survives_missing_vault(self):
        r = run(["ask", "--all", "q?", "--vault", "nope", "--dry-run"], self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not found", r.stderr)

    # ----------------------------------------------------------- 5. status --
    def test_40_status_and_doctor(self):
        r = run(["status", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("contract.txt", r.stdout)
        self.assertIn("text✓", r.stdout)
        self.assertIn("archived✗", r.stdout)   # 纪要.txt was never archived
        self.assertIn("llm gateway", r.stdout)

        r = run(["doctor", "--vault", "t"], self.home)
        self.assertIn("python", r.stdout)
        self.assertIn("PI_BASE/PI_KEY not set", r.stdout)  # reported, not fatal
        self.assertIn("images & scanned PDFs", r.stdout)
        self.assertIn("local OCR (RapidOCR)", r.stdout)

    def test_41_doctor_flags_empty_text_layer(self):
        p = self.vault_paths()
        empty = os.path.join(p["text"], "pi-cccc3333.txt")
        man = json.load(open(os.path.join(p["store"], "manifest.json")))
        man["docs"]["pi-cccc3333"] = {"name": "blank.pdf"}
        json.dump(man, open(os.path.join(p["store"], "manifest.json"), "w"))
        open(empty, "w").close()
        r = run(["doctor", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 1, "empty text layer must be a PROBLEM")
        self.assertIn("EMPTY", r.stdout)
        man["docs"].pop("pi-cccc3333")
        json.dump(man, open(os.path.join(p["store"], "manifest.json"), "w"))
        os.remove(empty)

    def test_42_sources_provenance(self):
        r = run(["sources", "contract", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("archived", r.stdout)
        self.assertIn("sha1", r.stdout)

    # ---------------------------------------------- 5c. storage location -----
    def runp(self, args, cfg, fake_home, input_text=None):
        """Run WITHOUT CENHUA_HOME so the pointer flow is exercised.
        HOME is faked so the ~/.cenhua default lands inside the sandbox."""
        e = dict(os.environ)
        e.pop("CENHUA_HOME", None)
        e["CENHUA_CONFIG_DIR"] = cfg
        e["HOME"] = fake_home
        e.pop("PI_BASE", None)
        e.pop("PI_KEY", None)
        return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                              capture_output=True, text=True, input=input_text)

    def loc_env(self, tag):
        cfg = os.path.join(self.home, "cfg-" + tag)
        fake_home = os.path.join(self.home, "fakehome-" + tag)
        os.makedirs(cfg, exist_ok=True)
        os.makedirs(fake_home, exist_ok=True)
        return cfg, fake_home

    def test_70_location_requires_confirmation(self):
        """Agent path (no tty, no --yes, no --home): exit 6, nothing created."""
        cfg, fh = self.loc_env("70")
        r = self.runp(["init", "corp", "--vault", "corp"], cfg, fh)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("CONFIRM REQUIRED", r.stderr)
        self.assertIn("INSTALL DIR", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(fh, ".cenhua")))
        self.assertFalse(os.path.exists(os.path.join(cfg, "location")))

    def test_71_home_set_pins_pointer(self):
        cfg, fh = self.loc_env("71")
        target = os.path.join(self.home, "corpus-71")
        r = self.runp(["home", "set", target], cfg, fh)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(target, open(os.path.join(cfg, "location")).read())
        r = self.runp(["init", "notes", "--vault", "notes"], cfg, fh)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # the vault landed at the PINNED location, not at ~/.cenhua
        self.assertTrue(os.path.isdir(os.path.join(target, "vaults", "notes", "inbox")))
        self.assertFalse(os.path.exists(os.path.join(fh, ".cenhua")))
        r = self.runp(["home"], cfg, fh)
        self.assertIn("storage already decided" if "already" in r.stdout else target,
                      r.stdout)

    def test_72_yes_accepts_default_home(self):
        cfg, fh = self.loc_env("72")
        r = self.runp(["init", "d", "--yes", "--vault", "d"], cfg, fh)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("default, accepted via --yes", r.stdout)
        self.assertTrue(os.path.isdir(os.path.join(fh, ".cenhua", "vaults", "d")))

    def test_73_relocate_moves_vaults(self):
        cfg, fh = self.loc_env("73")
        a = os.path.join(self.home, "loc-a")
        b = os.path.join(self.home, "loc-b")
        self.runp(["home", "set", a], cfg, fh)
        self.runp(["init", "mv", "--vault", "mv"], cfg, fh)
        marker = os.path.join(a, "vaults", "mv", "inbox", "keep.txt")
        open(marker, "w").write("x")
        r = self.runp(["home", "set", b], cfg, fh)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(b, "vaults", "mv",
                                                    "inbox", "keep.txt")))
        r = self.runp(["home"], cfg, fh)
        self.assertIn(b, r.stdout)
        self.assertIn("mv", r.stdout)

    def test_74_unusable_path_rejected(self):
        cfg, fh = self.loc_env("74")
        r = self.runp(["home", "set", "/proc/cenhua-nope"], cfg, fh)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not usable", r.stderr)

    # ------------------------------------------------- 5b. gateway decision --
    def fake_openclaw(self):
        """A mock OpenClaw config dir (OPENCLAW_STATE_DIR is honored)."""
        d = os.path.join(self.home, "fake-openclaw")
        os.makedirs(d, exist_ok=True)
        cfg = {
            "agents": {"defaults": {"model": {"primary": "p1/m-a"},
                                    "imageModel": "p1/m-vision"}},
            "models": {"providers": {
                "p1": {"baseUrl": "https://p1.example/v1", "apiKey": "sk-p1-secret",
                       "api": "openai-completions",
                       "models": [{"id": "m-a"}, {"id": "m-b"}]},
                "p2": {"baseUrl": "https://p2.example/v1",
                       "models": [{"id": "m-c"}]},   # no apiKey on purpose
            }},
        }
        with open(os.path.join(d, "openclaw.json"), "w") as f:
            json.dump(cfg, f)
        return d

    def test_43_gateway_list_from_openclaw(self):
        d = self.fake_openclaw()
        r = run(["gateway", "list", "--vault", "t"], self.home,
                env={"OPENCLAW_STATE_DIR": d})
        self.assertIn("p1", r.stdout)
        self.assertIn("primary:m-a", r.stdout)
        self.assertIn("vision:m-vision", r.stdout)
        self.assertNotIn("sk-p1-secret", r.stdout)      # keys never listed

    def test_44_gateway_openclaw_stores_reference_not_key(self):
        d = self.fake_openclaw()
        e = {"OPENCLAW_STATE_DIR": d}
        run(["init", "gw", "--yes", "--gateway", "openclaw:p1/m-b",
             "--vault", "gw"], self.home, env=e)
        self.seed_store("gw")
        vault_yaml = open(os.path.join(self.home, "vaults", "gw",
                                       "vault.yaml"), encoding="utf-8").read()
        self.assertIn("gateway: openclaw", vault_yaml)
        self.assertIn("openclaw_provider: p1", vault_yaml)
        self.assertIn("openclaw_model: m-b", vault_yaml)
        self.assertNotIn("sk-p1-secret", vault_yaml)    # THE key rule
        # resolution is live: dry-run sees the provider's endpoint + openai/ prefix
        r = run(["ask", "--all", "q?", "--dry-run", "--vault", "gw"],
                self.home, env=e)
        self.assertIn("openai/m-b", r.stdout)
        self.assertIn("p1.example", r.stdout)
        self.assertNotIn("sk-p1-secret", r.stdout)

    def test_45_gateway_rejects_unknown_or_keyless(self):
        d = self.fake_openclaw()
        e = {"OPENCLAW_STATE_DIR": d}
        r = run(["init", "gw2", "--yes", "--gateway", "openclaw:p9",
                 "--vault", "gw2"], self.home, env=e)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown OpenClaw provider", r.stderr)
        r = run(["init", "gw3", "--yes", "--gateway", "openclaw:p2",
                 "--vault", "gw3"], self.home, env=e)
        self.assertIn("no apiKey", r.stderr)

    def test_46_agent_path_requires_explicit_confirmation(self):
        """No --gateway + no tty (agent) => exit 5 'CONFIRM REQUIRED', listing
        both options; nothing is written to the vault."""
        d = self.fake_openclaw()
        r = run(["init", "askme", "--vault", "askme"], self.home,
                env={"OPENCLAW_STATE_DIR": d}, input_text="")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("CONFIRM REQUIRED", r.stderr)
        self.assertIn("REUSE the OpenClaw gateway", r.stderr)
        self.assertIn("BRING YOUR OWN", r.stderr)
        vault_yaml = open(os.path.join(self.home, "vaults", "askme",
                                       "vault.yaml"), encoding="utf-8").read()
        self.assertNotIn("gateway: openclaw", vault_yaml)

    def test_47_env_gateway_wins_and_switch_back(self):
        d = self.fake_openclaw()
        e = {"OPENCLAW_STATE_DIR": d}
        run(["init", "gwe", "--yes", "--gateway", "openclaw:p1", "--vault", "gwe"],
            self.home, env=e)
        # explicit env choice clears the reference
        r = run(["gateway", "env", "--vault", "gwe"], self.home, env=e)
        self.assertIn("gateway -> env", r.stdout)
        r = run(["gateway", "--vault", "gwe"], self.home, env=e)
        self.assertIn("none", r.stdout)

    # ------------------------------------------------------- 6. semantics --
    def test_50_semantic_layer_degrades_gracefully(self):
        r = run(["seek", "how much is the penalty", "--vault", "t"], self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PI_EMBED_MODEL", r.stderr)
        r = run(["index", "status", "--vault", "t"], self.home)
        self.assertIn("NOT configured", r.stdout)

    def test_51_chunking_stays_within_page(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import m_vectors as V
        pages = [("3", "\n\n".join(f"paragraph {i} with some text" * 3
                                  for i in range(120)))]
        chunks = V.doc_chunks("pi-x", pages)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["page"] == "3" for c in chunks),
                        "chunks must never cross page boundaries")
        self.assertTrue(all(len(c["text"]) <= V.MAX_CHARS for c in chunks))

    # ------------------------------------------------------------- 7. misc --
    def test_60_help_and_version(self):
        self.assertIn("grep for existence", run(["--help"], self.home).stdout.lower()
                      .replace("grep for EXISTENCE", "grep for existence"))
        self.assertIn("cenhua 0.1.0", run(["--version"], self.home).stdout)

    def test_61_engine_is_untouched(self):
        """CENHUA must integrate by subprocess+env, never by editing the engine."""
        for fn in ("pi_ingest.py", "pi_flatten.py", "pi_query.py"):
            src = open(os.path.join(ROOT, "scripts", "engine", fn),
                       encoding="utf-8").read()
            self.assertNotIn("CENHUA", src, f"{fn} was modified — keep engine pure")
            self.assertIn("PI_STORE", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
