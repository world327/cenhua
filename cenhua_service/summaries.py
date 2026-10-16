"""cenhua_service.summaries — deferred 总结的**规则先行层**（M1b §5.3，零 LLM）。

设计（roadmap §5.3）：摄取后不立即花 LLM 做摘要，而是先用纯规则给每篇文档
产出一份"够用"的粗总结（首段 + 正则实体 + TF 关键词 + 标题结构），落
`<vault>/meta/summaries/<doc_id>.json`，`status=rule-only`。文档被
query/related 命中后才进精化队列（refine_queue），按预算消费升级为
`status=refined`。

分层纪律：本模块**零 LLM、零网络**，纯函数 + 文件读写，不 print/exit
（service 层铁律，test_70 全量管辖；`summarize` 不是用户命令，不入
test_71 白名单——F10）。

schema_version 读侧容忍：字段只增不改，旧文件缺字段按默认处理。
"""

import json
import math
import os
import re
import time

SCHEMA_VERSION = 1
TIER = "internal-artifact"          # 派生产物：正文不进引文（可作 hint）

STATUS_RULE_ONLY = "rule-only"
STATUS_REFINED = "refined"

# ---------------------------------------------------------------- 路径 ----
def summaries_dir(vault):
    return os.path.join(vault.meta, "summaries")


def summary_path(vault, doc_id):
    return os.path.join(summaries_dir(vault), f"{doc_id}.json")


def load_summary(vault, doc_id):
    """读一份 summaries；不存在/损坏返回 None（读侧容忍）。"""
    try:
        with open(summary_path(vault, doc_id), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("schema_version", 0)
            data.setdefault("status", STATUS_RULE_ONLY)
            return data
    except (OSError, ValueError):
        pass
    return None


def save_summary(vault, doc):
    os.makedirs(summaries_dir(vault), exist_ok=True)
    tmp = summary_path(vault, doc["doc_id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, summary_path(vault, doc["doc_id"]))


# ------------------------------------------------------------ 文本清洗 ----
PAGE_MARK = re.compile(r"^(?:=== PAGE \d+ ===|第\d+页)$")


def plain_text(text_layer):
    """文本层 -> 连续正文（去页码标记、折叠空白），供规则提取。"""
    out = []
    for line in text_layer.splitlines():
        s = line.strip()
        if not s or PAGE_MARK.match(s):
            continue
        out.append(s)
    return "\n".join(out)


# ---------------------------------------------------------------- 首段 ----
MIN_PARA = 40          # 短于此的段视为标题/页眉，继续往下找


def _is_body(line):
    """正文行：够长，或以句读结尾（标题行短且无句读）。"""
    s = line.strip()
    return len(s) >= MIN_PARA or s.endswith(("。", "；", "！", "？", ".", ";"))


def first_paragraph(text):
    """第一段"有内容"的段落：跳过开头的标题行/页眉，聚合连续正文行。"""
    acc, started = [], False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if started:
                break
            continue
        if _is_body(s):
            acc.append(s)
            started = True
            if sum(len(x) for x in acc) >= 600:
                break
        elif started:
            break                    # 段落结束（遇到标题/表头）
    return "\n".join(acc)[:600]


# ---------------------------------------------------------------- 实体 ----
ENTITY_PATTERNS = {
    "money": re.compile(
        r"(?:[¥$€]\s?\d[\d,]*(?:\.\d+)?(?:\s?[万千百亿元美元]+)?"
        r"|\d[\d,]*(?:\.\d+)?\s?(?:元|万元|亿元|美元|人民币))"),
    "date": re.compile(
        r"\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?|\d{1,2}月\d{1,2}日"),
    "email": re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"),
    "id_number": re.compile(
        r"\d{17}[\dXx]"                       # 身份证
        r"|[A-Z]{2}\d{8}"                     # 护照类
        r"|\d{9,20}"                          # 合同号/账号（长数字串）
    ),
    "capitalized": re.compile(
        r"\b(?:[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*"     # CamelCase: PyMuPDF
        r"|[A-Z]{2,}[a-z]\w*"                          # 缩写开头: OpenAI
        r"|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"      # Title Case: Finance Dept
    ),
}

# 常见噪声（TF 关键词与实体共用的排除表）
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "have", "will",
    "you", "your", "our", "are", "was", "were", "not", "but", "all",
    "可以", "我们", "一个", "进行", "相关", "由于", "因此", "以及", "这些",
    "那些", "什么", "如何", "已经", "不是", "如果", "虽然", "但是", "并且",
}


def extract_entities(text, per_type=12):
    """正则实体粗提。返回 {type: [值, ...]}（去重、限量）。"""
    out = {}
    for name, pat in ENTITY_PATTERNS.items():
        seen, vals = set(), []
        for m in pat.findall(text):
            v = m if isinstance(m, str) else m[0]
            v = v.strip()
            if not v or v in seen:
                continue
            # 长数字串误报防护：纯数字要求至少 9 位（已限），金额单位词单独走 money
            seen.add(v)
            vals.append(v)
            if len(vals) >= per_type:
                break
        if vals:
            out[name] = vals
    return out


# -------------------------------------------------------------- 关键词 ----
WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}|[一-鿿]{2,6}")


def keywords(text, top=12):
    """TF 关键词：英文词 + 中文 n-gram（2~4 字滑窗按长度加权），去停用词。

    不引分词器（个人库够用、零依赖、离线）；同一片中文按不同长度计权，
    高频长词自然胜出。返回 [{"term","tf"}]，tf 为原始词频。
    """
    counts = {}
    for w in WORD.findall(text.lower()):
        if w in STOPWORDS:
            continue
        if re.match(r"^[一-鿿]+$", w):
            # 中文段：整段（<=6 字）+ 2/3-gram 全计
            counts[w] = counts.get(w, 0) + 2
            n = len(w)
            for k in (2, 3):
                for i in range(max(0, n - k + 1)):
                    g = w[i:i + k]
                    if g not in STOPWORDS:
                        counts[g] = counts.get(g, 0) + 1
        else:
            if len(w) < 2:
                continue
            counts[w] = counts.get(w, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"term": t, "tf": c} for t, c in ranked[:top]]


