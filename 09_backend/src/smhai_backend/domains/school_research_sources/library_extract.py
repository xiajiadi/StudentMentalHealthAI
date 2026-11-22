"""Bounded, text-only extraction subprocess for school library uploads."""

from __future__ import annotations

import logging
import re
import sys
import xml.etree.ElementTree as ET
from typing import BinaryIO
from zipfile import ZipFile

MAX_TEXT = 240_000
WORD_P = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
WORD_T = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def extract(content: BinaryIO, suffix: str, wheel: str = "") -> str:
    if suffix == ".pdf":
        if content.read(5) != b"%PDF-":
            raise ValueError("invalid PDF signature")
        content.seek(0)
        if wheel:
            sys.path.insert(0, wheel)
        from pypdf import PdfReader

        reader = PdfReader(content, strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 300:
            raise ValueError("unsupported PDF")
        pages = []
        size = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            size += len(text)
            if size > MAX_TEXT:
                raise ValueError("document text is too large")
            pages.append(text)
        result = "\n\n".join(pages)
    elif suffix == ".docx":
        with ZipFile(content) as archive:
            names = archive.namelist()
            if names.count("word/document.xml") != 1 or len(names) > 300:
                raise ValueError("invalid Word document")
            info = archive.getinfo("word/document.xml")
            if info.file_size > 4_000_000 or any("vbaproject" in name.lower() for name in names):
                raise ValueError("unsupported Word document")
            with archive.open(info) as source:
                xml = source.read(4_000_001).decode("utf-8-sig")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise ValueError("invalid Word XML")
        root = ET.fromstring(xml)
        result = "\n".join("".join(node.text or "" for node in para.iter(WORD_T)) for para in root.iter(WORD_P))
    elif suffix in {".txt", ".md"}:
        result = content.read(MAX_TEXT * 4 + 1).decode("utf-8-sig")
        if content.read(1):
            raise ValueError("document text is too large")
    else:
        raise ValueError("unsupported file type")
    result = re.sub(r"[^\S\n]+", " ", result.replace("\r\n", "\n").replace("\r", "\n"))
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    if "\0" in result or not 20 <= len(result) <= MAX_TEXT:
        raise ValueError("no usable text or document text is too large")
    return result


def main() -> int:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    logging.disable(logging.CRITICAL)
    try:
        extracted = extract(sys.stdin.buffer, sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    except ImportError:
        return 3
    except Exception:
        return 2
    sys.stdout.buffer.write(extracted.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
