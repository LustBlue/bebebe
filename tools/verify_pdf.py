"""Проверка структуры PDF-файлов, созданных :mod:`src.report_module.pdf_writer`.

Модуль разбирает файл без внешних библиотек и проверяет:

* сигнатуру ``%PDF`` и завершающий маркер ``%%EOF``;
* наличие таблицы ``xref`` и корректность смещений всех объектов;
* наличие каталога, дерева страниц и объектов страниц;
* корректность длины потоков содержимого (``/Length``);
* распаковку потоков содержимого и наличие текстовых операторов ``BT``/``Tj``;
* декодируемость текста в кодировке WinAnsi (в том числе кириллицы).

Запуск::

    python tools/verify_pdf.py reports/report.pdf
    python tools/verify_pdf.py reports/            # все PDF каталога
"""

from __future__ import annotations

import argparse
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def decode_winansi(raw: bytes) -> str:
    """Декодировать байты строки PDF (WinAnsi + кириллица CP1251) в Unicode."""
    out: list[str] = []
    for byte in raw:
        if byte < 0x80:
            out.append(chr(byte))
        elif 0xC0 <= byte <= 0xFF:
            out.append(chr(byte - 0xC0 + 0x0410))
        elif byte == 0xA8:
            out.append("Ё")
        elif byte == 0xB8:
            out.append("ё")
        elif byte in (0x96, 0x97):
            out.append("–" if byte == 0x96 else "—")
        else:
            out.append(chr(byte))
    return "".join(out)


