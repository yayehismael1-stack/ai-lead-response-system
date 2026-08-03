/* Force-directed graph on canvas.
   Canvas, not SVG — SVG needs a DOM node per element and stalls past ~1,500
   nodes. Repulsion uses a spatial hash with a distance cutoff so cost stays
   near-linear instead of O(n^2). */

const REPULSION_CUTOFF = 190;   // px; beyond this, nodes ignore each other
const CELL = REPULSION_CUTOFF;  // spatial hash cell size
const REPULSION = 5200;
const SPRING = 0.0085;
const SPRING_LEN = 82;
const CENTER_PULL = 0.0016;
const DAMPING = 0.9;
const BREATH = 0.055;           // never fully freezes — keeps breathing
const PULSE_EVERY_MS = 3400;

const TYPE_COLORS = {
  project: '#4fd1e0',
  client: '#7ee0a2',
  prospect: '#e0c24f',
  note: '#8fa3bd',
  tool: '#a98fe0',
  meeting: '#e08f9f',
  invoice: '#e0a24f',
};
const DEFAULT_COLOR = '#8fa3bd';

class Graph {
  constructor(canvas) {
    this.cv = canvas;
    this.ctx = canvas.getContext('2d');
    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.hidden = new Set();

    this.cam = { x: 0, y: 0, z: 1 };
    this.hover = null;
    this.focus = null;
    this.pathIds = new Set();
    this.pathEdges = new Set();
    this.pulses = [];
    this.alpha = 1;
    this.onFocus = () => {};
    this.onPath = () => {};

    this._resize();
    addEventListener('resize', () => this._resize());
    this._bindPointer();
    setInterval(() => this._spawnPulse(), PULSE_EVERY_MS);
    requestAnimationFrame(() => this._frame());
  }

