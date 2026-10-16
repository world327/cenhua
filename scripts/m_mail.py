#!/usr/bin/env python3
"""m_mail.py — 邮件摄取展开（M1b §4.4，唯一归属）。

.eml（RFC 822/2822，标准库 email）与 .msg（Outlook OLE，olefile）都不是
引擎可索引格式：本模块把邮件**展开**成可摄取的部件——
  * 正文 -> 一份 Markdown（主题/发件人/日期/收件人 抬头 + 正文文本）；
  * 附件 -> 逐个还原成文件（仅 m_lib.EXTS 支持的类型；其余类型在正文
    清单化留痕，不静默丢弃）。

展开产物落 <vault>/meta/mail/<sha1前12>/ 下（派生产物，internal-artifact；
原件由调用方归档进 sources/）。每个部件独立走 ingest_one()：单附件失败
进 .failed/ 不拖垮整封邮件。olefile 缺失时 .msg 明确报错，.eml 不受影响。
"""

import email
import email.policy
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402

MAIL_EXTS = (".eml", ".msg")


def is_mail(path):
    return os.path.splitext(path)[1].lower() in MAIL_EXTS


def _safe_name(name, fallback):
    """附件名消毒：去路径分隔与危险字符，限长，空则用 fallback。"""
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[^\w.\- \u4e00-\u9fff]", "_", name).strip() or fallback
    return name[:120]


def _desugar(s):
    """去掉 <a@b.c> 形式的尖括号（-> (a@b.c)）。

    原因：markdown 会把尖括号邮箱自动链接成 <a href="&#109;&#97;...">，
    引擎 html_to_pdf 的完整性校验按"去标签后的 HTML 文本"计数字符数，
    实体编码（每个 ~7 字符）让期望值虚高，PDF 真实字符永远达不到 85%，
    短邮件必现 `layout integrity check failed`。引擎字节级不动，
    生产端消毒是正解。
    """
    return re.sub(r"<([^<>\s@]+@[^<>\s@]+)>", r"(\1)", s or "")


def _mail_md(headers, body_text, attachments, failed_attachments):
    """邮件 -> Markdown（抬头 + 正文 + 附件清单）。"""
    lines = [f"# {_desugar(headers.get('subject')) or '(无主题)'}", ""]
    for k in ("from", "date", "to", "cc"):
        if headers.get(k):
            lines.append(f"- **{k}**: {_desugar(headers[k])}")
    lines += ["", "## 正文", "", _desugar(body_text).strip() or "(无正文文本)"]
    names = [a["name"] for a in attachments]
    names += [f"{n}（展开失败）" for n in failed_attachments]
    if names:
        lines += ["", "## 附件清单", ""] + [f"- {n}" for n in names]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- .eml ----
