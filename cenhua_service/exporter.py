"""cenhua_service.exporter — `cenhua export` 导出（M4c 任务 13，roadmap §7.5）。

Markdown / HTML / PDF 三种格式，产物落 `<vault>/works/exports/`。

复用（dev-plan §8.6 L622 登记表，**引擎字节不可改**）：
  * MD -> HTML：`webui.pages._md_to_html`（markdown tables+fenced_code，
    已去 script / on* 属性）；
  * HTML -> PDF：引擎 `scripts/engine/pi_ingest.html_to_pdf`
    （pymupdf、CJK 内置字体、宽表横排、字符数 >=85% 完整性校验；
    m_ocr.py 已有同法 import 先例）。
源文件限 works/drafts/ 内的 .md（draft/模板产物与 Web 编辑同一目录，
`draft._draft_path` 防路径穿越）。纯离线零 LLM。

rc 语义：0 成功 / 1 导出失败（含 PDF 完整性校验不过）/ 2 源文件非法。
service 纪律：零 print / 零 exit（test_70）。
"""
from __future__ import annotations

import os
import shutil
import sys

import m_lib as L  # noqa: E402  (scripts/ 在 sys.path)

EXPORT_DIR = "exports"              # <vault>/works/exports
FMTS = ("md", "html", "pdf")

_HTML_DOC = ("<!DOCTYPE html>\n<html lang=\"zh\">\n<head>\n<meta "
             "charset=\"utf-8\">\n<title>%s</title>\n"
             "<style>body{font-family:system-ui,'Noto Sans CJK SC',"
             "'Microsoft YaHei',sans-serif;max-width:860px;margin:2em auto;"
             "padding:0 1em;line-height:1.7;color:#222}"
             "table{border-collapse:collapse}th,td{border:1px solid #999;"
             "padding:4px 8px}blockquote{color:#555;border-left:3px solid "
             "#bbb;padding-left:1em;margin-left:0}</style>\n</head>\n"
             "<body>\n%s\n</body>\n</html>\n")


def exports_dir(vault) -> str:
    return os.path.join(vault.works, EXPORT_DIR)


def md_to_html_body(text: str) -> str:
    """MD -> 受限 HTML 片段（复用 pages._md_to_html，单一消毒口径）。"""
    from cenhua_service.webui.pages import _md_to_html
    return _md_to_html(text)


def _html_to_pdf(html: str, out: str) -> None:
    """引擎渲染（字节不可改；import 方式同 m_ocr.py 先例）。"""
    if L.ENGINE not in sys.path:
        sys.path.insert(0, L.ENGINE)
    from pi_ingest import html_to_pdf
    html_to_pdf(html, out)


def export(vault, file: str, fmt: str = "md"):
    """导出 works/drafts/ 下草稿为 md/html/pdf。

    返回 {"rc","lines","path"}；rc：0 成功 / 1 导出失败 / 2 源非法。
    """
    from cenhua_service import draft as D

    fmt = (fmt or "md").strip().lower()
    if fmt not in FMTS:
        return {"rc": 2, "lines": ["export: 格式需为 %s" % "/".join(FMTS)]}
    src = D._draft_path(vault, file)
    if not src or not os.path.isfile(src):
        return {"rc": 2, "lines": ["export: 源文件需是 works/drafts/ 内"
                                   "已存在的 .md（`draft --list` 查看）"]}
    with open(src, encoding="utf-8") as f:
        text = f.read()
    stem = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(exports_dir(vault), exist_ok=True)
    out = os.path.join(exports_dir(vault), stem + "." + fmt)
    try:
        if fmt == "md":
            shutil.copyfile(src, out)
        else:
            body = md_to_html_body(text)
            if fmt == "html":
                with open(out, "w", encoding="utf-8") as f:
                    f.write(_HTML_DOC % (stem, body))
                    f.flush()
                    os.fsync(f.fileno())
            else:
                _html_to_pdf(body, out)
    except Exception as exc:             # PDF 完整性校验/渲染异常都归 1
        try:
            if os.path.isfile(out):
                os.remove(out)
        except OSError:
            pass
        vault.log("export", ["fmt=%s file=%s error=%s"
                             % (fmt, os.path.basename(src),
                                type(exc).__name__)])
        return {"rc": 1, "lines": ["export: %s 导出失败（%s: %s）"
                                   % (fmt, type(exc).__name__,
                                      str(exc)[:160])]}
    vault.log("export", ["fmt=%s file=%s out=%s"
                         % (fmt, os.path.basename(src),
                            os.path.basename(out))])
    return {"rc": 0, "lines": ["+ exported %s -> works/%s/%s"
                               % (fmt.upper(), EXPORT_DIR,
                                  os.path.basename(out))],
            "path": out}


# ------------------------------------------------------------ CLI ----
USAGE = ("usage: cenhua export <works/drafts 内文件名.md> "
         "--md|--html|--pdf [OFFLINE]\n"
         "       产物 works/exports/<同名>.<fmt>")


def parse_cli(rest):
    """export CLI 参数 -> (file, fmt)（service 层解析）。"""
    rest = list(rest or [])
    fmt = ""
    for flag, val in (("--md", "md"), ("--html", "html"), ("--pdf", "pdf")):
        if flag in rest:
            fmt = val
    pos = [a for a in rest if not a.startswith("-")]
    return (pos[0] if pos else "", fmt or "md")


def flow(vault, rest):
    """`cenhua export ...` 总入口。"""
    file, fmt = parse_cli(rest)
    if not file:
        return {"rc": 2, "lines": [USAGE]}
    return export(vault, file, fmt)
