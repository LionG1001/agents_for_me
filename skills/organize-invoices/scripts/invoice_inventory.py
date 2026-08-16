#!/usr/bin/env python3
"""中国电子发票 PDF 只读盘点工具。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover - 取决于运行环境
    raise SystemExit("缺少 pdfplumber，请运行：python -m pip install pdfplumber") from exc


INVOICE_NUMBER_RE = re.compile(
    r"(?:发票\s*号码|发\s*票\s*号\s*码)\s*[：:]\s*(\d{20})"
)
ANY_20_DIGIT_RE = re.compile(r"(?<!\d)(\d{20})(?!\d)")
DATE_RE = re.compile(r"(20\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?")
CURRENCY_RE = re.compile(r"[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)")


def read_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text(x_tolerance=2, y_tolerance=3) or "" for page in pdf.pages)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def extract_date(text: str) -> str | None:
    normalized = text.translate(str.maketrans({"⽉": "月", "⽇": "日"}))
    marker = re.search(r"开票\s*日期\s*[：:]?([\s\S]{0,50})", normalized)
    match = DATE_RE.search(marker.group(1)) if marker else None
    if not match:
        match = DATE_RE.search(normalized)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def extract_amount(text: str) -> float | None:
    values = CURRENCY_RE.findall(text)
    return float(values[-1]) if values else None


def classify(text: str, path: Path) -> str:
    joined = f"{path.name}\n{text}"
    if re.search(r"滴滴|行程单|交通运输服务|客运服务|出租车", joined):
        return "交通"
    if re.search(r"水果|蔬菜|食用菌|肉及肉制品", joined) and not re.search(
        r"餐饮服务|餐饮费|餐费", joined
    ):
        return "其他"
    if re.search(r"方便食品|熟肉制品|熟食|即食|炸带鱼", joined):
        return "餐饮"
    if re.search(r"餐费|餐饮费|餐饮服务|软饮料|包装费", joined):
        return "餐饮"
    if re.search(r"配送服务|配送费|配送相关", joined):
        return "配送"
    return "其他"


def inspect(path: Path) -> dict[str, object]:
    try:
        text = read_text(path)
        number = first_match(INVOICE_NUMBER_RE, text) or first_match(ANY_20_DIGIT_RE, text)
        return {
            "path": str(path),
            "invoice_number": number,
            "issue_date": extract_date(text),
            "amount": extract_amount(text),
            "category": classify(text, path),
            "sha256": sha256(path),
            "error": None,
        }
    except Exception as exc:  # 单个文件失败时继续盘点其他文件
        return {
            "path": str(path),
            "invoice_number": None,
            "issue_date": None,
            "amount": None,
            "category": "未知",
            "sha256": sha256(path),
            "error": repr(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="包含发票 PDF 的目录")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    parser.add_argument(
        "--fail-on-duplicates",
        action="store_true",
        help="发现同一发票号码出现多次时返回退出码 2",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        parser.error(f"不是目录：{args.root}")

    records = [inspect(path) for path in sorted(args.root.rglob("*.pdf"))]
    by_number: dict[str, list[str]] = defaultdict(list)
    for record in records:
        number = record["invoice_number"]
        if isinstance(number, str):
            by_number[number].append(str(record["path"]))
    duplicates = {number: paths for number, paths in by_number.items() if len(paths) > 1}

    summary = {
        "PDF数量": len(records),
        "已识别号码数量": sum(record["invoice_number"] is not None for record in records),
        "唯一发票号码数量": len(by_number),
        "重复发票号码数量": len(duplicates),
        "错误数量": sum(record["error"] is not None for record in records),
    }

    if args.json:
        localized_records = [
            {
                "路径": record["path"],
                "发票号码": record["invoice_number"],
                "开票日期": record["issue_date"],
                "金额": record["amount"],
                "类别": record["category"],
                "SHA256": record["sha256"],
                "错误": record["error"],
            }
            for record in records
        ]
        print(
            json.dumps(
                {"汇总": summary, "重复发票": duplicates, "明细": localized_records},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("发票号码\t开票日期\t金额\t类别\t路径")
        for record in records:
            amount = "" if record["amount"] is None else f"{record['amount']:.2f}"
            print(
                "\t".join(
                    [
                        str(record["invoice_number"] or ""),
                        str(record["issue_date"] or ""),
                        amount,
                        str(record["category"]),
                        str(record["path"]),
                    ]
                )
            )
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)

    return 2 if args.fail_on_duplicates and duplicates else 0


if __name__ == "__main__":
    raise SystemExit(main())
