import os
from functools import partial
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from exam_agent.chat import ChatContext, answer_chat
from exam_agent.grading import export_excel, grade_exam
from exam_agent.question_pdf import QuestionTextUnavailable, extract_question


ASSETS = Path(__file__).resolve().parent / "assets"


def setting(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        try:
            value = st.secrets.get(name, default)
        except StreamlitSecretNotFoundError:
            value = default
    return str(value).strip()


def landing() -> None:
    with st.container(key="landing-hero"):
        intro, artwork = st.columns([1, 1.45], gap="large", vertical_alignment="center")
        with intro:
            st.html("""
                <p class="eyebrow"><span aria-hidden="true">🎓</span> 영어 모의고사</p>
                <h1>AI 성적분석<br>에이전트</h1>
                <p class="hero-copy">모의고사를 채점하고 성적을 살펴보세요.
                학생들이 많이 틀린 유형은 다음 수업의 연습 문제로 만들어 보세요.</p>
            """)
            if st.button("성적 분석 시작하기", icon=":material/arrow_forward:", type="primary"):
                st.switch_page(analysis_page)
        with artwork:
            st.image(
                str(ASSETS / "agent-classroom.png"),
                width="stretch",
                alt="AI 성적분석 에이전트 교실 로고",
            )

    steps = (
        ("📂", "시험 자료 올리기", "문제지, OMR 인식 결과, 정답지 세 파일을 준비합니다."),
        ("📝", "자동 채점하기", "정답지의 문항 번호·정답·배점을 읽어 학생별 점수를 계산합니다."),
        ("📊", "결과 확인하기", "엑셀로 결과를 받고, 성적이나 오답 유형을 채팅으로 물어봅니다."),
    )
    with st.container(key="landing-workflow"):
        st.header("이용 방법", anchor=False)
        for number, (column, (icon, title, detail)) in enumerate(zip(st.columns(3), steps), start=1):
            column.html(f"""
                <div class="workflow-card">
                    <div class="workflow-top">
                        <span class="emoji-tile" aria-hidden="true">{icon}</span>
                        <span class="workflow-number">STEP {number:02d}</span>
                    </div>
                    <h3>{title}</h3>
                    <p>{detail}</p>
                </div>
            """)

    with st.container(key="landing-footer"):
        st.caption("가천대학교 · 생성형 AI 활용 최종평가")


def clear_analysis() -> None:
    st.session_state.pop("analysis", None)


def run_analysis(question_file, omr_file, answer_file) -> None:
    clear_analysis()
    question_bytes = question_file.getvalue()
    try:
        if b"%PDF-" not in question_bytes[:1024]:
            raise ValueError("문제지로 읽을 수 있는 PDF 파일을 올려 주세요.")
        result = grade_exam(answer_file.getvalue(), omr_file.getvalue())
        top_missed = result.top_missed[0]
        try:
            source_question = extract_question(question_bytes, top_missed.number)
        except QuestionTextUnavailable:
            source_question = None
    except ValueError as error:
        st.error(str(error))
        return

    st.session_state.analysis = {
        "result": result,
        "source_question": source_question if top_missed.incorrect_count else None,
        "messages": [],
        "context": ChatContext(),
    }


def analysis() -> None:
    with st.sidebar:
        files_header = st.empty()
        st.caption("같은 시험의 파일 3개를 선택하거나 끌어다 놓으세요.")
        question_file = st.file_uploader(
            "문제지 · PDF",
            type=["pdf"],
            key="question_pdf",
            on_change=clear_analysis,
            max_upload_size=20,
        )
        omr_file = st.file_uploader(
            "OMR 인식 결과 · XLSX",
            type=["xlsx"],
            key="omr_xlsx",
            on_change=clear_analysis,
            max_upload_size=10,
        )
        answer_file = st.file_uploader(
            "정답지 · PDF",
            type=["pdf"],
            key="answer_pdf",
            on_change=clear_analysis,
            max_upload_size=10,
        )
        file_count = sum(file is not None for file in (question_file, omr_file, answer_file))
        ready = file_count == 3
        files_header.html(f"""
            <div class="sidebar-title">
                <h2><span aria-hidden="true">📂</span> 시험 자료</h2>
                <span class="file-count">{file_count} / 3</span>
            </div>
        """)
        if st.button("분석 시작", icon=":material/play_arrow:", type="primary", disabled=not ready, width="stretch"):
            with st.spinner("정답 PDF와 OMR 응답을 분석하는 중입니다."):
                run_analysis(question_file, omr_file, answer_file)

        current = st.session_state.get("analysis")
        st.download_button(
            "엑셀 추출",
            data=partial(export_excel, current["result"]) if current else b"",
            file_name="시험_채점_결과.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            disabled=current is None,
            on_click="ignore",
            width="stretch",
        )

    status = "채점 완료" if current else "분석 시작 가능" if ready else "자료 업로드 대기"
    st.html(f"""
        <div class="workspace-heading">
            <span class="emoji-tile" aria-hidden="true">📊</span>
            <div>
                <h1>성적 분석</h1>
                <p>시험 자료를 올리고 채점 결과를 확인하세요.</p>
            </div>
            <span class="state-chip">{status}</span>
        </div>
    """)

    if current:
        st.subheader("결과 요약")
        result = current["result"]
        labels = ("채점 학생", "평균", "중앙값", "모표준편차")
        values = (f"{len(result.students)}명", f"{result.mean:.2f}점", f"{result.median:.2f}점", f"{result.stdev:.2f}점")
        for column, label, value in zip(st.columns(4), labels, values):
            column.metric(label, value, border=True)
        missed = ", ".join(f"{item.number}번 ({item.incorrect_count}명)" for item in result.top_missed)
        st.write(f"**오답 상위 3문항**  {missed}")
        if not ready:
            st.caption("이 세션의 마지막 분석 결과입니다. 새 파일을 선택하면 결과가 초기화됩니다.")
        if result.top_missed and result.top_missed[0].incorrect_count and not current["source_question"]:
            st.warning("시험지에서 최다 오답 문항을 읽을 수 없어 유사 문항 생성이 제한됩니다.")

    with st.container(key="workspace-chat"):
        st.html('<h2><span aria-hidden="true">💬</span> 성적 분석 챗봇</h2>')
        if current:
            for role, content in current["messages"]:
                with st.chat_message(role):
                    if role == "assistant":
                        st.markdown(content, unsafe_allow_html="<u>" in content)
                    else:
                        st.text(content)
            if not current["messages"]:
                st.caption("예시 질문 · 학생들 이번 시험 점수 평균이랑 중앙값이 뭐야?")
        else:
            st.html("""
                <div class="chat-empty">
                    <span class="emoji-tile" aria-hidden="true">🤖</span>
                    <strong>채점이 끝나면 질문을 시작할 수 있어요</strong>
                    <p>평균, 학생별 점수, 가장 많이 틀린 문항을 물어보세요.</p>
                </div>
            """)

        message = st.chat_input(
            "채점 결과에 대해 질문하세요",
            disabled=current is None,
            max_chars=600,
        )
        if message and current:
            current["messages"].append(("user", message))
            with st.chat_message("user"):
                st.text(message)
            with st.chat_message("assistant"), st.spinner("질문을 확인하는 중입니다."):
                reply = answer_chat(
                    message,
                    current["result"],
                    current["source_question"],
                    current["context"],
                    api_key=setting("OPENAI_API_KEY") or None,
                    model=setting("OPENAI_MODEL", "gpt-5.4-mini"),
                )
                st.markdown(reply, unsafe_allow_html="<u>" in reply)
            current["messages"].append(("assistant", reply))


st.set_page_config(page_title="AI 성적분석 에이전트", page_icon="🎓", layout="wide")
st.html(ASSETS / "interface.css")
landing_page = st.Page(landing, title="서비스 소개", icon="🏠", default=True)
analysis_page = st.Page(analysis, title="성적 분석", icon="📊", url_path="analysis")
st.navigation([landing_page, analysis_page], position="top").run()
