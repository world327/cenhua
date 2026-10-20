#!/usr/bin/env python3
"""test_graph.py — M4a 知识图谱离线单测（三元组 / 存储 / 查询 / Mermaid）。

纯离线：rebuild 与三个查询子命令零网络；LLM 只在 `extract_triples` 内发生，
统一 patch **`refine.call_llm`**（唯一打桩点，见 dev-plan §8.6 约束 2）。
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-graph-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
from cenhua_service import summaries as S  # noqa: E402
from cenhua_service import graph as G  # noqa: E402


class _Vault:
    """图谱单测用最小 vault（meta/store/textdir + ledger 需要的 logs）。"""

    def __init__(self, home):
        self.meta = os.path.join(home, "meta")
        self.store = os.path.join(home, "store")
        self.textdir = os.path.join(home, "text")
        self.logs = os.path.join(home, "logs")
        self.root = home
        for d in (self.meta, self.store, self.textdir, self.logs):
            os.makedirs(d, exist_ok=True)
        self.logs_written = []

    def put(self, doc_id, name, text):
        with open(os.path.join(self.textdir, doc_id + ".txt"), "w",
                  encoding="utf-8") as f:
            f.write(text)
        led_path = os.path.join(self.store, "ingest_manifest.json")
        led = json.load(open(led_path)) if os.path.exists(led_path) else {}
        led[doc_id] = {"name": name}
        with open(led_path, "w", encoding="utf-8") as f:
            json.dump(led, f)
        S.refresh(self, doc_id, name, text)

    def cfg(self):
        return {}

    def log(self, stream, text):
        self.logs_written.append((stream, text))


def make_vault(prefix="cenhua-gv-"):
    v = _Vault(tempfile.mkdtemp(prefix=prefix))
    # 合成语料：doc1/doc2 共享 AlphaCorp+BetaLabs+128万元；doc3/doc4 另一簇
    v.put("doc1", "合同A.pdf",
          "=== PAGE 1 ===\nAlphaCorp 与 BetaLabs 签订合同，金额 128万元。\n"
          "=== PAGE 2 ===\nCommonEntity 例行条款，日期 2026-01-05，履行中。\n")
    v.put("doc2", "付款B.pdf",
          "=== PAGE 1 ===\nAlphaCorp 向 BetaLabs 付款 128万元，"
          "日期 2026-01-06，CommonEntity 条款不变。\n")
    v.put("doc3", "立项C.pdf",
          "=== PAGE 1 ===\nGammaCo 独立立项 77万元，CommonEntity 适用，"
          "日期 2026-02-01。\n")
    v.put("doc4", "纪要D.pdf",
          "=== PAGE 1 ===\nGammaCo 第二次会议复核 77万元预算，"
          "CommonEntity 适用，日期 2026-03-01。\n")
    return v


# ---------------------------------------------------------- 纯函数解析 ----
class ParseTest(unittest.TestCase):
    def test_01_well_formed_json(self):
        out = G._parse_triples('{"triples":[{"s":"A","p":"签署","o":"B"}]}')
        self.assertEqual(out, [("A", "签署", "B")])

    def test_02_predicate_whitelist_filters(self):
        out = G._parse_triples('{"triples":[{"s":"A","p":"大概也许","o":"B"},'
                               '{"s":"C","p":"投资","o":"D"}]}')
        self.assertEqual(out, [("C", "投资", "D")])

    def test_03_fenced_output_ok(self):
        out = G._parse_triples('好的：\n```json\n{"triples":[]}\n```')
        self.assertEqual(out, [])                  # 合法 JSON 但无关系 = 结论

    def test_04_unparseable_returns_none(self):
        self.assertIsNone(G._parse_triples("抱歉，我无法抽取"))
        self.assertIsNone(G._parse_triples(""))
        self.assertIsNone(G._parse_triples("{坏掉的 JSON,,,}"))
        self.assertIsNone(G._parse_triples("[1,2,3]"))

    def test_05_cap_at_pred_max(self):
        rows = ",".join('{"s":"A","p":"包含","o":"%d"}' % i
                        for i in range(G.PRED_MAX + 6))
        self.assertEqual(len(G._parse_triples('{"triples":[%s]}' % rows)),
                         G.PRED_MAX)


# -------------------------------------------------------------- 重建 ----
class RebuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault = make_vault()
        cls.stat = G.rebuild(cls.vault)

    def test_10_writes_graph_json(self):
        self.assertTrue(os.path.isfile(G.graph_path(self.vault)))
        self.assertEqual(self.stat["docs"], 4)

    def test_11_json_serializable_and_roundtrip(self):
        raw = open(G.graph_path(self.vault), encoding="utf-8").read()
        data = json.loads(raw)                     # 落盘即 JSON
        json.loads(json.dumps(data))               # 可再序列化（任务 3 验收）
        self.assertEqual(data["schema_version"], G.SCHEMA_VERSION)
        self.assertEqual(data["tier"], "internal-artifact")

    def test_12_nodes_doc_and_entity(self):
        g = G.load_graph(self.vault)
        docs = [n for n in g["nodes"] if n["kind"] == "doc"]
        ents = [n for n in g["nodes"] if n["kind"] == "entity"]
        self.assertEqual(len(docs), 4)
        self.assertTrue(any(n["id"] == "alphacorp" for n in ents))
        # 实体节点带 df 与 tier（图谱产物是 internal-artifact）
        e = [n for n in ents if n["id"] == "alphacorp"][0]
        self.assertEqual(e["df"], 2)
        self.assertEqual(e["tier"], "internal-artifact")

    def test_13_mentions_edges_present(self):
        g = G.load_graph(self.vault)
        men = [e for e in g["edges"] if e["type"] == G.TYPE_MENTIONS]
        self.assertTrue(men)
        self.assertTrue(all(e["pages"] is not None for e in men))

    def test_14_cooccur_edges_inherit_noise_gates(self):
        g = G.load_graph(self.vault)
        co = [e for e in g["edges"] if e["type"] == G.TYPE_COOCCUR]
        self.assertTrue(co)
        # 自动边硬上限 0.6（继承 relations._auto_weight）
        self.assertTrue(all(e["weight"] <= 0.6 for e in co), co[:2])
        for e in co:
            self.assertIn("nPMI=", e["evidence"])
            self.assertTrue(e["docs"])

    def test_15_hub_not_linked(self):
        g = G.load_graph(self.vault)
        hubs = set(g["hubs"])
        self.assertTrue(hubs, "CommonEntity df=4/4 应判枢纽")
        for e in g["edges"]:
            if e["type"] == G.TYPE_COOCCUR:
                self.assertNotIn(e["from"], hubs)
                self.assertNotIn(e["to"], hubs)

    def test_16_atomic_write_no_tmp_left(self):
        G.rebuild(self.vault)
        self.assertFalse(os.path.exists(G.graph_path(self.vault) + ".tmp"))

    def test_17_load_graph_missing_rebuilds(self):
        v2 = make_vault()
        self.assertFalse(os.path.isfile(G.graph_path(v2)))
        g = G.load_graph(v2)
        self.assertTrue(g["nodes"])
        self.assertTrue(os.path.isfile(G.graph_path(v2)))

    def test_18_load_graph_corrupt_degrades(self):
        v2 = make_vault()
        G.rebuild(v2)
        with open(G.graph_path(v2), "w", encoding="utf-8") as f:
            f.write("{损坏")
        g = G.load_graph(v2)
        self.assertEqual(g["nodes"], [])           # 空图骨架，不抛
        self.assertEqual(g["tier"], "internal-artifact")


# -------------------------------------------------------------- 查询 ----
class QueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault = make_vault()
        G.rebuild(cls.vault)

    def test_21_entity(self):
        r = G.entity(self.vault, "alphacorp")
        self.assertTrue(r["ok"])
        self.assertEqual(r["df"], 2)
        self.assertEqual(sorted(r["docs"]), ["doc1", "doc2"])
        self.assertIn("alphacorp", r["lines"][0])  # 实体名走 relations 归一小写
        self.assertTrue(any("betalabs" in x for x in r["lines"]))

    def test_22_entity_missing_is_conclusion(self):
        r = G.entity(self.vault, "GhostCorp")
        self.assertFalse(r["ok"])
        self.assertIn("无此实体", r["lines"][0])

    def test_23_entity_prefix_and_substring(self):
        self.assertTrue(G.entity(self.vault, "alph")["ok"])
        self.assertTrue(G.entity(self.vault, "gamma")["ok"])

    def test_24_path_within_cluster(self):
        r = G.path(self.vault, "alphacorp", "betalabs")
        self.assertTrue(r["ok"])
        self.assertEqual(r["hops"], 1)
        self.assertIn("evidence:", "\n".join(r["lines"]))

    def test_25_path_across_clusters_absent(self):
        r = G.path(self.vault, "alphacorp", "gammaco")
        self.assertFalse(r["ok"])                  # 两簇无桥 —— 未相连也是结论
        self.assertIn("无关系路径", r["lines"][0])

    def test_26_path_skips_mentions(self):
        # 文档节点经 mentions 边可"直达"，但关系路径不该走它
        r = G.path(self.vault, "alphacorp", "77万元")
        self.assertFalse(r["ok"])

    def test_27_path_same_node(self):
        r = G.path(self.vault, "alphacorp", "alphacorp")
        self.assertTrue(r["ok"])
        self.assertEqual(r["hops"], 0)

    def test_28_clusters(self):
        r = G.clusters(self.vault)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["clusters"]), 2)    # Alpha 簇 / Gamma 簇
        self.assertGreaterEqual(r["isolated"], 0)
        self.assertIn("connected cluster", r["lines"][0])

    def test_29_mermaid_shape(self):
        out = G.mermaid(self.vault)
        self.assertTrue(out.startswith("```mermaid"))
        self.assertTrue(out.endswith("```"))
        self.assertIn("graph LR", out)
        self.assertNotIn("-->|mentions|", out)     # 提及边不入图

    def test_30_mermaid_centered(self):
        out = G.mermaid(self.vault, "alphacorp")
        self.assertIn("alphacorp", out)
        self.assertNotIn("gammaco", out)           # 只画邻域

    def test_31_mermaid_empty_graph(self):
        v2 = _Vault(tempfile.mkdtemp(prefix="cenhua-gempty-"))
        out = G.mermaid(v2)
        self.assertIn("图谱为空", out)

    def test_32_mermaid_label_sanitized(self):
        v2 = make_vault()
        v2.put("doc9", "怪名字[含]括号.pdf",
               "=== PAGE 1 ===\nWeird|Name 与 AlphaCorp 签署 3万元，"
               "日期 2026-04-01。\n")
        G.rebuild(v2)
        out = G.mermaid(v2)
        self.assertNotIn("[[", out)
        self.assertNotIn("]]", out)
        # 每条边只允许 2 个竖线（标签分隔符），节点名里的竖线必须被洗掉
        for line in out.split("\n"):
            line = line.strip()
            if "-->" in line:
                self.assertEqual(line.count("|"), 2, line)


# ------------------------------------------------------ LLM 三元组 ----
class TripleTest(unittest.TestCase):
    def setUp(self):
        self.vault = make_vault()
        G.rebuild(self.vault)
        import cenhua_service.refine as R
        self.R = R
        self._orig = R.call_llm
        os.environ.pop("CENHUA_LONGJOB_MAX_COST_CNY", None)

    def tearDown(self):
        self.R.call_llm = self._orig

    def _stub(self, fn):
        self.R.call_llm = fn

    def test_40_ok_writes_triples_and_ledger(self):
        self._stub(lambda p, **kw: ('{"triples":[{"s":"AlphaCorp",'
                                    '"p":"签署","o":"BetaLabs"}]}', 900, 40))
        r = G.extract_triples(self.vault, "doc1")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["triples"], 1)
        self.assertFalse(r["fallback"])
        rows = [json.loads(x) for x in
                open(G.triple_path(self.vault), encoding="utf-8")]
        self.assertEqual(rows[0]["doc"], "doc1")
        self.assertEqual(rows[0]["source"], "llm")
        led = os.path.join(self.vault.meta, "cost-ledger.jsonl")
        self.assertTrue(os.path.isfile(led))       # 全量记账（T5）
        self.assertIn('"cmd": "graph"', open(led, encoding="utf-8").read())

    def test_41_idempotent_replace(self):
        self._stub(lambda p, **kw: ('{"triples":[{"s":"A","p":"包含",'
                                    '"o":"B"}]}', 10, 5))
        G.extract_triples(self.vault, "doc1")
        n1 = len(G._load_triples_raw(self.vault))
        G.extract_triples(self.vault, "doc1")      # 重跑不累积
        self.assertEqual(len(G._load_triples_raw(self.vault)), n1)

    def test_42_unparseable_falls_back_to_rules(self):
        self._stub(lambda p, **kw: ("我想了想，抽取不了", 10, 5))
        r = G.extract_triples(self.vault, "doc1")
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["fallback"])             # 铁律：LLM 环节必有兜底
        rows = G._load_triples_raw(self.vault)
        self.assertTrue(rows)
        self.assertTrue(all(x["p"] == "提及" for x in rows), rows[:2])

    def test_43_gateway_failure_isolated(self):
        def boom(p, **kw):
            raise RuntimeError("connection refused")
        self._stub(boom)
        r = G.extract_triples(self.vault, "doc1")
        self.assertEqual(r["status"], "failed")
        self.assertFalse(os.path.exists(G.triple_path(self.vault)))

    def test_44_skip_without_summary(self):
        self._stub(lambda p, **kw: ("x", 1, 1))
        self.assertEqual(G.extract_triples(self.vault, "ghost"),
                         {"status": "skip", "triples": 0})

    def test_45_rebuild_merges_triples_and_pads_nodes(self):
        self._stub(lambda p, **kw: ('{"triples":[{"s":"NewCo","p":"投资",'
                                    '"o":"OtherCo"}]}', 50, 20))
        G.extract_triples(self.vault, "doc1")
        stat = G.rebuild(self.vault)
        self.assertEqual(stat["triples"], 1)
        g = G.load_graph(self.vault)
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("NewCo", ids)                # 端点缺节点自动补
        self.assertIn("OtherCo", ids)
        self.assertTrue(any(e["type"] == "投资" and e["weight"] == G.W_TRIPLE
                            for e in g["edges"]))

    def test_46_extract_all_partial_failure(self):
        calls = {"n": 0}

        def flaky(p, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return '{"triples":[{"s":"A","p":"包含","o":"B"}]}', 10, 5
        self._stub(flaky)
        r = G.extract_all(self.vault)
        self.assertEqual(r["docs"], 3)             # 4 篇里 1 篇失败
        self.assertEqual(r["failed"], 1)
        self.assertEqual(r["triples"], 3)

    def test_47_rule_triples_only_touches_summary(self):
        out = G._rule_triples(self.vault, "doc1")
        self.assertTrue(out)
        self.assertEqual({t[1] for t in out}, {"提及"})


# ---------------------------------------------------------- 三元组三闸 ----
class TripleGateTest(unittest.TestCase):
    def setUp(self):
        self.vault = make_vault()
        G.rebuild(self.vault)
        import cenhua_service.refine as R
        self.R = R
        self._orig = R.call_llm
        self.hits = []

        def spy(p, **kw):
            self.hits.append(p)
            return '{"triples":[{"s":"A","p":"包含","o":"B"}]}', 100, 50
        R.call_llm = spy
        self._env = {k: os.environ.get(k) for k in
                     ("PI_KEY", "PI_BASE", "PI_MODEL",
                      "CENHUA_LONGJOB_MAX_COST_CNY")}

    def tearDown(self):
        self.R.call_llm = self._orig
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_50_no_selection_is_usage_error(self):
        r = G.cli(self.vault, ["triples"])
        self.assertEqual(r["rc"], 2)
        self.assertIn("--doc", r["lines"][0])
        self.assertFalse(self.hits)

    def test_51_dry_run_never_calls_gateway(self):
        r = G.cli(self.vault, ["triples", "--all", "--dry-run"])
        self.assertEqual(r["rc"], 0)
        self.assertFalse(self.hits)
        self.assertIn("dry-run", "\n".join(r["lines"]))
        self.assertFalse(os.path.exists(G.triple_path(self.vault)))

    def test_52_no_gateway_rc3(self):
        os.environ.pop("PI_KEY", None)
        os.environ.pop("PI_BASE", None)
        r = G.cli(self.vault, ["triples", "--all"])
        self.assertEqual(r["rc"], 3)
        self.assertFalse(self.hits)

    def test_53_budget_gate_refuses(self):
        os.environ.update(PI_KEY="sk-x", PI_BASE="http://127.0.0.1:9/v1",
                          CENHUA_LONGJOB_MAX_COST_CNY="0.0001")
        r = G.cli(self.vault, ["triples", "--all"])
        self.assertEqual(r["rc"], 4)
        self.assertIn("REFUSED", r["lines"][0])
        self.assertFalse(self.hits)                # 拒启 = 一毛不拔

    def test_54_force_overrides_gate(self):
        os.environ.update(PI_KEY="sk-x", PI_BASE="http://127.0.0.1:9/v1",
                          CENHUA_LONGJOB_MAX_COST_CNY="0.0001")
        r = G.cli(self.vault, ["triples", "--doc", "合同A", "--force"])
        self.assertEqual(r["rc"], 0)
        self.assertTrue(self.hits)
        self.assertIn("--force overrides", "\n".join(r["lines"]))

    def test_55_max_cost_overrides_gate(self):
        os.environ.update(PI_KEY="sk-x", PI_BASE="http://127.0.0.1:9/v1",
                          CENHUA_LONGJOB_MAX_COST_CNY="0.0001")
        r = G.cli(self.vault, ["triples", "--all", "--max-cost", "99"])
        self.assertEqual(r["rc"], 0)
        self.assertTrue(self.hits)

    def test_56_limit_caps_docs(self):
        os.environ.update(PI_KEY="sk-x", PI_BASE="http://127.0.0.1:9/v1")
        r = G.cli(self.vault, ["triples", "--all", "--limit", "2"])
        self.assertEqual(r["rc"], 0)
        self.assertEqual(len(self.hits), 2)        # --limit 真圈住，不多花钱


# ------------------------------------------------------------ CLI 分派 ----
class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault = make_vault()
        G.rebuild(cls.vault)

    def test_60_entity_rc0(self):
        r = G.cli(self.vault, ["entity", "alphacorp"])
        self.assertEqual(r["rc"], 0)

    def test_61_entity_missing_rc1(self):
        self.assertEqual(G.cli(self.vault, ["entity", "ghost"])["rc"], 1)

    def test_62_usage_errors(self):
        self.assertEqual(G.cli(self.vault, [])["rc"], 2)
        self.assertEqual(G.cli(self.vault, ["entity"])["rc"], 2)
        self.assertEqual(G.cli(self.vault, ["path", "one"])["rc"], 2)
        self.assertEqual(G.cli(self.vault, ["nope"])["rc"], 2)

    def test_63_mermaid_via_cli(self):
        r = G.cli(self.vault, ["mermaid"])
        self.assertEqual(r["rc"], 0)
        self.assertEqual(r["lines"][0], "```mermaid")

    def test_64_rebuild_via_cli(self):
        r = G.cli(self.vault, ["rebuild"])
        self.assertEqual(r["rc"], 0)
        self.assertIn("graph rebuilt", r["lines"][0])

    def test_65_cluster_flags(self):
        self.assertEqual(G.cli(self.vault, ["cluster", "--top", "1"])["rc"], 0)

    def test_66_graph_cmd_is_thin(self):
        import m_graph
        src, _start = __import__("inspect").getsourcelines(m_graph.graph_cmd)
        body = [s for s in src[1:-1]]
        self.assertLessEqual(len(body), 10)

    def test_67_registry_dispatch(self):
        src = open(os.path.join(ROOT, "scripts", "m_cenhua.py"),
                   encoding="utf-8").read()
        self.assertIn('if cmd == "graph"', src)
        self.assertIn("--max-cost", src)           # VALUE_OPTS 已登记


if __name__ == "__main__":
    unittest.main(verbosity=2)