  _resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    this.cv.width = innerWidth * dpr;
    this.cv.height = innerHeight * dpr;
    this.cv.style.width = innerWidth + 'px';
    this.cv.style.height = innerHeight + 'px';
    this.dpr = dpr;
  }

  load(data) {
    const cx = innerWidth / 2, cy = innerHeight / 2;
    this.nodes = data.nodes.map((n, i) => {
      const a = i * 2.399963; // golden angle — deterministic spread, no RNG
      const r = 26 * Math.sqrt(i + 1);
      return {
        ...n,
        x: cx + Math.cos(a) * r,
        y: cy + Math.sin(a) * r,
        vx: 0, vy: 0,
        r: 3.4 + Math.sqrt(n.degree) * 2.9,
        color: TYPE_COLORS[n.type] || DEFAULT_COLOR,
      };
    });
    this.byId = new Map(this.nodes.map(n => [n.id, n]));
    this.edges = data.edges
      .map(e => ({ s: this.byId.get(e.source), t: this.byId.get(e.target) }))
      .filter(e => e.s && e.t);
    this.nodes.forEach(n => { n.adj = []; });
    this.edges.forEach(e => { e.s.adj.push(e.t); e.t.adj.push(e.s); });
    this.alpha = 1;
  }

  setHidden(types) { this.hidden = new Set(types); }
  visible(n) { return !this.hidden.has(n.type); }

  setPath(ids) {
    this.pathIds = new Set(ids);
    this.pathEdges = new Set();
    for (let i = 0; i + 1 < ids.length; i++) {
      this.pathEdges.add(ids[i] + '|' + ids[i + 1]);
      this.pathEdges.add(ids[i + 1] + '|' + ids[i]);
    }
  }

  focusOn(id) {
    const n = this.byId.get(id);
    if (!n) return;
    this.focus = n;
    this.cam.x = innerWidth / 2 - n.x * this.cam.z;
    this.cam.y = innerHeight / 2 - n.y * this.cam.z;
    this.alpha = Math.max(this.alpha, 0.3);
    this.onFocus(n);
  }

  // ---------- physics ----------

  _step() {
    const grid = new Map();
    for (const n of this.nodes) {
      if (!this.visible(n)) continue;
      const k = ((n.x / CELL) | 0) + ',' + ((n.y / CELL) | 0);
      let cell = grid.get(k);
      if (!cell) grid.set(k, (cell = []));
      cell.push(n);
    }

    for (const n of this.nodes) {
      if (!this.visible(n)) continue;
      const gx = (n.x / CELL) | 0, gy = (n.y / CELL) | 0;
      for (let ix = gx - 1; ix <= gx + 1; ix++) {
        for (let iy = gy - 1; iy <= gy + 1; iy++) {
          const cell = grid.get(ix + ',' + iy);
          if (!cell) continue;
          for (const m of cell) {
            if (m === n) continue;
            let dx = n.x - m.x, dy = n.y - m.y;
            let d2 = dx * dx + dy * dy;
            if (d2 > REPULSION_CUTOFF * REPULSION_CUTOFF) continue;
            if (d2 < 0.01) { dx = (Math.random() - 0.5); dy = (Math.random() - 0.5); d2 = 0.01; }
            const d = Math.sqrt(d2);
            const f = REPULSION / d2;
            n.vx += (dx / d) * f * this.alpha;
            n.vy += (dy / d) * f * this.alpha;
          }
        }
      }
    }

    for (const e of this.edges) {
      if (!this.visible(e.s) || !this.visible(e.t)) continue;
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = (d - SPRING_LEN) * SPRING * this.alpha;
      const ux = dx / d, uy = dy / d;
      e.s.vx += ux * f; e.s.vy += uy * f;
      e.t.vx -= ux * f; e.t.vy -= uy * f;
    }

    const cx = innerWidth / 2, cy = innerHeight / 2;
    for (const n of this.nodes) {
      if (n === this.dragging) continue;
      n.vx += (cx - n.x) * CENTER_PULL;
      n.vy += (cy - n.y) * CENTER_PULL;
      n.vx *= DAMPING; n.vy *= DAMPING;
      n.x += n.vx; n.y += n.vy;
    }

    // Settles, then keeps a faint drift so it never looks frozen.
    this.alpha = Math.max(BREATH, this.alpha * 0.994);
  }

  _spawnPulse() {
    const live = this.edges.filter(e => this.visible(e.s) && this.visible(e.t));
    if (!live.length || this.pulses.length > 3) return;
    const e = live[(Math.random() * live.length) | 0];
    this.pulses.push({ e, t: 0 });
  }

  // ---------- render ----------

  _frame() {
    this._step();
    const c = this.ctx;
    c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    c.clearRect(0, 0, innerWidth, innerHeight);
    c.save();
    c.translate(this.cam.x, this.cam.y);
    c.scale(this.cam.z, this.cam.z);

    const lit = this.hover || this.focus;
    const litSet = lit ? new Set([lit, ...lit.adj]) : null;
    const dim = id => {
      if (this.pathIds.size) return this.pathIds.has(id) ? 1 : 0.1;
      if (!litSet) return 1;
      return litSet.has(this.byId.get(id)) ? 1 : 0.1;
    };

    // edges
    for (const e of this.edges) {
      if (!this.visible(e.s) || !this.visible(e.t)) continue;
      const onPath = this.pathEdges.has(e.s.id + '|' + e.t.id);
      let a;
      if (this.pathIds.size) a = onPath ? 0.85 : 0.04;
      else if (litSet) a = (litSet.has(e.s) && litSet.has(e.t)) ? 0.6 : 0.05;
      else a = 0.14;
      c.strokeStyle = onPath ? 'rgba(79,209,224,' + a + ')' : 'rgba(140,165,190,' + a + ')';
      c.lineWidth = onPath ? 1.8 / this.cam.z : 1 / this.cam.z;
      c.beginPath();
      c.moveTo(e.s.x, e.s.y);
      c.lineTo(e.t.x, e.t.y);
      c.stroke();
    }

    // pulses along links
    for (let i = this.pulses.length - 1; i >= 0; i--) {
      const p = this.pulses[i];
      p.t += 0.014;
      if (p.t >= 1 || !this.visible(p.e.s) || !this.visible(p.e.t)) { this.pulses.splice(i, 1); continue; }
      const x = p.e.s.x + (p.e.t.x - p.e.s.x) * p.t;
      const y = p.e.s.y + (p.e.t.y - p.e.s.y) * p.t;
      const fade = Math.sin(p.t * Math.PI);
      c.fillStyle = 'rgba(79,209,224,' + (0.5 * fade) + ')';
      c.beginPath();
      c.arc(x, y, 1.9 / this.cam.z, 0, 7);
      c.fill();
    }

    // nodes, hubs last so they sit on top
    const drawable = this.nodes.filter(n => this.visible(n)).sort((a, b) => a.degree - b.degree);
    for (const n of drawable) {
      const a = dim(n.id);
      const isLit = n === lit;
      const r = n.r * (isLit ? 1.5 : 1);
      if (isLit || this.pathIds.has(n.id)) {
        c.shadowColor = n.color;
        c.shadowBlur = 16;
      }
      c.globalAlpha = a;
      c.fillStyle = n.color;
      c.beginPath();
      c.arc(n.x, n.y, r, 0, 7);
      c.fill();
      c.shadowBlur = 0;
      if (n === this.focus) {
        c.globalAlpha = 0.8;
        c.strokeStyle = '#4fd1e0';
        c.lineWidth = 1.4 / this.cam.z;
        c.beginPath();
        c.arc(n.x, n.y, r + 5 / this.cam.z, 0, 7);
        c.stroke();
      }
      c.globalAlpha = 1;
    }

    this._labels(drawable, dim);
    c.restore();
    requestAnimationFrame(() => this._frame());
  }

  _labels(drawable, dim) {
    const c = this.ctx;
    const size = 11 / this.cam.z;
    c.font = `${size}px ui-sans-serif, system-ui, sans-serif`;
    c.textBaseline = 'middle';
    const placed = [];
    // Most-connected first; skip any label whose box collides with one already
    // placed, otherwise the hub cluster turns to mush.
    const ordered = [...drawable].sort((a, b) => b.degree - a.degree);
    for (const n of ordered) {
      const a = dim(n.id);
      if (a < 0.5 && n !== this.hover) continue;
      const w = c.measureText(n.title).width;
      const x = n.x + n.r + 5 / this.cam.z;
      const y = n.y;
      const box = { x0: x, y0: y - size * 0.7, x1: x + w, y1: y + size * 0.7 };
      let clash = false;
      for (const p of placed) {
        if (box.x0 < p.x1 && box.x1 > p.x0 && box.y0 < p.y1 && box.y1 > p.y0) { clash = true; break; }
      }
      if (clash) continue;
      placed.push(box);
      c.globalAlpha = a * (n === this.hover || n === this.focus ? 1 : 0.62);
      c.fillStyle = (n === this.hover || n === this.focus) ? '#dde5ee' : '#8b96a5';
      c.fillText(n.title, x, y);
      c.globalAlpha = 1;
    }
  }

  // ---------- interaction ----------

  _toWorld(cx, cy) {
    return { x: (cx - this.cam.x) / this.cam.z, y: (cy - this.cam.y) / this.cam.z };
  }

  _pick(cx, cy) {
    const p = this._toWorld(cx, cy);
    let best = null, bd = Infinity;
    for (const n of this.nodes) {
      if (!this.visible(n)) continue;
      const d = Math.hypot(n.x - p.x, n.y - p.y);
      if (d < n.r + 9 && d < bd) { bd = d; best = n; }
    }
    return best;
  }

  _bindPointer() {
    const cv = this.cv;
    let panning = false, last = null, moved = 0;

    cv.addEventListener('mousedown', e => {
      e.preventDefault();  // shift-click traces a path; it must not select text
      const hit = this._pick(e.clientX, e.clientY);
      moved = 0;
      last = { x: e.clientX, y: e.clientY };
      if (hit) { this.dragging = hit; }
      else { panning = true; cv.classList.add('dragging'); }
    });

    addEventListener('mousemove', e => {
      if (this.dragging) {
        const p = this._toWorld(e.clientX, e.clientY);
        this.dragging.x = p.x; this.dragging.y = p.y;
        this.dragging.vx = this.dragging.vy = 0;
        this.alpha = Math.max(this.alpha, 0.35);
        moved += 1;
        return;
      }
      if (panning && last) {
        this.cam.x += e.clientX - last.x;
        this.cam.y += e.clientY - last.y;
        last = { x: e.clientX, y: e.clientY };
        moved += 1;
        return;
      }
      this.hover = this._pick(e.clientX, e.clientY);
      cv.style.cursor = this.hover ? 'pointer' : 'grab';
    });

    addEventListener('mouseup', e => {
      const wasDrag = moved > 3;
      this.dragging = null;
      panning = false;
      cv.classList.remove('dragging');
      if (wasDrag) return;
      const hit = this._pick(e.clientX, e.clientY);
      if (!hit) { this.focus = null; this.setPath([]); this.onFocus(null); return; }
      if (e.shiftKey && this.focus && this.focus !== hit) {
        this.onPath(this.focus.id, hit.id);
        return;
      }
      this.setPath([]);
      this.focus = hit;
      this.onFocus(hit);
    });

    cv.addEventListener('wheel', e => {
      e.preventDefault();
      const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const z = Math.min(4, Math.max(0.18, this.cam.z * f));
      const k = z / this.cam.z;
      this.cam.x = e.clientX - (e.clientX - this.cam.x) * k;
      this.cam.y = e.clientY - (e.clientY - this.cam.y) * k;
      this.cam.z = z;
    }, { passive: false });
  }
}
