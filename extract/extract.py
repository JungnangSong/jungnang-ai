"""docs 폴더의 hwpx/hwp/PDF 에서 글자를 뽑아 data/ 아래에 저장한다.

사용법
  python extract/extract.py            # 전체 (OCR 포함, 캐시가 있으면 이어서)
  python extract/extract.py --no-ocr   # 글자층 있는 파일만 (빠름)
  python extract/extract.py --workers 4
산출물: data/cache/*.json (파일별), data/chunks.json, data/report.md
"""
import argparse, json, os, re, struct, sys, zlib, zipfile, unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
CACHE = DATA / "cache"
CHUNK_SIZE = 700
OCR_SCALE = 2.0


# ---------- 공통 ----------
def norm_ws(s):
    s = s.replace(" ", " ").replace("​", "")
    return re.sub(r"[ \t]+", " ", s).strip()


def quality(text):
    """한글 비율·깨짐 비율로 글자 품질 점수 (높을수록 깨끗)."""
    if not text:
        return 0.0
    n = len(text)
    bad = sum(1 for c in text if c == "�" or (ord(c) < 32 and c not in "\n\t") or 0xE000 <= ord(c) <= 0xF8FF)
    hangul = sum(1 for c in text if "가" <= c <= "힣")
    return (hangul / n) * 0.5 + (1 - bad / n) * 0.5


def cache_path(path):
    return CACHE / (re.sub(r"[^\w가-힣]+", "_", path.stem) + ".json")


# ---------- HWPX (zip + XML) ----------
def _ln(el):
    return el.tag.rsplit("}", 1)[-1]


def _own_text(p):
    """문단 p 의 글자 (안쪽 표는 제외)."""
    out = []

    def walk(e):
        for c in e:
            n = _ln(c)
            if n == "tbl":
                continue
            if n == "t":
                out.append(c.text or "")
                for sub in c:  # <hp:tab/>, <hp:lineBreak/> 등
                    out.append(" " if _ln(sub) in ("tab", "fwSpace", "nbSpace") else "")
                    out.append(sub.tail or "")
            else:
                walk(c)

    walk(p)
    return norm_ws("".join(out))


def _table_rows(tbl):
    rows = []
    for tr in tbl:
        if _ln(tr) != "tr":
            continue
        cells = []
        for tc in tr:
            if _ln(tc) != "tc":
                continue
            parts = [t for t in _flatten(tc)]
            cells.append(" ".join(parts))
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def _flatten(el):
    """셀 안의 모든 문단·중첩표 글자를 순서대로."""
    for c in el.iter():
        if _ln(c) == "p":
            t = _own_text(c)
            if t:
                yield t


def hwpx_paragraphs(path):
    from lxml import etree

    paras = []
    with zipfile.ZipFile(path) as z:
        secs = sorted(
            (n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.findall(r"\d+", n)[0]),
        )
        for name in secs:
            with z.open(name) as fh:
                root = etree.parse(fh, etree.XMLParser(huge_tree=True, recover=True)).getroot()

            def visit(e):
                for c in e:
                    n = _ln(c)
                    if n == "p":
                        t = _own_text(c)
                        if t:
                            paras.append(t)
                        for tbl in c.iter():
                            if _ln(tbl) == "tbl":
                                paras.extend(_table_rows(tbl))
                    elif n not in ("tbl",):
                        visit(c)

            visit(root)
    return paras


# ---------- HWP5 (OLE 바이너리; 확장자만 hwpx 인 파일 대응) ----------
def hwp5_paragraphs(path):
    import olefile

    ole = olefile.OleFileIO(str(path))
    flags = struct.unpack("<I", ole.openstream("FileHeader").read()[36:40])[0]
    compressed, encrypted = bool(flags & 1), bool(flags & 2)
    if encrypted:
        raise RuntimeError("암호화된 HWP")
    secs = sorted(
        (e for e in ole.listdir() if e[0] == "BodyText" and e[1].startswith("Section")),
        key=lambda e: int(e[1][7:]),
    )
    paras = []
    for e in secs:
        data = ole.openstream(e).read()
        if compressed:
            data = zlib.decompress(data, -15)
        i = 0
        while i + 4 <= len(data):
            h = struct.unpack_from("<I", data, i)[0]
            tag, size = h & 0x3FF, h >> 20
            i += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", data, i)[0]
                i += 4
            body = data[i : i + size]
            i += size
            if tag == 67:  # PARA_TEXT
                chars, k = [], 0
                while k + 2 <= len(body):
                    ch = struct.unpack_from("<H", body, k)[0]
                    k += 2
                    if ch < 32:
                        if ch in (10, 13):
                            chars.append("\n")
                        elif ch not in (0, 24, 25, 26, 27, 28, 29, 30, 31):
                            k += 14  # 확장/인라인 컨트롤은 8 wchar
                        continue
                    chars.append(chr(ch))
                text = "".join(chars).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "ignore")
                for line in text.split("\n"):
                    line = norm_ws(line)
                    if line:
                        paras.append(line)
    return paras