def _expand_eml(data):
    """RFC 822 邮件 -> (headers dict, body_text, [(name, bytes)], [失败名])."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    headers = {
        "subject": str(msg.get("Subject") or "").strip(),
        "from": str(msg.get("From") or "").strip(),
        "date": str(msg.get("Date") or "").strip(),
        "to": str(msg.get("To") or "").strip(),
        "cc": str(msg.get("Cc") or "").strip(),
    }
    body = None
    attachments, failed = [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = (part.get_content_disposition() or "").lower()
        fn = part.get_filename()
        ctype = part.get_content_type()
        if disp == "attachment" or (fn and ctype != "text/plain"
                                    and ctype != "text/html"):
            if fn:
                try:
                    payload = part.get_payload(decode=True) or b""
                except Exception:
                    payload = None
                if payload is None:
                    failed.append(_safe_name(fn, "attachment"))
                    continue
                attachments.append((_safe_name(fn, "attachment"), payload))
            continue
        if ctype == "text/plain" and body is None:
            try:
                body = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                body = payload.decode("utf-8", "replace")
        elif ctype == "text/html" and body is None:
            # 无纯文本部件时从 HTML 粗取文本（规则优先，够用即可）
            try:
                html = part.get_content()
            except Exception:
                html = (part.get_payload(decode=True) or b"").decode(
                    "utf-8", "replace")
            body = re.sub(r"<[^>]+>", " ", html)
    return headers, body or "", attachments, failed


# ------------------------------------------------------------- .msg ----
# Outlook OLE 属性类型（[MS-OXMSG]）
_MSG_W = 0x001F       # UTF-16 字符串
_MSG_T = 0x001E       # ASCII 字符串
_MSG_BINARY = 0x0102  # 二进制


def _msg_props(ole):
    """收集顶层消息属性 {prop_id: {type: bytes}}（仅 __properties_version1.0，
    不含附件表；附件流按 entry[0] 过滤）。"""
    props = {}
    for entry in ole.listdir():
        if len(entry) != 2 or not entry[1].startswith("__substg1.0_"):
            continue
        if not entry[0].startswith("__properties_version"):
            continue
        leaf = entry[1]
        try:
            pid, ptype = leaf[-8:-4], int(leaf[-4:], 16)
        except ValueError:
            continue
        try:
            data = ole.openstream(entry).read()
        except Exception:
            continue
        props.setdefault(pid, {})[ptype] = data
    return props


def _msg_text(props, pid):
    d = props.get(pid, {})
    if _MSG_W in d:
        return d[_MSG_W].decode("utf-16-le", "replace").strip("\x00")
    if _MSG_T in d:
        return d[_MSG_T].decode("utf-8", "replace").strip("\x00")
    return ""


def _expand_msg(data):
    """Outlook .msg -> (headers, body, [(name, bytes)], [失败名])。

    取常规消息属性表（__properties_version1.0 的顶层流即可覆盖
    subject/body/发件人）；附件表 __attach_version1.0_XXXX 逐个还原。
    RTF 压缩正文（1009）不做解压，仅在无纯文本时声明缺失。
    """
    try:
        import olefile
    except ImportError:
        raise RuntimeError(
            "olefile not installed — run: cenhua setup "
            "(or pip install olefile)")
    import io
    if not olefile.isOleFile(io.BytesIO(data)):
        raise RuntimeError("not a real OLE .msg file")
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        props = _msg_props(ole)
        headers = {
            "subject": _msg_text(props, "0037"),
            "from": _msg_text(props, "0C1A"),
            "date": _msg_text(props, "0039"),
            "to": _msg_text(props, "0E04"),
            "cc": _msg_text(props, "0E03"),
        }
        body = _msg_text(props, "1000")
        attachments, failed = [], []
        # 附件表：__attach_version1.0_XXXXXXXX/ 下的流（2 层结构）
        attach_dirs = {}
        for entry in ole.listdir():
            if len(entry) == 2 and entry[0].startswith("__attach_version"):
                attach_dirs.setdefault(entry[0], {})[entry[1]] = \
                    ole.openstream(entry).read()
        for dname, streams in sorted(attach_dirs.items()):
            ap = {}
            for leaf, raw in streams.items():
                if leaf.startswith("__substg1.0_"):
                    try:
                        ap.setdefault(leaf[-8:-4], {})[int(leaf[-4:], 16)] = raw
                    except ValueError:
                        pass
            name = (_msg_text(ap, "0F01") or _msg_text(ap, "3707")
                    or f"attachment-{len(attachments)}")
            # 附件内容流：0E20=嵌入对象，3701=附件二进制
            blob = (ap.get("0E20", {}).get(_MSG_BINARY)
                    or ap.get("3701", {}).get(_MSG_BINARY))
            if blob is None:
                failed.append(_safe_name(name, "attachment"))
                continue
            attachments.append((_safe_name(name, "attachment"), blob))
    finally:
        ole.close()
    return headers, body, attachments, failed


# ------------------------------------------------------------ 展开 ----
def expand(vault, path, digest):
    """邮件 -> 可摄取部件列表。

    返回 (parts, fails)：
      parts = [{"kind": "mail"|"attach", "path": 展开产物路径, "name": 展示名}]
      fails = [附件名]（展开失败/不支持的附件，已在正文清单留痕）
    解析失败抛异常（调用方按摄取失败隔离）。
    """
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        data = f.read()
    if ext == ".eml":
        headers, body, attachments, failed = _expand_eml(data)
    elif ext == ".msg":
        headers, body, attachments, failed = _expand_msg(data)
    else:
        raise ValueError(f"not a mail file: {ext}")

    out_dir = os.path.join(vault.meta, "mail", digest[:12])
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    stem_safe = _safe_name(stem, "mail")

    # 附件只展开 CENHUA 支持的类型；其余进"留痕清单"
    # （注意 is_supported 吃完整文件名：splitext(".csv") 会把裸扩展名
    #  当隐藏文件返回空扩展）
    keep, dropped = [], []
    for name, blob in attachments:
        if L.is_supported(name):
            keep.append((name, blob))
        else:
            dropped.append(name)
    md = _mail_md(headers, body,
                  [{"name": n} for n, _ in keep], failed + dropped)
    mail_path = os.path.join(out_dir, f"{stem_safe}.md")
    with open(mail_path, "w", encoding="utf-8") as f:
        f.write(md)
    parts = [{"kind": "mail", "path": mail_path,
              "name": f"{stem_safe}（邮件正文）.md"}]
    for i, (name, blob) in enumerate(keep):
        apath = os.path.join(out_dir, f"att{i:02d}-{name}")
        with open(apath, "wb") as f:
            f.write(blob)
        parts.append({"kind": "attach", "path": apath, "name": name})
    return parts, failed + dropped