def unescape_pdf_string(raw: bytes) -> bytes:
    """Обратить экранирование строки PDF."""
    result = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0x5C and index + 1 < len(raw):  # обратный слэш
            nxt = raw[index + 1]
            mapping = {0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09,
                       0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
            result.append(mapping.get(nxt, nxt))
            index += 2
            continue
        result.append(byte)
        index += 1
    return bytes(result)


def verify(pdf_path: Path) -> dict:
    """Проверить структуру одного PDF-файла.

    :return: словарь с результатами проверки
    """
    data = pdf_path.read_bytes()
    report: dict = {
        "file": str(pdf_path),
        "size": len(data),
        "checks": [],
        "pages": 0,
        "text_sample": "",
        "errors": [],
    }

    def check(title: str, condition: bool, detail: str = "") -> None:
        report["checks"].append({"check": title, "passed": bool(condition),
                                 "detail": detail})
        if not condition:
            report["errors"].append(title)

    check("Сигнатура %PDF-1.4", data.startswith(b"%PDF-1.4"),
          data[:8].decode("latin-1"))
    check("Маркер конца файла %%EOF", data.rstrip().endswith(b"%%EOF"))

    # --- Таблица перекрёстных ссылок -----------------------------------
    xref_positions = [m.start() for m in re.finditer(rb"\nxref\r?\n", data)]
    check("Таблица xref присутствует", bool(xref_positions))
    if not xref_positions:
        return report

    startxref = re.search(rb"startxref\s+(\d+)", data)
    check("Ключ startxref присутствует и указывает на xref",
          bool(startxref) and int(startxref.group(1)) == xref_positions[-1] + 1,
          f"startxref={startxref.group(1).decode() if startxref else 'нет'}")

    xref_block = data[xref_positions[-1]:]
    entries = re.findall(rb"(\d{10}) (\d{5}) ([nf])", xref_block)
    check("Таблица xref содержит записи", len(entries) > 0, f"записей: {len(entries)}")

    # --- Проверка смещений объектов ------------------------------------
    bad_offsets = []
    for offset_bytes, _generation, kind in entries:
        if kind != b"n":
            continue
        offset = int(offset_bytes)
        if not re.match(rb"\d+ 0 obj", data[offset:offset + 24]):
            bad_offsets.append(offset)
    check("Все смещения объектов в xref корректны", not bad_offsets,
          f"ошибочных: {len(bad_offsets)}")

    # --- Обязательные объекты ------------------------------------------
    check("Каталог документа (/Type /Catalog) присутствует",
          b"/Type /Catalog" in data)
    check("Дерево страниц (/Type /Pages) присутствует", b"/Type /Pages" in data)

    page_objects = re.findall(rb"/Type /Page[^s]", data)
    report["pages"] = len(page_objects)
    count_match = re.search(rb"/Count (\d+)", data)
    declared = int(count_match.group(1)) if count_match else -1
    check("Число объектов страниц совпадает с /Count",
          report["pages"] == declared,
          f"страниц: {report['pages']}, /Count: {declared}")

    # --- Шрифты ---------------------------------------------------------
    for base_font in (b"/Helvetica", b"/Helvetica-Bold", b"/Courier"):
        check(f"Шрифт {base_font.decode()} объявлен", base_font in data)
    check("Кодировка WinAnsi объявлена", b"/WinAnsiEncoding" in data)

    # --- Потоки содержимого ---------------------------------------------
    streams = re.findall(
        rb"<< /Length (\d+) /Filter /FlateDecode >>\s*stream\r?\n", data
    )
    check("Потоки содержимого найдены", bool(streams),
          f"потоков: {len(streams)}")

    decoded_texts: list[str] = []
    length_errors = 0
    for match in re.finditer(
        rb"<< /Length (\d+) /Filter /FlateDecode >>\s*stream\r?\n", data
    ):
        declared_length = int(match.group(1))
        start = match.end()
        payload = data[start:start + declared_length]
        try:
            content = zlib.decompress(payload)
        except zlib.error:
            length_errors += 1
            continue
        if not content.strip().startswith(b"BT"):
            length_errors += 1
        for text_match in re.finditer(rb"\((.*?)\) Tj", content, re.DOTALL):
            decoded_texts.append(decode_winansi(unescape_pdf_string(text_match.group(1))))

    check("Значения /Length соответствуют потокам", length_errors == 0,
          f"ошибок: {length_errors}")
    check("Текстовые операторы BT/Tj присутствуют", bool(decoded_texts),
          f"строк: {len(decoded_texts)}")

    cyrillic = [text for text in decoded_texts
                if any("А" <= char <= "я" or char in "Ёё" for char in text)]
    check("Кириллица корректно закодирована", bool(cyrillic),
          f"строк с кириллицей: {len(cyrillic)}")

    report["text_sample"] = " | ".join(decoded_texts[:6])
    return report


def main(argv: list[str] | None = None) -> int:
    """Проверить один файл или все PDF указанного каталога."""
    parser = argparse.ArgumentParser(description="Проверка структуры PDF-отчётов")
    parser.add_argument("target", nargs="?", default="reports",
                        help="PDF-файл или каталог с PDF-файлами")
    parser.add_argument("-q", "--quiet", action="store_true", help="краткий вывод")
    args = parser.parse_args(argv)

    target = Path(args.target)
    if not target.is_absolute():
        target = ROOT / target

    files = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
    if not files:
        print(f"PDF-файлы не найдены: {target}")
        return 1

    failed = 0
    for pdf_path in files:
        result = verify(pdf_path)
        if not args.quiet:
            print(f"\n=== {pdf_path.name} ({result['size']} байт) ===")
            for item in result["checks"]:
                mark = "OK  " if item["passed"] else "FAIL"
                detail = f" — {item['detail']}" if item["detail"] else ""
                print(f"[{mark}] {item['check']}{detail}")
            if result["text_sample"]:
                print(f"       текст: {result['text_sample'][:160]}")
        if result["errors"]:
            failed += 1
            print(f"\n[{pdf_path.name}] не пройдено проверок: {len(result['errors'])}")
        elif not args.quiet:
            print(f"[{pdf_path.name}] структура корректна, страниц: {result['pages']}")

    print("\n" + "=" * 62)
    print(f"Проверено файлов: {len(files)}, с ошибками: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
