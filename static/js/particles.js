(() => {
  'use strict';

  const DEFAULTS = Object.freeze({
    count:560,
    mobileCount:90,
    densityArea:1550,
    colors:['#005bb5', '#0071e3', '#1685ed', '#4a7aa8'],
    darkColors:['#2997ff', '#64d2ff', '#0a84ff', '#78baff'],
    minSize:1.4,
    maxSize:2.7,
    minOpacity:0.72,
    maxOpacity:1,
    influenceRadius:520,
    attraction:0.65,       // Spring acceleration per second squared.
    damping:1.15,          // Velocity decay per second (not per frame).
    maxSpeed:32,           // CSS pixels per second.
    idleSpeed:2.5,
    cursorLag:0.7,         // Seconds for the target to follow the real cursor.
    cursorDamping:0.95,    // Near-critical spring; preserves velocity on reversal.
    turnTime:0.35,
    releaseTime:1.2,
    dispersion:160,
    swirl:0.09,
    minLength:0.5,
    maxLength:3.8,
    maxDpr:1.75,
    maxPixels:4000000,
  });
  const STEP = 1 / 120;
  const TAU = Math.PI * 2;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  class ParticleBackground {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.options = {...DEFAULTS, ...options};
      this.ctx = canvas.getContext('2d');
      this.particles = [];
      this.frameId = null;
      this.lastTime = null;
      this.accumulator = 0;
      this.time = 0;
      this.palette = [];
      this.width = 0;
      this.height = 0;
      this.visible = true;
      this.destroyed = false;
      this.pointer = {x:0, y:0, vx:0, vy:0, targetX:0, targetY:0, active:false, strength:0, initialized:false};
      this.abort = new AbortController();
      this.motion = matchMedia('(prefers-reduced-motion: reduce)');
      this.mobile = matchMedia('(max-width: 700px), (pointer: coarse)');
      if (!this.ctx) return;

      const listen = (target, event, handler) => target.addEventListener(
        event, handler, {passive:true, signal:this.abort.signal}
      );
      listen(window, 'pointermove', event => this.onPointer(event));
      listen(document.documentElement, 'pointerleave', () => this.release());
      listen(window, 'pointercancel', () => this.release());
      listen(window, 'blur', () => this.release());
      listen(window, 'scroll', () => this.release());
      listen(window, 'resize', () => this.resize());
      listen(document, 'visibilitychange', () => {
        if (document.hidden) this.release();
        this.refresh();
      });
      listen(this.motion, 'change', () => {
        this.release();
        this.pointer.strength = 0;
        this.refresh();
      });
      listen(this.mobile, 'change', () => this.resize());

      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(canvas);
      this.themeObserver = new MutationObserver(() => { this.updatePalette(); this.draw(); });
      this.themeObserver.observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
      this.removalObserver = new MutationObserver(() => {
        if (!canvas.isConnected) this.destroy();
      });
      this.removalObserver.observe(document.body, {childList:true, subtree:true});
      this.intersectionObserver = new IntersectionObserver(entries => {
        this.visible = entries[0].isIntersecting;
        if (!this.visible) this.release();
        this.refresh();
      });
      this.intersectionObserver.observe(canvas);
      this.updatePalette();
      this.resize();
    }

    onPointer(event) {
      if (this.motion.matches || event.pointerType === 'touch') return;
      const rect = this.canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
        this.release();
        return;
      }
      const p = this.pointer;
      p.targetX = x;
      p.targetY = y;
      if (!p.initialized) {
        p.x = x;
        p.y = y;
        p.vx = 0;
        p.vy = 0;
        p.initialized = true;
      }
      p.active = true;
    }

    release() { this.pointer.active = false; }

    updatePalette() {
      // A precomputed gradient gives neighboring strokes coherent colors.
      const colors = document.documentElement.dataset.theme === 'dark'
        ? this.options.darkColors : this.options.colors;
      const strip = document.createElement('canvas');
      strip.width = 256; strip.height = 1;
      const ctx = strip.getContext('2d', {willReadFrequently:true});
      const gradient = ctx.createLinearGradient(0, 0, 255, 0);
      colors.forEach((color, i) => gradient.addColorStop(i / Math.max(1, colors.length - 1), color));
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, 256, 1);
      const rgba = ctx.getImageData(0, 0, 256, 1).data;
      this.palette = Array.from({length:256}, (_, i) => `rgb(${rgba[i*4]},${rgba[i*4+1]},${rgba[i*4+2]})`);
    }

    fieldTarget() {
      const p = this.pointer;
      // Keep a slow ambient wave visible before the first pointer movement.
      const x = this.width * (0.48 + Math.sin(this.time * 0.055) * 0.27);
      const y = this.height * (0.5 + Math.cos(this.time * 0.045) * 0.16);
      return {x:x+(p.x-x)*p.strength, y:y+(p.y-y)*p.strength};
    }

    createParticle() {
      const o = this.options;
      const phase = Math.random() * TAU;
      return {
        x:Math.random() * this.width, y:Math.random() * this.height,
        vx:Math.cos(phase) * o.idleSpeed, vy:Math.sin(phase) * o.idleSpeed,
        size:o.minSize + Math.random() * (o.maxSize - o.minSize),
        opacity:o.minOpacity + Math.random() * (o.maxOpacity - o.minOpacity),
        speed:0.65 + Math.random() * 0.7,
        phase, orbit:Math.random() * TAU,
        distance:o.dispersion * (0.35 + 0.65 * Math.sqrt(Math.random())),
        heading:null,
      };
    }

    resize() {
      if (this.destroyed) return;
      const rect = this.canvas.getBoundingClientRect();
      const oldWidth = this.width || rect.width;
      const oldHeight = this.height || rect.height;
      this.width = rect.width;
      this.height = rect.height;
      if (!this.width || !this.height) { this.stop(); return; }
      const o = this.options;
      const ratio = Math.min(window.devicePixelRatio || 1, o.maxDpr,
        Math.sqrt(o.maxPixels / (this.width * this.height)));
      this.canvas.width = Math.max(1, Math.floor(this.width * ratio));
      this.canvas.height = Math.max(1, Math.floor(this.height * ratio));
      this.ctx.setTransform(this.canvas.width / this.width, 0, 0, this.canvas.height / this.height, 0, 0);
      this.particles.forEach(p => {
        p.x *= this.width / oldWidth;
        p.y *= this.height / oldHeight;
      });
      const count = Math.max(0, Math.min(
        this.mobile.matches ? o.mobileCount : o.count,
        Math.ceil(this.width * this.height / o.densityArea)
      ));
      // Re-space the whole field when changing density; truncating a grid
      // would leave only its first rows after switching to mobile.
      if (this.particles.length !== count) this.particles = [];
      const columns = Math.max(1, Math.round(Math.sqrt(count * this.width / this.height)));
      const rows = Math.max(1, Math.ceil(count / columns));
      while (this.particles.length < count) {
        const index = this.particles.length;
        const particle = this.createParticle();
        // Jittered spacing, like the reference's fine field of strokes.
        particle.x = ((index % columns) + 0.25 + Math.random() * 0.5) * this.width / columns;
        particle.y = (Math.floor(index / columns) + 0.25 + Math.random() * 0.5) * this.height / rows;
        this.particles.push(particle);
      }
      this.release();
      this.refresh();
    }

    step(dt) {
      const o = this.options;
      const cursor = this.pointer;
      this.time += dt;
      const frequency = 2 / Math.max(0.1, o.cursorLag);
      const friction = Math.exp(-2 * o.cursorDamping * frequency * dt);
      cursor.vx = ((cursor.vx || 0) + (cursor.targetX - cursor.x) * frequency * frequency * dt) * friction;
      cursor.vy = ((cursor.vy || 0) + (cursor.targetY - cursor.y) * frequency * frequency * dt) * friction;
      cursor.x += cursor.vx * dt;
      cursor.y += cursor.vy * dt;
      cursor.strength += ((cursor.active ? 1 : 0) - cursor.strength) *
        (1 - Math.exp(-dt / Math.max(0.01, o.releaseTime)));
      const decay = Math.exp(-Math.max(0, o.damping) * dt);
      const field = this.fieldTarget();
      for (const p of this.particles) {
        const t = this.time * 0.18 * p.speed;
        let ax = Math.cos(p.phase + t) * o.idleSpeed * o.damping * p.speed;
        let ay = Math.sin(p.phase + t * 0.73) * o.idleSpeed * o.damping * p.speed;
        const dx = cursor.x - p.x;
        const dy = cursor.y - p.y;
        const proximity = clamp(1 - Math.hypot(dx, dy) / Math.max(1, o.influenceRadius), 0, 1);
        // Unique slowly wandering targets keep a loose cloud instead of a single point.
        const angle = p.orbit + this.time * 0.035 * p.speed;
        const force = o.attraction * proximity * proximity * cursor.strength;
        ax += (dx + Math.cos(angle) * p.distance) * force;
        ay += (dy + Math.sin(angle) * p.distance * 0.8) * force;
        const fx = field.x - p.x, fy = field.y - p.y;
        const wave = clamp(1 - Math.hypot(fx, fy) / o.influenceRadius, 0, 1);
        ax += -fy * o.swirl * wave * wave;
        ay += fx * o.swirl * wave * wave;
        p.vx = (p.vx + ax * dt) * decay;
        p.vy = (p.vy + ay * dt) * decay;
        const speed = Math.hypot(p.vx, p.vy);
        const limit = Math.max(0, o.maxSpeed);
        if (speed > limit) { p.vx *= limit / speed; p.vy *= limit / speed; }
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        const targetHeading = Math.atan2(p.y - field.y, p.x - field.x) + 0.85
          + Math.sin(this.time * 0.15 + p.phase) * 0.12;
        if (p.heading === null) p.heading = targetHeading;
        const turn = Math.atan2(Math.sin(targetHeading - p.heading), Math.cos(targetHeading - p.heading));
        p.heading += turn * (1 - Math.exp(-dt / Math.max(0.01, o.turnTime)));
        const pad = 12;
        if (p.x < -pad) p.x = this.width + pad;
        if (p.x > this.width + pad) p.x = -pad;
        if (p.y < -pad) p.y = this.height + pad;
        if (p.y > this.height + pad) p.y = -pad;
      }
    }

    draw() {
      if (this.destroyed || !this.ctx) return;
      const ctx = this.ctx;
      const o = this.options;
      const field = this.fieldTarget();
      ctx.clearRect(0, 0, this.width, this.height);
      ctx.lineCap = 'round';
      for (const p of this.particles) {
        const dx = p.x - field.x, dy = p.y - field.y;
        const distance = Math.hypot(dx, dy);
        const proximity = clamp(1 - distance / o.influenceRadius, 0, 1);
        // A broad band of curved strokes; the quiet field remains as fine dots.
        const envelope = Math.sin(proximity * Math.PI);
        const angle = p.heading ?? Math.atan2(dy, dx) + 0.85;
        const length = o.minLength + (o.maxLength - o.minLength) * envelope;
        const colorPosition = clamp(0.5 + (dy - dx * 0.35) / (o.influenceRadius * 1.35), 0, 1);
        const edge = clamp(Math.min(p.x, p.y, this.width-p.x, this.height-p.y) / 24, 0, 1);
        const fade = edge * edge * (3 - 2 * edge);
        ctx.globalAlpha = p.opacity * (0.28 + envelope * 0.72) * fade;
        ctx.strokeStyle = this.palette[Math.round(colorPosition * 255)];
        ctx.lineWidth = p.size * (0.45 + envelope * 0.65);
        const halfX = Math.cos(angle) * length / 2;
        const halfY = Math.sin(angle) * length / 2;
        ctx.beginPath();
        ctx.moveTo(p.x - halfX, p.y - halfY);
        ctx.lineTo(p.x + halfX, p.y + halfY);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    tick(now) {
      this.frameId = null;
      if (this.destroyed) return;
      if (this.lastTime !== null) {
        this.accumulator += Math.min(0.05, Math.max(0, (now - this.lastTime) / 1000));
        while (this.accumulator >= STEP) {
          this.step(STEP);
          this.accumulator -= STEP;
        }
      }
      this.lastTime = now;
      this.draw();
      this.frameId = requestAnimationFrame(time => this.tick(time));
    }

    stop() {
      if (this.frameId !== null) cancelAnimationFrame(this.frameId);
      this.frameId = null;
      this.lastTime = null;
      this.accumulator = 0;
    }

    refresh() {
      this.stop();
      if (this.destroyed || !this.width || !this.height) return;
      this.draw();
      if (!document.hidden && this.visible && !this.motion.matches) {
        this.frameId = requestAnimationFrame(time => this.tick(time));
      }
    }

    destroy() {
      if (this.destroyed) return;
      this.stop();
      this.destroyed = true;
      this.abort.abort();
      this.resizeObserver?.disconnect();
      this.themeObserver?.disconnect();
      this.removalObserver?.disconnect();
      this.intersectionObserver?.disconnect();
      this.ctx?.clearRect(0, 0, this.width, this.height);
      this.particles = [];
    }
  }

  ParticleBackground.defaults = DEFAULTS;
  window.ParticleBackground = ParticleBackground;
  const mount = () => {
    const canvas = document.querySelector('[data-particle-background]');
    if (canvas && (!window.mesaParticles || window.mesaParticles.destroyed)) {
      window.mesaParticles = new ParticleBackground(canvas, window.MESA_PARTICLES_CONFIG);
    }
  };
  window.addEventListener('pagehide', () => window.mesaParticles?.destroy());
  window.addEventListener('pageshow', mount);
  mount();
})();

