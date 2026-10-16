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
echo "== M1b knowledge weaving (summaries/refine gates/relations, 28 tests)"
python3 -W ignore::ResourceWarning tests/test_weave.py -q || rc=1
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
