/* JARVIS front end.

   Voice goes through the Python server both directions — ElevenLabs Scribe for
   speech in, ElevenLabs TTS for speech out. The browser's Web Speech API is
   deliberately not used: it is Chrome-only, ships audio to Google, and in Brave
   it is a stub that fails silently. */

// --- tune these ---
const SILENCE_MS = 900;        // quiet for this long ends the turn
const SILENCE_LEVEL = 0.055;   // 0..1 RMS below this counts as quiet
const MIN_TURN_MS = 600;       // ignore blips shorter than this
const LEVEL_TICK_MS = 50;      // setInterval, NOT requestAnimationFrame:
                               // RAF stops dead in a backgrounded tab and the
                               // mic goes silently deaf.
const MAX_TURN_MS = 30000;

const EXAMPLES = [
  'What is the lead response system?',
  'Brief me.',
  'What should I work on first?',
  'Who is in my inbox?',
  'What did I write about pricing?',
  'Remember that Scribe handles speech in.',
];

const $ = s => document.querySelector(s);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const state = {
  history: [],     // last ~10 turns, sent with every ask
  status: null,
  muted: false,
  listening: false,
  speaking: false,
  mode: 'idle',
  types: new Set(),
  hiddenTypes: new Set(),
};

let graph, audioEl = null;

// ---------------------------------------------------------------- notices

function notice(text, kind = 'warn', ttl = 0) {
  const box = $('#notices');
  // Same problem reported twice is noise; loud once is the point.
  for (const existing of box.children) {
    if (existing.textContent === text) return existing;
  }
  const n = el('div', 'notice ' + (kind === 'info' ? 'info' : ''), text);
  box.appendChild(n);
  if (ttl) setTimeout(() => n.remove(), ttl);
  return n;
}

// ---------------------------------------------------------------- reactor

const reactor = (() => {
  const cv = $('#reactor'), c = cv.getContext('2d');
  let t = 0, level = 0;
  const COLOR = { idle: '#4a5a6a', listening: '#4fd1e0', thinking: '#a98fe0', speaking: '#7ee0a2' };

  function draw() {
    t += 0.02;
    const w = cv.width, h = cv.height, cx = w / 2, cy = h / 2;
    c.clearRect(0, 0, w, h);
    const col = COLOR[state.mode] || COLOR.idle;
    const base = 78;

    c.strokeStyle = 'rgba(140,165,190,0.16)';
    c.lineWidth = 2;
    c.beginPath(); c.arc(cx, cy, base + 34, 0, 7); c.stroke();

    // rotating arc segments
    for (let i = 0; i < 3; i++) {
      const off = t * (i % 2 ? -0.55 : 0.75) + i * 2.1;
      c.strokeStyle = col;
      c.globalAlpha = 0.34 + 0.12 * i;
      c.lineWidth = 2.5;
      c.beginPath();
      c.arc(cx, cy, base + 16 - i * 9, off, off + 1.15);
      c.stroke();
    }
    c.globalAlpha = 1;

    const pulse = state.mode === 'idle' ? 1 + Math.sin(t * 1.5) * 0.02
                : state.mode === 'listening' ? 1 + level * 0.55
                : state.mode === 'thinking' ? 1 + Math.sin(t * 5) * 0.05
                : 1 + Math.sin(t * 9) * 0.08;

    const g = c.createRadialGradient(cx, cy, 4, cx, cy, base * pulse);
    g.addColorStop(0, col);
    g.addColorStop(0.45, col + '55');
    g.addColorStop(1, 'transparent');
    c.fillStyle = g;
    c.beginPath(); c.arc(cx, cy, base * pulse, 0, 7); c.fill();

    c.strokeStyle = col;
    c.globalAlpha = 0.75;
    c.lineWidth = 2;
    c.beginPath(); c.arc(cx, cy, 30 * pulse, 0, 7); c.stroke();
    c.globalAlpha = 1;
    requestAnimationFrame(draw);
  }
  draw();
  return { setLevel: v => { level = v; } };
})();

