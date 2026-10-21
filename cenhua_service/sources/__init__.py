# -*- coding: utf-8 -*-
"""cenhua_service.sources — 多源摄取（M5-4）。

适配器模式：Source ABC 定义 fetch() 统一接口，子类负责把数据拉进 inbox/，
之后复用 core.ingest 链路（引擎 + flatten 文本层，既 dedupe 又增量）。

注册表 + vault.yaml 解析：站点级配置走 vault.yaml `sources[]`，走 vault.cfg()
读取，优先级 env > vault.yaml（与 web_host/web_port 同机制）。

依赖策略：
- feedparser（rss）必需（轻量 60KB）
- boto3（s3）、lark-oapi（feishu）可选；未装时源自动禁用，不影响其他源
- webhook 零依赖

service 纪律：零 print / 零 exit（test_70）。
"""
from __future__ import annotations

import abc
import dataclasses
import json
import os
import re
from typing import List, Optional

import m_lib as L  # noqa: E402  (scripts/ 在 sys.path)

# -------------------------------------------------------------- 注册表 ---
_REGISTRY: dict[str, type["Source"]] = {}


def register(cls: type["Source"]):
    """按 Source._type 注册子类；子类定义后自动调用（无显式注册开销）。"""
    _REGISTRY[cls._type] = cls
    return cls


def get_source_type(name: str) -> Optional[type["Source"]]:
    return _REGISTRY.get(name)


def list_source_types() -> list[str]:
    return sorted(_REGISTRY.keys())


# -------------------------------------------------------------- ABC ---
class Source(abc.ABC):
    """多源适配器基类。

    子类必实现：_type（注册键）、fetch(vault, cfg) -> SourceResult。
    cfg 是 vault.yaml `sources[]` 的 dict 项，已解析为普通 Python dict。
    """

    _type: str = ""          # 子类覆盖，如 "rss" / "webhook"

    @abc.abstractmethod
    def fetch(self, vault, cfg: dict) -> "SourceResult":
        """拉取一次。返回 SourceResult；rc=1 表示拉取失败（不影响同批其他源）。"""

    # ---- 通用工具 ----
    @staticmethod
    def _sanitize_filename(name: str, max_len: int = 120) -> str:
        """文件名安全化：去 OS 非法字符 + 截断 + 保留扩展名。"""
        name = re.sub(r"[\\/:*?\"<>|]", "_", name or "untitled")
        name = name.strip(" ._-") or "untitled"
        if len(name) > max_len:
            name = name[:max_len].rsplit(".", 1)[0]
        return name

    @staticmethod
    def _append_to_inbox(vault, filename: str, content: bytes) -> str:
        """通用：把字节写进 inbox，同名时间戳避让，返回绝对路径。"""
        safe = Source._sanitize_filename(filename)
        dest = os.path.join(vault.inbox, safe)
        if os.path.exists(dest):
            root, ext = os.path.splitext(safe)
            dest = os.path.join(vault.inbox,
                                "%s.%d%s" % (root, int(__import__("time").time()),
                                             ext))
        with open(dest, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())               # 文件可见性（flush+fsync）
        return dest


@dataclasses.dataclass
class SourceResult:
    """单次拉取结果。"""
    source: str = ""           # 源名
    source_type: str = ""      # 类型（rss/webhook/...）
    rc: int = 0                # 0 成功 / 1 拉取失败
    added: int = 0             # ingest 后 added 数
    dupe: int = 0              # ingest 后 dupe 数
    failed: int = 0            # ingest 后 failed 数
    lines: list = dataclasses.field(default_factory=list)
    error: str = ""


# -------------------------------------------------------------- vault.yaml 解析 ---
def parse_sources(vault) -> list[dict]:
    """从 vault.yaml `sources[]` 字段解析站点级配置。

    vault.yaml 是极简 KV（m_lib.Vault.cfg 只支持单层 key: value），
    嵌套数组无法原生表达 → 走 `sources.yaml` 附属文件
    （`<vault>/meta/sources.yaml`，YAML 格式，支持嵌套）。

    找不到 sources.yaml → 空列表（fail-closed：未配置 = 不触发任何源）。
    """
    import yaml as _yaml
    meta = os.path.join(vault.root, "meta")
    cfg_path = os.path.join(meta, "sources.yaml")
    if not os.path.isfile(cfg_path):
        return []
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            raw = _yaml.safe_load(fh) or {}
        sources = raw.get("sources") or []
        return [s for s in sources
                if isinstance(s, dict) and s.get("type") in _REGISTRY]
    except Exception as exc:
        vault.log("sources", ["sources.yaml 解析失败: %s" % type(exc).__name__])
        return []


def _ensure_yaml_available():
    """启动时确认 PyYAML 可用，否则 sources 静默禁用。"""
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


# -------------------------------------------------------------- sources_state.json ---
def _state_path(vault) -> str:
    return os.path.join(vault.meta, "sources_state.json")


def load_state(vault) -> dict:
    """读/写 sources_state.json（每源 last_seen/last_success/last_error）。"""
    return L.read_json(_state_path(vault), {}) or {}


def save_state(vault, state: dict) -> None:
    """原子写 sources_state.json（flock + 临时文件 rename，零竞态）。"""
    import fcntl, tempfile
    os.makedirs(vault.meta, exist_ok=True)
    lock_path = _state_path(vault) + ".lock"
    try:
        lock = open(lock_path, "w")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        fd, tmp = tempfile.mkstemp(
            dir=os.path.dirname(_state_path(vault)), suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, _state_path(vault))
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
    except Exception:
        pass
    finally:
        try: lock.close()
        except Exception: pass
