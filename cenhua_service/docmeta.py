# -*- coding: utf-8 -*-
"""文档级用户标注（tags/notes）— 编织页最小 service 面（M3b 任务 4）。

存储：meta/docmeta.json  {doc_id: {"tags": [...], "note": "..."}}
- 缺失/损坏视为"无标注"降级返回 {}，不抛（外部输入降级铁律）。
- update 走 tmp+fsync+rename 原子写（AGENTS §1）。
- 不碰 store.json：标注与摄取元数据分层，互不覆盖。
"""
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

FILE = "docmeta.json"


@dataclass
class DocMeta:
    doc_id: str
    tags: List[str] = field(default_factory=list)
    note: str = ""


def _path(vault) -> str:
    return os.path.join(vault.meta, FILE)


def load(vault) -> dict:
    """全量标注表；缺失/损坏 -> {}（降级不抛）。"""
    try:
        with open(_path(vault), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(vault, doc_id: str) -> DocMeta:
    d = load(vault).get(doc_id) or {}
    tags = [str(t) for t in d.get("tags", []) if str(t).strip()]
    return DocMeta(doc_id=doc_id, tags=tags, note=str(d.get("note", "")))


def update(vault, doc_id: str, tags: Optional[List[str]] = None,
           note: Optional[str] = None) -> DocMeta:
    """None = 该字段不改；tags 去空去重保序；原子写。"""
    data = load(vault)
    entry = dict(data.get(doc_id) or {})
    if tags is not None:
        seen, clean = set(), []
        for t in tags:
            t = str(t).strip()
            if t and t not in seen:
                seen.add(t)
                clean.append(t)
        entry["tags"] = clean
    if note is not None:
        entry["note"] = str(note)
    entry.setdefault("tags", [])
    entry.setdefault("note", "")
    data[doc_id] = entry
    os.makedirs(vault.meta, exist_ok=True)
    tmp = _path(vault) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, _path(vault))
    return get(vault, doc_id)
