/**
 * UAM Corridor Canvas Renderer
 * High-performance HTML5 Canvas rendering with improved contrast in both themes.
 */
class CorridorRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;

    // View state
    this.viewX = 0;
    this.viewWidth = 5000;
    this.viewY = -2500;
    this.viewHeight = 5000;
    this._lastMode = 'corridor';
    this._hasAutoFit = false;

    // Interaction
    this.isDragging = false;
    this.dragStartX = 0;
    this.dragStartY = 0;
    this.dragViewX = 0;
    this.dragViewY = 0;

    // State
    this.state = null;
    this.mode = 'corridor';
    this.designMode = false;
    this.selectedId = null;
    this.hoveredId = null;
    this.selectedRouteNodeId = null;
    this.hoveredRouteNodeId = null;
    this.showSegments = true;
    this.showDensity = true;
    this.showCongestion = true;
    this.showSpeedLabels = true;
    this.showWind = true;
    this.followSelected = false;

    // Theme
    this.isDark = true;

    // Segment colors
    this.segColorsDark = [
      'rgba(52, 199, 89, 0.54)',
      'rgba(255, 204, 0, 0.54)',
      'rgba(255, 149, 0, 0.58)',
      'rgba(255, 59, 48, 0.62)',
    ];
    this.segColorsLight = [
      'rgba(52, 199, 89, 0.46)',
      'rgba(255, 204, 0, 0.48)',
      'rgba(255, 149, 0, 0.52)',
      'rgba(255, 59, 48, 0.56)',
    ];

    this._setupResize();
    this._setupInteraction();
    this.resize();
  }

  _setupResize() {
    const ro = new ResizeObserver(() => this.resize());
    ro.observe(this.canvas.parentElement);
  }

  _metersPerPixel(baseWidth = this.width, baseHeight = this.height) {
    if (!baseWidth || !baseHeight) return 1;
    return Math.max(this.viewWidth / baseWidth, this.viewHeight / baseHeight);
  }

  _setUniformView(centerX, centerY, metersPerPixel) {
    const mpp = Math.max(1e-6, metersPerPixel);
    this.viewWidth = mpp * this.width;
    this.viewHeight = mpp * this.height;
    this.viewX = centerX - this.viewWidth / 2;
    this.viewY = centerY - this.viewHeight / 2;
  }

  _fitToState(state) {
    const params = state?.params || {};
    const pathLen = params.path_length_m || 20000;
    const xMin = -Math.max(1000, Number(params.spawn_margin_m || 0) * 0.25);
    const xMax = pathLen + 1000;

    let yMin = -((params.lane_width_m || 200) * 3);
    let yMax = (params.lane_width_m || 200) * 3;
    if ((state?.mode || params.simulation_mode) === 'route') {
      const nodes = state?.route_network?.nodes || [];
      if (nodes.length) {
        const ys = nodes.map((node) => Number(node.y));
        const pad = Math.max(500, Number(state?.route_network?.row_gap_m || 0) * 0.9);
        yMin = Math.min(...ys) - pad;
        yMax = Math.max(...ys) + pad;
      }
    }

    const boundsWidth = Math.max(1000, xMax - xMin);
    const boundsHeight = Math.max(800, yMax - yMin);
    const centerX = (xMin + xMax) / 2;
    const centerY = (yMin + yMax) / 2;
    const metersPerPixel = Math.max(boundsWidth / Math.max(this.width, 1), boundsHeight / Math.max(this.height, 1));
    this._setUniformView(centerX, centerY, metersPerPixel);
  }

  resize() {
    const parent = this.canvas.parentElement;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    const prevWidth = this.width;
    const prevHeight = this.height;
    const prevCenterX = Number.isFinite(this.viewX) ? this.viewX + this.viewWidth / 2 : 0;
    const prevCenterY = Number.isFinite(this.viewY) ? this.viewY + this.viewHeight / 2 : 0;
    const prevMetersPerPixel = this._metersPerPixel(prevWidth, prevHeight);

    this.canvas.width = w * this.dpr;
    this.canvas.height = h * this.dpr;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    this.width = w;
    this.height = h;
    if (prevWidth && prevHeight && (prevWidth !== w || prevHeight !== h)) {
      this._setUniformView(prevCenterX, prevCenterY, prevMetersPerPixel);
    }
    this.render();
  }

  _setupInteraction() {
    this.canvas.addEventListener('mousedown', (e) => {
      this.isDragging = true;
      this.dragStartX = e.clientX;
      this.dragStartY = e.clientY;
      this.dragViewX = this.viewX;
      this.dragViewY = this.viewY;
      this.canvas.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
      if (this.isDragging) {
        const dx = e.clientX - this.dragStartX;
        const dy = e.clientY - this.dragStartY;
        const scale = this._metersPerPixel();

        this.viewX = this.dragViewX - dx * scale;
        this.viewY = this.dragViewY - dy * scale;
        this.render();
      } else {
        this._detectHover(e);
      }
    });

    window.addEventListener('mouseup', () => {
      this.isDragging = false;
      this.canvas.style.cursor = 'default';
    });

    this.canvas.addEventListener('wheel', (e) => {
      e.preventDefault();

      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      const worldX = this.viewX + (mx / this.width) * this.viewWidth;
      const worldY = this.viewY + (my / this.height) * this.viewHeight;
      const zoomFactor = e.deltaY > 0 ? 1.15 : 1 / 1.15;

      const newWidth = this.viewWidth * zoomFactor;
      const newHeight = this.viewHeight * zoomFactor;

      if (newWidth < 500 || newWidth > 100000) return;

      const rx = (worldX - this.viewX) / this.viewWidth;
      const ry = (worldY - this.viewY) / this.viewHeight;

      this.viewX = worldX - rx * newWidth;
      this.viewY = worldY - ry * newHeight;
      this.viewWidth = newWidth;
      this.viewHeight = newHeight;

      this.render();
    }, { passive: false });

    this.canvas.addEventListener('click', (e) => {
      if (Math.abs(e.clientX - this.dragStartX) > 4) return;
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

  _isRouteMode() {
    return this.mode === 'route';
  }

  _findClosestRouteNode(sx, sy) {
    const nodes = this.state?.route_network?.nodes || [];
    let closest = null;
    let closestDist = Infinity;

    for (const node of nodes) {
      const [nx, ny] = this.worldToScreen(node.x, node.y);
      const dist = Math.hypot(nx - sx, ny - sy);
      if (dist < closestDist) {
        closestDist = dist;
        closest = node;
      }
    }

    return {
      node: closest,
      distance: closestDist,
    };
  }

  getStartButtonAnchors() {
    if (!this._isRouteMode()) return [];
    const starts = this.state?.route_network?.start_nodes || [];
    return starts.map((node) => {
      const [sx, sy] = this.worldToScreen(node.x, node.y);
      return {
        ...node,
        sx,
        sy,
        visible: sx >= -48 && sx <= this.width + 48 && sy >= -48 && sy <= this.height + 48,
      };
    });
  }

  getCorridorSpawnAnchor() {
    if (this._isRouteMode()) return null;
    const [sx, sy] = this.worldToScreen(0, 0);
    return {
      sx,
      sy,
      visible: sx >= -56 && sx <= this.width + 56 && sy >= -56 && sy <= this.height + 56,
    };
  }

  _detectHover(e) {
    if (!this.state) return;

    const rect = this.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (this._isRouteMode() && this.designMode) {
      const hit = this._findClosestRouteNode(sx, sy);
      const pickRadius = 18;
      const newHovered = hit.node && hit.distance <= pickRadius ? hit.node.id : null;
      if (newHovered !== this.hoveredRouteNodeId) {
        this.hoveredRouteNodeId = newHovered;
        this.canvas.style.cursor = newHovered ? 'pointer' : 'default';
        this.render();
      }
      return;
    }

    if (!this.state.aircraft) return;

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

    if (this._isRouteMode() && this.designMode) {
      const hit = this._findClosestRouteNode(sx, sy);
      const pickRadius = 18;
      if (!hit.node || hit.distance > pickRadius) {
        this.selectedRouteNodeId = null;
        this.render();
        return;
      }

      const node = hit.node;
      const selected = this.selectedRouteNodeId
        ? (this.state.route_network?.nodes || []).find((item) => item.id === this.selectedRouteNodeId)
        : null;

      if (selected && selected.id !== node.id && node.col === selected.col + 1) {
        if (this.onRouteLinkToggle) this.onRouteLinkToggle(selected.id, node.id);
        this.selectedRouteNodeId = node.role === 'end' ? null : node.id;
      } else {
        this.selectedRouteNodeId = node.id;
      }

      this.render();
      return;
    }

    if (!this.state.aircraft) return;

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
    this.selectedId = (closest && closestDist < pickRadius) ? closest.id : null;

    if (this.onSelect) this.onSelect(this.selectedId);
    this.render();
  }

  setState(state) {
    const nextMode = state?.mode || state?.params?.simulation_mode || 'corridor';
    const modeChanged = nextMode !== this._lastMode;
    this.state = state;
    this.mode = nextMode;
    if (modeChanged || !this._hasAutoFit) {
      this._fitToState(state);
      this._hasAutoFit = true;
      this._lastMode = nextMode;
    }

    if (this.followSelected && this.selectedId && state.aircraft) {
      const ac = state.aircraft.find((item) => item.id === this.selectedId);
      if (ac) {
        this.viewX = ac.x - this.viewWidth / 2;
      }
    }

    this.render();
  }

  setMode(mode) {
    this.mode = mode;
    if (!this._isRouteMode()) {
      this.designMode = false;
      this.selectedRouteNodeId = null;
      this.hoveredRouteNodeId = null;
    }
    this.render();
  }

  setDesignMode(enabled) {
    this.designMode = !!enabled;
    if (!this.designMode) {
      this.selectedRouteNodeId = null;
      this.hoveredRouteNodeId = null;
    }
    this.render();
  }

  render() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;

    if (!w || !h) return;

    const palette = this._getPalette();
    const bg = ctx.createLinearGradient(0, 0, 0, h);
    bg.addColorStop(0, palette.bgTop);
    bg.addColorStop(1, palette.bgBottom);
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    if (!this.state) return;

    const params = this.state.params || {};
    const pathLen = params.path_length_m || 20000;
    const laneWidth = params.lane_width_m || 200;
    const routeMode = this._isRouteMode();

    if (routeMode) {
      this._drawGrid(ctx, pathLen, palette);
      if (this.state.route_network?.links) {
        this._drawRouteLinks(ctx, this.state.route_network.links, palette);
      }
      if (this.showCongestion && this.state.aircraft?.length) {
        this._drawAircraftCongestion(ctx, this.state.aircraft);
      }
      this._drawRouteNodes(ctx, this.state.route_network?.nodes || [], palette);
    } else {
      this._drawCorridor(ctx, pathLen, laneWidth, palette);

      if (this.state.heatmaps) {
        if (this.showDensity && this.state.heatmaps.density) {
          this._drawHeatmap(ctx, this.state.heatmaps, 'density', 'blue');
        }
      }

      if (this.showSegments && this.state.segments) {
        this._drawSegments(ctx, this.state.segments, laneWidth, palette);
      }
      if (this.showCongestion && this.state.aircraft?.length) {
        this._drawAircraftCongestion(ctx, this.state.aircraft);
      }

      this._drawGrid(ctx, pathLen, palette);
    }

    if (this.showWind && this.state.wind?.enabled) {
      this._drawWindField(ctx, this.state.wind, palette);
    }

    if (this.state.aircraft) {
      if (!routeMode) {
        this._drawManagedActionGuides(ctx, this.state.aircraft, palette);
        this._drawSelectedSpacing(ctx, this.state.aircraft, params, palette);
      }
      this._labelSlots = new Set();
      this._drawAircraft(ctx, this.state.aircraft, palette);
    }

    this._drawScaleBar(ctx, palette);
    this._drawVerticalScaleBar(ctx, palette);
    if (this.onRender) this.onRender();
  }

  _getPalette() {
    if (this.isDark) {
      return {
        bgTop: '#131821',
        bgBottom: '#0a0f16',
        corridorFill: 'rgba(221, 233, 250, 0.045)',
        corridorBorder: 'rgba(255, 255, 255, 0.16)',
        centerLine: 'rgba(168, 194, 255, 0.16)',
        centerLineStrong: 'rgba(220, 232, 255, 0.42)',
        gridMajor: 'rgba(255, 255, 255, 0.075)',
        textMuted: 'rgba(239, 244, 251, 0.68)',
        textStrong: 'rgba(250, 252, 255, 0.88)',
        textHalo: 'rgba(8, 11, 16, 0.95)',
        segmentBorder: 'rgba(255, 255, 255, 0.12)',
        selectionGlow: 'rgba(10, 132, 255, 0.24)',
        hoverGlow: 'rgba(255, 255, 255, 0.09)',
        selectionRing: '#3a9bff',
        hoverRing: 'rgba(255, 255, 255, 0.42)',
        aircraftNormal: '#ffffff',
        aircraftDelayed: '#ff645c',
        aircraftTurn: '#ffb347',
        aircraftOvertake: '#7c9bff',
        speedTrail: 'rgba(255, 255, 255, 0.32)',
        speedTrailDelayed: 'rgba(255, 100, 92, 0.48)',
        speedTrailTurn: 'rgba(255, 179, 71, 0.5)',
        speedTrailOvertake: 'rgba(124, 155, 255, 0.46)',
        speedLabel: 'rgba(255, 255, 255, 0.92)',
        scaleLine: 'rgba(255, 255, 255, 0.65)',
        windArrow: 'rgba(68, 205, 255, 0.82)',
        windArrowStrong: 'rgba(255, 170, 54, 0.92)',
        windChipBg: 'rgba(8, 11, 16, 0.64)',
        sepZoneFill: 'rgba(58, 155, 255, 0.10)',
        sepZoneLine: 'rgba(96, 180, 255, 0.55)',
        sepZoneText: 'rgba(228, 240, 255, 0.92)',
        spacingOk: '#7fd7ff',
        spacingWarn: '#ff7b72',
        routePreview: 'rgba(202, 215, 239, 0.26)',
        routePreviewStrong: 'rgba(220, 232, 255, 0.56)',
        routeLinkBase: 'rgba(88, 214, 141, 0.88)',
        routeNodeFill: '#0c1320',
        routeNodeStroke: 'rgba(255, 255, 255, 0.58)',
        routeNodeStart: '#ffb347',
        routeNodeEnd: '#7fd7ff',
        routeNodeSelected: '#68a8ff',
        routeNodeHover: '#ffffff',
        routeGuide: 'rgba(104, 168, 255, 0.48)',
      };
    }

    return {
      bgTop: '#f8fafc',
      bgBottom: '#edf2f8',
      corridorFill: 'rgba(51, 65, 85, 0.035)',
      corridorBorder: 'rgba(51, 65, 85, 0.16)',
      centerLine: 'rgba(51, 65, 85, 0.12)',
      centerLineStrong: 'rgba(51, 65, 85, 0.34)',
      gridMajor: 'rgba(71, 85, 105, 0.10)',
      textMuted: 'rgba(15, 23, 42, 0.60)',
      textStrong: 'rgba(15, 23, 42, 0.84)',
      textHalo: 'rgba(255, 255, 255, 0.98)',
      segmentBorder: 'rgba(15, 23, 42, 0.12)',
      selectionGlow: 'rgba(0, 122, 255, 0.12)',
      hoverGlow: 'rgba(15, 23, 42, 0.05)',
      selectionRing: '#007aff',
      hoverRing: 'rgba(15, 23, 42, 0.24)',
      aircraftNormal: '#0f172a',
      aircraftDelayed: '#d92d20',
      aircraftTurn: '#b25a00',
      aircraftOvertake: '#0a63ff',
      speedTrail: 'rgba(15, 23, 42, 0.22)',
      speedTrailDelayed: 'rgba(217, 45, 32, 0.38)',
      speedTrailTurn: 'rgba(178, 90, 0, 0.34)',
      speedTrailOvertake: 'rgba(10, 99, 255, 0.34)',
      speedLabel: 'rgba(15, 23, 42, 0.86)',
      scaleLine: 'rgba(15, 23, 42, 0.58)',
      windArrow: 'rgba(0, 122, 255, 0.66)',
      windArrowStrong: 'rgba(191, 95, 0, 0.82)',
      windChipBg: 'rgba(255, 255, 255, 0.82)',
      sepZoneFill: 'rgba(0, 122, 255, 0.08)',
      sepZoneLine: 'rgba(0, 122, 255, 0.40)',
      sepZoneText: 'rgba(15, 23, 42, 0.84)',
      spacingOk: '#0a84ff',
      spacingWarn: '#d92d20',
      routePreview: 'rgba(71, 85, 105, 0.18)',
      routePreviewStrong: 'rgba(71, 85, 105, 0.34)',
      routeLinkBase: 'rgba(34, 197, 94, 0.86)',
      routeNodeFill: '#ffffff',
      routeNodeStroke: 'rgba(15, 23, 42, 0.38)',
      routeNodeStart: '#d97706',
      routeNodeEnd: '#0a84ff',
      routeNodeSelected: '#0a84ff',
      routeNodeHover: '#111827',
      routeGuide: 'rgba(10, 132, 255, 0.36)',
    };
  }

  _drawTextWithHalo(ctx, text, x, y, fillStyle, strokeStyle, lineWidth = 3) {
    ctx.save();
    ctx.lineJoin = 'round';
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = lineWidth;
    ctx.strokeText(text, x, y);
    ctx.fillStyle = fillStyle;
    ctx.fillText(text, x, y);
    ctx.restore();
  }

  _displayHalfLane(laneWidth) {
    return Math.max(80, (laneWidth / 2) * 1.75);
  }

  _drawCorridor(ctx, pathLen, laneWidth, palette) {
    const halfLane = this._displayHalfLane(laneWidth);
    const [x0, y0] = this.worldToScreen(0, -halfLane);
    const [x1, y1] = this.worldToScreen(pathLen, halfLane);

    ctx.fillStyle = palette.corridorFill;
    ctx.fillRect(x0, Math.min(y0, y1), x1 - x0, Math.abs(y1 - y0));

    ctx.strokeStyle = palette.corridorBorder;
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

    ctx.strokeStyle = palette.centerLineStrong;
    ctx.lineWidth = 2.4;
    const [, centerY] = this.worldToScreen(0, 0);
    ctx.beginPath();
    ctx.moveTo(startX, centerY);
    ctx.lineTo(endX, centerY);
    ctx.stroke();

    ctx.font = '600 10px Inter, sans-serif';
    ctx.textAlign = 'center';
    const [sx] = this.worldToScreen(0, 0);
    const [ex] = this.worldToScreen(pathLen, 0);
    this._drawTextWithHalo(ctx, '시작', sx, topY - 6, palette.textMuted, palette.textHalo, 3);
    this._drawTextWithHalo(ctx, `종점 (${pathLen / 1000}km)`, ex, topY - 6, palette.textMuted, palette.textHalo, 3);
  }

  _linkLevelColor(level) {
    switch (level) {
      case 0: return this.isDark ? 'rgba(52, 199, 89, 0.72)' : 'rgba(47, 191, 113, 0.86)';
      case 1: return this.isDark ? 'rgba(255, 204, 0, 0.76)' : 'rgba(212, 169, 0, 0.86)';
      case 2: return this.isDark ? 'rgba(255, 149, 0, 0.78)' : 'rgba(240, 118, 28, 0.88)';
      case 3: return this.isDark ? 'rgba(255, 59, 48, 0.82)' : 'rgba(223, 59, 52, 0.90)';
      default: return this.isDark ? 'rgba(220, 232, 255, 0.48)' : 'rgba(71, 85, 105, 0.42)';
    }
  }

  _drawRoutePathPreviews(ctx, paths, palette) {
    if (!paths.length) return;

    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (const path of paths) {
      if (!path.points || path.points.length < 2) continue;
      ctx.strokeStyle = palette.routePreview;
      ctx.lineWidth = 5;
      ctx.beginPath();
      path.points.forEach((point, index) => {
        const [sx, sy] = this.worldToScreen(point[0], point[1]);
        if (index === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.stroke();
    }

    ctx.restore();
  }

  _drawRouteLinks(ctx, links, palette) {
    const nodes = new Map((this.state?.route_network?.nodes || []).map((node) => [node.id, node]));
    const sepMin = Math.max(Number(this.state?.params?.sep_min_m || 200), 1e-6);
    const maxScore = (1.0 / 0.35) - 1.0;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (const link of links) {
      const start = nodes.get(link.start_id);
      const end = nodes.get(link.end_id);
      if (!start || !end) continue;
      const [sx0, sy0] = this.worldToScreen(start.x, start.y);
      const [sx1, sy1] = this.worldToScreen(end.x, end.y);
      const dx = sx1 - sx0;
      const dy = sy1 - sy0;
      const screenLen = Math.hypot(dx, dy);
      if (screenLen < 1) continue;

      const capacity = Math.max(1.0, Number(link.length_m || 0) / sepMin);
      const densityNorm = Math.max(0, Math.min(1, Number(link.count || 0) / capacity));
      const congestionNorm = Math.max(0, Math.min(1, Number(link.score || 0) / maxScore));
      const angle = Math.atan2(dy, dx);

      if (this.showDensity) {
        ctx.strokeStyle = this.isDark
          ? `rgba(64, 196, 255, ${(0.14 + densityNorm * 0.28).toFixed(3)})`
          : `rgba(10, 132, 255, ${(0.10 + densityNorm * 0.24).toFixed(3)})`;
        ctx.lineWidth = 14 + densityNorm * 28;
        ctx.beginPath();
        ctx.moveTo(sx0, sy0);
        ctx.lineTo(sx1, sy1);
        ctx.stroke();
      }

      ctx.strokeStyle = palette.routeLinkBase;
      ctx.lineWidth = 4.2;
      ctx.beginPath();
      ctx.moveTo(sx0, sy0);
      ctx.lineTo(sx1, sy1);
      ctx.stroke();

      if (this.showSegments) {
        ctx.strokeStyle = this._linkLevelColor(link.level);
        ctx.lineWidth = 3.6 + congestionNorm * 6.6;
        ctx.beginPath();
        ctx.moveTo(sx0, sy0);
        ctx.lineTo(sx1, sy1);
        ctx.stroke();
      }

      if (this.showSegments && screenLen > 72) {
        const mx = (sx0 + sx1) / 2;
        const my = (sy0 + sy1) / 2;
        const readableAngle = angle > Math.PI / 2 || angle < -Math.PI / 2 ? angle + Math.PI : angle;
        ctx.save();
        ctx.translate(mx, my);
        ctx.rotate(readableAngle);
        ctx.font = '600 11px Inter, sans-serif';
        ctx.textAlign = 'center';
        this._drawTextWithHalo(
          ctx,
          `${link.count}대 | ${Number(link.v_mean || 0).toFixed(0)} kt`,
          0,
          -10,
          palette.textStrong,
          palette.textHalo,
          3
        );
        ctx.restore();
      }
    }

    ctx.restore();
  }

  _drawRouteNodes(ctx, nodes, palette) {
    if (!nodes.length) return;

    const selected = this.selectedRouteNodeId;
    const hovered = this.hoveredRouteNodeId;
    ctx.save();

    for (const node of nodes) {
      const [sx, sy] = this.worldToScreen(node.x, node.y);
      if (sx < -30 || sx > this.width + 30 || sy < -30 || sy > this.height + 30) continue;

      let stroke = palette.routeNodeStroke;
      let fill = palette.routeNodeFill;
      if (node.role === 'start') stroke = palette.routeNodeStart;
      if (node.role === 'end') stroke = palette.routeNodeEnd;
      if (node.id === hovered) stroke = palette.routeNodeHover;
      if (node.id === selected) stroke = palette.routeNodeSelected;

      ctx.beginPath();
      ctx.arc(sx, sy, 7.5, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = stroke;
      ctx.lineWidth = node.id === selected ? 3 : 2;
      ctx.stroke();
    }

    if (this.designMode && selected) {
      const base = nodes.find((node) => node.id === selected);
      if (base) {
        const validTargets = nodes.filter((node) => node.col === base.col + 1);
        ctx.strokeStyle = palette.routeGuide;
        ctx.lineWidth = 1.6;
        ctx.setLineDash([7, 5]);
        for (const target of validTargets) {
          const [sx0, sy0] = this.worldToScreen(base.x, base.y);
          const [sx1, sy1] = this.worldToScreen(target.x, target.y);
          ctx.beginPath();
          ctx.moveTo(sx0, sy0);
          ctx.lineTo(sx1, sy1);
          ctx.stroke();
        }
        ctx.setLineDash([]);
      }
    }

    ctx.restore();
  }

  _drawAircraftCongestion(ctx, aircraft) {
    if (!aircraft.length) return;
    const outerRgb = this.isDark ? '174, 91, 255' : '162, 86, 255';
    const innerRgb = this.isDark ? '140, 82, 255' : '126, 58, 242';
    const congRef = Math.max(0.05, Number(this.state?.params?.cong_ref ?? 3));
    const normScale = 2.8 * (3 / congRef);
    ctx.save();
    for (const ac of aircraft) {
      const rawC = Number(ac.c || 0);
      const norm = Math.max(0, Math.min(1, rawC * normScale));
      if (norm < 0.03) continue;

      const [sx, sy] = this.worldToScreen(ac.x, ac.y);
      if (sx < -60 || sx > this.width + 60 || sy < -60 || sy > this.height + 60) continue;

      const heading = this._aircraftDisplayHeading(ac);
      const outerL = 22 + norm * 52;
      const outerW = 12 + norm * 28;
      const innerL = 11 + norm * 26;
      const innerW = 6 + norm * 12;

      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(heading);

      ctx.fillStyle = `rgba(${outerRgb}, ${(0.10 + norm * 0.28).toFixed(3)})`;
      ctx.beginPath();
      ctx.ellipse(0, 0, outerL, outerW, 0, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = `rgba(${innerRgb}, ${(0.12 + norm * 0.34).toFixed(3)})`;
      ctx.beginPath();
      ctx.ellipse(0, 0, innerL, innerW, 0, 0, Math.PI * 2);
      ctx.fill();

      ctx.restore();
    }
    ctx.restore();
  }

  _drawSegments(ctx, segments, laneWidth, palette) {
    const halfLane = this._displayHalfLane(laneWidth);
    const colors = this.isDark ? this.segColorsDark : this.segColorsLight;

    for (const seg of segments) {
      const [x0, y0] = this.worldToScreen(seg.x_start, -halfLane);
      const [x1, y1] = this.worldToScreen(seg.x_end, halfLane);
      const sw = x1 - x0;
      const sh = Math.abs(y1 - y0);

      ctx.fillStyle = colors[seg.level];
      ctx.fillRect(x0, Math.min(y0, y1), sw, sh);

      ctx.strokeStyle = palette.segmentBorder;
      ctx.lineWidth = 0.7;
      ctx.strokeRect(x0, Math.min(y0, y1), sw, sh);

      if (sw > 60) {
        ctx.font = '600 10px Inter, sans-serif';
        ctx.textAlign = 'center';
        const cx = (x0 + x1) / 2;
        const cy = Math.min(y0, y1) + 14;
        this._drawTextWithHalo(ctx, `${seg.count}대 | ${seg.v_mean.toFixed(0)}kt`, cx, cy, palette.textMuted, palette.textHalo, 3);
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
        if (val < 0.01) continue;

        const [sx0, sy0] = this.worldToScreen(xg[i], yg[j]);
        const [sx1, sy1] = this.worldToScreen(xg[i + 1], yg[j + 1]);
        const cw = Math.max(2, sx1 - sx0 + 1);
        const ch = Math.max(2, Math.abs(sy1 - sy0) + 1);

        let r;
        let g;
        let b;

        if (colorScheme === 'blue') {
          r = 18;
          g = 126 + val * 104;
          b = 255;
        } else {
          r = 146 + val * 104;
          g = 54;
          b = 212 + val * 28;
        }

        const alpha = val * (this.isDark ? 0.78 : 0.64);
        ctx.fillStyle = `rgba(${r | 0},${g | 0},${b | 0},${alpha.toFixed(2)})`;
        ctx.fillRect(sx0, Math.min(sy0, sy1), cw, ch);
      }
    }
  }

  _drawGrid(ctx, pathLen, palette) {
    ctx.strokeStyle = palette.gridMajor;
    ctx.font = '600 10px Inter, sans-serif';
    ctx.lineWidth = 1;

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

      if (km >= 0 && km <= Math.ceil(pathLen / 1000)) {
        this._drawTextWithHalo(ctx, `${km} km`, sx, this.height - 8, palette.textStrong, palette.textHalo, 3);
      }
    }
  }

  _drawWindField(ctx, wind, palette) {
    const samples = wind?.samples || [];
    if (!samples.length) return;

    for (const sample of samples) {
      const [sx, sy] = this.worldToScreen(sample.x, sample.y);
      if (sx < -30 || sx > this.width + 30 || sy < -30 || sy > this.height + 30) continue;

      const mag = Number(sample.mag_knots) || 0;
      if (mag < 1) continue;

      const angle = Math.atan2(sample.v_knots || 0, sample.u_knots || 0);
      const len = 10 + Math.min(18, mag * 0.45);
      const color = mag >= 30 ? palette.windArrowStrong : palette.windArrow;

      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(angle);
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = mag >= 30 ? 2 : 1.4;
      ctx.beginPath();
      ctx.moveTo(-len * 0.45, 0);
      ctx.lineTo(len * 0.35, 0);
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(len * 0.35, 0);
      ctx.lineTo(len * 0.12, -4);
      ctx.lineTo(len * 0.12, 4);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    const windLabel = wind.display_label || wind.level || 'wind';
    const magValue = wind.prevailing_mag_knots?.toFixed ? wind.prevailing_mag_knots.toFixed(1) : wind.prevailing_mag_knots;
    const dirValue = Number.isFinite(Number(wind.prevailing_dir_deg)) ? `${Math.round(Number(wind.prevailing_dir_deg))}°` : '-';
    const chipText = `바람 ${windLabel} ${magValue} kt | ${dirValue}`;
    ctx.save();
    ctx.font = '600 11px Inter, sans-serif';
    const chipWidth = Math.max(126, ctx.measureText(chipText).width + 18);
    const chipX = this.width - chipWidth - 16;
    const chipY = 16;
    ctx.fillStyle = palette.windChipBg;
    ctx.strokeStyle = palette.gridMajor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(chipX, chipY, chipWidth, 28, 12);
    ctx.fill();
    ctx.stroke();
    ctx.textAlign = 'left';
    this._drawTextWithHalo(ctx, chipText, chipX + 10, chipY + 18, palette.textStrong, palette.textHalo, 2.5);
    ctx.restore();
  }

  _drawManagedActionGuides(ctx, aircraft, palette) {
    for (const ac of aircraft) {
      if (!ac.managed || !ac.action_meta) continue;

      if (ac.action === 'turn') {
        this._drawTurnGuide(ctx, ac, palette);
      } else if (ac.action === 'overtake') {
        this._drawOvertakeGuide(ctx, ac, palette);
      }
    }
  }

  _drawTurnGuide(ctx, ac, palette) {
    const meta = ac.action_meta || {};
    const cxWorld = Number(meta.center_x_m);
    const cyWorld = Number(meta.center_y_m);
    const radiusWorld = Number(meta.radius_m);
    if (!Number.isFinite(cxWorld) || !Number.isFinite(cyWorld) || !Number.isFinite(radiusWorld)) return;

    const [cx, cy] = this.worldToScreen(cxWorld, cyWorld);
    const [rxEdge] = this.worldToScreen(cxWorld + radiusWorld, cyWorld);
    const [, ryEdge] = this.worldToScreen(cxWorld, cyWorld + radiusWorld);
    const rx = Math.abs(rxEdge - cx);
    const ry = Math.abs(ryEdge - cy);

    ctx.save();
    ctx.strokeStyle = palette.aircraftTurn;
    ctx.lineWidth = 1.6;
    ctx.setLineDash([8, 6]);
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  _drawOvertakeGuide(ctx, ac, palette) {
    const meta = ac.action_meta || {};
    const offset = Number(meta.offset_m);
    const transition = Number(meta.transition_m);
    const startX = Number(meta.start_x_m);
    if (!Number.isFinite(offset) || !Number.isFinite(transition) || !Number.isFinite(startX)) return;

    const mergeStartRaw = meta.merge_start_x_m;
    const mergeStartX = mergeStartRaw === null || mergeStartRaw === undefined ? NaN : Number(mergeStartRaw);
    const cruiseEndX = Number.isFinite(mergeStartX) ? mergeStartX : Math.max(ac.x, startX + transition);
    const guideEndX = cruiseEndX + transition;

    const points = [];
    const sampleCount = 32;

    for (let i = 0; i <= sampleCount; i += 1) {
      const x = startX + (guideEndX - startX) * (i / sampleCount);
      let y = 0;
      if (x <= startX + transition) {
        y = offset * this._smooth01((x - startX) / transition);
      } else if (x < cruiseEndX) {
        y = offset;
      } else {
        y = offset * (1 - this._smooth01((x - cruiseEndX) / transition));
      }
      points.push(this.worldToScreen(x, y));
    }

    ctx.save();
    ctx.strokeStyle = palette.aircraftOvertake;
    ctx.lineWidth = 1.6;
    ctx.setLineDash([7, 5]);
    ctx.beginPath();
    points.forEach(([sx, sy], index) => {
      if (index === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  _smooth01(x) {
    const t = Math.min(1, Math.max(0, x));
    return t * t * (3 - 2 * t);
  }

  _aircraftDisplayHeading(ac) {
    const track = Number(ac?.data?.position?.track_rad);
    if (Number.isFinite(track)) return track;
    const heading = Number(ac?.heading_rad);
    if (Number.isFinite(heading)) return heading;
    return 0;
  }

  _drawSelectedSpacing(ctx, aircraft, params, palette) {
    if (!this.selectedId || !aircraft || aircraft.length === 0) return;

    const spacing = this._getSelectedSpacingContext(aircraft);
    if (!spacing) return;

    const { selected, front, back } = spacing;
    const sepMin = Math.max(0, params.sep_min_m || 0);
    const laneWidth = params.lane_width_m || 200;
    const acSize = Math.max(4, Math.min(12, 800 / (this.viewWidth / 1000)));
    const [selX, selY] = this.worldToScreen(selected.x, selected.y);

    if (sepMin > 0) {
      const [zoneLeft] = this.worldToScreen(selected.x - sepMin, 0);
      const [zoneRight] = this.worldToScreen(selected.x + sepMin, 0);
      const displayHalfLane = this._displayHalfLane(laneWidth);
      const [, zoneTop] = this.worldToScreen(0, -displayHalfLane);
      const [, zoneBottom] = this.worldToScreen(0, displayHalfLane);
      const zoneY = Math.min(zoneTop, zoneBottom);
      const zoneH = Math.abs(zoneBottom - zoneTop);

      ctx.save();
      ctx.fillStyle = palette.sepZoneFill;
      ctx.fillRect(zoneLeft, zoneY, zoneRight - zoneLeft, zoneH);

      ctx.strokeStyle = palette.sepZoneLine;
      ctx.lineWidth = 1.25;
      ctx.setLineDash([7, 5]);
      ctx.beginPath();
      ctx.moveTo(zoneLeft, zoneY);
      ctx.lineTo(zoneLeft, zoneY + zoneH);
      ctx.moveTo(zoneRight, zoneY);
      ctx.lineTo(zoneRight, zoneY + zoneH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();

      const labelY = Math.max(18, zoneY - 8);
      this._drawTextWithHalo(
        ctx,
        `분리 기준 ±${this._formatWorldDistance(sepMin)}`,
        (zoneLeft + zoneRight) / 2,
        labelY,
        palette.sepZoneText,
        palette.textHalo,
        4
      );
    }

    const measureOffset = Math.max(26, acSize * 3);
    if (front) {
      const [frontX] = this.worldToScreen(front.x, front.y);
      const frontGap = front.x - selected.x;
      const frontColor = frontGap < sepMin ? palette.spacingWarn : palette.spacingOk;
      this._drawSpacingMeasure(
        ctx,
        selX,
        frontX,
        selY - measureOffset,
        `전방 ${this._formatWorldDistance(frontGap)}`,
        frontColor,
        palette,
        -8
      );
    }

    if (back) {
      const [backX] = this.worldToScreen(back.x, back.y);
      const backGap = selected.x - back.x;
      const backColor = backGap < sepMin ? palette.spacingWarn : palette.spacingOk;
      this._drawSpacingMeasure(
        ctx,
        backX,
        selX,
        selY + measureOffset,
        `후방 ${this._formatWorldDistance(backGap)}`,
        backColor,
        palette,
        18
      );
    }
  }

  _getSelectedSpacingContext(aircraft) {
    const selected = aircraft.find((ac) => ac.id === this.selectedId);
    if (!selected || selected.managed) return null;

    const ordered = aircraft.filter((ac) => !ac.managed).sort((a, b) => a.x - b.x);
    const index = ordered.findIndex((ac) => ac.id === this.selectedId);
    if (index < 0) return null;

    return {
      selected: ordered[index],
      back: index > 0 ? ordered[index - 1] : null,
      front: index < ordered.length - 1 ? ordered[index + 1] : null,
    };
  }

  _drawSpacingMeasure(ctx, x0, x1, y, label, color, palette, labelOffsetY) {
    const left = Math.min(x0, x1);
    const right = Math.max(x0, x1);
    if (right < -24 || left > this.width + 24) return;

    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.beginPath();
    ctx.moveTo(x0, y - 5);
    ctx.lineTo(x0, y + 5);
    ctx.moveTo(x1, y - 5);
    ctx.lineTo(x1, y + 5);
    ctx.stroke();
    ctx.restore();

    const labelX = Math.max(54, Math.min((x0 + x1) / 2, this.width - 54));
    this._drawTextWithHalo(ctx, label, labelX, y + labelOffsetY, color, palette.textHalo, 4);
  }

  _formatWorldDistance(distanceM) {
    if (distanceM >= 1000) {
      return `${(distanceM / 1000).toFixed(distanceM >= 10000 ? 0 : 1)} km`;
    }
    return `${Math.round(distanceM)} m`;
  }

  _drawAircraft(ctx, aircraft, palette) {
    const freeKnots = this.state?.params?.v_free_knots || 100;
    const acSize = Math.max(4, Math.min(12, 800 / (this.viewWidth / 1000)));

    for (const ac of aircraft) {
      const [sx, sy] = this.worldToScreen(ac.x, ac.y);

      if (sx < -20 || sx > this.width + 20 || sy < -20 || sy > this.height + 20) {
        continue;
      }

      const isSelected = ac.id === this.selectedId;
      const isHovered = ac.id === this.hoveredId;
      const isDelayed = ac.delayed;
      const isTurn = ac.action === 'turn';
      const isOvertake = ac.action === 'overtake';

      if (isSelected || isHovered) {
        ctx.beginPath();
        ctx.arc(sx, sy, acSize + 8, 0, Math.PI * 2);
        ctx.fillStyle = isSelected ? palette.selectionGlow : palette.hoverGlow;
        ctx.fill();

        ctx.beginPath();
        ctx.arc(sx, sy, acSize + 4, 0, Math.PI * 2);
        ctx.strokeStyle = isSelected ? palette.selectionRing : palette.hoverRing;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(this._aircraftDisplayHeading(ac));
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(acSize * 1.18, 0);
      ctx.lineTo(acSize * 0.08, -acSize * 0.26);
      ctx.lineTo(-acSize * 0.12, -acSize * 0.74);
      ctx.lineTo(-acSize * 0.28, -acSize * 0.18);
      ctx.lineTo(-acSize * 0.98, -acSize * 0.12);
      ctx.lineTo(-acSize * 0.82, 0);
      ctx.lineTo(-acSize * 0.98, acSize * 0.12);
      ctx.lineTo(-acSize * 0.28, acSize * 0.18);
      ctx.lineTo(-acSize * 0.12, acSize * 0.74);
      ctx.lineTo(acSize * 0.08, acSize * 0.26);
      ctx.closePath();
      if (isTurn) ctx.fillStyle = palette.aircraftTurn;
      else if (isOvertake) ctx.fillStyle = palette.aircraftOvertake;
      else ctx.fillStyle = isDelayed ? palette.aircraftDelayed : palette.aircraftNormal;
      ctx.fill();
      ctx.strokeStyle = this.isDark ? 'rgba(255, 255, 255, 0.28)' : 'rgba(15, 23, 42, 0.18)';
      ctx.lineWidth = 0.8;
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(-acSize * 0.58, 0);
      ctx.lineTo(acSize * 0.48, 0);
      ctx.strokeStyle = this.isDark ? 'rgba(8, 11, 16, 0.35)' : 'rgba(255, 255, 255, 0.55)';
      ctx.lineWidth = 0.9;
      ctx.stroke();

      const speedRatio = ac.v_act_knots / freeKnots;
      const lineLen = acSize * 2 * speedRatio;
      if (isTurn) ctx.strokeStyle = palette.speedTrailTurn;
      else if (isOvertake) ctx.strokeStyle = palette.speedTrailOvertake;
      else ctx.strokeStyle = isDelayed ? palette.speedTrailDelayed : palette.speedTrail;
      ctx.lineWidth = 1.25;
      ctx.beginPath();
      ctx.moveTo(-acSize, 0);
      ctx.lineTo(-acSize - lineLen, 0);
      ctx.stroke();
      ctx.restore();

      if (this.showSpeedLabels && acSize > 5) {
        const labelKey = `${Math.round(sx / 40)}_${Math.round(sy / 20)}`;
        if (!this._labelSlots.has(labelKey)) {
          this._labelSlots.add(labelKey);
          ctx.font = `600 ${Math.max(9, acSize - 1)}px Inter, sans-serif`;
          ctx.textAlign = 'center';
          this._drawTextWithHalo(
            ctx,
            `${ac.v_act_knots.toFixed(0)} kt`,
            sx,
            sy - acSize - 6,
            palette.speedLabel,
            palette.textHalo,
            3
          );
        }
      }

      if (isSelected || isHovered) {
        ctx.font = '700 10px Inter, sans-serif';
        ctx.textAlign = 'center';
        this._drawTextWithHalo(ctx, `#${ac.id}`, sx, sy + acSize + 13, palette.selectionRing, palette.textHalo, 3);
      }
    }
  }

  _drawScaleBar(ctx, palette) {
    const barWorldLen = this._niceScaleLen();
    const [x0] = this.worldToScreen(0, 0);
    const [x1] = this.worldToScreen(barWorldLen, 0);
    const barPx = x1 - x0;

    const margin = 16;
    const y = this.height - 24;

    ctx.strokeStyle = palette.scaleLine;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(margin, y);
    ctx.lineTo(margin + barPx, y);
    ctx.moveTo(margin, y - 3);
    ctx.lineTo(margin, y + 3);
    ctx.moveTo(margin + barPx, y - 3);
    ctx.lineTo(margin + barPx, y + 3);
    ctx.stroke();

    ctx.font = '600 10px Inter, sans-serif';
    ctx.textAlign = 'center';
    const label = barWorldLen >= 1000 ? `${barWorldLen / 1000} km` : `${barWorldLen} m`;
    this._drawTextWithHalo(ctx, label, margin + barPx / 2, y - 6, palette.textStrong, palette.textHalo, 3);
  }

  _drawVerticalScaleBar(ctx, palette) {
    const barWorldLen = this.viewHeight;
    const x = this.width - 20;
    const yTop = 20;
    const yBottom = this.height - 28;
    const barPx = yBottom - yTop;

    ctx.strokeStyle = palette.scaleLine;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, yBottom);
    ctx.lineTo(x, yTop);
    ctx.moveTo(x - 3, yBottom);
    ctx.lineTo(x + 3, yBottom);
    ctx.moveTo(x - 3, yTop);
    ctx.lineTo(x + 3, yTop);
    ctx.stroke();

    ctx.save();
    ctx.translate(x - 10, yBottom - barPx / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.font = '600 10px Inter, sans-serif';
    ctx.textAlign = 'center';
    const label = barWorldLen >= 1000
      ? `${(barWorldLen / 1000).toFixed(barWorldLen % 1000 === 0 ? 0 : 1)} km`
      : `${Math.round(barWorldLen)} m`;
    this._drawTextWithHalo(ctx, label, 0, 0, palette.textStrong, palette.textHalo, 3);
    ctx.restore();
  }

  _niceScaleLen() {
    const targetPx = 100;
    const mPerPx = this.viewWidth / this.width;
    const rough = targetPx * mPerPx;
    const niceVals = [100, 200, 500, 1000, 2000, 5000, 10000, 20000];

    for (const value of niceVals) {
      if (value >= rough * 0.5) return value;
    }

    return 20000;
  }

  setTheme(isDark) {
    this.isDark = isDark;
    this.render();
  }
}
