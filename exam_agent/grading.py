"""Grade uploaded OMR responses against the answer table and export results."""

import re
from dataclasses import dataclass
from io import BytesIO
from statistics import mean, median, pstdev
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import pdfplumber
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from pdfminer.pdfdocument import PDFException
from pdfminer.psparser import PSException
from pdfplumber.utils.exceptions import PdfminerException


CHOICES = {str(number): number for number in range(1, 6)}
CHOICES.update(dict(zip("①②③④⑤", range(1, 6))))
KEY_COLUMNS = ["문항번호", "정답", "배점"]


@dataclass(frozen=True)
class StudentResult:
    student_id: str
    score: int
    correct: tuple[bool, ...]


@dataclass(frozen=True)
class MissedQuestion:
    number: int
    incorrect_count: int


@dataclass(frozen=True)
class ExamResult:
    students: tuple[StudentResult, ...]
    question_numbers: tuple[int, ...]
    max_score: int
    mean: float
    median: float
    stdev: float
    top_missed: tuple[MissedQuestion, ...]

    @property
    def lowest_students(self) -> tuple[StudentResult, ...]:
        lowest_score = min(student.score for student in self.students)
        return tuple(student for student in self.students if student.score == lowest_score)


def _read_answer_key(content: bytes) -> dict[int, tuple[int, int]]:
    answer_key: dict[int, tuple[int, int]] = {}
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    headers = ["".join((cell or "").split()) for cell in table[0]]
                    if len(headers) % 3 or headers != KEY_COLUMNS * (len(headers) // 3):
                        continue
                    for row in table[1:]:
                        for column in range(0, len(headers), 3):
                            number, answer, points = ((cell or "").strip() for cell in row[column:column + 3])
                            if not (number or answer or points):
                                continue
                            if not (number.isdecimal() and answer in CHOICES and points.isdecimal()):
                                raise ValueError("정답 PDF의 표에서 문항 번호, 정답 또는 배점을 읽을 수 없습니다.")
                            question = int(number)
                            score = int(points)
                            if question < 1 or score < 1:
                                raise ValueError("정답 PDF의 문항 번호와 배점은 양의 정수여야 합니다.")
                            if question in answer_key:
                                raise ValueError(f"정답 PDF에 {question}번 문항이 중복되어 있습니다.")
                            answer_key[question] = (CHOICES[answer], score)
    except (PDFException, PSException, PdfminerException) as error:
        raise ValueError("정답 파일을 읽을 수 없습니다. 열 수 있는 PDF 파일인지 확인해 주세요.") from error
    if not answer_key:
        raise ValueError("정답 PDF에서 문항 번호, 정답, 배점이 있는 표를 찾지 못했습니다.")
    return answer_key


def _omr_headers(headers: tuple, question_numbers: tuple[int, ...]) -> tuple[int, dict[int, int]]:
    student_column = None
    question_columns = {}
    for column, value in enumerate(headers):
        if value is None:
            continue
        header = str(value).strip()
        if header == "학생명":
            if student_column is not None:
                raise ValueError("OMR 엑셀에 학생명 열이 중복되어 있습니다.")
            student_column = column
            continue
        match = re.fullmatch(r"Q([0-9]+)", header, re.IGNORECASE)
        if match:
            question = int(match[1])
            if question in question_columns:
                raise ValueError(f"OMR 엑셀에 {question}번 문항 열이 중복되어 있습니다.")
            question_columns[question] = column
    if student_column is None:
        raise ValueError("OMR 엑셀에서 학생명 열을 찾지 못했습니다.")
    missing = set(question_numbers) - question_columns.keys()
    extra = question_columns.keys() - set(question_numbers)
    if missing or extra:
        missing_list = ", ".join(map(str, sorted(missing))) or "없음"
        extra_list = ", ".join(map(str, sorted(extra))) or "없음"
        raise ValueError(
            f"정답 PDF와 OMR 엑셀의 문항 번호가 다릅니다. "
            f"OMR에 없는 문항 {missing_list} / 정답 PDF에 없는 문항 {extra_list}"
        )
    return student_column, question_columns


def _read_omr(content: bytes, question_numbers: tuple[int, ...]) -> dict[str, tuple[int | None, ...]]:
    responses = {}
    try:
        workbook = load_workbook(BytesIO(content), read_only=True)
        try:
            sheet = workbook["OMR_응답"] if "OMR_응답" in workbook else workbook.active
            rows = sheet.iter_rows(values_only=True)
            student_column, question_columns = _omr_headers(next(rows, ()), question_numbers)
            for row_number, row in enumerate(rows, start=2):
                if all(value is None or value == "" for value in row):
                    continue
                raw_id = row[student_column]
                if type(raw_id) not in (str, int) or not str(raw_id).strip():
                    raise ValueError(f"OMR 엑셀 {row_number}행의 학생명을 확인해 주세요.")
                student_id = str(raw_id).strip()
                if student_id in responses:
                    raise ValueError(f"OMR 엑셀에 같은 학생명({student_id})이 중복되어 있습니다.")
                answers = []
                for question in question_numbers:
                    value = row[question_columns[question]]
                    choice = "" if value is None else str(value).strip()
                    if choice and choice not in CHOICES:
                        raise ValueError(
                            f"OMR 엑셀 {row_number}행의 {question}번 응답은 1~5 또는 빈칸이어야 합니다."
                        )
                    answers.append(CHOICES.get(choice))
                responses[student_id] = tuple(answers)
        finally:
            workbook.close()
    except (BadZipFile, InvalidFileException, KeyError, OSError, ParseError) as error:
        raise ValueError("OMR 파일을 읽을 수 없습니다. 열 수 있는 .xlsx 파일인지 확인해 주세요.") from error
    if not responses:
        raise ValueError("OMR 엑셀에서 채점할 학생 응답을 찾지 못했습니다.")
    return responses


def grade_exam(answer_pdf: bytes, omr_xlsx: bytes) -> ExamResult:
    answer_key = _read_answer_key(answer_pdf)
    question_numbers = tuple(sorted(answer_key))
    # 이번 과제는 반드시 1~45번 전체 문항을 채점해야 합니다.
    # 정답 및 배점은 계속 업로드한 PDF에서만 읽으며 코드에 고정하지 않습니다.
    expected_numbers = tuple(range(1, 46))
    if question_numbers != expected_numbers:
        missing = sorted(set(expected_numbers) - set(question_numbers))
        extra = sorted(set(question_numbers) - set(expected_numbers))
        raise ValueError(
            "정답 PDF는 1~45번 전체 문항이 필요합니다. "
            f"누락: {missing or '없음'} / 범위 밖: {extra or '없음'}"
        )
    responses = _read_omr(omr_xlsx, question_numbers)
    answers, points = zip(*(answer_key[number] for number in question_numbers))
    students = []
    missed_counts = dict.fromkeys(question_numbers, 0)
    for student_id, choices in responses.items():
        correct = tuple(choice == answer for choice, answer in zip(choices, answers))
        score = sum(point for point, is_correct in zip(points, correct) if is_correct)
        students.append(StudentResult(student_id, score, correct))
        for number, is_correct in zip(question_numbers, correct):
            missed_counts[number] += not is_correct

    scores = [student.score for student in students]
    most_missed = sorted(missed_counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    return ExamResult(
        students=tuple(students),
        question_numbers=question_numbers,
        max_score=sum(points),
        mean=float(mean(scores)),
        median=float(median(scores)),
        stdev=pstdev(scores),
        top_missed=tuple(MissedQuestion(number, count) for number, count in most_missed),
    )


def _style_header(cells: tuple) -> None:
    for cell in cells:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="215B4D")
        cell.alignment = Alignment(horizontal="center")


def export_excel(result: ExamResult) -> bytes:
    workbook = Workbook()
    overview = workbook.active
    overview.title = "전체 성적 개요"
    overview.append(("성적 지표", "결과"))
    overview.append(("학생 수", len(result.students)))
    overview.append(("만점", result.max_score))
    overview.append(("평균", result.mean))
    overview.append(("중앙값", result.median))
    overview.append(("표준편차 (모집단)", result.stdev))
    for row in range(4, 7):
        overview.cell(row, 2).number_format = "0.00"
    overview.append(())
    overview.append(("오답 순위", "문항 번호", "오답자 수"))
    for rank, question in enumerate(result.top_missed, start=1):
        overview.append((rank, question.number, question.incorrect_count))
    overview.column_dimensions["A"].width = 23
    overview.column_dimensions["B"].width = 14
    overview.column_dimensions["C"].width = 14
    _style_header(overview[1][:2])
    _style_header(overview[8])

    detail = workbook.create_sheet("학생별 채점")
    detail.append(("학생명", "점수", *(f"Q{number:02d}" for number in result.question_numbers)))
    for row, student in enumerate(result.students, start=2):
        detail.append((student.student_id, student.score, *("정답" if correct else "오답" for correct in student.correct)))
        detail.cell(row, 1).data_type = "s"
    detail.freeze_panes = "C2"
    detail.auto_filter.ref = detail.dimensions
    detail.column_dimensions["A"].width = 23
    detail.column_dimensions["B"].width = 10
    for column in range(3, detail.max_column + 1):
        detail.column_dimensions[get_column_letter(column)].width = 8
    _style_header(detail[1])

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
