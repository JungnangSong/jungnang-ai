const log = document.getElementById('log');
const form = document.getElementById('form');
const input = document.getElementById('input');
const send = document.getElementById('send');
let busy = false;

function add(role, text) {
  const m = document.createElement('div');
  m.className = 'msg ' + role;
  const b = document.createElement('div');
  b.className = 'bubble';
  b.textContent = text;
  m.appendChild(b);
  log.appendChild(m);
  log.scrollTop = log.scrollHeight;
  return b;
}

async function ask(q) {
  q = q.trim();
  if (!q || busy) return;
  busy = true; send.disabled = true;
  add('user', q);
  input.value = ''; input.style.height = 'auto';
  const b = add('bot', '');
  b.innerHTML = '<span class="dots"><span></span><span></span><span></span></span>';
  try {
    const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || '오류가 발생했습니다.');
    b.textContent = d.body || d.answer;
    if (d.sources && d.sources.length) {
      const s = document.createElement('div');
      s.className = 'src';
      s.innerHTML = '<b>참고</b>';
      for (const x of d.sources) {
        const line = document.createElement('span');
        line.textContent = `${x.doc} · ${x.format} · ${x.loc}`;
        s.appendChild(line);
      }
      b.appendChild(s);
    }
  } catch (e) {
    b.textContent = '⚠ ' + e.message;
  } finally {
    busy = false; send.disabled = false; log.scrollTop = log.scrollHeight; input.focus();
  }
}

form.addEventListener('submit', (e) => { e.preventDefault(); ask(input.value); });
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
});
input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 120) + 'px'; });

fetch('/api/suggestions').then((r) => r.json()).then((list) => {
  const box = document.getElementById('chips');
  for (const q of list.slice(0, 3)) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.textContent = q;
    btn.addEventListener('click', () => ask(q));
    box.appendChild(btn);
  }
});
