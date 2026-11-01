"""트랙소개서 PDF(홈페이지 MN355) → data/tracks.json. 학교가 새 판을 올리면 다시 돌린다.
uv run --with pdfplumber python build_tracks.py"""
import io
import json
import pathlib
import re
import statistics
import urllib.request

import pdfplumber
from pypdf import PdfReader

URL = "https://www.ulsan.ac.kr/kor/ajx_json/UploadMgr/downloadRun.do?qcode=Q29udGVudE1nciwxNzQ0MSxZ"


def curriculum(page) -> str:
    """이수체계도 표를 글자 좌표로 '2학년 1학기: 과목, …'로 정리. 학기 헤더(1학기/2학기) 열의 x 중심에 과목을 붙인다."""
    words = page.extract_words()
    cx = lambda w: (w["x0"] + w["x1"]) / 2
    sems = [w for w in words if w["text"] in ("1학기", "2학기")]
    rows = sorted({round(w["top"]) for w in sems})
    out = []
    for i, top in enumerate(rows):
        bottom = rows[i + 1] - 30 if i + 1 < len(rows) else page.height
        hdr = sorted((w for w in sems if abs(w["top"] - top) < 3), key=cx)
        if len(hdr) < 2:
            continue
        years = [w for w in words if re.match(r"\d학년", w["text"]) and top - 40 < w["top"] < top]
        label = lambda h: (min(years, key=lambda y: abs(cx(y) - cx(h)))["text"][:3] + " " if years else "") + h["text"]
        gap = statistics.median(cx(b) - cx(a) for a, b in zip(hdr, hdr[1:]))
        cols = {label(h): [] for h in hdr}
        for w in sorted((w for w in words if top + 5 < w["top"] < bottom), key=lambda w: (w["top"], w["x0"])):
            h = min(hdr, key=lambda h: abs(cx(h) - cx(w)))
            if abs(cx(h) - cx(w)) < gap * 0.6 and not w["text"].startswith("※"):
                cols[label(h)].append(w["text"])
        title = [w for w in words if "이수체계도" in w["text"] and w["top"] < top]
        title_line = " ".join(x["text"] for x in words if title and abs(x["top"] - title[-1]["top"]) < 3) if title else "이수체계도"
        out.append(title_line)
        for k, v in cols.items():
            courses = [c.strip() for c in re.findall(r"[^()]+?\(\d\)", " ".join(v))]
            if courses:
                out.append(f"- {k}: {', '.join(courses)}")
    return "\n".join(out)


raw = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read()
pages = []
with pdfplumber.open(io.BytesIO(raw)) as plumb:
    for i, p in enumerate(PdfReader(io.BytesIO(raw)).pages, 1):
        # layout 모드: 표가 대략 줄 맞춰 나온다(기본 모드는 칸이 뒤섞임)
        text = p.extract_text(extraction_mode="layout") or ""
        text = re.sub(r" {3,}", "   ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", "\n".join(l.rstrip() for l in text.splitlines())).strip()
        if len(text) < 50:  # 표지·간지(이미지뿐)는 버림
            continue
        if "이수체계도" in text and "1학기" in text:
            cur = curriculum(plumb.pages[i - 1])
            if cur:
                text += "\n\n[이수체계도 학기별 정리(PDF 좌표로 자동 정리, 원본 표와 다를 수 있음)]\n" + cur
        pages.append({"page": i, "text": text})
out = pathlib.Path(__file__).parent / "uou_mcp" / "data" / "tracks.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({"source": URL, "title": "2026 울산대학교 트랙소개서", "pages": pages}, ensure_ascii=False), encoding="utf-8")
print(f"{len(pages)} pages, {sum('학기별 정리' in p['text'] for p in pages)} curriculum pages → {out}")
