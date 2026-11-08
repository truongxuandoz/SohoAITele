"""CLI thử nhanh không cần Telegram: bóc tin nhắn -> in preview -> (tuỳ chọn) ghi sổ.

    python -m soho.cli "p304 tt 1.480.000 chi soho"
    python -m soho.cli "chi 159k cước hotline, thu 1tr2 hoàn ứng" --write
"""

from __future__ import annotations

import argparse
import sys

from .ai import parse_message


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SoHo AI – bóc tin nhắn thành bút toán")
    ap.add_argument("text", nargs="+", help="tin nhắn cần bóc")
    ap.add_argument("--write", action="store_true", help="ghi thẳng vào sổ (không hỏi)")
    ap.add_argument("--no-context", action="store_true", help="không gửi vài dòng cuối sổ làm ngữ cảnh")
    args = ap.parse_args(argv)

    text = " ".join(args.text)
    store = None
    context_rows: list[list[str]] = []
    headers = ["Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"]

    try:
        from .sheets import build_store

        store = build_store(2)
        headers = store.headers or headers
        if not args.no_context:
            context_rows = store.tail(8)
    except Exception as exc:
        print(f"⚠️ chưa kết nối được sổ: {exc}")
        print("   (vẫn bóc được, chỉ là không có ngữ cảnh để AI học cách viết)\n")

    print(f"— Tin nhắn: {text}\n")
    items, note = parse_message(text, context_rows=context_rows, headers=headers)

    if not items:
        print("Không bóc được bút toán nào.")
        return 1

    width = max((len(i.noi_dung) for i in items), default=10)
    print(f"{'#':>2}  {'Nội dung':<{width}}  {'Thu':>12}  {'Chi':>12}  Ngày      Ghi chú")
    for idx, item in enumerate(items, 1):
        thu = f"{item.thu:,}".replace(",", ".") if item.thu else ""
        chi = f"{item.chi:,}".replace(",", ".") if item.chi else ""
        print(
            f"{idx:>2}  {item.noi_dung:<{width}}  {thu:>12}  {chi:>12}  "
            f"{item.ngay_thang or '':<9} {item.ghi_chu}"
        )

    if note:
        print(f"\nAI ghi chú: {note}")

    if args.write:
        if store is None:
            print("\n❌ Không có sổ để ghi.")
            return 1
        written = store.append([i.as_row() for i in items])
        print(f"\n✅ Đã ghi {len(written)} dòng vào sổ: {written}")
    else:
        print("\n(dry-run) thêm --write để ghi thật vào sổ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
