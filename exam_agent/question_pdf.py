"""Extract the source text of a numbered question from an exam PDF."""

from collections.abc import Iterator
from io import BytesIO
import re

import pdfplumber
from pdfminer.pdfdocument import PDFException
from pdfminer.psparser import PSException
from pdfplumber.pdf import PDF
from pdfplumber.utils.exceptions import PdfminerException


ITEM_START = re.compile(r"^(\d{1,3})\.(?:\s|$)")
SHARED_START = re.compile(r"^\[(\d{1,3})\s*[~～∼–-]\s*(\d{1,3})\]")
EXAM_NOTICES = (
    "* 확인 사항",
    "이제 듣기 문제가 끝났습니다.",
    "이 문제지에 관한 저작권",
)


class QuestionTextUnavailable(ValueError):
    """A readable PDF does not contain the requested question as text."""


def _question_lines(pdf: PDF) -> Iterator[str]:
    for page in pdf.pages:
        left, top, right, bottom = page.bbox
        midpoint = (left + right) / 2
        dividers = (
            edge
            for edge in page.edges
            if edge["orientation"] == "v"
            and abs(edge["x0"] - midpoint) <= page.width * 0.02
            and edge["height"] >= page.height * 0.6
        )
        divider = max(dividers, key=lambda edge: edge["height"], default=None)
        columns = (page,)
        if divider is not None:
            center = divider["x0"]
            top, bottom = divider["top"], divider["bottom"]
            columns = (
                page.crop((left, top, center, bottom)),
                page.crop((center, top, right, bottom)),
            )

        for column in columns:
            for line in column.extract_text(x_tolerance=2).splitlines():
                if line.strip():
                    yield line.strip()


def extract_question(pdf_bytes: bytes, item_number: int) -> str:
    """Return a numbered question and its shared instructions or passage."""
    shared_lines: list[str] = []
    item_lines: list[str] = []
    reading_shared = False

    try:
        with BytesIO(pdf_bytes) as source, pdfplumber.open(source) as pdf:
            if not pdf.pages:
                raise ValueError("문제지 PDF에 페이지가 없습니다.")
            for line in _question_lines(pdf):
                shared_start = SHARED_START.match(line)
                item_start = ITEM_START.match(line)
                if shared_start:
                    if item_lines:
                        break
                    first, last = map(int, shared_start.groups())
                    reading_shared = first <= item_number <= last
                    shared_lines = [line] if reading_shared else []
                elif item_start:
                    if item_lines:
                        break
                    reading_shared = False
                    if int(item_start[1]) == item_number:
                        item_lines.append(line)
                elif item_lines:
                    if line.startswith(EXAM_NOTICES):
                        break
                    item_lines.append(line)
                elif reading_shared:
                    shared_lines.append(line)
    except (PDFException, PSException, PdfminerException, ValueError) as exc:
        raise ValueError("문제지 PDF를 읽을 수 없습니다.") from exc

    if not item_lines or (len(item_lines) == 1 and ITEM_START.fullmatch(item_lines[0])):
        raise QuestionTextUnavailable(f"문제지 PDF에서 {item_number}번 문항의 텍스트를 찾을 수 없습니다.")

    if shared_lines:
        return "\n".join(shared_lines) + "\n\n" + "\n".join(item_lines)
    return "\n".join(item_lines)
