"""Published English listening resources for the preceding CSAT."""

_QUESTION_PDF = "https://www.suneung.re.kr/boardCnts/fileDown.do?fileSeq=1050e33a51398273bdb891bd1d4cc2e4"
_AUDIO_MP3 = "https://wdown.ebsi.co.kr/W61001/01exam/20241114/go3/eng_1_mp3_A8AB96OL.mp3"


def listening_reference(item_number: int) -> str:
    """Point to the same listening item in the 2025 CSAT odd form."""
    if not 1 <= item_number <= 17:
        raise ValueError("듣기 문항 번호는 1~17번입니다.")
    page = 1 if item_number <= 12 else 2
    return (
        f"**2025학년도 수능 영어 홀수형 {item_number}번**으로 연습해 보세요. "
        f"문제지 {page}쪽에 있습니다. MP3는 듣기 전체 음원이므로 "
        f"{item_number}번 안내가 나오는 부분을 들으세요.\n\n"
        f"- [한국교육과정평가원 문제지 PDF]({_QUESTION_PDF})\n"
        f"- [EBSi 듣기평가 전체 음원 MP3]({_AUDIO_MP3})"
    )
