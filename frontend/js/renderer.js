/**
 * UAM Corridor Canvas Renderer
 * High-performance HTML5 Canvas rendering with Apple-style aesthetics.
 */
class CorridorRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;

    // View state
    this.viewX = -3000;  // meters (left edge in world coords)
    this.viewWidth = 23000;  // meters visible
    this.viewY = -120;
    this.viewHeight = 240;

    // Interaction
    this.isDragging = false;
    this.dragStartX = 0;
    this.dragStartY = 0;
    this.dragViewX = 0;
    this.dragViewY = 0;

    // State
    this.state = null;
    this.selectedId = null;
    this.hoveredId = null;
    this.showSegments = true;
    this.showDensity = true;
    this.showCongestion = true;
    this.showSpeedLabels = true;
    this.followSelected = false;

    // Theme
    this.isDark = true;

    // Colors
    this.segColors = ['#34c759', '#ffcc00', '#ff9500', '#ff3b30'];
    this.segColorsDark = ['rgba(52,199,89,0.35)', 'rgba(255,204,0,0.35)', 'rgba(255,149,0,0.35)', 'rgba(255,59,48,0.35)'];
    this.segColorsLight = ['rgba(52,199,89,0.25)', 'rgba(255,204,0,0.25)', 'rgba(255,149,0,0.25)', 'rgba(255,59,48,0.25)'];

    this._setupResize();
    this._setupInteraction();
    this.resize();
  }

  _setupResize() {
    const ro = new ResizeObserver(() => this.resize());
    ro.observe(this.canvas.parentElement);
  }

  resize() {
    const parent = this.canvas.parentElement;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    this.canvas.width = w * this.dpr;
    this.canvas.height = h * this.dpr;
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.width = w;
    this.height = h;
    this.render();
  }

  _setupInteraction() {
    this.canvas.addEventListener('mousedown', e => {
      this.isDragging = true;
      this.dragStartX = e.clientX;
      this.dragStartY = e.clientY;
      this.dragViewX = this.viewX;
      this.dragViewY = this.viewY;
      this.canvas.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', e => {
      if (this.isDragging) {
        const dx = e.clientX - this.dragStartX;
        const dy = e.clientY - this.dragStartY;
        const scale = this.viewWidth / this.width;
        const scaleY = this.viewHeight / this.height;
        this.viewX = this.dragViewX - dx * scale;
        this.viewY = this.dragViewY - dy * scaleY;
        this.render();
      } else {
        // Hover detection
        this._detectHover(e);
      }
    });

    window.addEventListener('mouseup', () => {
      this.isDragging = false;
      this.canvas.style.cursor = 'default';
    });

    this.canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      const worldX = this.viewX + (mx / this.width) * this.viewWidth;
      const worldY = this.viewY + (my / this.height) * this.viewHeight;

      const zoomFactor = e.deltaY > 0 ? 1.15 : 1 / 1.15;

      const newWidth = this.viewWidth * zoomFactor;
      const newHeight = this.viewHeight * zoomFactor;

      // Clamp zoom
      if (newWidth < 500 || newWidth > 100000) return;

      const rx = (worldX - this.viewX) / this.viewWidth;
      const ry = (worldY - this.viewY) / this.viewHeight;

      this.viewX = worldX - rx * newWidth;
      this.viewY = worldY - ry * newHeight;
      this.viewWidth = newWidth;
      this.viewHeight = newHeight;

      this.render();
    }, { passive: false });

    this.canvas.addEventListener('click', e => {
      if (Math.abs(e.clientX - this.dragStartX) > 4) return; // was drag
      this._handleClick(e);
    });
  }

  worldToScreen(wx, wy) {
    const sx = ((wx - this.viewX) / this.viewWidth) * this.width;
    const sy = ((wy - this.viewY) / this.viewHeight) * this.height;
    return [sx, sy];
  }

  screenToWorld(sx, sy) {
    const wx = this.viewX + (sx / this.width) * this.viewWidth;
    const wy = this.viewY + (sy / this.height) * this.viewHeight;
    return [wx, wy];
  }

  _detectHover(e) {
    if (!this.state || !this.state.aircraft) return;
    const rect = this.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const [wx, wy] = this.screenToWorld(sx, sy);

    let closest = null;
    let closestDist = Infinity;
    for (const ac of this.state.aircraft) {
      const d = Math.sqrt((ac.x - wx) ** 2 + (ac.y - wy) ** 2);
      if (d < closestDist) {
        closestDist = d;
        closest = ac;
      }
    }

    const pickRadius = this.viewWidth * 0.015;
    const newHovered = (closest && closestDist < pickRadius) ? closest.id : null;
    if (newHovered !== this.hoveredId) {
      this.hoveredId = newHovered;
      this.canvas.style.cursor = newHovered ? 'pointer' : 'default';
      this.render();
    }
  }

  _handleClick(e) {
    if (!this.state) return;
    const rect = this.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const [wx, wy] = this.screenToWorld(sx, sy);

    let closest = null;
    let closestDist = Infinity;
    for (const ac of this.state.aircraft) {
      const d = Math.sqrt((ac.x - wx) ** 2 + (ac.y - wy) ** 2);
      if (d < closestDist) {
        closestDist = d;
        closest = ac;
      }
    }

    const pickRadius = this.viewWidth * 0.015;
    if (closest && closestDist < pickRadius) {
      this.selectedId = closest.id;
    } else {
      this.selectedId = null;
    }

    if (this.onSelect) this.onSelect(this.selectedId);
    this.render();
  }

  setState(state) {
    this.state = state;
    if (this.followSelected && this.selectedId && state.aircraft) {
      const ac = state.aircraft.find(a => a.id === this.selectedId);
      if (ac) {
        this.viewX = ac.x - this.viewWidth / 2;
      }
    }
    this.render();
  }

  render() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;

    if (!w || !h) return;

    // Background
    ctx.fillStyle = this.isDark ? '#0a0a0a' : '#e8e8ed';
    ctx.fillRect(0, 0, w, h);

    if (!this.state) return;

    const params = this.state.params || {};
    const pathLen = params.path_length_m || 20000;
    const laneWidth = params.lane_width_m || 200;

    // Draw corridor background
    this._drawCorridor(ctx, pathLen, laneWidth);

    // Draw segment congestion
    if (this.showSegments && this.state.segments) {
      this._drawSegments(ctx, this.state.segments, laneWidth);
    }

    // Draw heatmaps
    if (this.state.heatmaps) {
      if (this.showDensity && this.state.heatmaps.density) {
        this._drawHeatmap(ctx, this.state.heatmaps, 'density', 'blue');
      }
      if (this.showCongestion && this.state.heatmaps.congestion) {
        this._drawHeatmap(ctx, this.state.heatmaps, 'congestion', 'purple');
      }
    }

    // Draw grid
    this._drawGrid(ctx, pathLen);

    // Draw aircraft
    if (this.state.aircraft) {
      this._labelSlots = new Set();
      this._drawAircraft(ctx, this.state.aircraft);
    }

    // Draw scale indicator
    this._drawScaleBar(ctx);
  }

  _drawCorridor(ctx, pathLen, laneWidth) {
    const halfLane = laneWidth / 2;
    const [x0, y0] = this.worldToScreen(0, -halfLane);
    const [x1, y1] = this.worldToScreen(pathLen, halfLane);

    // Corridor fill
    ctx.fillStyle = this.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)';
    ctx.fillRect(x0, Math.min(y0, y1), x1 - x0, Math.abs(y1 - y0));

    // Corridor borders
    ctx.strokeStyle = this.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
    ctx.lineWidth = 1;
    ctx.setLineDash([8, 4]);
    ctx.beginPath();
    const [, topY] = this.worldToScreen(0, -halfLane);
    const [, botY] = this.worldToScreen(0, halfLane);
    const [startX] = this.worldToScreen(0, 0);
    const [endX] = this.worldToScreen(pathLen, 0);
    ctx.moveTo(startX, topY);
    ctx.lineTo(endX, topY);
    ctx.moveTo(startX, botY);
    ctx.lineTo(endX, botY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Center line
    ctx.strokeStyle = this.isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)';
    ctx.lineWidth = 1;
    const [, centerY] = this.worldToScreen(0, 0);
    ctx.beginPath();
    ctx.moveTo(startX, centerY);
    ctx.lineTo(endX, centerY);
    ctx.stroke();

    // Start / End markers
    ctx.fillStyle = this.isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'center';
    const [sx] = this.worldToScreen(0, 0);
    const [ex] = this.worldToScreen(pathLen, 0);
    ctx.fillText('START', sx, topY - 6);
    ctx.fillText(`END (${pathLen/1000}km)`, ex, topY - 6);
  }

  _drawSegments(ctx, segments, laneWidth) {
    const halfLane = laneWidth / 2;
    const colors = this.isDark ? this.segColorsDark : this.segColorsLight;

    for (const seg of segments) {
      const [x0, y0] = this.worldToScreen(seg.x_start, -halfLane);
      const [x1, y1] = this.worldToScreen(seg.x_end, halfLane);
      const sw = x1 - x0;
      const sh = Math.abs(y1 - y0);

      ctx.fillStyle = colors[seg.level];
      ctx.fillRect(x0, Math.min(y0, y1), sw, sh);

      // Segment border
      ctx.strokeStyle = this.isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(x0, Math.min(y0, y1), sw, sh);

      // Segment info
      if (sw > 60) {
        ctx.fillStyle = this.isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)';
        ctx.font = '9px Inter, sans-serif';
        ctx.textAlign = 'center';
        const cx = (x0 + x1) / 2;
        const cy = Math.min(y0, y1) + 14;
        ctx.fillText(`${seg.count}대 | ${seg.v_mean.toFixed(0)}kt`, cx, cy);
      }
    }
  }

  _drawHeatmap(ctx, heatmaps, key, colorScheme) {
    const data = heatmaps[key];
    if (!data || !data.length) return;
    const xg = heatmaps.xg;
    const yg = heatmaps.yg;
    if (!xg || !yg) return;

    const ny = data.length;
    const nx = data[0].length;

    for (let j = 0; j < ny - 1; j++) {
      for (let i = 0; i < nx - 1; i++) {
        const val = data[j][i];
        if (val < 0.02) continue;

        const [sx0, sy0] = this.worldToScreen(xg[i], yg[j]);
        const [sx1, sy1] = this.worldToScreen(xg[i + 1], yg[j + 1]);

        const cw = Math.max(1, sx1 - sx0);
        const ch = Math.max(1, Math.abs(sy1 - sy0));

        let r, g, b;
        if (colorScheme === 'blue') {
          r = 10; g = 100 + val * 132; b = 255;
        } else {
          r = 120 + val * 135; g = 50; b = 200 + val * 55;
        }
        const alpha = val * (this.isDark ? 0.4 : 0.3);
        ctx.fillStyle = `rgba(${r|0},${g|0},${b|0},${alpha.toFixed(2)})`;
        ctx.fillRect(sx0, Math.min(sy0, sy1), cw, ch);
      }
    }
  }

  _drawGrid(ctx, pathLen) {
    ctx.strokeStyle = this.isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)';
    ctx.fillStyle = this.isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.25)';
    ctx.font = '10px Inter, sans-serif';
    ctx.lineWidth = 0.5;

    // Calculate good grid spacing
    const pixPerKm = this.width / (this.viewWidth / 1000);
    let gridKm = 1;
    if (pixPerKm < 20) gridKm = 10;
    else if (pixPerKm < 50) gridKm = 5;
    else if (pixPerKm < 100) gridKm = 2;

    const startKm = Math.floor(this.viewX / 1000 / gridKm) * gridKm;
    const endKm = Math.ceil((this.viewX + this.viewWidth) / 1000 / gridKm) * gridKm;

    ctx.textAlign = 'center';
    for (let km = startKm; km <= endKm; km += gridKm) {
      const [sx] = this.worldToScreen(km * 1000, 0);
      ctx.beginPath();
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, this.height);
      ctx.stroke();
      ctx.fillText(`${km} km`, sx, this.height - 6);
    }
  }

  _drawAircraft(ctx, aircraft) {
    const acSize = Math.max(4, Math.min(12, 800 / (this.viewWidth / 1000)));

    for (const ac of aircraft) {
      const [sx, sy] = this.worldToScreen(ac.x, ac.y);

      // Skip if off screen
      if (sx < -20 || sx > this.width + 20 || sy < -20 || sy > this.height + 20) continue;

      const isSelected = ac.id === this.selectedId;
      const isHovered = ac.id === this.hoveredId;
      const isDelayed = ac.delayed;

      // Glow for selected/hovered
      if (isSelected || isHovered) {
        ctx.beginPath();
        ctx.arc(sx, sy, acSize + 8, 0, Math.PI * 2);
        ctx.fillStyle = isSelected
          ? (this.isDark ? 'rgba(10,132,255,0.2)' : 'rgba(0,122,255,0.15)')
          : (this.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.05)');
        ctx.fill();

        ctx.beginPath();
        ctx.arc(sx, sy, acSize + 4, 0, Math.PI * 2);
        ctx.strokeStyle = isSelected ? '#0a84ff' : (this.isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.2)');
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Aircraft triangle (pointing right)
      ctx.save();
      ctx.translate(sx, sy);
      ctx.beginPath();
      ctx.moveTo(acSize, 0);
      ctx.lineTo(-acSize * 0.7, -acSize * 0.6);
      ctx.lineTo(-acSize * 0.4, 0);
      ctx.lineTo(-acSize * 0.7, acSize * 0.6);
      ctx.closePath();

      if (isDelayed) {
        ctx.fillStyle = this.isDark ? '#ff453a' : '#ff3b30';
      } else {
        ctx.fillStyle = this.isDark ? '#f5f5f7' : '#1d1d1f';
      }
      ctx.fill();

      // Speed indicator line
      const speedRatio = ac.v_act_knots / (this.state.params.v_free_knots || 100);
      const lineLen = acSize * 2 * speedRatio;
      ctx.strokeStyle = isDelayed
        ? (this.isDark ? 'rgba(255,69,58,0.5)' : 'rgba(255,59,48,0.4)')
        : (this.isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.15)');
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(-acSize, 0);
      ctx.lineTo(-acSize - lineLen, 0);
      ctx.stroke();

      ctx.restore();

      // Speed label (with collision avoidance)
      if (this.showSpeedLabels && acSize > 5) {
        const labelKey = `${Math.round(sx/40)}_${Math.round(sy/20)}`;
        if (!this._labelSlots || !this._labelSlots.has(labelKey)) {
          if (!this._labelSlots) this._labelSlots = new Set();
          this._labelSlots.add(labelKey);
          ctx.fillStyle = this.isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.55)';
          ctx.font = `500 ${Math.max(9, acSize - 1)}px Inter, sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(`${ac.v_act_knots.toFixed(0)}kt`, sx, sy - acSize - 5);
        }
      }

      // ID label for selected/hovered
      if (isSelected || isHovered) {
        ctx.fillStyle = this.isDark ? 'rgba(10,132,255,0.9)' : 'rgba(0,122,255,0.9)';
        ctx.font = 'bold 10px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`#${ac.id}`, sx, sy + acSize + 12);
      }
    }
  }

  _drawScaleBar(ctx) {
    // Scale bar in bottom-left
    const barWorldLen = this._niceScaleLen();
    const [x0] = this.worldToScreen(0, 0);
    const [x1] = this.worldToScreen(barWorldLen, 0);
    const barPx = x1 - x0;

    const margin = 16;
    const y = this.height - 24;

    ctx.strokeStyle = this.isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(margin, y);
    ctx.lineTo(margin + barPx, y);
    ctx.moveTo(margin, y - 3);
    ctx.lineTo(margin, y + 3);
    ctx.moveTo(margin + barPx, y - 3);
    ctx.lineTo(margin + barPx, y + 3);
    ctx.stroke();

    ctx.fillStyle = this.isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'center';
    const label = barWorldLen >= 1000 ? `${barWorldLen / 1000} km` : `${barWorldLen} m`;
    ctx.fillText(label, margin + barPx / 2, y - 6);
  }

  _niceScaleLen() {
    const targetPx = 100;
    const mPerPx = this.viewWidth / this.width;
    const rough = targetPx * mPerPx;
    const niceVals = [100, 200, 500, 1000, 2000, 5000, 10000, 20000];
    for (const v of niceVals) {
      if (v >= rough * 0.5) return v;
    }
    return 20000;
  }

  setTheme(isDark) {
    this.isDark = isDark;
    this.render();
  }
}