function setMode(m) {
  state.mode = m;
  $('#state').textContent = m;
  $('#state').className = m;
}

// ---------------------------------------------------------------- meters

const meters = (() => {
  const wrap = $('#meters');
  const bars = [];
  for (let i = 0; i < 7; i++) { const b = el('i'); wrap.appendChild(b); bars.push(b); }
  return {
    set(level) {
      for (let i = 0; i < bars.length; i++) {
        const k = 1 - Math.abs(i - 3) / 4.5;
        const h = 2 + level * 46 * k * (0.7 + Math.random() * 0.6);
        bars[i].style.height = Math.min(18, h) + 'px';
        bars[i].style.opacity = 0.3 + level * 1.2;
      }
    },
  };
})();

// ---------------------------------------------------------------- transcript

function addTurn(who, text) {
  const t = el('div', 'turn ' + who);
  t.appendChild(el('div', 'who', who === 'user' ? 'you' : 'jarvis'));
  t.appendChild(el('div', 'said', text));
  $('#transcript').appendChild(t);
  $('#transcript').scrollTop = 1e6;
  return t;
}

function addCard(card) {
  if (!card) return;
  const c = el('div', 'card');
  c.appendChild(el('div', 'ck', card.kind));
  const row = (title, sub, noteId) => {
    const r = el('div', 'row');
    if (noteId) {
      const cite = el('cite', null, title);
      cite.onclick = () => { graph.focusOn(noteId); openNote(noteId); };
      r.appendChild(cite);
    } else {
      r.appendChild(el('div', 't', title));
    }
    if (sub) r.appendChild(el('div', 's', sub));
    c.appendChild(r);
  };

  if (card.kind === 'search') {
    if (!card.results.length) row('No match', card.query);
    card.results.forEach(r => row(r.rel, r.excerpt, r.id));
    (card.flagged || []).forEach(f => row('⚠ instruction-like text in ' + f, 'Reported, not followed.'));
  } else if (card.kind === 'plan') {
    (card.items || []).forEach((it, i) => row(`${i + 1}. ${it.task}`, `${it.source} · ${it.why}${it.due ? ' · due ' + it.due : ''}`));
  } else if (card.kind === 'brief') {
    (card.events || []).forEach(e => row(e.title, e.start.replace('T', ' ')));
    (card.unread || []).forEach(m => row(m.subject, m.from));
    (card.slipped || []).forEach(s => row('⚠ ' + s.task, `${s.note} · was due ${s.due}`));
    if (!card.events.length && !card.unread.length && !card.slipped.length) row('Clear', 'Nothing scheduled, nothing unread.');
  } else if (card.kind === 'inbox') {
    if (card.status !== 'ok') row('Inbox unavailable', 'Set JARVIS_INBOX_PATH.');
    (card.messages || []).forEach(m => row(
      m.subject,
      `${m.from} · ${m.known_from && m.known_from.length ? 'known: ' + m.known_from.join(', ') : 'not in your files'}${m.flagged ? ' · ⚠ instruction-like text' : ''}`
    ));
  } else if (card.kind === 'memory') {
    if (card.written) row(card.written.file, card.written.fact);
    (card.all || []).slice(0, 8).forEach(f => { if (!card.written || f.file !== card.written.file) row(f.file, f.fact); });
  } else if (card.kind === 'research') {
    row('Not run', card.why);
    (card.local_context || []).forEach(r => row(r.rel, r.excerpt, r.id));
  } else if (card.kind === 'error') {
    row('Error', card.detail);
  } else {
    row(JSON.stringify(card).slice(0, 300), '');
  }
  $('#transcript').appendChild(c);
  $('#transcript').scrollTop = 1e6;
}

// ---------------------------------------------------------------- asking

