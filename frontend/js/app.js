/**
 * UAM Corridor Simulator app controller.
 * Handles WebSocket updates, UI state, route-design interactions, and user actions.
 */
(function () {
  'use strict';

  let ws = null;
  let isRunning = false;
  let selectedId = null;
  let currentState = null;
  let isDark = false;
  let reconnectTimer = null;
  let paramDebounce = null;
  let isRouteDesignMode = false;

  const $ = (id) => document.getElementById(id);
  const canvas = $('sim-canvas');
  const renderer = new CorridorRenderer(canvas);

  const btnPlay = $('btn-play');
  const btnReset = $('btn-reset');
  const btnStep = $('btn-step');
  const btnSpawn = $('btn-spawn');
  const btnTheme = $('btn-theme');
  const btnLogicStudio = $('btn-logic-studio');
  const btnRouteDesign = $('btn-route-design');
  const btnClearRoutes = $('btn-clear-routes');
  const btnResetRoutes = $('btn-reset-routes');
  const selSpeed = $('sel-speed');
  const selMode = $('sel-mode');
  const btnAutoSpawn = $('btn-auto-spawn');
  const inputAutoSpacing = $('input-auto-spacing');
  const simTime = $('sim-time');
  const routeToolbar = $('route-toolbar');
  const routeSpawnLayer = $('route-spawn-layer');
  const vizLegend = $('viz-legend');
  const legendDensity = $('legend-density');
  const legendCongestion = $('legend-congestion');
  const legendSegments = $('legend-segments');
  const legendWind = $('legend-wind');

  const acList = $('aircraft-list');
  const acCount = $('ac-count');
  const emptyAircraftListMarkup = acList.innerHTML;
  const aircraftCards = new Map();

  const commandEmpty = $('command-empty');
  const acDetail = $('ac-detail');
  const detailId = $('detail-id');
  const detailAction = $('detail-action');
  const detailVAct = $('detail-v-act');
  const detailRemaining = $('detail-remaining');
  const detailOrigin = $('detail-origin');
  const detailDestination = $('detail-destination');
  const detailSTA = $('detail-sta');
  const detailETA = $('detail-eta');
  const detailTTI = $('detail-tti');
  const detailDelayTime = $('detail-delay-time');
  const detailBattery = $('detail-battery');
  const detailBatteryRemaining = $('detail-battery-remaining');
  const detailWait = $('detail-wait');
  const detailRoute = $('detail-route');
  const detailRouteProgress = $('detail-route-progress');
  const btnDelete = $('btn-delete');
  const inputSpeed = $('input-speed');
  const sliderSpeed = $('slider-speed');
  const btnSpeedDown = $('btn-speed-down');
  const btnSpeedUp = $('btn-speed-up');
  const inputTurnDiameter = $('input-turn-diameter');
  const btnTurn = $('btn-turn');
  const selectOvertakeTarget = $('select-overtake-target');
  const inputOvertakeOffset = $('input-overtake-offset');
  const inputOvertakeBoost = $('input-overtake-boost');
  const btnOvertake = $('btn-overtake');

  const sumN = $('sum-n');
  const sumDR = $('sum-dr');
  const sumTD = $('sum-td');

  const connIndicator = $('connection-indicator');
  const connLabel = connIndicator.querySelector('.label');

  const chkSegments = $('chk-segments');
  const chkDensity = $('chk-density');
  const chkCongestion = $('chk-congestion');
  const chkFollow = $('chk-follow');
  const chkWindEnabled = $('chk-wind-enabled');
  const chkWindOverlay = $('chk-wind-overlay');
  const selWindLevel = $('sel-wind-level');

  const paramMap = {
    'p-v-free': { key: 'v_free_knots', type: 'float' },
    'p-v-init': { key: 'v_init_knots', type: 'float' },
    'p-v-min': { key: 'v_min_knots', type: 'float' },
    'p-v-max': { key: 'v_max_knots', type: 'float' },
    'p-sep-min': { key: 'sep_min_m', type: 'float' },
    'p-fifo-gap-scale': { key: 'fifo_queue_sep_scale', type: 'float' },
    'p-fifo-node-clear-min': { key: 'fifo_node_clearance_min_m', type: 'float' },
    'p-fifo-node-clear-scale': { key: 'fifo_node_clearance_scale', type: 'float' },
    'p-fifo-hold-min': { key: 'fifo_hold_buffer_min_m', type: 'float' },
    'p-fifo-hold-scale': { key: 'fifo_hold_buffer_scale', type: 'float' },
    'p-fifo-approach-scale': { key: 'fifo_approach_sep_scale', type: 'float' },
    'p-fifo-approach-time': { key: 'fifo_approach_time_s', type: 'float' },
    'p-a-max': { key: 'a_max_mps2', type: 'float' },
    'p-b-max': { key: 'b_max_mps2', type: 'float' },
    'p-lane-width': { key: 'lane_width_m', type: 'float' },
    'p-seg-len': { key: 'segment_length_m', type: 'float', factor: 1000 },
    'p-w-over': { key: 'seg_w_overflow', type: 'float' },
    'p-w-tti': { key: 'seg_w_tti', type: 'float' },
    'p-sig-par': { key: 'sigma_parallel_m', type: 'float' },
    'p-sig-perp': { key: 'sigma_perp_m', type: 'float' },
    'p-l-look': { key: 'lookahead_L_m', type: 'float' },
    'p-delay-t': { key: 'delay_window_T_s', type: 'float' },
    'p-d-thr': { key: 'delayed_thr_s', type: 'float' },
    'p-rho-ref': { key: 'rho_ref', type: 'float' },
    'p-cong-ref': { key: 'cong_ref', type: 'float' },
    'p-dt': { key: 'dt_s', type: 'float' },
  };

  acList.addEventListener('click', (event) => {
    const card = event.target.closest('.ac-card');
    if (!card || !acList.contains(card)) return;
    selectAircraft(parseInt(card.dataset.id, 10));
  });

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      connIndicator.classList.add('connected');
      connIndicator.classList.remove('error');
      connLabel.textContent = '연결됨';
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onclose = () => {
      connIndicator.classList.remove('connected');
      connIndicator.classList.remove('error');
      connLabel.textContent = '재연결 중...';
      reconnectTimer = setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      connIndicator.classList.add('error');
      connLabel.textContent = '연결 오류';
    };

    ws.onmessage = (event) => {
      handleMessage(JSON.parse(event.data));
    };
  }

  function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data));
    }
  }

  function handleMessage(msg) {
    if (msg.type === 'state') {
      currentState = msg;
      syncParamInputs(msg.params || {});
      syncSpeedControls(msg.params || {});
      syncWindControls(msg.params || {}, msg.wind || {});
      syncModeControls(msg);
      syncAutoSpawnControls(msg.params || {});
      updateLegendVisibility(msg);
      renderer.setState(msg);
      updateAircraftList(msg.aircraft || []);
      updateSummary(msg.summary || {});
      simTime.textContent = `T = ${msg.t?.toFixed(1) || 0}s`;

      if (msg.spawned_id) {
        selectAircraft(msg.spawned_id);
      } else if (selectedId !== null) {
        updateDetail(msg.aircraft?.find((ac) => ac.id === selectedId));
      }
      return;
    }

    if (msg.type === 'status') {
      isRunning = !!msg.running;
      updatePlayButton();
    }
  }

  function isRouteMode(state = currentState) {
    return (state?.mode || state?.params?.simulation_mode) === 'route';
  }

  function getNodeMap(state = currentState) {
    return new Map((state?.route_network?.nodes || []).map((node) => [node.id, node]));
  }

  function updatePlayButton() {
    const iconPlay = $('icon-play');
    const iconPause = $('icon-pause');
    iconPlay.style.display = isRunning ? 'none' : '';
    iconPause.style.display = isRunning ? '' : 'none';
  }

  function clampValue(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function formatDuration(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '-';
    if (seconds < 60) return `${seconds.toFixed(1)} s`;
    const total = Math.round(seconds);
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return `${mins}:${String(secs).padStart(2, '0')}`;
  }

  function formatSimTimestamp(seconds) {
    const formatted = formatDuration(seconds);
    return formatted === '-' ? '-' : `T=${formatted}`;
  }

  function formatDistance(meters) {
    if (meters === null || meters === undefined || Number.isNaN(meters)) return '-';
    if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
    return `${meters.toFixed(0)} m`;
  }

  function formatTTI(tti) {
    if (tti === null || tti === undefined || Number.isNaN(tti)) return '-';
    return `${tti.toFixed(2)}x`;
  }

  function formatBatteryPercent(percent) {
    if (percent === null || percent === undefined || Number.isNaN(percent)) return '-';
    return `${Math.max(0, percent).toFixed(0)}%`;
  }

  function getBatteryTone(percent) {
    if (percent === null || percent === undefined || Number.isNaN(percent)) return '';
    if (percent <= 15) return 'critical';
    if (percent <= 30) return 'warning';
    return '';
  }

  function formatNodeLabel(nodeId) {
    if (!nodeId) return '-';
    const node = getNodeMap().get(nodeId);
    if (!node) return nodeId;
    const prefix = node.role === 'start' ? '출발' : node.role === 'end' ? '도착' : '노드';
    return `${prefix} (${node.col * 5}km, R${node.row + 1})`;
  }

  function formatRouteLabel(ac) {
    if (!ac?.route_node_ids?.length) return '-';
    return ac.route_node_ids.join(' → ');
  }

  function formatWaitReason(reason) {
    switch (reason) {
      case 'spacing': return '전방 분리 유지';
      case 'start_hold': return '출발 노드 대기';
      case 'fifo_hold': return '교차 노드 FIFO 대기';
      case 'node_hold': return '교차/합류 노드 대기';
      case 'merge_hold': return '합류 후방 확보 대기';
      case 'route_start': return '출발 준비';
      default: return reason || '-';
    }
  }

  function getActionLabel(ac) {
    if (!ac) return '일반 비행';
    if (ac.action === 'turn') return '우선회 비행 중';
    if (ac.action === 'overtake') return '추월 경로 비행 중';
    if (ac.route_mode) return '사전 항로 추종';
    if (!ac.managed) return '일반 비행';
    return '교통관리 액션 비행 중';
  }

  function getActionTone(ac) {
    if (ac.action === 'turn') return 'turn';
    if (ac.action === 'overtake') return 'overtake';
    if (!ac || ac.route_mode || !ac.managed) return 'idle';
    return 'idle';
  }

  function getCardStatus(ac) {
    if (ac.action === 'turn') return '우선회';
    if (ac.action === 'overtake') return '추월';
    if (ac.route_mode) return '항로';
    if (ac.delayed) return '지연';
    return '';
  }

  function getOvertakeCandidates(acId) {
    const aircraft = currentState?.aircraft || [];
    const selected = aircraft.find((ac) => ac.id === acId);
    if (!selected) return [];

    if (selected.route_mode) {
      const sepMin = Number(currentState?.params?.sep_min_m ?? 200);
      const maxGap = Math.max(sepMin * 8, 2000);
      return aircraft
        .filter((ac) => (
          ac.id !== acId
          && ac.route_mode
          && !ac.action
          && !!selected.active_link_id
          && ac.active_link_id === selected.active_link_id
          && ac.route_progress_m > selected.route_progress_m
          && (ac.route_progress_m - selected.route_progress_m) <= maxGap
        ))
        .sort((a, b) => a.route_progress_m - b.route_progress_m);
    }

    return aircraft
      .filter((ac) => ac.id !== acId && !ac.managed && !ac.route_mode && ac.x > selected.x)
      .sort((a, b) => a.x - b.x);
  }

  function syncOvertakeTargets(ac) {
    if (!selectOvertakeTarget) return;

    const previousValue = parseInt(selectOvertakeTarget.value, 10);
    const candidates = ac ? getOvertakeCandidates(ac.id) : [];
    selectOvertakeTarget.textContent = '';

    if (!candidates.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = '대상 없음';
      selectOvertakeTarget.appendChild(option);
      selectOvertakeTarget.disabled = true;
      return;
    }

    for (const target of candidates) {
      const option = document.createElement('option');
      option.value = String(target.id);
      option.textContent = ac.route_mode
        ? `기체 #${target.id} · ${formatDistance(target.route_progress_m - ac.route_progress_m)} 전방`
        : `기체 #${target.id} · ${formatDistance(target.x - ac.x)} 전방`;
      selectOvertakeTarget.appendChild(option);
    }

    const nextValue = candidates.some((target) => target.id === previousValue)
      ? String(previousValue)
      : String(candidates[0].id);
    selectOvertakeTarget.value = nextValue;
    selectOvertakeTarget.disabled = false;
  }

  function getSpeedBounds(params = currentState?.params || {}) {
    const min = Number(params.v_min_knots ?? 60);
    const max = Number(params.v_max_knots ?? 120);
    return {
      min,
      max: Math.max(min, max),
    };
  }

  function syncSpeedControls(params = currentState?.params || {}) {
    const playback = Number(params.realtime_factor ?? 1);
    if (selSpeed && document.activeElement !== selSpeed) {
      const matched = Array.from(selSpeed.options).some((option) => Number(option.value) === playback);
      selSpeed.value = matched ? String(playback) : '1';
    }

    const bounds = getSpeedBounds(params);
    inputSpeed.min = String(bounds.min);
    inputSpeed.max = String(bounds.max);
    sliderSpeed.min = String(bounds.min);
    sliderSpeed.max = String(bounds.max);

    if (inputSpeed.value !== '') {
      const clamped = clampValue(parseFloat(inputSpeed.value) || bounds.min, bounds.min, bounds.max);
      inputSpeed.value = String(clamped);
      sliderSpeed.value = String(clamped);
    }
  }

  function syncWindControls(params = {}, wind = {}) {
    if (chkWindEnabled && document.activeElement !== chkWindEnabled) {
      chkWindEnabled.checked = !!params.wind_enabled;
    }
    if (selWindLevel && document.activeElement !== selWindLevel && params.wind_level) {
      selWindLevel.value = params.wind_level;
    }
    renderer.showWind = chkWindOverlay ? chkWindOverlay.checked : true;
    if (selWindLevel) {
      selWindLevel.disabled = !(params.wind_enabled ?? wind.enabled ?? false);
    }
  }

  function syncModeControls(state = currentState || {}) {
    const routeMode = isRouteMode(state);
    if (selMode && document.activeElement !== selMode) {
      selMode.value = routeMode ? 'route' : 'corridor';
    }

    renderer.setMode(routeMode ? 'route' : 'corridor');
    routeToolbar?.classList.toggle('is-visible', routeMode);
    btnRouteDesign?.classList.toggle('is-active', routeMode && isRouteDesignMode);

    if (!routeMode && isRouteDesignMode) {
      isRouteDesignMode = false;
      renderer.setDesignMode(false);
    }
  }

  function syncAutoSpawnControls(params = {}) {
    const sepMin = Number(params.sep_min_m ?? 200);
    const spacing = Math.max(sepMin, Number(params.spawn_spacing_m ?? sepMin));

    if (inputAutoSpacing) {
      inputAutoSpacing.min = String(sepMin);
      if (document.activeElement !== inputAutoSpacing) {
        inputAutoSpacing.value = String(spacing);
      }
    }

    if (btnAutoSpawn) {
      const enabled = !!params.auto_spawn_enabled;
      btnAutoSpawn.classList.toggle('is-active', enabled);
      btnAutoSpawn.textContent = enabled ? 'ON' : 'OFF';
      btnAutoSpawn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    }
  }

  function updateCorridorSpawnButton(state = currentState || {}) {
    if (btnSpawn) {
      btnSpawn.style.display = 'none';
    }
    if (!routeSpawnLayer) return;

    if (isRouteMode(state)) {
      const existing = routeSpawnLayer.querySelector('[data-spawn-mode="corridor"]');
      existing?.remove();
      return;
    }

    if (!state?.params) {
      const existing = routeSpawnLayer.querySelector('[data-spawn-mode="corridor"]');
      if (existing) existing.style.visibility = 'hidden';
      return;
    }

    const anchor = renderer.getCorridorSpawnAnchor();
    const clampedX = anchor ? Math.max(anchor.sx, 58) : 58;
    let button = routeSpawnLayer.querySelector('[data-spawn-mode="corridor"]');
    if (!button) {
      button = document.createElement('button');
      button.className = 'route-start-btn corridor-start-btn';
      button.type = 'button';
      button.dataset.spawnMode = 'corridor';
      button.title = '시작점에서 출발';
      button.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
      `;
      button.addEventListener('pointerdown', (event) => {
        event.stopPropagation();
      });
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        send({ action: 'spawn' });
      });
      routeSpawnLayer.appendChild(button);
    }

    button.style.left = `${clampedX}px`;
    button.style.top = `${anchor ? anchor.sy : 0}px`;
    button.style.visibility = anchor?.visible === false ? 'hidden' : 'visible';
  }

  function updateRouteSpawnButtons(state = currentState || {}) {
    if (!routeSpawnLayer) return;
    if (!isRouteMode(state)) {
      routeSpawnLayer.textContent = '';
      return;
    }

    const anchors = renderer.getStartButtonAnchors().filter((item) => item.visible);
    const keepIds = new Set();
    for (const anchor of anchors) {
      keepIds.add(anchor.id);
      let button = routeSpawnLayer.querySelector(`[data-start-node-id="${anchor.id}"]`);
      if (!button) {
        button = document.createElement('button');
        button.className = 'route-start-btn';
        button.type = 'button';
        button.dataset.startNodeId = anchor.id;
        button.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          <span class="route-start-btn-label">R${anchor.row + 1}</span>
        `;
        button.addEventListener('pointerdown', (event) => {
          event.stopPropagation();
        });
        button.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (button.disabled) return;
          send({ action: 'spawn', start_node_id: button.dataset.startNodeId });
        });
        routeSpawnLayer.appendChild(button);
      }
      button.style.left = `${anchor.sx}px`;
      button.style.top = `${anchor.sy}px`;
      button.disabled = !anchor.spawn_enabled;
      if (!anchor.spawn_enabled) button.classList.add('is-disabled');
      else button.classList.remove('is-disabled');
      button.title = anchor.spawn_enabled
        ? (
          isRouteDesignMode
            ? `${formatNodeLabel(anchor.id)}에서 출발 / 설계는 원형 노드 클릭`
            : `${formatNodeLabel(anchor.id)}에서 출발`
        )
        : `${formatNodeLabel(anchor.id)}에서 도달 가능한 도착지가 없습니다`;
    }

    for (const button of Array.from(routeSpawnLayer.querySelectorAll('.route-start-btn'))) {
      if (!keepIds.has(button.dataset.startNodeId || '')) {
        button.remove();
      }
    }
  }

  function updateLegendVisibility(state = currentState || {}) {
    if (!vizLegend) return;
    legendDensity?.classList.toggle('is-hidden', !chkDensity?.checked);
    legendCongestion?.classList.toggle('is-hidden', !chkCongestion?.checked);
    legendSegments?.classList.toggle('is-hidden', !chkSegments?.checked);
    legendWind?.classList.toggle('is-hidden', !(chkWindOverlay?.checked && state.wind?.enabled));
    const rows = [legendDensity, legendCongestion, legendSegments, legendWind].filter(Boolean);
    vizLegend.style.display = rows.some((row) => !row.classList.contains('is-hidden')) ? '' : 'none';
  }

  function syncParamInputs(params = {}) {
    for (const [domId, cfg] of Object.entries(paramMap)) {
      const el = $(domId);
      if (!el || params[cfg.key] === undefined || document.activeElement === el) continue;
      let val = Number(params[cfg.key]);
      if (cfg.factor) val /= cfg.factor;
      el.value = String(val);
    }
  }

  function setSelectedCard(id) {
    for (const [cardId, card] of aircraftCards.entries()) {
      card.classList.toggle('selected', cardId === id);
    }
  }

  function createAircraftCard() {
    const card = document.createElement('div');
    card.className = 'ac-card is-new';

    const icon = document.createElement('div');
    icon.className = 'ac-card-icon';

    const info = document.createElement('div');
    info.className = 'ac-card-info';

    const name = document.createElement('div');
    name.className = 'ac-card-name';

    const meta = document.createElement('div');
    meta.className = 'ac-card-meta';

    const eta = document.createElement('span');
    const tti = document.createElement('span');
    const status = document.createElement('span');
    status.className = 'ac-card-status';

    meta.appendChild(eta);
    meta.appendChild(tti);
    meta.appendChild(status);
    info.appendChild(name);
    info.appendChild(meta);

    const speed = document.createElement('div');
    speed.className = 'ac-card-speed';
    const battery = document.createElement('div');
    battery.className = 'ac-card-battery';
    const side = document.createElement('div');
    side.className = 'ac-card-side';
    side.appendChild(speed);
    side.appendChild(battery);

    card.appendChild(icon);
    card.appendChild(info);
    card.appendChild(side);
    card._refs = { icon, name, eta, tti, status, speed, battery };
    setTimeout(() => card.classList.remove('is-new'), 220);
    return card;
  }

  function syncAircraftCard(card, ac) {
    const refs = card._refs;
    card.dataset.id = String(ac.id);
    card.classList.toggle('selected', ac.id === selectedId);
    card.classList.toggle('delayed', !!ac.delayed);
    card.classList.toggle('managed', !!ac.managed && !ac.route_mode);
    card.dataset.action = ac.action || '';

    refs.icon.textContent = ac.id;
    refs.name.textContent = `기체 #${ac.id}`;
    refs.eta.textContent = `ETA ${formatSimTimestamp(ac.eta_s)}`;
    refs.tti.textContent = `TTI=${formatTTI(ac.tti)}`;
    refs.status.textContent = getCardStatus(ac);
    refs.status.hidden = !refs.status.textContent;
    refs.speed.textContent = `${ac.v_act_knots.toFixed(0)} kt`;
    refs.battery.textContent = formatBatteryPercent(ac.battery_pct);
    refs.battery.classList.toggle('is-warning', getBatteryTone(ac.battery_pct) === 'warning');
    refs.battery.classList.toggle('is-critical', getBatteryTone(ac.battery_pct) === 'critical');
  }

  function updateAircraftList(aircraft) {
    acCount.textContent = aircraft.length;

    if (aircraft.length === 0) {
      aircraftCards.clear();
      acList.innerHTML = emptyAircraftListMarkup;
      return;
    }

    if (acList.querySelector('.empty-state')) {
      acList.textContent = '';
    }

    const nextIds = new Set();
    let previousCard = null;

    for (const ac of aircraft) {
      nextIds.add(ac.id);
      let card = aircraftCards.get(ac.id);
      if (!card) {
        card = createAircraftCard();
        aircraftCards.set(ac.id, card);
      }
      syncAircraftCard(card, ac);

      if (previousCard === null) {
        if (acList.firstElementChild !== card) acList.insertBefore(card, acList.firstElementChild);
      } else if (previousCard.nextElementSibling !== card) {
        acList.insertBefore(card, previousCard.nextElementSibling);
      }

      previousCard = card;
    }

    for (const [id, card] of aircraftCards.entries()) {
      if (!nextIds.has(id)) {
        card.remove();
        aircraftCards.delete(id);
      }
    }
  }

  function clearDetail() {
    selectedId = null;
    renderer.selectedId = null;
    renderer.render();
    setSelectedCard(null);
    acDetail.style.display = 'none';
    commandEmpty.style.display = '';
    syncOvertakeTargets(null);
    btnTurn.disabled = true;
    btnOvertake.disabled = true;
  }

  function selectAircraft(id) {
    selectedId = id;
    renderer.selectedId = id;
    renderer.render();
    setSelectedCard(id);
    if (currentState) {
      updateDetail(currentState.aircraft?.find((ac) => ac.id === id));
    }
  }

  function updateDetail(ac) {
    if (!ac) {
      clearDetail();
      return;
    }

    const routeMode = isRouteMode();
    commandEmpty.style.display = 'none';
    acDetail.style.display = '';

    detailId.textContent = `기체 #${ac.id}`;
    detailAction.textContent = getActionLabel(ac);
    detailAction.dataset.tone = getActionTone(ac);
    detailVAct.textContent = `${ac.v_act_knots.toFixed(1)} kt`;
    detailRemaining.textContent = formatDistance(ac.remaining_m);
    detailOrigin.textContent = formatNodeLabel(ac.origin_node_id);
    detailDestination.textContent = formatNodeLabel(ac.destination_node_id);
    detailSTA.textContent = formatSimTimestamp(ac.sta_s);
    detailETA.textContent = formatSimTimestamp(ac.eta_s);
    detailTTI.textContent = formatTTI(ac.tti);
    detailDelayTime.textContent = `${ac.D.toFixed(1)} s`;
    detailBattery.textContent = formatBatteryPercent(ac.battery_pct);
    detailBatteryRemaining.textContent = formatDuration(ac.battery_remaining_s);
    detailWait.textContent = formatWaitReason(ac.wait_reason);
    detailRoute.textContent = formatRouteLabel(ac);
    detailRouteProgress.textContent = ac.route_total_m
      ? `${formatDistance(ac.route_progress_m)} / ${formatDistance(ac.route_total_m)}`
      : '-';

    const bounds = getSpeedBounds();
    const cmdSpeed = clampValue(ac.v_cmd_knots, bounds.min, bounds.max);
    inputSpeed.value = cmdSpeed.toFixed(0);
    sliderSpeed.value = String(cmdSpeed);

    syncOvertakeTargets(ac);
    btnTurn.disabled = !!ac.managed || !!ac.action;
    btnOvertake.disabled = !!ac.managed || !!ac.action || selectOvertakeTarget.disabled;
  }

  function updateSummary(summary) {
    sumN.textContent = summary.N || 0;
    sumDR.textContent = `${((summary.DR || 0) * 100).toFixed(1)}%`;
    sumTD.textContent = `${(summary.TD_min || 0).toFixed(1)}분`;
  }

  function sendSpeed() {
    if (selectedId === null) return;
    const bounds = getSpeedBounds();
    const v = clampValue(parseFloat(inputSpeed.value), bounds.min, bounds.max);
    if (Number.isNaN(v)) return;
    inputSpeed.value = String(v);
    sliderSpeed.value = String(v);
    send({ action: 'set_speed', id: selectedId, speed: v });
  }

  function sendParams() {
    const params = {};
    for (const [domId, cfg] of Object.entries(paramMap)) {
      const el = $(domId);
      if (!el) continue;
      let val = parseFloat(el.value);
      if (Number.isNaN(val)) continue;
      if (cfg.factor) val *= cfg.factor;
      params[cfg.key] = val;
    }
    send({ action: 'update_params', params });
  }

  btnPlay.addEventListener('click', () => {
    send({ action: isRunning ? 'pause' : 'start' });
  });

  btnReset.addEventListener('click', () => {
    send({ action: 'reset' });
    clearDetail();
  });

  btnStep.addEventListener('click', () => send({ action: 'step' }));
  btnSpawn.addEventListener('click', () => send({ action: 'spawn' }));
  btnLogicStudio?.addEventListener('click', () => {
    window.open('/logic.html', 'uam-logic-studio', 'noopener');
  });

  btnDelete.addEventListener('click', () => {
    if (selectedId === null) return;
    send({ action: 'delete', id: selectedId });
    clearDetail();
  });

  inputSpeed.addEventListener('change', sendSpeed);
  sliderSpeed.addEventListener('input', () => {
    inputSpeed.value = sliderSpeed.value;
    sendSpeed();
  });

  btnSpeedDown.addEventListener('click', () => {
    const bounds = getSpeedBounds();
    const v = Math.max(bounds.min, (parseFloat(inputSpeed.value) || bounds.min) - 5);
    inputSpeed.value = String(v);
    sliderSpeed.value = String(v);
    sendSpeed();
  });

  btnSpeedUp.addEventListener('click', () => {
    const bounds = getSpeedBounds();
    const v = Math.min(bounds.max, (parseFloat(inputSpeed.value) || bounds.min) + 5);
    inputSpeed.value = String(v);
    sliderSpeed.value = String(v);
    sendSpeed();
  });

  btnTurn.addEventListener('click', () => {
    if (selectedId === null) return;
    const diameterM = parseFloat(inputTurnDiameter.value) || 800;
    send({ action: 'turn', id: selectedId, diameter_m: diameterM });
  });

  btnOvertake.addEventListener('click', () => {
    if (selectedId === null) return;
    const targetId = parseInt(selectOvertakeTarget.value, 10);
    if (!Number.isFinite(targetId)) {
      window.alert('추월할 전방 기체를 선택하세요.');
      return;
    }
    const lateralOffsetM = parseFloat(inputOvertakeOffset.value) || 100;
    const speedBoostKnots = parseFloat(inputOvertakeBoost.value) || 20;
    send({
      action: 'overtake',
      id: selectedId,
      target_id: targetId,
      lateral_offset_m: lateralOffsetM,
      speed_boost_knots: speedBoostKnots,
    });
  });

  selSpeed.addEventListener('change', () => {
    const val = parseFloat(selSpeed.value);
    send({ action: 'update_params', params: { realtime_factor: val } });
  });

  selMode.addEventListener('change', () => {
    send({ action: 'set_mode', mode: selMode.value });
    clearDetail();
  });

  btnAutoSpawn?.addEventListener('click', () => {
    const enabled = !(currentState?.params?.auto_spawn_enabled);
    send({ action: 'update_params', params: { auto_spawn_enabled: enabled } });
  });

  inputAutoSpacing?.addEventListener('change', () => {
    const sepMin = Number(currentState?.params?.sep_min_m ?? 200);
    const spacing = Math.max(sepMin, parseFloat(inputAutoSpacing.value) || sepMin);
    inputAutoSpacing.value = String(spacing);
    send({ action: 'update_params', params: { spawn_spacing_m: spacing } });
  });

  btnRouteDesign?.addEventListener('click', () => {
    if (!isRouteMode()) return;
    isRouteDesignMode = !isRouteDesignMode;
    renderer.setDesignMode(isRouteDesignMode);
    syncModeControls(currentState);
  });

  btnClearRoutes?.addEventListener('click', () => {
    send({ action: 'clear_route_links' });
    clearDetail();
  });

  btnResetRoutes?.addEventListener('click', () => {
    send({ action: 'reset_route_links' });
    clearDetail();
  });

  chkSegments.addEventListener('change', () => {
    renderer.showSegments = chkSegments.checked;
    updateLegendVisibility();
    renderer.render();
  });

  chkDensity.addEventListener('change', () => {
    renderer.showDensity = chkDensity.checked;
    updateLegendVisibility();
    renderer.render();
  });

  chkCongestion.addEventListener('change', () => {
    renderer.showCongestion = chkCongestion.checked;
    updateLegendVisibility();
    renderer.render();
  });

  chkFollow.addEventListener('change', () => {
    renderer.followSelected = chkFollow.checked;
  });

  chkWindEnabled?.addEventListener('change', () => {
    send({ action: 'update_params', params: { wind_enabled: chkWindEnabled.checked } });
    syncWindControls({ ...(currentState?.params || {}), wind_enabled: chkWindEnabled.checked }, currentState?.wind || {});
    updateLegendVisibility({ ...(currentState || {}), wind: { ...(currentState?.wind || {}), enabled: chkWindEnabled.checked } });
  });

  chkWindOverlay?.addEventListener('change', () => {
    renderer.showWind = chkWindOverlay.checked;
    updateLegendVisibility();
    renderer.render();
  });

  selWindLevel?.addEventListener('change', () => {
    send({ action: 'update_params', params: { wind_level: selWindLevel.value } });
  });

  for (const domId of Object.keys(paramMap)) {
    const el = $(domId);
    if (!el) continue;
    el.addEventListener('change', () => {
      clearTimeout(paramDebounce);
      paramDebounce = setTimeout(sendParams, 300);
    });
  }

  renderer.onSelect = (id) => {
    if (id === null) {
      clearDetail();
    } else {
      selectAircraft(id);
    }
  };

  renderer.onRouteLinkToggle = (startId, endId) => {
    send({ action: 'toggle_route_link', start_id: startId, end_id: endId });
  };

  renderer.onRender = () => {
    updateRouteSpawnButtons(currentState);
    updateCorridorSpawnButton(currentState);
  };

  function setTheme(dark) {
    isDark = dark;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    renderer.setTheme(dark);
    btnTheme.innerHTML = dark
      ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
      : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  }

  btnTheme.addEventListener('click', () => setTheme(!isDark));

  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    switch (e.key) {
      case ' ':
        e.preventDefault();
        btnPlay.click();
        break;
      case 'n':
        if (isRouteMode()) {
          const firstEnabled = routeSpawnLayer.querySelector('.route-start-btn:not(:disabled)');
          firstEnabled?.click();
        } else {
          btnSpawn.click();
        }
        break;
      case 'r':
        btnReset.click();
        break;
      case '.':
        btnStep.click();
        break;
      case 'Delete':
      case 'Backspace':
        if (selectedId !== null) btnDelete.click();
        break;
    }
  });

  setTheme(false);
  clearDetail();
  renderer.showWind = chkWindOverlay ? chkWindOverlay.checked : true;
  renderer.showSegments = chkSegments.checked;
  renderer.showDensity = chkDensity.checked;
  renderer.showCongestion = chkCongestion.checked;
  renderer.followSelected = chkFollow.checked;
  updateLegendVisibility();
  connect();
})();
