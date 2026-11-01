"""울산대학교(UOU) MCP 서버. 공개 홈페이지·학과 사이트·도서관을 그때그때 긁어서 답한다(로그인 데이터 없음).

uou-mcp            → stdio (Claude Desktop/Code가 직접 띄움)
uou-mcp --http     → http://127.0.0.1:44610/mcp 로컬 서버
"""
import datetime as dt
import html
import io
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.mcpserver import MCPServer

BASE = "https://www.ulsan.ac.kr"
KST = dt.timezone(dt.timedelta(hours=9))
DATA = pathlib.Path(__file__).with_name("data")
UA = {"User-Agent": "Mozilla/5.0 uou-mcp"}

mcp = MCPServer("uou", instructions=(
    "울산대학교(UOU) 정보: 학식, 학사일정, 본교·학과 공지, 학부/전공·트랙(2026 트랙소개서), 도서 검색·도서관, "
    "캠퍼스 건물, 학과 연락처, 그리고 홈페이지 모든 안내 페이지(site_menu로 찾고 site_page로 읽기: "
    "등록금, 장학, 기숙사, 통학/셔틀버스, 편의시설, 주차, 의료, 증명서 등). 답할 때 출처 링크를 같이 준다."))


# ── 공통 ──────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, str, bytes]] = {}


def _fetch(url: str, ttl: int = 600) -> tuple[str, bytes]:
    """(최종 URL, 본문 bytes). 10분 캐시."""
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1], hit[2]
    for attempt in range(3):  # 학교 서버가 가끔 연결을 끊는다(WinError 10054) → 잠깐 쉬고 다시
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                final, body = r.geturl(), r.read()
            break
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt == 2 or "getaddrinfo" in str(e):
                raise
            time.sleep(1 + attempt)
    if len(_cache) > 300:  # ponytail: 통째 비우기, 메모리 문제 생기면 LRU로
        _cache.clear()
    _cache[url] = (time.time(), final, body)
    return final, body


def _get(path: str, **params) -> str:
    """path는 '/kor/...'(본교) 또는 'https://...'. 쿼리는 params로."""
    url = path if path.startswith("http") else BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return _fetch(url)[1].decode("utf-8", "replace")


def _text(s: str) -> str:
    s = re.sub(r"<!--.*?-->|<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</li>|</tr>|</h\d>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return "\n".join(l for l in (re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n")) if l)


def _norm(s: str) -> str:
    return re.sub(r"[\s·‧ㆍ・.,()/-]", "", s).lower()


def _today() -> dt.date:
    return dt.datetime.now(KST).date()


def _parse_date(s: str) -> dt.date:
    words = {"오늘": 0, "내일": 1, "모레": 2, "어제": -1}
    s = s.replace("이번주", "").replace("이번 주", "").strip()
    if s in words:
        return _today() + dt.timedelta(days=words[s])
    wd = "월화수목금토일".find(s[:1]) if s.endswith(("요일", "욜")) or len(s) == 1 else -1
    if wd >= 0:  # 이번 주(월요일 시작)의 그 요일
        t = _today()
        return t + dt.timedelta(days=wd - t.weekday())
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})", s)  # 11/6 → 올해
    if m:
        return dt.date(_today().year, int(m[1]), int(m[2]))
    return dt.date.fromisoformat(s.replace(".", "-").replace("/", "-"))


def _pdf_text(raw: bytes, limit: int) -> str:
    from pypdf import PdfReader
    out = []
    for i, p in enumerate(PdfReader(io.BytesIO(raw)).pages, 1):
        out.append(f"--- {i}쪽 ---\n{p.extract_text() or '(글자 없음: 이미지 쪽)'}")
        if sum(map(len, out)) > limit:
            break
    return "\n".join(out)[:limit]


# ── 학식 ──────────────────────────────────────────────────────────────
CAFETERIAS = {"학생": 1, "교직원": 2, "기숙사": 3}


def parse_diet(page: str) -> dict[str, dict[str, list[str]]]:
    """식단표 HTML → {'2026-11-02': {'조식': [...], '중식': [...], '석식': [...]}}"""
    out = {}
    for m in re.finditer(r'id="calDay(\d{4})\.(\d{2})\.(\d{2})"(.*?)</tr>', page, re.S):
        meals = {}
        for n, ul in re.findall(r'<ul class="res-depth(\d)">(.*?)</ul>', m[4], re.S):
            items = [_text(li) for li in re.findall(r"<li>(.*?)</li>", ul, re.S)]
            meals[{"1": "조식", "2": "중식", "3": "석식"}[n]] = [i for i in items if i]
        out[f"{m[1]}-{m[2]}-{m[3]}"] = meals
    return out


