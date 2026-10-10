#!/usr/bin/env python3
"""Batch-verify + decode mainland China resident ID numbers (GB 11643).

Usage: id_verify.py NUM [NUM ...]   (or pipe one number per line on stdin)
Output per number: checksum OK/WRONG(expected) | region | birth date | sex

OCR commonly misreads 1-2 digits; a WRONG checksum number must NOT be used
for identity lookups without checking the original document.
"""
import sys

# Province / major-city prefixes (4-digit and common 6-digit). Extend freely.
REGION = {
    "11": "北京 Beijing", "12": "天津 Tianjin", "13": "河北 Hebei",
    "14": "山西 Shanxi", "15": "内蒙古 Inner Mongolia",
    "21": "辽宁 Liaoning", "22": "吉林 Jilin", "23": "黑龙江 Heilongjiang",
    "31": "上海 Shanghai", "32": "江苏 Jiangsu", "33": "浙江 Zhejiang",
    "34": "安徽 Anhui", "35": "福建 Fujian", "36": "江西 Jiangxi",
    "37": "山东 Shandong", "41": "河南 Henan", "42": "湖北 Hubei",
    "43": "湖南 Hunan", "44": "广东 Guangdong", "45": "广西 Guangxi",
    "46": "海南 Hainan", "50": "重庆 Chongqing", "51": "四川 Sichuan",
    "52": "贵州 Guizhou", "53": "云南 Yunnan", "54": "西藏 Tibet",
    "61": "陕西 Shaanxi", "62": "甘肃 Gansu", "63": "青海 Qinghai",
    "64": "宁夏 Ningxia", "65": "新疆 Xinjiang",
}
W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
CK = "10X98765432"

def verify(n):
    n = n.strip()
    if len(n) != 18 or not n[:17].isdigit() or n[17] not in "0123456789X":
        return f"{n} | x invalid format"
    c = CK[sum(int(a) * b for a, b in zip(n, W)) % 11]
    ok = "OK" if c == n[-1] else f"WRONG(check={c})"
    region = REGION.get(n[:2], "?")
    birth = f"{n[6:10]}-{n[10:12]}-{n[12:14]}"
    sex = "M" if int(n[16]) % 2 else "F"
    return f"{n} | {ok} | {region} code {n[:6]} | {birth} {sex}"

if __name__ == "__main__":
    args = sys.argv[1:]
    ids = args if args else [l.strip() for l in sys.stdin if l.strip()]
    bad = 0
    for n in ids:
        line = verify(n)
        print(line)
        if "WRONG" in line or "invalid" in line:
            bad += 1
    if len(ids) > 1:
        print(f"\ntotal {len(ids)}, invalid checksum {bad}" +
              (" — likely OCR misreads or masked/synthetic data; "
               "verify against originals before identity lookups" if bad else ""))
