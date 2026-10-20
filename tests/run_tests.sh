#!/usr/bin/env bash
# Run every CENHUA test suite (all offline, no API keys).
set -uo pipefail
cd "$(dirname "$0")/.."
rc=0
echo "== unit (24 tests, real pi_flatten/pi_query offline halves)"
python3 -W ignore::ResourceWarning tests/test_cenhua.py -q || rc=1
echo
echo "== M1a service layer (cost/verify/bench, 19 tests)"
python3 -W ignore::ResourceWarning tests/test_service.py -q || rc=1
echo
echo "== M2a web ingestion (robots/rate-limit/render/artifacts, 24 tests)"
python3 -W ignore::ResourceWarning tests/test_web.py -q || rc=1
echo
echo "== M1b mail intake + watch hardening (5 tests)"
python3 -W ignore::ResourceWarning tests/test_mail.py -q || rc=1
echo
echo "== M1b knowledge weaving (summaries/refine gates/relations/ROI, 33 tests)"
python3 -W ignore::ResourceWarning tests/test_weave.py -q || rc=1
echo
echo "== M2b query (4-section/two-part hint/snippet/tier/refusal+injection gate, 46 tests)"
python3 -W ignore::ResourceWarning tests/test_query.py -q || rc=1
echo
echo "== M3a jobs channel (submit/status/result/stale/wait, 10 tests)"
python3 -W ignore::ResourceWarning tests/test_jobs.py -q || rc=1
echo
echo "== M3a core service (ingest/find/query/related/ask/stats, 14 tests)"
python3 -W ignore::ResourceWarning tests/test_core.py -q || rc=1
echo
echo "== M3a long-job channel (channel_job/run_cli/confirm gates, 11 tests)"
python3 -W ignore::ResourceWarning tests/test_channel.py -q || rc=1
echo
echo "== M3a digest (window/est/hint/compose 四节/longjob 三闸/回流闭环, 27 tests)"
python3 -W ignore::ResourceWarning tests/test_digest.py -q || rc=1
echo
echo "== M3b webui (auth/rate-limit/SSE/docmeta/pages/rid, 45 tests)"
python3 -W ignore::ResourceWarning tests/test_webui.py -q || rc=1
echo
echo "== M4a knowledge graph (parse/rebuild/entity-path-cluster/Mermaid/triples gates, 49 tests)"
python3 -W ignore::ResourceWarning tests/test_graph.py -q || rc=1
echo
echo "== M4a topic draft (recall/gates/rid-idempotency/verify/extend-rewrite-diff-restore/backflow, 36 tests)"
python3 -W ignore::ResourceWarning tests/test_draft.py -q || rc=1
echo
echo "== local OCR layer (RapidOCR stubbed, real renderers)"
python3 tests/test_ocr.py 2>&1 | tail -3 || rc=1
echo
echo "== semantic layer vs mock embeddings endpoint"
python3 tests/test_vectors_live.py || rc=1
echo
echo "== real formats (md/txt/html/csv/docx/xlsx -> PDF -> grep)"
python3 tests/test_formats.py || rc=1
echo
echo "== end-to-end smoke (offline)"
bash tests/smoke.sh | tail -1 || rc=1
echo
[ $rc -eq 0 ] && echo -e "\033[32mALL SUITES PASSED\033[0m" || echo -e "\033[31mFAILURES\033[0m"
exit $rc