@mcp.tool()
def meal(date: str = "오늘", cafeteria: str = "학생") -> str:
    """학식 메뉴. date는 '오늘'/'내일'/'금요일'(이번 주)/'YYYY-MM-DD', cafeteria는 학생·교직원·기숙사.
    운영시간은 site_page('MN134'). 학생식당은 기숙사식당(무거관)으로 옮겨 같은 메뉴다."""
    try:
        day = _parse_date(date)
    except ValueError:
        return f"날짜 '{date}'를 못 알아들었습니다. '오늘', '내일', '금요일', '2026-11-06' 형식으로 주세요."
    cafeteria = cafeteria.replace("식당", "").strip()
    if cafeteria not in CAFETERIAS:
        return f"식당은 {', '.join(CAFETERIAS)} 중 하나입니다."
    page = _get("/kor/CMS/DietMenuMgr/list.do", mCode="MN203",
                searchDietCategory=CAFETERIAS[cafeteria], searchDay=day.isoformat())
    week = parse_diet(page)
    meals = week.get(day.isoformat())
    if not meals or not any(meals.values()):
        if not any(any(m.values()) for m in week.values()):
            return f"{cafeteria}식당은 {day}가 있는 주 식단이 홈페이지에 아예 올라와 있지 않습니다(학교가 안 올린 것)."
        return f"{day} {cafeteria}식당 식단이 없습니다(주말·휴일 등 운영 안 하는 날)."
    return f"{day} {cafeteria}식당\n" + "\n".join(f"\n[{k}]\n" + "\n".join(v) for k, v in meals.items() if v)


# ── 학사일정 ──────────────────────────────────────────────────────────
def parse_schedule(page: str, year: int) -> list[tuple[str, str]]:
    """연간 학사일정 HTML → [('2026-06-16 ~ 2026-06-22', '2026-1학기 기말고사'), ...]"""
    out = []
    for d, body in re.findall(r'class="date-core">(.*?)</div>\s*<div class="body-core">(.*?)</div>', page, re.S):
        dates = [f"{year}-{mm}-{dd}" for mm, dd in re.findall(r"(\d{2})\. (\d{2})", _text(d))]
        out.append((" ~ ".join(dates), _text(body)))
    return out


@mcp.tool()
def academic_schedule(keyword: str = "", year: int = 0) -> str:
    """학사일정. keyword(예: '기말', '수강신청', '휴학')가 없으면 오늘 이후 일정 15개."""
    year = year or _today().year
    rows = parse_schedule(_get("/kor/CMS/ScheduleMgr/YearList.do", mCode="MN080", calendar_year=year), year)
    if keyword:
        alias = {"졸업": "학위수여|졸업", "종강": "종강|기말고사", "휴학": "휴학|복학|휴·복학", "방학": "방학|계절"}
        pat = alias.get(keyword, re.escape(keyword))
        rows = [r for r in rows if re.search(pat, r[1])]
        if not rows:
            return f"학사일정에 '{keyword}'가 들어간 일정이 없습니다. 절차 안내는 site_menu('{keyword}')로 찾아보세요."
    else:
        today = _today().isoformat()
        rows = [r for r in rows if r[0].split(" ~ ")[-1] >= today][:15]
    return "\n".join(f"{d}  {t}" for d, t in rows) or "해당 일정이 없습니다."


# ── 본교 공지 ─────────────────────────────────────────────────────────
BOARDS = {"공지": "MN113", "사업": "MN246", "산학": "MN247"}


@mcp.tool()
def notices(keyword: str = "", board: str = "공지", page: int = 1, limit: int = 10) -> str:
    """본교 게시판 목록. board: 공지(일반공지·학사 포함), 사업(산학 사업공지), 산학(산학 일반공지), 또는 site_menu에 나온
    게시판 mCode(예: MN104 UOU소식, MN106 언론 속 울산대, MN119 중앙동아리, MN180 예산공개). 채용공지는 jobs.
    keyword는 제목 검색. 결과의 [번호]를 notice_detail(번호, board)에 넘기면 본문·첨부를 본다."""
    mcode = BOARDS.get(board, board)
    params = {"mCode": mcode, "mode": "list", "page": page}
    if keyword:
        params |= {"searchID": "sch001", "searchKeyword": keyword}
    return "\n".join(parse_board(_get("/kor/CMS/Board/Board.do", **params))[:limit]) or "글이 없습니다."


def parse_board(page: str) -> list[str]:
    """본교 게시판 목록(표·뉴스·사진·자료실형 모두) → ['[번호] 날짜 제목', ...]. 글 링크 board_seq 기준."""
    rows, seen = [], set()
    for m in re.finditer(r"""href=['"][^'"]*(?:board|video)_seq=(\d+)[^'"]*['"][^>]*>(.*?)</a>""", page, re.S):
        seq = m[1]
        title = re.sub(r"\s*\d{4}-\d{2}-\d{2}.*", "", _text(m[2]).replace("\n", " ")).strip()
        if not title:  # 사진만 링크된 형식: 제목은 바로 앞 <p class="title">
            before = re.findall(r'<p class="title">(.*?)</p>', page[max(0, m.start() - 600):m.start()], re.S)
            title = _text(before[-1]) if before else ""
        if seq in seen or not title:
            continue
        seen.add(seq)
        date = re.search(r"\d{4}-\d{2}-\d{2}", m[2]) or re.search(r"\d{4}-\d{2}-\d{2}", page[m.end():m.end() + 1500])
        rows.append(f"[{seq}] {date[0] if date else ''} {title}")
    if not rows:  # 언론 보도형: 글이 외부 언론사 링크
        for u, t, src, d in re.findall(r'<a href="(https?://[^"]+)"[^>]*>\s*<div class="news-cont">\s*<p class="subject">(.*?)</p>'
                                       r'.*?class="pressName">(.*?)</span>.*?class="date">(.*?)</span>', page, re.S):
            rows.append(f"{_text(d)} [{_text(src)}] {_text(t)}  {html.unescape(u)}")
    return rows