async function ask(text) {
  text = (text || '').trim();
  if (!text) return;
  addTurn('user', text);
  state.history.push({ role: 'user', text });
  setMode('thinking');
  $('#ask').value = '';

  let data;
  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, history: state.history.slice(-20) }),
    });
    data = await res.json();
  } catch (e) {
    setMode('idle');
    notice('Server unreachable: ' + e.message);
    return;
  }

  if (data.notice) notice(data.notice, 'warn', 6000);
  addTurn('jarvis', data.say || '(nothing)');
  addCard(data.card);
  state.history.push({ role: 'assistant', text: data.say || '' });
  state.history = state.history.slice(-20);

  if (data.card && (data.card.kind === 'memory' || data.card.kind === 'search')) refreshStatus();
  await speak(data.say);
}

// ---------------------------------------------------------------- speech out

async function speak(text) {
  if (!text || state.muted) { setMode('idle'); return; }
  setMode('speaking');
  state.speaking = true;   // mic goes deaf here — see micTick()
  try {
    const res = await fetch('/api/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      notice('Speech out failed: ' + (err.error || res.status), 'warn', 8000);
      return;
    }
    const buf = await res.arrayBuffer();
    await new Promise(resolve => {
      audioEl = new Audio(URL.createObjectURL(new Blob([buf], { type: 'audio/mpeg' })));
      audioEl.onended = audioEl.onerror = resolve;
      audioEl.play().catch(() => resolve());
    });
  } catch (e) {
    notice('Speech out failed: ' + e.message, 'warn', 8000);
  } finally {
    audioEl = null;
    state.speaking = false;
    setMode(state.listening ? 'listening' : 'idle');
  }
}

function stopSpeaking() {
  if (audioEl) { audioEl.pause(); audioEl.onended && audioEl.onended(); }
}

// ---------------------------------------------------------------- speech in

const mic = (() => {
  let stream = null, ctx = null, analyser = null, buf = null;
  let recorder = null, chunks = [], timer = null;
  let quietFor = 0, turnMs = 0, sawSpeech = false;

  async function start() {
    if (state.listening) return;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch (e) {
      // A blocked microphone that produces no error is the most confusing
      // failure in this build. Always say so on screen.
      notice('Microphone blocked or unavailable: ' + e.name + '. Check the browser permission for localhost.');
      return;
    }
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    buf = new Float32Array(analyser.fftSize);
    ctx.createMediaStreamSource(stream).connect(analyser);

    state.listening = true;
    $('#mic').classList.add('on');
    setMode('listening');
    $('#caption').textContent = 'Listening — press mic, Space or Esc to stop.';
    $('#caption').className = 'live';
    beginTurn();
    timer = setInterval(tick, LEVEL_TICK_MS);
  }

  function beginTurn() {
    chunks = []; quietFor = 0; turnMs = 0; sawSpeech = false;
    let mimeType = '';
    for (const m of ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) { mimeType = m; break; }
    }
    try {
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    } catch (e) {
      notice('MediaRecorder unavailable in this browser: ' + e.message);
      stop();
      return;
    }
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = () => send(recorder.mimeType || 'audio/webm');
    recorder.start(200);
  }

  function tick() {
    if (!analyser) return;
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const level = Math.min(1, Math.sqrt(sum / buf.length) * 5);

    // Deaf while speaking, or it transcribes its own voice through the
    // speakers and talks to itself forever.
    const deaf = state.speaking;
    meters.set(deaf ? 0 : level);
    reactor.setLevel(deaf ? 0 : level);
    if (deaf) { quietFor = 0; return; }

    turnMs += LEVEL_TICK_MS;
    if (level > SILENCE_LEVEL) { sawSpeech = true; quietFor = 0; }
    else if (sawSpeech) quietFor += LEVEL_TICK_MS;

    if ((sawSpeech && quietFor >= SILENCE_MS && turnMs >= MIN_TURN_MS) || turnMs >= MAX_TURN_MS) {
      if (recorder && recorder.state === 'recording') recorder.stop();
    }
  }

  async function send(mimeType) {
    const blob = new Blob(chunks, { type: mimeType });
    const wasListening = state.listening;
    if (!sawSpeech || blob.size < 1200) {
      if (wasListening) beginTurn();
      return;
    }
    $('#caption').textContent = 'Transcribing…';
    let text = '';
    try {
      const res = await fetch('/api/listen', {
        method: 'POST',
        headers: { 'Content-Type': mimeType },
        body: blob,
      });
      const data = await res.json();
      if (!res.ok) {
        notice('Transcription failed: ' + (data.error || res.status));
        if (wasListening) beginTurn();
        return;
      }
      text = (data.text || '').trim();
    } catch (e) {
      notice('Transcription failed: ' + e.message);
      if (wasListening) beginTurn();
      return;
    }
    $('#caption').textContent = text || '(nothing heard)';
    if (text) await ask(text);
    // Press once, then just talk — no wake word between turns.
    if (state.listening) { beginTurn(); $('#caption').textContent = 'Listening…'; }
  }

  function stop() {
    state.listening = false;
    $('#mic').classList.remove('on');
    $('#caption').textContent = '';
    $('#caption').className = '';
    clearInterval(timer); timer = null;
    if (recorder && recorder.state === 'recording') recorder.stop();
    recorder = null;
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null;
    if (ctx) ctx.close();
    ctx = null; analyser = null;
    meters.set(0); reactor.setLevel(0);
    if (!state.speaking) setMode('idle');
  }

  return { start, stop, toggle: () => (state.listening ? stop() : start()) };
})();

