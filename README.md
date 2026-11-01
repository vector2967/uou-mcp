# uou-mcp — 울산대학교 MCP 서버

Claude, Cursor 같은 AI에게 **울산대학교 정보**를 물어볼 수 있게 해 주는 [MCP](https://modelcontextprotocol.io) 서버입니다.
학교 공개 홈페이지·학과 홈페이지·도서관을 그때그때 읽어서 답하므로 항상 최신 정보를 줍니다.

> "내일 학식 뭐야?" · "산업ICT공학 기본트랙 2학년 1학기 과목 알려줘" · "ICT융합학부 사무실 어디야?"
> "도서관에 파이썬 책 대출 가능한 거 있어?" · "기말고사 언제야?" · "최근 채용공지 보여줘"

- 비공식 프로젝트입니다. 울산대학교와 관계없으며, 정확한 내용은 학교 공식 안내를 확인하세요.
- 로그인이 필요한 정보(UWINS 시간표·성적, UCLASS, 도서관 좌석)는 다루지 않습니다. 개인정보를 저장하지 않습니다.

## 설치

**준비물: [uv](https://docs.astral.sh/uv/getting-started/installation/) 하나만** 설치하면 됩니다.

- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

그다음 쓰는 앱에 아래처럼 등록합니다. 처음 실행할 때 자동으로 내려받아 실행됩니다.

### Claude Code

```bash
claude mcp add --scope user uou -- uvx --from git+https://github.com/vector2967/uou-mcp uou-mcp
```

### Claude Desktop

설정 → 개발자 → 구성 편집(`claude_desktop_config.json`)에 추가하고 Claude Desktop을 다시 켭니다.

```json
{
  "mcpServers": {
    "uou": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/vector2967/uou-mcp", "uou-mcp"]
    }
  }
}
```

### Cursor / 기타 MCP 앱

`~/.cursor/mcp.json` 등 앱의 MCP 설정에 위와 같은 `command`/`args`를 넣으면 됩니다.

### 로컬 HTTP 서버로 쓰기 (선택)

여러 앱이 같이 쓰거나 URL로 연결해야 할 때:

```bash
uvx --from git+https://github.com/vector2967/uou-mcp uou-mcp --http        # → http://127.0.0.1:44610/mcp
claude mcp add --transport http uou http://127.0.0.1:44610/mcp
```

### 업데이트

```bash
uv cache clean uou-mcp
```

다음에 앱을 켤 때 최신 버전을 다시 받습니다.

## 할 수 있는 것

| 도구 | 하는 일 |
|---|---|
| `meal` | 학식 메뉴(학생·교직원·기숙사, 오늘/내일/금요일/11/6 등) |
| `academic_schedule` | 학사일정(기말고사·수강신청·휴복학 등 검색) |
| `track_search` / `track_page` | 2026 트랙소개서(258쪽)에서 트랙·이수체계도(학년·학기별 과목)·전공필수·진로 검색 |
| `departments` | 단과대학·학부(2025 개편)와 학부/전공 홈페이지 |
| `dept_contact` | 학부·학과 사무실 위치·전화, 교수·직원 연락처 |
| `dept_site` | 학과 홈페이지 메뉴(찾아오시는길·교수소개·교육과정 등) 읽기 |
| `dept_notices` / `dept_notice_detail` | 학부·학과 공지사항(학과 사이트 117곳 중 107곳) |
| `notices` / `notice_detail` | 본교 공지·UOU소식·언론보도·연구성과·동아리 등 게시판, 본문·첨부 |
| `read_attachment` | 공지 첨부 PDF를 글자로 읽기(울산대 링크만) |
| `jobs` / `job_detail` | 채용공지(기업 채용·교내채용, 마감일·자격요건) |
| `site_menu` / `site_page` | 홈페이지 전체 메뉴 → 페이지 읽기(등록금·장학·기숙사·통학버스·주차·의료·증명서·학칙 등) |
| `site_search` | 홈페이지 통합검색(본문·게시판까지) |
| `library_search` / `library_hours` | 도서 검색(위치·청구기호·대출가능), 도서관 운영시간 |
| `campus_building` | 건물 번호·이름 찾기 |

### 알려진 한계

- 교직원식당 식단은 학교 홈페이지에 올라오지 않아 볼 수 없습니다.
- 일부 학과 사이트는 닫혔거나(공공인재·국제학부·의대 등) 게시판을 읽을 수 없습니다(간호학과). 이 경우 링크를 안내합니다.
- 이미지로만 올라온 안내(셔틀 노선도 등)는 글자를 읽지 못하고 이미지 링크만 줍니다.
- 이수체계도의 학년·학기 정리는 PDF 글자 위치로 자동 생성한 것이라 원본 표와 조금 다를 수 있습니다.

## 개발

```bash
git clone https://github.com/vector2967/uou-mcp && cd uou-mcp
uv sync
uv run uou-mcp                 # stdio 실행
uv run python check.py         # 실제 학교 사이트로 전 도구 점검(사이트 구조가 바뀌면 여기서 먼저 깨짐)
uv run --with pdfplumber python build_tracks.py   # 트랙소개서 새 판이 올라오면 데이터 다시 만들기
```

- 학교 서버 부담을 줄이려고 요청을 10분 캐시합니다. 대량 요청(크롤링)에 쓰지 마세요.
- 학교 사이트 구조가 바뀌어 안 되는 기능이 있으면 이슈로 알려 주세요.

## 라이선스

MIT. 트랙소개서 등 학교 자료의 저작권은 울산대학교에 있습니다(`uou_mcp/data/tracks.json`은 공개 PDF에서 뽑은 텍스트).
