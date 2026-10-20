# -*- coding: utf-8 -*-
"""CENHUA Web UI / 局域网 API 适配层（M3b v0.5）。

定位（roadmap §3.3）：薄包装在 service 层上——本包只做 HTTP/HTML/SSE
协议转换，零业务逻辑；M3b 失败产品仍是完整 CLI。
依赖 fastapi/jinja2/uvicorn 全部延迟导入，CLI 用户零成本。
"""