// ---------------------------------------------------------------- panels

function renderFilters(byType) {
  const wrap = $('#filters');
  wrap.innerHTML = '';
  const colors = { project: '#4fd1e0', client: '#7ee0a2', prospect: '#e0c24f', note: '#8fa3bd', tool: '#a98fe0', meeting: '#e08f9f', invoice: '#e0a24f' };
  Object.entries(byType).sort((a, b) => b[1] - a[1]).forEach(([type, count]) => {
    const row = el('div', 'filter');
    const left = el('div');
    const dot = el('span', 'dot');
    dot.style.background = colors[type] || '#8fa3bd';
    left.appendChild(dot);
    left.appendChild(document.createTextNode(type));
    row.appendChild(left);
    row.appendChild(el('b', null, String(count)));
    row.onclick = () => {
      if (state.hiddenTypes.has(type)) state.hiddenTypes.delete(type);
      else state.hiddenTypes.add(type);
      row.classList.toggle('off', state.hiddenTypes.has(type));
      graph.setHidden(state.hiddenTypes);
    };
    wrap.appendChild(row);
  });
}

function renderHubs(hubs) {
  const wrap = $('#hubs');
  wrap.innerHTML = '';
  hubs.forEach(h => {
    const row = el('div', 'hub');
    row.appendChild(el('span', null, h.title));
    row.appendChild(el('b', null, String(h.degree)));
    row.onclick = () => { graph.focusOn(h.id); openNote(h.id); };
    wrap.appendChild(row);
  });
}

async function openNote(id) {
  const box = $('#inspector');
  if (!id) { box.innerHTML = '<div class="empty">Click a node to open it. Shift-click a second to trace the path between them.</div>'; return; }
  let n;
  try { n = await (await fetch('/api/note?id=' + encodeURIComponent(id))).json(); }
  catch { return; }
  box.innerHTML = '';
  box.appendChild(el('h3', null, n.title));
  box.appendChild(el('div', 'meta', `${n.type} · ${n.degree} links · ${n.rel}`));
  const links = [...new Set([...(n.links || []), ...(n.backlinks || [])])];
  if (links.length) {
    const row = el('div', 'linkrow');
    links.forEach(l => {
      const b = el('button', 'chip', l.replace(/\.md$/, '').split('/').pop());
      b.onclick = () => { graph.focusOn(l); openNote(l); };
      row.appendChild(b);
    });
    box.appendChild(row);
  }
  box.appendChild(el('div', 'body', (n.text || '').slice(0, 4000)));
}

