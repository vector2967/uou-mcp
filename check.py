"""실제 사이트로 도는 스모크 체크: uv run python check.py  (사이트 HTML이 바뀌면 여기서 먼저 깨진다)"""
import re
import sys

from uou_mcp import server as s

fails = []


def check(name, out, *must):
    ok = all(re.search(m, out, re.M) for m in must)
    print(f"{'OK ' if ok else 'FAIL'} {name}: {out[:160]!r}")
    if not ok:
        fails.append(name)
    return out


check("meal", s.meal("2026-11-03", "학생"), r"\[중식\]", "쌀밥")
check("schedule", s.academic_schedule("기말", 2026), "기말고사")
check("notices", s.notices(limit=3), r"^\[\d+\] \d{4}-")
check("notices search", s.notices("공모전", limit=5), "공모전")
check("notices 사업", s.notices(board="사업", limit=3), r"^\[\d+\]")
d = check("notice_detail", s.notice_detail(91520), "트랙", "downloadRun")
pdf = re.search(r"(https://\S+downloadRun\S+)", d)[1]
check("read_attachment", s.read_attachment(pdf, 2000), "1쪽")
check("read_attachment 외부 차단", s.read_attachment("https://example.com/a.pdf"), "울산대")
check("site_menu", s.site_menu("기숙사"), "MN243")
check("site_page 기숙사", s.site_page("MN243"), "청운학사")
check("site_page 통학버스", s.site_page("MN194"), "통학버스")
check("departments", s.departments(), "ICT융합학부", r"ict\.ulsan\.ac\.kr")
dn = check("dept_notices", s.dept_notices("ICT융합학부", limit=3), r"^\[\d+\] \d{4}-")
no = int(re.search(r"\[(\d+)\]", dn)[1])
check("dept_notice_detail", s.dept_notice_detail("ICT융합학부", no), "action=view")
check("dept_notices 이전 사이트", s.dept_notices("산업경영공학부", limit=2), r"^\[\d+\]")
check("dept_contact", s.dept_contact("국어국문"), "052-")
check("track_search", s.track_search("산업ICT공학"), r"\d+쪽")
check("track_search 여러 단어", s.track_search("마이크로특화트랙 신청"), r"쪽")
check("track_page", s.track_page(3), "트랙")
check("library_search", s.library_search("파이썬", 3), "검색 결과", "신관|본관|대출")
check("library_hours", s.library_hours(), r"\d{1,2}:\d{2}")
check("campus_building", s.campus_building("7"), "07호관")
assert "27호관" not in s.campus_building("7")
check("campus_building 이름", s.campus_building("도서관"), "도서관")
check("dept_notices 학사공지", s.dept_notices("전기전자공학전공", limit=2), "1064", r"^\[\d+\]")
check("dept_notices 대학원 게시판", s.dept_notices("전기전자공학전공", board="대학원", limit=2), "2222")
check("meal 요일", s.meal("금요일"), r"\d{4}-\d\d-\d\d")
check("meal 잘못된 날짜", s.meal("아무날"), "못 알아들었습니다")
check("schedule 별칭", s.academic_schedule("졸업", 2026), "학위수여")
check("notices 뉴스형", s.notices(board="MN104", limit=2), r"^\[\d+\] \d{4}-")
check("notices 사진형", s.notices(board="MN119", limit=2), r"^\[\d+\]")
check("notice_detail 이미지 글", s.notice_detail(91565), "본문 이미지")
check("site_search", s.site_search("근로장학"), "장학", "https://")
check("site_menu → 통합검색", s.site_menu("근로장학"), "통합검색")
check("jobs", s.jobs(limit=3), r"^\[\d+\] \[")
jn = int(re.search(r"\[(\d+)\]", s.jobs(limit=1))[1])
check("job_detail", s.job_detail(jn), "boardView02")
check("dept_site 위치", s.dept_site("ICT융합학부", "찾아오시는길"), "7- ?320")
check("dept_site 위치 별칭", s.dept_site("영어영문학과", "찾아오시는길"), "14호관")
check("dept_site 메뉴", s.dept_site("ICT융합학부"), "교수소개")
check("library 영문", s.library_search("machine learning", 2), "검색 결과")
check("campus 기숙사", s.campus_building("기숙사"), "청운학사")
print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