@mcp.tool()
def notice_detail(seq: int, board: str = "공지") -> str:
    """본교 공지 본문 + 첨부파일 목록(첨부 PDF는 read_attachment로 읽는다)."""
    mcode = BOARDS.get(board, board)
    link = f"{BASE}/kor/CMS/Board/Board.do?mCode={mcode}&mode=view&board_seq={seq}"
    page = _get(link)
    title = _text((re.search(r'<h4 class="vtitle">(.*?)</h4>', page, re.S) or ["", ""])[1])
    body = re.search(r'<div id="boardContents">(.*?)<!--e: View Contents', page, re.S)
    files = [f"- {_text(n)}: {urllib.parse.urljoin(BASE, u)}"
             for u, n in re.findall(r'<a[^>]*href="(/kor/ajx_json/UploadMgr/downloadRun\.do\?qcode=[^"]+)"[^>]*>(.*?)</a>', page, re.S)]
    body = body[1] if body else ""
    imgs = [urllib.parse.urljoin(BASE, s) for s in re.findall(r'<img[^>]*src="([^"]+)"', body) if "/attach/" in s or "Upload" in s]
    out = f"{title}\n{link}\n\n{_text(body)[:5000] or '(본문 글자 없음: 아래 이미지·첨부로만 된 글)'}"
    if imgs:
        out += "\n\n본문 이미지(글자 아님):\n" + "\n".join(dict.fromkeys(imgs))
    return out + ("\n\n첨부:\n" + "\n".join(files) if files else "")


@mcp.tool()
def read_attachment(url: str, max_chars: int = 15000) -> str:
    """울산대 사이트 첨부파일(PDF)을 텍스트로 읽는다. 이미지·HWP는 링크만 돌려준다."""
    host = urllib.parse.urlparse(url).hostname or ""
    if not (host == "ulsan.ac.kr" or host.endswith(".ulsan.ac.kr")):
        return "울산대(ulsan.ac.kr) 링크만 읽습니다."
    _, raw = _fetch(url, ttl=3600)
    if raw[:5] != b"%PDF-":
        return f"PDF가 아니라 글자를 못 뽑습니다(이미지·HWP 등). 직접 열어 보세요: {url}"
    return _pdf_text(raw, max_chars)


JOBS = "/kor/CMS/HaksaProgramMgr/boardList02.do"


@mcp.tool()
def jobs(keyword: str = "", page: int = 1, limit: int = 10) -> str:
    """본교 채용공지(기업 채용정보·교내채용): [번호] 구분 기업 제목 (등록일 ~ 마감일). keyword는 기업·제목에서 거른다
    (앞 5쪽 안에서). 본문은 job_detail(번호)."""
    rows = []
    for p in ([page] if not keyword else range(1, 6)):
        body = _get(JOBS, mCode="MN114", page=p)
        for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
            m = re.search(r"seq=(\d+)\">(.*?)</a>.*?seq=\d+\">(.*?)</a>.*?class=\"date\">(.*?)</td>\s*<td class=\"date\">(.*?)</td>", tr, re.S)
            if m:
                kind = _text((re.search(r'class="subject">\s*(\[[^\]]+\])', tr) or ["", ""])[1])
                rows.append(f"[{m[1]}] {kind} {_text(m[2])} / {_text(m[3])} ({_text(m[4])} ~ {_text(m[5])})")
    if keyword:
        rows = [r for r in rows if _norm(keyword) in _norm(r)]
    return "\n".join(rows[:limit]) or "채용공지가 없습니다."


@mcp.tool()
def job_detail(seq: int) -> str:
    """채용공지 본문(자격요건·연봉·마감·제출방법 등)."""
    link = f"{BASE}/kor/CMS/HaksaProgramMgr/boardView02.do?mCode=MN114&seq={seq}"
    page = _get(link)
    i = page.find('id="contents"')
    seg = page[page.find(">", i) + 1:page.find("<footer", i)]
    files = [f"- {_text(n)}: {urllib.parse.urljoin(BASE, u)}"
             for u, n in re.findall(r'<a[^>]*href="([^"]*downloadRun\.do\?qcode=[^"]+)"[^>]*>(.*?)</a>', seg, re.S)]
    return f"{link}\n\n{_text(seg)[:6000]}" + ("\n\n첨부:\n" + "\n".join(files) if files else "")


