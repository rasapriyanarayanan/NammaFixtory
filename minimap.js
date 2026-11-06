/* NammaFixtory offline map: a dependency-free SVG map used when Leaflet cannot load.
   It draws points, rings and labels from latitude/longitude (no background tiles),
   with wheel/pinch-free zoom buttons, drag to pan, and click popups. */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function el(name, attrs, parent) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  class MiniMap {
    constructor(container) {
      this.box = container;
      this.items = [];
      this.view = null;
      this.box.innerHTML = '';
      this.box.classList.add('minimap');
      this.svg = el('svg', { width: '100%', height: '100%', role: 'img', 'aria-label': 'Map of reported problems (offline view, no street background)' }, this.box);
      this.bg = el('rect', { width: '100%', height: '100%', fill: '#EEF1EC' }, this.svg);
      this.grid = el('g', { stroke: '#D6DCD3', 'stroke-width': 1 }, this.svg);
      this.layer = el('g', {}, this.svg);
      this.pop = document.createElement('div');
      this.pop.className = 'mm-pop';
      this.pop.style.display = 'none';
      this.box.appendChild(this.pop);
      const ctl = document.createElement('div');
      ctl.className = 'mm-ctl';
      ctl.innerHTML = '<button type="button" aria-label="Zoom in">+</button><button type="button" aria-label="Zoom out">&minus;</button><button type="button" aria-label="Fit all">&#9974;</button>';
      this.box.appendChild(ctl);
      const [zi, zo, fit] = ctl.querySelectorAll('button');
      zi.onclick = () => this.zoom(1.5);
      zo.onclick = () => this.zoom(1 / 1.5);
      fit.onclick = () => { this.fit(); this.render(); };
      const note = document.createElement('div');
      note.className = 'mm-note';
      note.textContent = 'Offline view: no street background. Distances are to scale.';
      this.box.appendChild(note);
      this._drag();
      this.svg.addEventListener('click', e => { if (!e.target.closest('[data-mm]')) this.pop.style.display = 'none'; });
      new ResizeObserver(() => this.render()).observe(this.box);
    }

    clear() { this.items = []; this.layer.innerHTML = ''; this.pop.style.display = 'none'; }

    /* kind: 'circle' (radius in metres, min px), 'dot' (px radius), 'pin' (marker + label) */
    add(kind, lat, lon, o) { this.items.push({ kind, lat, lon, o: o || {} }); }

    fit() {
      const pts = this.items.map(i => [i.lat, i.lon]);
      if (!pts.length) pts.push([13.0827, 80.2707]);
      let la0 = Math.min(...pts.map(p => p[0])), la1 = Math.max(...pts.map(p => p[0]));
      let lo0 = Math.min(...pts.map(p => p[1])), lo1 = Math.max(...pts.map(p => p[1]));
      if (la1 - la0 < 0.002) { la0 -= 0.002; la1 += 0.002; }
      if (lo1 - lo0 < 0.002) { lo0 -= 0.002; lo1 += 0.002; }
      this.view = { lat: (la0 + la1) / 2, lon: (lo0 + lo1) / 2, la0, la1, lo0, lo1, k: null };
      this.view.fit = true;
    }

    _size() { const r = this.box.getBoundingClientRect(); return { w: Math.max(200, r.width), h: Math.max(200, r.height) }; }

    _scale() {
      /* pixels per degree of latitude */
      const { w, h } = this._size(), v = this.view;
      if (v.k == null) {
        const cosl = Math.cos(v.lat * Math.PI / 180);
        const kx = (w * 0.84) / ((v.lo1 - v.lo0) * cosl), ky = (h * 0.84) / (v.la1 - v.la0);
        v.k = Math.min(kx, ky);
      }
      return v.k;
    }

    zoom(f) { if (!this.view) return; this._scale(); this.view.k *= f; this.render(); }

    _xy(lat, lon) {
      const { w, h } = this._size(), v = this.view, k = this._scale(), cosl = Math.cos(v.lat * Math.PI / 180);
      return [w / 2 + (lon - v.lon) * cosl * k, h / 2 - (lat - v.lat) * k];
    }

    _drag() {
      let sx, sy, v0, moved = false, down = false;
      this.svg.addEventListener('pointerdown', e => { if (e.target.closest('[data-mm]')) return; down = true; moved = false; sx = e.clientX; sy = e.clientY; v0 = this.view && { lat: this.view.lat, lon: this.view.lon }; this.svg.setPointerCapture(e.pointerId); });
      this.svg.addEventListener('pointermove', e => {
        if (!down || !this.view) return;
        const dx = e.clientX - sx, dy = e.clientY - sy; if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
        const k = this._scale(), cosl = Math.cos(this.view.lat * Math.PI / 180);
        this.view.lon = v0.lon - dx / (k * cosl); this.view.lat = v0.lat + dy / k; this.render();
      });
      const up = () => { down = false; };
      this.svg.addEventListener('pointerup', up); this.svg.addEventListener('pointercancel', up);
      this.svg.addEventListener('wheel', e => { e.preventDefault(); this.zoom(e.deltaY < 0 ? 1.25 : 0.8); }, { passive: false });
    }

    _popup(html, x, y) {
      this.pop.innerHTML = html; this.pop.style.display = 'block';
      const { w, h } = this._size();
      this.pop.style.left = Math.min(Math.max(8, x + 10), w - this.pop.offsetWidth - 8) + 'px';
      this.pop.style.top = Math.min(Math.max(8, y - 8), h - this.pop.offsetHeight - 8) + 'px';
    }

    render() {
      if (!this.view) this.fit();
      const { w, h } = this._size(), k = this._scale(), v = this.view;
      this.layer.innerHTML = ''; this.grid.innerHTML = '';
      /* 1 km grid so people can read scale */
      const mPerDegLat = 111320, kmPx = k / mPerDegLat * 1000;
      if (kmPx > 14) {
        const cosl = Math.cos(v.lat * Math.PI / 180);
        const step = kmPx > 600 ? 0.1 : kmPx > 150 ? 0.5 : 1;
        const stepPx = kmPx * step;
        const [ox, oy] = this._xy(Math.round(v.lat * 100) / 100, Math.round(v.lon * 100) / 100);
        for (let x = ((ox % stepPx) + stepPx) % stepPx; x < w; x += stepPx) el('line', { x1: x, y1: 0, x2: x, y2: h }, this.grid);
        for (let y = ((oy % stepPx) + stepPx) % stepPx; y < h; y += stepPx) el('line', { x1: 0, y1: y, x2: w, y2: y }, this.grid);
        const t = el('text', { x: 10, y: h - 28, fill: '#5C6B73', 'font-size': 11 }, this.layer);
        t.textContent = 'grid: ' + (step === 1 ? '1 km' : step === 0.5 ? '500 m' : '100 m');
        void cosl;
      }
      const order = { circle: 0, dot: 1, pin: 2 };
      this.items.slice().sort((a, b) => order[a.kind] - order[b.kind]).forEach(it => {
        const [x, y] = this._xy(it.lat, it.lon); const o = it.o;
        if (x < -60 || y < -60 || x > w + 60 || y > h + 60) return;
        let node;
        if (it.kind === 'circle') {
          const r = Math.max(o.minPx || 6, (o.radiusM || 20) / mPerDegLat * k);
          node = el('circle', { cx: x, cy: y, r, fill: o.fill || 'none', 'fill-opacity': o.fillOpacity == null ? 0.15 : o.fillOpacity, stroke: o.color || '#333', 'stroke-width': o.weight || 2, 'stroke-dasharray': o.dash || '' }, this.layer);
        } else if (it.kind === 'dot') {
          node = el('circle', { cx: x, cy: y, r: o.r || 6, fill: o.fill || '#555', stroke: '#fff', 'stroke-width': 1.5 }, this.layer);
        } else {
          const g = el('g', {}, this.layer); node = g;
          el('path', { d: `M${x} ${y} l-5 -12 a6 6 0 1 1 10 0 z`, fill: o.fill || '#1B7FA0', stroke: '#fff', 'stroke-width': 1 }, g);
          if (o.label && kmPx > 40) { const t = el('text', { x: x + 9, y: y - 8, 'font-size': 10.5, fill: '#2B3640' }, g); t.textContent = o.label; }
        }
        node.setAttribute('data-mm', '1');
        node.style.cursor = o.html || o.tip ? 'pointer' : 'default';
        if (o.tip) { const t = el('title', {}, node); t.textContent = o.tip; }
        if (o.html) node.addEventListener('click', e => { e.stopPropagation(); this._popup(o.html, x, y); });
      });
    }
  }
  window.MiniMap = MiniMap;
  window.esc_mm = esc;
})();