# ---------------------------------------------------------------- 标题 ----
HEADING = re.compile(r"^(#{1,4}\s+.+|[A-Z][A-Za-z0-9 \-,.:&/()']{4,}|"
                     r"\d+(?:\.\d+)*\s+\S.+|[一二三四五六七八九十]+[、.]\S.+)$")
# 中文标题形态：短行、无句读（正文句必有标点）
CJK_TITLE = re.compile(r"^[一-鿿A-Za-z0-9 ]{3,24}$")


def headings(text, top=15):
    """标题结构：markdown 标题 / 全大写行 / 编号小节 / 中文短标题行。"""
    out, seen = [], set()
    for line in text.splitlines():
        s = line.strip()
        if not (3 <= len(s) <= 120) or s in seen:
            continue
        if s.endswith(("。", "；", "，", "、", ".", ";", ",", "：", ":")):
            continue                                  # 句子，不是标题
        if HEADING.match(s) or CJK_TITLE.match(s):
            seen.add(s)
            out.append(s.lstrip("# ").strip())
            if len(out) >= top:
                break
    return out


# ------------------------------------------------------------ 规则总结 ----
def rule_summarize(doc_id, name, text_layer):
    """单文档规则先行总结（纯函数，无 IO）。

    返回 summaries dict（status=rule-only, tier=internal-artifact）。
    """
    text = plain_text(text_layer)
    est_in = max(1, math.ceil(len(text) / 2.6))     # 精化估价用（CJK≈2.6字/token）
    return {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "name": name,
        "ts": time.strftime("%F %T"),
        "status": STATUS_RULE_ONLY,
        "tier": TIER,
        "title": (headings(text, top=1) or [""])[0],
        "first_paragraph": first_paragraph(text),
        "entities": extract_entities(text),
        "keywords": keywords(text),
        "headings": headings(text),
        "chars": len(text),
        "tokens_estimate": est_in,
        "refined": None,
    }


def refresh(vault, doc_id, name, text_layer):
    """生成并落盘规则总结；已有 refined 结果时只补元数据不降级（幂等）。"""
    old = load_summary(vault, doc_id)
    if old and old.get("status") == STATUS_REFINED:
        return old
    doc = rule_summarize(doc_id, name, text_layer)
    save_summary(vault, doc)
    return doc


def ensure_all(vault, store_docs, read_text):
    """为所有缺总结的文档补规则层（离线、零 LLM）。

    store_docs: {doc_id: {"name": ...}}；read_text(doc_id) -> str|None。
    返回 {"rule-only": n, "skipped": m}。
    """
    made = skipped = 0
    for doc_id, rec in sorted(store_docs.items()):
        if load_summary(vault, doc_id):
            skipped += 1
            continue
        text = read_text(doc_id)
        if not text:
            skipped += 1
            continue
        refresh(vault, doc_id, rec.get("name", doc_id), text)
        made += 1
    return {"rule-only": made, "skipped": skipped}