@mcp.tool()
def site_search(keyword: str, kind: str = "") -> str:
    """울산대 홈페이지 통합검색: 메뉴 이름에 없는 단어도 페이지 본문·게시판 글에서 찾는다(예: '근로장학', '교환학생', '전과').
    kind: ''(전체) / 'C'(안내 페이지만) / 'B'(게시판 글만, 더 많이). 결과의 mCode는 site_page로, board_seq는 notice_detail로."""
    data = urllib.parse.urlencode({"mCode": "MN211", "searchKeyword": keyword, "category_code": kind}).encode()
    req = urllib.request.Request(f"{BASE}/kor/CMS/TotalSearch/total.do?mCode=MN211", data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        page = r.read().decode("utf-8", "replace")
    total = _text((re.search(r'class="searchrst-msg">(.*?)</p>', page, re.S) or ["", ""])[1])
    out = [total]
    for sec in page.split('class="searchrst-listbox"')[1:]:
        head = _text((re.search(r'<h3 class="c-tit01">(.*?)</h3>', sec, re.S) or ["", ""])[1])
        items = re.findall(r'<a class="ptit"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<span class="plinks">(.*?)</span>\s*'
                           r'(?:</[^>]+>\s*)*(?:<p class="pcont">(.*?)</p>)?', sec, re.S)
        if items:
            out.append(f"\n[{head}]")
            for u, t, path, cont in items:
                u = re.sub(r"(=\d+)\.0\b", r"\1", urllib.parse.urljoin(BASE, html.unescape(u))).replace("http://", "https://")
                out.append(f"- {_text(t)}  ({_text(path)})\n  {u}\n  {_text(cont or '').replace(chr(10), ' ')[:160]}")
    return "\n".join(out) if len(out) > 1 else f"'{keyword}' 검색 결과가 없습니다."


# ── 홈페이지 전체 안내 페이지 ─────────────────────────────────────────
def _sitemap() -> list[tuple[str, str, str]]:
    """사이트맵 → [(mCode, '대학생활 > 학생지원 > 기숙사', url)]"""
    page = _get("/kor/CMS/SiteMap/SiteMap.do", mCode="MN013")
    out, path = [], {}
    for lv, url, name in re.findall(r'<li class="lm_l(\d)">\s*<a\s+href="([^"]+)"[^>]*>\s*<span>(.*?)</span>', page, re.S):
        lv = int(lv)
        path = {k: v for k, v in path.items() if k < lv} | {lv: _text(name)}
        m = re.search(r"mCode=(MN\d+)", url)
        out.append((m[1] if m else "", " > ".join(path[k] for k in sorted(path)), html.unescape(url)))
    return out


@mcp.tool()
def site_menu(keyword: str = "") -> str:
    """울산대 홈페이지 메뉴(사이트맵) 검색. 예: '장학', '기숙사', '셔틀', '등록금', '휴학', '졸업', '동아리'.
    나온 mCode를 site_page에 넘기면 그 페이지 내용을 읽는다."""
    rows = [r for r in _sitemap() if _norm(keyword) in _norm(r[1])] if keyword else _sitemap()
    if not rows:  # 메뉴 이름에 없으면 본문·게시판까지 통합검색
        return f"메뉴 이름에는 '{keyword}'가 없어 통합검색 결과를 보여줍니다.\n" + site_search(keyword)
    return "\n".join(f"{c or '-'}  {p}  {u if not c else ''}".rstrip() for c, p, u in rows[:80])


@mcp.tool()
def site_page(mcode: str) -> str:
    """홈페이지 안내 페이지 본문(표 포함)과 첨부·링크. mcode는 site_menu 결과(예: 'MN243' 기숙사, 'MN194' 통학버스)."""
    hit = next((u for c, _, u in _sitemap() if c == mcode), f"{BASE}/kor/CMS/Contents/Contents.do?mCode={mcode}")
    if "/Board/" in hit:
        return notices(board=mcode)
    hit = hit.replace("http://", "https://")
    page = _get(hit)
    i = page.find('id="contents"')
    seg = page[page.find(">", i) + 1:page.find("<footer", i)] if i > 0 else page
    links = []
    for u, n in re.findall(r'<a[^>]*href="([^"#][^"]*)"[^>]*>(.*?)</a>', seg, re.S):
        n = _text(n)
        if n and not u.startswith("javascript") and ("downloadRun" in u or u.startswith("http")):
            links.append(f"- {n}: {urllib.parse.urljoin(BASE, u)}")
    imgs = [urllib.parse.urljoin(BASE, s) for s in re.findall(r'<img[^>]*src="([^"]+/attach/[^"]+)"', seg)]
    body = _text(seg).replace("\nPREV\nNEXT", "", 1)  # 제목 뒤 이전/다음 버튼 글자
    if "\n" not in body.strip():
        body += "\n(본문 글자 없음: 이미지·링크로만 된 페이지)"
    out = f"{hit}\n\n{body[:8000]}"
    if links:
        out += "\n\n링크·첨부:\n" + "\n".join(dict.fromkeys(links))
    if imgs:
        out += "\n\n안내 이미지(글자 아님):\n" + "\n".join(dict.fromkeys(imgs))
    return out


# ── 학부·학과 ─────────────────────────────────────────────────────────
def _dept_sites() -> dict[str, str]:
    """메인 메뉴의 학부·전공 홈페이지 링크 → {이름: URL} (2025 개편 학부 + 이전 학과 사이트)."""
    page = _get("/kor/Main.do")
    out = {}
    for url, name in re.findall(r'<a[^>]*href="(https?://[^"]+)"[^>]*>\s*([▷ㆍ][^<]{1,40})</a>', page):
        name = name.strip("▷ㆍ ").strip()
        if "ulsan.ac.kr" in url and "/kor/CMS/" not in url:
            out.setdefault(name, url)
    return out


@mcp.tool()
def departments() -> str:
    """단과대학·학부(2025 개편) 목록과 학부/전공 홈페이지. 전공·트랙 내용은 track_search."""
    page = _get("/kor/CMS/DeptIntro/intro.do", depart_type="CDE_000176", mCode="MN333")
    sites = _dept_sites()
    lines = []
    for block in page.split('<div class="dept-list')[1:]:
        col = _text((re.search(r'<span class="ktit">(.*?)</span>', block, re.S) or ["", ""])[1])
        names = [_text(n) for n in re.findall(r'<span class="name">(.*?)</span>', block, re.S)]
        if col and names:
            lines.append(f"\n[{col}]\n" + "\n".join(f"- {n}  {sites.get(n, '')}".rstrip() for n in names))
    old = [f"- {n}  {u}" for n, u in sites.items() if not any(n in l for l in lines)]
    return "2025학년도~ 단과대학·학부" + "".join(lines) + "\n\n이전 학과·전공 사이트(학과 공지는 여기 있는 경우가 많음)\n" + "\n".join(old)


def _dept_home(dept: str) -> tuple[str, str, str]:
    """학과 이름 → (공식 이름, 홈 URL, 홈 HTML)."""
    sites = _dept_sites()
    key = _norm(dept)
    name = next((n for n in sites if _norm(n) == key), None) or next((n for n in sites if key in _norm(n)), None)
    if not name:
        raise ValueError(f"'{dept}' 학과 사이트를 못 찾았습니다. departments()로 이름을 확인하세요.")
    url = re.sub(r"/main\.do$", "/", sites[name])  # 옛 주소 /main.do는 404
    try:
        home, body = _fetch(url.replace("http://", "https://"))
    except Exception:
        try:
            home, body = _fetch(url)
        except Exception as e:
            raise ValueError(f"{name} 사이트({url})에 접속이 안 됩니다({type(e).__name__}). 사이트가 닫혔을 수 있습니다.")
    return name, home, body.decode("utf-8", "replace")


def _dept_menu(home: str, body: str) -> dict[str, str]:
    """학과 홈 HTML → {메뉴 이름: URL} (같은 사이트 /<site>/<번호> 링크)."""
    site = urllib.parse.urlparse(home).path.strip("/").split("/")[0]
    menu = {}
    for u, t in re.findall(rf'<a[^>]*href="(/{re.escape(site)}/\d+)"[^>]*>(.*?)</a>', body, re.S):
        t = _text(t).replace("\n", " ")
        u = urllib.parse.urljoin(home, u)
        if t and not u.endswith("/9999") and u not in menu.values():
            n, k = t, 2
            while n in menu:  # 전공마다 있는 '이수체계도' 같은 같은 이름 메뉴는 #2, #3…
                n, k = f"{t} #{k}", k + 1
            menu[n] = u
    return menu


def _dept_board(dept: str, board: str = "") -> tuple[str, list[str]]:
    """학과 이름 → (고른 공지 게시판 URL, 그 사이트의 공지 게시판 이름들)."""
    name, home, body = _dept_home(dept)
    found = {}
    for u, t in re.findall(r'<a[^>]*href="(/[^"]+)"[^>]*>(.*?)</a>', body, re.S):
        t = _text(t)
        if re.search(r"(?<!인)공지|알림", t) and len(t) < 15:  # "산업인공지능" 제외
            found.setdefault(t, urllib.parse.urljoin(home, u))
    if not found:
        raise ValueError(f"{name} 사이트({home})에서 공지 게시판을 못 찾았습니다.")
    names = list(found)
    if board:
        pick = next((n for n in names if _norm(board) in _norm(n)), names[0])
    else:  # 학부·학사 공지 우선, 대학원·학생회·취업은 뒤로
        pick = sorted(names, key=lambda n: (any(w in n for w in ("대학원", "학생회", "취업", "프로그램")),
                                            not any(w in n for w in ("학부", "학사"))))[0]
    return found[pick], names


@mcp.tool()
def dept_notices(dept: str, keyword: str = "", board: str = "", page: int = 1, limit: int = 10) -> str:
    """학부·학과 홈페이지 공지 목록. dept 예: 'ICT융합학부', '산업경영공학부', '전기전자공학전공'.
    board는 그 사이트에 공지 게시판이 여럿일 때(예: '대학원', '취업') 고른다. [번호]는 dept_notice_detail로."""
    try:
        board, names = _dept_board(dept, board)
    except ValueError as e:
        return str(e)
    params = {"pageIndex": page}
    if keyword:
        params |= {"searchCondition": "title", "searchKeyword": keyword}
    body = _get(board, **params)
    rows = re.findall(r'action=view&(?:amp;)?no=(\d+)"[^>]*>(.*?)</a>.*?class="bdlDate">(.*?)</td>', body, re.S)
    lines = [f"[{no}] {_text(d)} {_text(t)}" for no, t, d in rows[:limit]]
    if not lines:
        lines = ["글이 없습니다." if "a_brdList" in body else
                 "이 게시판은 서버가 본문 없이 빈 페이지를 줍니다(로그인 전용이거나 다른 방식). 위 링크를 브라우저로 직접 여세요."]
    return f"{board}  (이 사이트 공지 게시판: {', '.join(names)})\n" + "\n".join(lines)


@mcp.tool()
def dept_notice_detail(dept: str, no: int, board: str = "") -> str:
    """학과 공지 본문과 첨부·이미지 링크. board는 dept_notices에서 쓴 값 그대로."""
    try:
        board, _ = _dept_board(dept, board)
    except ValueError as e:
        return str(e)
    link = f"{board}?action=view&no={no}"
    body = _get(link)
    title = _text((re.search(r'class="bdvTitle">(.*?)</td>', body, re.S) or ["", ""])[1])
    cont = re.search(r'class="bdvEdit">(.*?)</td>', body, re.S)
    cont = cont[1] if cont else ""
    files = [f"- {_text(n)}: {urllib.parse.urljoin(board, u)}" for u, n in
             re.findall(r'<a[^>]*href="([^"]*boardDownload\.do\?no=\d+)"[^>]*>(.*?)</a>', body, re.S)]
    imgs = [urllib.parse.urljoin(board, s) for s in re.findall(r'<img[^>]*src="([^"]+)"', cont)]
    out = f"{title}\n{link}\n\n{_text(cont)[:5000]}"
    if files:
        out += "\n\n첨부(PDF는 read_attachment로):\n" + "\n".join(dict.fromkeys(files))
    if imgs:
        out += "\n\n본문 이미지(글자 아님):\n" + "\n".join(dict.fromkeys(imgs))
    return out


@mcp.tool()
def dept_site(dept: str, menu: str = "") -> str:
    """학부·학과 홈페이지의 다른 메뉴 읽기: 찾아오시는길(사무실 위치), 교수소개, 직원소개, 학부소개, 교육과정,
    트랙소개, 이수체계도, 학사일정, 입학안내 등. menu를 비우면 그 사이트 메뉴 목록. 공지 게시판은 dept_notices."""
    try:
        name, home, body = _dept_home(dept)
    except ValueError as e:
        return str(e)
    items = _dept_menu(home, body)
    if not menu:
        return f"{name} {home}\n" + "\n".join(f"- {n}" for n in items) if items else f"{name} {home}: 메뉴를 못 읽었습니다."
    key = _norm(menu)
    hits = [n for n in items if key == _norm(n)] or [n for n in items if key in _norm(n)]
    alias = {"찾아오시는길": ("오시는길", "위치", "사무실", "행정실", "학과행정", "연락처"), "교수": ("교수진", "교원", "전임"),
             "교육과정": ("교과과정", "커리큘럼", "이수체계")}
    for k, alts in alias.items():
        if not hits and (key in _norm(k) or _norm(k) in key):
            hits = [n for n in items if any(a in _norm(n) for a in alts)]
    if not hits:
        return f"'{menu}' 메뉴가 없습니다. {name} 메뉴: " + ", ".join(items)
    for pick in hits[:4]:  # 게시판이 걸리면 다음 후보(예: '학과행정' 게시판 대신 안내 페이지)
        url = items[pick]
        page = _get(url)
        i = page.find('class="subCont')
        seg = page[page.find(">", i) + 1:page.find("<footer", i)] if i > 0 else page
        if "a_brdList" not in seg:
            break
    hits.insert(0, hits.pop(hits.index(pick)))
    if "a_brdList" in seg and key != _norm(pick) and not any(w in key for w in ("공지", "게시", "자료")):
        return f"{name} 홈페이지에 '{menu}' 안내 페이지가 없습니다(비슷한 '{pick}'은 게시판). 메뉴: " + ", ".join(items)
    text = _text(seg)
    if "a_brdList" in seg:
        text = "(게시판입니다. 글 목록은 dept_notices로 보세요)\n" + text[:1500]
    imgs = [urllib.parse.urljoin(url, s) for s in re.findall(r'<img[^>]*src="([^"]+)"', seg) if "/upload" in s or "/attach" in s]
    out = f"{name} > {hits[0]}\n{url}\n\n{text[:8000] or '(본문 글자 없음: 이미지로만 된 페이지일 수 있음)'}"
    if imgs:
        out += "\n\n본문 이미지(글자 아님):\n" + "\n".join(dict.fromkeys(imgs))
    if len(hits) > 1:
        out += f"\n\n(같은 이름 메뉴 더 있음: {', '.join(hits[1:6])} — 이수체계도·트랙소개는 전공마다 하나씩이라 겹침. 트랙 내용은 track_search가 더 정확)"
    return out


@mcp.tool()
def dept_contact(name: str) -> str:
    """학부·학과 사무실 전화번호와 교수·직원 연락처표(본교 전화번호 안내). 2025 신설 학부는 위치가 비어 있을 수 있어
    dept_site(학부, '찾아오시는길')로 학부 홈페이지에서 확인한다."""
    page = _get("/kor/CMS/UnivOrganMgr/organlist.do", mCode="MN062")
    units = {_text(n): c for c, n in re.findall(r"getHakSaData\('\d+','(DE\d+)'\);\">(.*?)</button>", page, re.S)}
    units |= {_text(n): c for c, n in re.findall(r'href="[^"]*view\.do\?mCode=MN086&(?:amp;)?code=(DE\d+)">(.*?)</a>', page, re.S)}
    key = _norm(name)
    hits = [n for n in units if key in _norm(n)]
    if not hits:  # 본교 전화번호 안내에 없으면 학과 홈페이지에서
        site = dept_site(name, "찾아오시는길")
        if "사이트를 못 찾았습니다" not in site:
            return "(본교 전화번호 안내에 없어 학과 홈페이지에서 찾음)\n" + site
        return "못 찾았습니다. 단위 목록: " + ", ".join(units)
    view = _get("/kor/CMS/UnivOrganMgr/view.do", mCode="MN086", code=units[hits[0]])
    i = view.find('class="unipart-wr"')
    seg = view[view.find(">", i) + 1:view.find("<footer", i)]
    more = f"\n(다른 일치: {', '.join(hits[1:6])})" if len(hits) > 1 else ""
    hint = ""
    if not re.search(r"위치\s*\S+\s*\d{2,}호", _text(seg)):  # 위치·호수가 비면 학과 홈페이지 '찾아오시는길'을 붙인다
        site = dept_site(hits[0], "찾아오시는길")
        if "\n" in site and "메뉴가 없습니다" not in site and "접속이 안 됩니다" not in site:
            hint = "\n\n[학과 홈페이지의 위치 안내]\n" + site[:1200]
    return f"{hits[0]}\n{_text(seg)[:5000]}{more}{hint}\n\n대표전화 052-277-3101~3"


# ── 트랙소개서 ────────────────────────────────────────────────────────
_tracks: dict | None = None


def _track_pages() -> list[dict]:
    global _tracks
    if _tracks is None:
        _tracks = json.loads((DATA / "tracks.json").read_text(encoding="utf-8"))
    return _tracks["pages"]


@mcp.tool()
def track_search(keyword: str, limit: int = 8) -> str:
    """2026 울산대 트랙소개서(258쪽 PDF, 홈페이지 MN355)에서 검색. 전공트랙 종류(기본·심화·통합·융복합·마이크로특화),
    학부별 트랙, 이수체계도·교과목, 진로 등. 여러 단어는 모두 들어간 쪽만. 쪽 전체는 track_page."""
    terms = [_norm(t) for t in keyword.split() if t]
    hits = []
    for p in _track_pages():
        flat = _norm(p["text"])
        if all(t in flat for t in terms):
            hits.append((sum(flat.count(t) for t in terms), p))
    hits.sort(key=lambda h: -h[0])
    out = []
    for _, p in hits[:limit]:
        t = re.sub(r"\s+", " ", p["text"])
        i = max(0, t.lower().find(keyword.split()[0].lower()) - 80)
        out.append(f"[{p['page']}쪽] …{t[i:i + 300]}…")
    total = f"{len(hits)}쪽 일치" + (f", 상위 {limit}쪽:" if len(hits) > limit else ":")
    return (total + "\n" + "\n".join(out)) if hits else "트랙소개서에 없음. 다른 단어나 notices('트랙')도 찾아보세요."


@mcp.tool()
def track_page(page: int) -> str:
    """트랙소개서 한 쪽 전체 텍스트(2~3쪽: 대학별 트랙 운영 현황표). 이수체계도 쪽은 '2학년 1학기 … 4학년 2학기'
    열 순서대로 과목이 한 줄에 놓여 있다(빈 칸은 건너뛰므로 열 위치는 대략). 맨 오른쪽 '…모듈'은 과목 묶음 이름."""
    p = next((p for p in _track_pages() if p["page"] == page), None)
    return f"[트랙소개서 {page}쪽]\n{p['text']}" if p else f"{page}쪽은 글자가 없는 쪽(표지·간지)이거나 범위 밖입니다."


# ── 도서관 ────────────────────────────────────────────────────────────
PRIMO = "https://ulsan.primo.exlibrisgroup.com"
_jwt: tuple[float, str] = (0.0, "")


@mcp.tool()
def library_search(query: str, limit: int = 8) -> str:
    """중앙도서관 소장 자료 검색: 제목·저자·출판·청구기호·위치·대출 가능 여부."""
    global _jwt
    if time.time() - _jwt[0] > 1800:
        _, raw = _fetch(f"{PRIMO}/primaws/rest/pub/institution/82ULSAN_INST/guestJwt?isGuest=true&lang=ko&viewId=82ULSAN_INST:ULSAN", ttl=0)
        _jwt = (time.time(), raw.decode().strip('"'))
    q = urllib.parse.urlencode({"inst": "82ULSAN_INST", "lang": "ko", "limit": min(limit, 20), "offset": 0,
                                "q": f"any,contains,{query}", "scope": "Myinst_books", "skipDelivery": "N",
                                "sort": "rank", "tab": "LibraryCatalog", "vid": "82ULSAN_INST:ULSAN"})
    req = urllib.request.Request(f"{PRIMO}/primaws/rest/pub/pnxs?{q}", headers=UA | {"Authorization": "Bearer " + _jwt[1]})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    lines = [f"검색 결과 {data.get('info', {}).get('total', 0)}건"]
    for d in data.get("docs", []):
        disp = d["pnx"]["display"]
        first = lambda k: re.sub(r"\$\$Q.*", "", (disp.get(k) or [""])[0]).strip()
        hold = [f"{h.get('subLocation', '')} {h.get('callNumber', '')} ({'대출가능' if h.get('availabilityStatus') == 'available' else h.get('availabilityStatus', '')})"
                for h in (d.get("delivery") or {}).get("holding") or []]
        lines.append(f"- {first('title')} / {first('creator')} / {first('publisher')} {first('creationdate')}\n  "
                     + ("; ".join(hold) or "소장정보 없음(전자자료일 수 있음)"))
    lines.append(f"상세: {PRIMO}/discovery/search?query=any,contains,{urllib.parse.quote(query)}&tab=LibraryCatalog&search_scope=Myinst_books&vid=82ULSAN_INST:ULSAN&lang=ko")
    return "\n".join(lines)


@mcp.tool()
def library_hours() -> str:
    """중앙도서관 자료실·열람실 운영시간. (좌석 현황은 로그인이 필요해 제공 못 함)"""
    page = _get("https://lib.ulsan.ac.kr/library/introduce/hours/")
    tables = re.findall(r"<table.*?</table>", page, re.S)
    rows = []
    for t in tables:
        for tr in re.findall(r"<tr.*?</tr>", t, re.S):
            cells = [_text(c).replace("\n", " ") for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            rows.append(" | ".join(c for c in cells if c))
    return "https://lib.ulsan.ac.kr/library/introduce/hours/\n" + "\n".join(r for r in rows if r)


# ── 캠퍼스 ────────────────────────────────────────────────────────────
@mcp.tool()
def campus_building(keyword: str = "") -> str:
    """캠퍼스 건물 번호·이름 찾기(예: '7', '공학', '도서관', '학생회관'). 비우면 전체 목록."""
    page = _get("/kor/CMS/CampusMgr/list.do", mCode="MN057")
    rows = dict.fromkeys((f"{n}호관 " if n.strip() else "") + _text(t) for n, t in re.findall(
        r'class="cmap-btn[^"]*"[^>]*>\s*<span class="num">(.*?)</span>\s*<span class="txt">(.*?)</span>', page, re.S))
    if keyword:
        k = keyword.strip().removesuffix("호관").lstrip("0")
        if k.isdigit():
            rows = [r for r in rows if r.split("호관")[0].lstrip("0") == k]
        else:
            alias = {"기숙사": "학사|생활관|기숙사", "식당": "식당|학생회관", "체육관": "체육|스포츠"}
            pat = alias.get(keyword.strip(), re.escape(_norm(keyword)))
            rows = [r for r in rows if re.search(pat, _norm(r))]
    return "\n".join(rows) + f"\n\n지도: {BASE}/kor/CMS/CampusMgr/list.do?mCode=MN057" if rows else "없음."


# ── 실행 ──────────────────────────────────────────────────────────────
def main() -> None:
    """uou-mcp           → stdio (Claude Desktop/Code가 직접 띄움)
    uou-mcp --http [포트] → http://127.0.0.1:44610/mcp 로컬 서버"""
    for s in (sys.stdout, sys.stderr):  # Windows 기본 cp949에서 한글 로그가 깨지지 않게
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if "--http" in sys.argv:
        i = sys.argv.index("--http")
        port = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 44610
        print(f"uou-mcp: http://127.0.0.1:{port}/mcp", file=sys.stderr)
        mcp.run("streamable-http", host="127.0.0.1", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
