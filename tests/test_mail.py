#!/usr/bin/env python3
"""test_mail.py — M1b 任务 1（§4.4 离线增强）离线单测。

覆盖：
  * .eml 展开（真实 RFC822 样本：正文/抬头/附件/不支持附件留痕）
  * .msg 展开（打桩 olefile：属性表 + 附件表，MS-OXMSG 布局）
  * 邮件摄取路由（无网关环境：正文部件必失败 -> 整封隔离进 .failed/，
    部件文件同步移进 .failed/，不崩不静默丢）
  * watch 强化：pending 按到达时间（ctime）排序 + min_age 龄期防护
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

# 必须在 import m_lib 之前重定向存储根（HOME 是 import 时常量）
_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-mail-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import m_lib as L  # noqa: E402
import m_mail as M  # noqa: E402

_MAIL_BODY = "请查收季度合同扫描件与预算表，截止周五。\r\n".encode("utf-8")
EML = (
    b"From: =?utf-8?B?5byg6I6O?= <li@example.com>\r\n"
    b"To: team@example.com\r\n"
    b"Subject: =?utf-8?B?5Zyo6K+35Y2VIEVGROMOmOS7o+eggQ==?=\r\n"
    b"Date: Mon, 12 Oct 2026 09:00:00 +0800\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="BOUND"\r\n\r\n'
    b"--BOUND\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    + _MAIL_BODY + b"\r\n"
    b"--BOUND\r\n"
    b'Content-Type: text/csv; name="budget.csv"\r\n'
    b"Content-Disposition: attachment; filename=\"budget.csv\"\r\n\r\n"
    b"item,amount\nserver,42000\n\r\n"
    b"--BOUND\r\n"
    b'Content-Type: application/zip; name="misc.zip"\r\n'
    b"Content-Disposition: attachment; filename=\"misc.zip\"\r\n\r\n"
    b"PK\x03\x04fakezip\r\n"
    b"--BOUND--\r\n"
)


def run(args, home):
    env = dict(os.environ, CENHUA_HOME=home)
    import subprocess
    return subprocess.run([CLI] + args, capture_output=True, text=True,
                          env=env, timeout=180)


class _FakeOle:
    """打桩 olefile：按 MS-OXMSG 布局提供 listdir/openstream。"""

    def __init__(self, streams):
        self._s = streams

    def listdir(self):
        return [tuple(k.split("/")) for k in self._s]

    def openstream(self, entry):
        import io
        return io.BytesIO(self._s["/".join(entry)])

    def close(self):
        pass


def _w(s):
    return s.encode("utf-16-le")


MSG_STREAMS = {
    "__properties_version1.0/__substg1.0_0037001F": _w("合同评审结论"),
    "__properties_version1.0/__substg1.0_0C1A001F": _w("wang@example.com"),
    "__properties_version1.0/__substg1.0_0039001F": _w("2026-10-12 10:00"),
    "__properties_version1.0/__substg1.0_0E04001F": _w("legal@example.com"),
    "__properties_version1.0/__substg1.0_1000001F": _w("同意签署，预算内。"),
    "__attach_version1.0_00000000/__substg1.0_3707001F": _w("contract.md"),
    "__attach_version1.0_00000000/__substg1.0_37010102":
        "# 合同\n甲方乙方签字。".encode("utf-8"),
}


class MailTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = run(["init", "mailv", "--yes"], _TEST_HOME)
        assert r.returncode == 0, r.stderr

    # -------------------------------------------------- .eml 展开 ----
    def test_01_expand_eml(self):
        vault = L.Vault("mailv")
        p = os.path.join(_TEST_HOME, "a.eml")
        with open(p, "wb") as f:
            f.write(EML)
        parts, fails = M.expand(vault, p, L.sha1(p))
        # 正文 md + budget.csv；misc.zip 不支持 -> 留痕清单
        self.assertEqual(len(parts), 2)
        self.assertEqual(fails, ["misc.zip"])
        md_path = parts[0]["path"]
        self.assertTrue(md_path.endswith(".md"))
        md = open(md_path, encoding="utf-8").read()
        self.assertIn("请查收季度合同扫描件", md)          # 正文
        self.assertIn("team@example.com", md)              # 抬头
        self.assertIn("(li@example.com)", md)              # 尖括号消毒
        self.assertNotIn("<li@example.com>", md)
        self.assertIn("budget.csv", md)                    # 附件清单
        self.assertIn("misc.zip（展开失败）", md)          # 留痕
        self.assertIn(b"item,amount", open(parts[1]["path"], "rb").read())
        self.assertEqual(parts[1]["name"], "budget.csv")

    # -------------------------------------------------- .msg 展开（打桩）----
    def test_02_expand_msg_stubbed(self):
        vault = L.Vault("mailv")
        import unittest.mock as mock
        p = os.path.join(_TEST_HOME, "b.msg")
        with open(p, "wb") as f:
            f.write(b"fake-ole-payload")   # sha1 用，不真解析
        with mock.patch("olefile.isOleFile", return_value=True), \
             mock.patch("olefile.OleFileIO",
                        return_value=_FakeOle(MSG_STREAMS)):
            parts, fails = M.expand(vault, p, L.sha1(p))
        self.assertEqual(fails, [])
        self.assertEqual(len(parts), 2)                    # 正文 + contract.md
        md = open(parts[0]["path"], encoding="utf-8").read()
        self.assertIn("合同评审结论", md)
        self.assertIn("同意签署，预算内。", md)
        self.assertIn("contract.md", md)
        self.assertIn("甲方乙方签字", open(parts[1]["path"],
                                       encoding="utf-8").read())

    def test_03_msg_bad_payload_fails_clean(self):
        # 非 OLE 内容必须明确报错（调用方隔离进 .failed/，不崩）
        vault = L.Vault("mailv")
        p = os.path.join(_TEST_HOME, "bad.msg")
        with open(p, "wb") as f:
            f.write(b"not an ole file at all")
        with self.assertRaises(Exception):
            M.expand(vault, p, L.sha1(p))

    # -------------------------------------------------- 摄取路由（离线：部件必失败，验证隔离）----
    def test_04_ingest_mail_isolated(self):
        vault = L.Vault("mailv")
        os.makedirs(vault.inbox, exist_ok=True)
        p = os.path.join(vault.inbox, "c.eml")     # inbox 路径：暂存语义生效
        with open(p, "wb") as f:
            f.write(EML)
        r = run(["add", "--inbox", "--vault", "mailv"], _TEST_HOME)
        out = r.stdout + r.stderr
        self.assertIn("mail -> 2 part(s)", out)     # 展开数量正确
        self.assertIn("PI_BASE", out)               # 无网关 -> 部件摄取失败
        self.assertEqual(r.returncode, 1)
        failed = os.listdir(vault.failed)
        # 邮件原件 + 2 个部件全部隔离进 .failed/，不静默丢弃
        self.assertTrue(any(f.startswith("c") and f.endswith(".eml")
                            for f in failed), failed)
        self.assertTrue(any("budget" in f for f in failed), failed)

    # -------------------------------------------------- watch 强化 ----
    def test_05_pending_order_and_age_guard(self):
        import time
        d = os.path.join(_TEST_HOME, "inbox-order")
        os.makedirs(d, exist_ok=True)
        # 名字乱序、真实到达序 zzz→aaa→mmm：utime 改不了 ctime，
        # 用创建间隔（>1s，兼容无纳秒精度文件系统）拉开真实 ctime。
        for name in ("zzz.txt", "aaa.txt", "mmm.txt"):
            with open(os.path.join(d, name), "w") as f:
                f.write(name)
            time.sleep(1.1)
        got = [os.path.basename(x) for x in L.pending(d)]
        self.assertEqual(got, ["zzz.txt", "aaa.txt", "mmm.txt"])  # 到达序而非字母序
        # 刚写入的文件在龄期内被跳过
        fresh = os.path.join(d, "fresh.txt")
        with open(fresh, "w") as f:
            f.write("x")
        self.assertNotIn(fresh, L.pending(d, min_age=3600))
        self.assertIn(fresh, L.pending(d, min_age=0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
