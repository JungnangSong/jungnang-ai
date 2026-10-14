// 한국어 문서 조각 검색: 글자 2-gram + 단어 BM25 (외부 라이브러리 없음)
const fs = require('fs');

const STOP = new Set(['은', '는', '이', '가', '을', '를', '의', '에', '도', '로', '과', '와', '및', '좀', '뭐', '무엇', '어떻게', '알려줘', '알려', '주세요', '알려주세요', '해줘', '어떤', '모두', '내용인가요', '인가요', '있나요', '무엇인가요', '몇', '대해', '관련', '대한', '등']);

function tokens(text) {
  const t = text.toLowerCase().replace(/[^0-9a-z가-힣\s]/g, ' ');
  const out = [];
  for (const w of t.split(/\s+/).filter(Boolean)) {
    if (STOP.has(w)) continue;
    if (/^[0-9a-z]+$/.test(w)) { out.push(w); continue; }
    for (let i = 0; i < w.length - 1; i++) out.push(w.slice(i, i + 2));
    for (let i = 0; i < w.length - 2; i++) out.push(w.slice(i, i + 3));
  }
  return out;
}

class Index {
  constructor(chunks) {
    // 완전히 같은 내용(동별 책자의 공통 부분 등)은 하나만 남김
    const seen = new Set();
    this.docs = [];
    for (const c of chunks) {
      const key = c.text.replace(/\s+/g, '');
      if (seen.has(key)) continue;
      seen.add(key);
      this.docs.push(c);
    }
    this.title = this.docs.map((d) => new Set(tokens(d.doc).filter((t) => t.length === 2)));
    this.tf = this.docs.map((d) => {
      const m = new Map();
      for (const t of tokens(d.text)) m.set(t, (m.get(t) || 0) + 1);
      return m;
    });
    this.len = this.tf.map((m) => [...m.values()].reduce((a, b) => a + b, 0));
    this.avg = this.len.reduce((a, b) => a + b, 0) / Math.max(1, this.len.length);
    this.df = new Map();
    for (const m of this.tf) for (const t of m.keys()) this.df.set(t, (this.df.get(t) || 0) + 1);
  }

  search(query, k = 8) {
    const q = [...new Set(tokens(query))];
    const N = this.docs.length;
    const scored = [];
    const idfOf = (t) => Math.log(1 + (N - (this.df.get(t) || 0) + 0.5) / ((this.df.get(t) || 0) + 0.5));
    const qTotal = q.reduce((a, t) => a + idfOf(t), 0) || 1;
    for (let i = 0; i < N; i++) {
      let s = 0, cov = 0;
      for (const t of q) {
        const f = this.tf[i].get(t);
        if (!f) continue;
        cov += idfOf(t);
        const df = this.df.get(t);
        const idf = Math.log(1 + (N - df + 0.5) / (df + 0.5));
        const w = t.length >= 3 ? 1.5 : 1;
        s += w * idf * ((f * 2.2) / (f + 1.2 * (0.25 + 0.75 * (this.len[i] / this.avg))));
      }
      if (s > 0) {
        let hit = 0;
        for (const t of q) if (t.length === 2 && this.title[i].has(t)) hit++;
        if (hit >= 2) s += 4 * hit;
      }
      if (s > 0) scored.push([s, i, cov / qTotal]);
    }
    scored.sort((a, b) => b[0] - a[0]);
    return scored.slice(0, k).map(([score, i, coverage]) => ({ ...this.docs[i], score, coverage }));
  }
}

function load(file) {
  return new Index(JSON.parse(fs.readFileSync(file, 'utf8')));
}

module.exports = { load };