function renderBadges(s) {
  const wrap = $('#badges');
  wrap.innerHTML = '';
  const add = (text, warn) => {
    const b = el('div', 'badge' + (warn ? ' warn' : ''), text);
    wrap.appendChild(b);
  };
  add(s.demo ? 'demo data' : 'live data', !s.demo);
  if (!s.model.available) add('model missing', true);
  if (!s.voice.available) add('voice off', true);
  add(`${s.count} notes`);
  add(`${s.memory_count} memories`);
}

async function refreshStatus() {
  let s;
  try { s = await (await fetch('/api/status')).json(); }
  catch (e) { notice('Cannot reach the server: ' + e.message); return; }
  state.status = s;
  $('#mode').textContent = s.demo ? 'demo' : 'live';
  renderFilters(s.by_type);
  renderHubs(s.top_hubs);
  renderBadges(s);
  if (!s.model.available) notice(s.model.reason);
  if (!s.voice.available) notice(s.voice.reason);
  if (s.errors && s.errors.length) notice('Index problems: ' + s.errors.slice(0, 2).join('; '));
  if (!s.count) notice('Nothing indexed. Check JARVIS_VAULT_PATHS in .env.');
}

// ---------------------------------------------------------------- boot

(async function init() {
  graph = new Graph($('#graph'));
  graph.onFocus = n => openNote(n ? n.id : null);
  graph.onPath = async (a, b) => {
    try {
      const r = await (await fetch(`/api/path?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`)).json();
      if (!r.path.length) { notice('No path between those two.', 'info', 4000); return; }
      graph.setPath(r.path);
      notice(`${r.path.length - 1} hop${r.path.length === 2 ? '' : 's'}: ` +
        r.path.map(id => id.split('/').pop().replace(/\.md$/, '')).join(' → '), 'info', 9000);
    } catch (e) { notice('Path lookup failed: ' + e.message); }
  };

  await refreshStatus();
  try {
    graph.load(await (await fetch('/api/graph')).json());
  } catch (e) {
    notice('Could not load the graph: ' + e.message);
  }

  let ei = 0;
  setInterval(() => {
    if (document.activeElement !== $('#ask') && !$('#ask').value) {
      $('#ask').placeholder = EXAMPLES[ei++ % EXAMPLES.length];
    }
  }, 5000);

  $('#ask').addEventListener('keydown', e => {
    if (e.key === 'Enter') { stopSpeaking(); ask($('#ask').value); }
  });
  $('#mic').onclick = () => { stopSpeaking(); mic.toggle(); };
  $('#mute').onclick = () => {
    state.muted = !state.muted;
    $('#mute').classList.toggle('on', state.muted);
    $('#mute').textContent = state.muted ? 'MUTED' : 'MUTE';
    if (state.muted) stopSpeaking();
  };
  $('#brief').onclick = () => { stopSpeaking(); ask('Brief me.'); };
  $('#plan').onclick = () => { stopSpeaking(); ask('Plan my day.'); };
  $('#mem').onclick = async () => {
    const r = await (await fetch('/api/memory')).json();
    addTurn('jarvis', r.facts.length ? `${r.facts.length} remembered.` : 'Nothing remembered yet.');
    addCard({ kind: 'memory', written: null, all: r.facts });
  };

  // Barge-in is an explicit action: mic button, Space, or Esc.
  addEventListener('keydown', e => {
    if (e.target === $('#ask')) return;
    if (e.code === 'Space') { e.preventDefault(); stopSpeaking(); mic.toggle(); }
    if (e.code === 'Escape') { stopSpeaking(); mic.stop(); }
  });
})();
