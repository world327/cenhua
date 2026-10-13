"""cenhua_service.verify — 引文校验原语（M1a，T4+F2）。

`verify_citation(doc, page, snippet) -> bool`：
  校验 snippet 归一化后确实存在于该页文本层。
  归一化：NFKC + 去空白 + 全半角折叠后正则匹配（F2）。

非"页存在"同义反复校验——引用一个存在但内容错误的页照样判 False。
门禁（cenhua bench）与草稿校验（cenhua draft --verify，M4）共用此单一事实源。

service 纪律：本模块禁止 print / exit。
"""

import re
import unicodedata

import m_lib as L  # noqa: E402


def _normalize(text):
    """NFKC 归一 + 去空白 + 全半角折叠。"""
    if not text:
        return ""
    # NFKC 归一（全角->半角、兼容字符折叠）
    t = unicodedata.normalize("NFKC", text)
    # 去所有空白（含换行、全角空格）
    t = re.sub(r"\s+", "", t)
    # 全半角折叠：把全角标点/字母折叠为半角（NFKC 已处理大部分，这里兜底）
    t = t.replace("，", ",").replace("。", ".").replace("：", ":")
    t = t.replace("；", ";").replace("（", "(").replace("）", ")")
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return t


def _page_text(vault, doc_id, page):
    """取某文档某页的文本层原文（未归一化）。"""
    pages = L.text_pages(vault, doc_id)
    for pno, text in pages:
        if str(pno) == str(page):
            return text
    return ""


def verify_citation(vault, doc, page, snippet):
    """校验 snippet 归一化后确实存在于该页文本层。

    返回 bool。snippet 为空 -> False（无 snippet 的引文在门禁计为失败，F2）。
    """
    if not snippet:
        return False
    page_text = _page_text(vault, doc, page)
    if not page_text:
        return False
    norm_page = _normalize(page_text)
    norm_snippet = _normalize(snippet)
    if not norm_snippet:
        return False
    # 归一化后正则匹配（snippet 可能被 LLM 摘录时略有截断，用 re.escape 精确匹配）
    return re.search(re.escape(norm_snippet), norm_page) is not None