def extract_hwp_family(path):
    with open(path, "rb") as f:
        magic = f.read(4)
    paras = hwpx_paragraphs(path) if magic == b"PK\x03\x04" else hwp5_paragraphs(path)
    kind = "hwpx" if magic == b"PK\x03\x04" else "hwpx(HWP5 바이너리)"
    return {"format": kind, "units": [{"n": i + 1, "text": t} for i, t in enumerate(paras)]}


# ---------- PDF ----------
def pdf_text_layer(path):
    import pypdfium2 as pdfium

    d = pdfium.PdfDocument(str(path))
    out = []
    for i in range(len(d)):
        out.append(norm_multiline(d[i].get_textpage().get_text_range()))
    return out


def norm_multiline(s):
    lines = [norm_ws(x) for x in s.replace("\r", "\n").split("\n")]
    return "\n".join(x for x in lines if x)


def ocr_lines(result):
    """RapidOCR 결과를 위→아래, 왼→오른 순 줄로 합친다."""
    items = []
    for box, text, score in result or []:
        if float(score) < 0.5:
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((sum(ys) / 4, min(xs), max(ys) - min(ys), text))
    items.sort(key=lambda t: (t[0], t[1]))
    lines, cur, cy, ch = [], [], None, 0
    for y, x, h, t in items:
        if cur and abs(y - cy) <= max(ch, h) * 0.6:
            cur.append((x, t))
        else:
            if cur:
                lines.append(" ".join(s for _, s in sorted(cur)))
            cur, cy, ch = [(x, t)], y, h
    if cur:
        lines.append(" ".join(s for _, s in sorted(cur)))
    return "\n".join(lines)


def extract_pdf(path, use_ocr, cpath):
    import pypdfium2 as pdfium

    layer = pdf_text_layer(path)
    n = len(layer)
    prev = json.loads(cpath.read_text("utf-8")) if cpath.exists() else {}
    done = {u["n"]: u for u in prev.get("units", [])}
    empty = [i for i, t in enumerate(layer) if len(t) < 20]
    ocr_target = empty if use_ocr else []
    # 글자층이 아예 없는 파일은 OCR 문서로 표시
    mode = "OCR" if len(empty) > n * 0.5 else "글자층"
    units = {}
    for i, t in enumerate(layer):
        units[i + 1] = {"n": i + 1, "text": t, "src": "text"}
    if ocr_target:
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np

        eng = RapidOCR()
        d = pdfium.PdfDocument(str(path))
        for k, i in enumerate(ocr_target):
            if (i + 1) in done and done[i + 1].get("src") == "ocr":
                units[i + 1] = done[i + 1]
                continue
            img = np.array(d[i].render(scale=OCR_SCALE).to_pil().convert("RGB"))
            res, _ = eng(img)
            units[i + 1] = {"n": i + 1, "text": ocr_lines(res), "src": "ocr"}
            if k % 5 == 4:
                save_cache(cpath, path, mode, n, units, partial=True)
                print(f"  [{path.name}] OCR {k + 1}/{len(ocr_target)}", flush=True)
    return {"format": "PDF", "mode": mode, "pages": n, "units": [units[i] for i in sorted(units)]}


def save_cache(cpath, path, mode, n, units, partial=False):
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(
        json.dumps(
            {"doc": path.stem, "file": path.name, "format": "PDF", "mode": mode, "pages": n,
             "partial": partial, "units": [units[i] for i in sorted(units)]},
            ensure_ascii=False),
        "utf-8")


# ---------- 파일 단위 ----------
def process(args):
    path, use_ocr = args
    path = Path(path)
    cpath = cache_path(path)
    try:
        ext = path.suffix.lower()
        if cpath.exists() and (lambda c: not c.get("partial", True) and not c.get("error"))(json.loads(cpath.read_text("utf-8"))):
            return path.name, "cached"
        if ext in (".hwpx", ".hwp"):
            r = extract_hwp_family(path)
            res = {"doc": path.stem, "file": path.name, **r, "partial": False}
        elif ext == ".pdf":
            r = extract_pdf(path, use_ocr, cpath)
            res = {"doc": path.stem, "file": path.name, **r,
                   "partial": use_ocr is False and r["mode"] == "OCR"}
            if use_ocr:
                res["partial"] = False
        else:
            return path.name, "skip"
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps(res, ensure_ascii=False), "utf-8")
        return path.name, "ok"
    except Exception as e:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps({"doc": path.stem, "file": path.name, "error": repr(e),
                                     "partial": False, "units": []}, ensure_ascii=False), "utf-8")
        return path.name, f"ERROR {e!r}"