// Lightweight table interactions are initialized globally after the particle layer.
document.addEventListener('DOMContentLoaded', () => {
  const path = location.pathname;
  document.querySelectorAll('nav a[href]').forEach(link => { try { if (new URL(link.href).pathname === path) link.setAttribute('aria-current', 'page'); } catch (_) {} });
  document.querySelectorAll('table thead th').forEach((header, index) => {
    header.tabIndex = 0;
    header.addEventListener('click', () => {
      const table = header.closest('table'); const body = table?.tBodies[0];
      if (!body || table.classList.contains('diameter-priority-table')) return;
      const rows = [...body.rows]; const direction = header.dataset.sort === 'asc' ? -1 : 1; header.dataset.sort = direction === 1 ? 'asc' : 'desc';
      rows.sort((a,b) => (a.cells[index]?.textContent || '').localeCompare(b.cells[index]?.textContent || '', 'es', {numeric:true}) * direction).forEach(row => body.appendChild(row));
    });
  });
  if (path.includes('heliang')) document.querySelectorAll('.priority-panel tbody tr.priority-row').forEach(row => { row.draggable = true; row.addEventListener('dragover', e => { e.preventDefault(); const active = document.querySelector('.priority-row.dragging'); if (active && active !== row) row.parentNode.insertBefore(active, row); }); row.addEventListener('dragstart', () => row.classList.add('dragging')); row.addEventListener('dragend', () => row.classList.remove('dragging')); });
});