# ---------- 보고서 / 청크 ----------
def key_of(name):
    s = unicodedata.normalize("NFC", Path(name).stem)
    return re.sub(r"[\s\W_]+", "", s).lower()


def chunk_units(doc, fmt, units, is_page):
    chunks = []
    if is_page:
        for u in units:
            t = u["text"].strip()
            if not t:
                continue
            for j in range(0, len(t), CHUNK_SIZE):
                chunks.append({"doc": doc, "format": fmt, "loc": f"{u['n']}쪽", "text": t[j : j + CHUNK_SIZE]})
    else:
        buf, first, last = [], None, None
        for u in units:
            t = u["text"]
            if buf and sum(len(x) for x in buf) + len(t) > CHUNK_SIZE:
                chunks.append({"doc": doc, "format": fmt, "loc": f"문단 {first}~{last}", "text": "\n".join(buf)})
                buf, first = [], None
            if first is None:
                first = u["n"]
            buf.append(t[:CHUNK_SIZE * 3])
            last = u["n"]
        if buf:
            chunks.append({"doc": doc, "format": fmt, "loc": f"문단 {first}~{last}", "text": "\n".join(buf)})
    return chunks


def build():
    docs = [json.loads(p.read_text("utf-8")) for p in sorted(CACHE.glob("*.json"))]
    # 중복(같은/비슷한 이름의 hwpx·PDF) → 품질 높은 쪽만
    groups = {}
    for d in docs:
        groups.setdefault(key_of(d["file"]), []).append(d)
    keep, dropped = [], []
    for g in groups.values():
        score = lambda d: quality("\n".join(u["text"] for u in d.get("units", [])[:300]))
        g.sort(key=score, reverse=True)
        keep.append(g[0])
        dropped += [(x["file"], g[0]["file"]) for x in g[1:]]
    keep.sort(key=lambda d: d["file"])

    chunks, lines, problems = [], [], []
    lines.append("# 추출 점검 보고서\n")
    lines.append("| 파일 | 형식 | 방식 | 단위 수 | 글자 수 | 품질 | 상태 |\n|---|---|---|---|---|---|---|")
    previews = []
    for d in keep:
        units = d.get("units", [])
        text = "\n".join(u["text"] for u in units)
        total = len(re.sub(r"\s", "", text))
        q = quality(re.sub(r"\s", "", text))
        is_page = d.get("format") == "PDF"
        status = "정상"
        if d.get("error"):
            status = "실패: " + d["error"]
        elif total < 200:
            status = "글자 거의 없음"
        elif q < 0.45:
            status = "깨짐 의심"
        if d.get("partial"):
            status += " (OCR 미완료)"
        if status != "정상":
            problems.append((d["file"], status))
        unit_n = d.get("pages") if is_page else len(units)
        lines.append(f"| {d['file']} | {d.get('format')} | {d.get('mode', '-')} | {unit_n} | {total:,} | {q:.2f} | {status} |")
        pv = re.sub(r"\s+", " ", text)[:200]
        previews.append(f"### {d['file']}\n- 글자 수: {total:,}\n- 미리보기: {pv or '(없음)'}\n")
        if not d.get("error") and total:
            chunks += chunk_units(d["doc"], d["format"], units, is_page)
    lines.append("\n## 파일별 앞부분 미리보기\n")
    lines += previews
    lines.append("\n## 추출 안 됨 / 깨짐 / 확인 필요\n")
    lines += [f"- {f}: {s}" for f, s in problems] or ["- 없음"]
    lines.append("\n## 중복으로 제외된 파일\n")
    lines += [f"- {a} → {b} 와 중복, 제외" for a, b in dropped] or ["- 없음 (이름이 같거나 비슷한 hwpx/PDF 쌍 없음)"]
    DATA.mkdir(exist_ok=True)
    (DATA / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), "utf-8")
    (DATA / "report.md").write_text("\n".join(lines), "utf-8")
    print("\n".join(lines))
    print(f"\n청크 {len(chunks):,}개 저장 → data/chunks.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not a.report_only:
        files = sorted(p for p in DOCS.iterdir() if p.suffix.lower() in (".hwpx", ".hwp", ".pdf"))
        # 큰 OCR 대상이 먼저 시작하도록 PDF 먼저
        files.sort(key=lambda p: p.suffix.lower() != ".pdf")
        with ProcessPoolExecutor(a.workers) as ex:
            for name, st in ex.map(process, [(f, not a.no_ocr) for f in files]):
                print(f"{st:8} {name}", flush=True)
    build()


if __name__ == "__main__":
    main()
