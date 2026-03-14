/**
 * UAM Corridor Simulator — App Controller
 * WebSocket connection, UI binding, state management.
 */
(function () {
  'use strict';

  // ---- State ----
  let ws = null;
  let isRunning = false;
  let selectedId = null;
  let currentState = null;
  let isDark = true;
  let reconnectTimer = null;

  // ---- DOM refs ----
  const $ = id => document.getElementById(id);
  const canvas = $('sim-canvas');
  const renderer = new CorridorRenderer(canvas);

  // Controls
  const btnPlay = $('btn-play');
  const btnReset = $('btn-reset');
  const btnStep = $('btn-step');
  const btnSpawn = $('btn-spawn');
  const btnTheme = $('btn-theme');
  const selSpeed = $('sel-speed');
  const simTime = $('sim-time');

  // Aircraft
  const acList = $('aircraft-list');
  const acCount = $('ac-count');
  const acDetail = $('ac-detail');
  const detailId = $('detail-id');
  const detailVAct = $('detail-v-act');
  const detailDelayRate = $('detail-delay-rate');
  const detailDelayTime = $('detail-delay-time');
  const detailFwd = $('detail-fwd');
  const btnDelete = $('btn-delete');
  const inputSpeed = $('input-speed');
  const sliderSpeed = $('slider-speed');
  const btnSpeedDown = $('btn-speed-down');
  const btnSpeedUp = $('btn-speed-up');

  // Summary
  const sumN = $('sum-n');
  const sumDR = $('sum-dr');
  const sumTD = $('sum-td');

  // Connection
  const connIndicator = $('connection-indicator');

  // Toggles
  const chkSegments = $('chk-segments');
  const chkDensity = $('chk-density');
  const chkCongestion = $('chk-congestion');
  const chkSpeedLabels = $('chk-speed-labels');
  const chkFollow = $('chk-follow');

  // Param inputs map: DOM id → param key
  const paramMap = {
    'p-v-free': { key: 'v_free_knots', type: 'float' },
    'p-sep-min': { key: 'sep_min_m', type: 'float' },
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

  // ---- WebSocket ----
  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Try __PORT_8000__ for deployed mode, fallback to localhost
    let wsUrl;
    const portToken = '__PORT_8000__';
    if (portToken.startsWith('__')) {
      wsUrl = `${protocol}//${location.hostname}:8000/ws`;
    } else {
      wsUrl = `${location.origin}${location.pathname.replace(/\/[^/]*$/, '')}/${portToken}/ws`;
    }

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      connIndicator.classList.add('connected');
      connIndicator.classList.remove('error');
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onclose = () => {
      connIndicator.classList.remove('connected');
      connIndicator.querySelector('.label').textContent = '재연결 중...';
      reconnectTimer = setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      connIndicator.classList.add('error');
      connIndicator.querySelector('.label').textContent = '연결 오류';
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
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
      renderer.setState(msg);
      updateAircraftList(msg.aircraft || []);
      updateSummary(msg.summary || {});
      simTime.textContent = `T = ${msg.t?.toFixed(1) || 0}s`;

      if (selectedId !== null) {
        updateDetail(msg.aircraft?.find(a => a.id === selectedId));
      }
    } else if (msg.type === 'status') {
      isRunning = msg.running;
      updatePlayButton();
    }
  }

  // ---- UI Updates ----
  function updatePlayButton() {
    const iconPlay = $('icon-play');
    const iconPause = $('icon-pause');
    if (isRunning) {
      iconPlay.style.display = 'none';
      iconPause.style.display = '';
    } else {
      iconPlay.style.display = '';
      iconPause.style.display = 'none';
    }
  }

  function updateAircraftList(aircraft) {
    acCount.textContent = aircraft.length;

    if (aircraft.length === 0) {
      acList.innerHTML = `
        <div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
          </svg>
          <p>"기체 추가" 버튼으로<br>기체를 생성하세요</p>
        </div>`;
      return;
    }

    let html = '';
    for (const ac of aircraft) {
      const selClass = ac.id === selectedId ? ' selected' : '';
      const delayClass = ac.delayed ? ' delayed' : '';
      html += `
        <div class="ac-card${selClass}${delayClass}" data-id="${ac.id}">
          <div class="ac-card-icon">${ac.id}</div>
          <div class="ac-card-info">
            <div class="ac-card-name">Aircraft #${ac.id}</div>
            <div class="ac-card-meta">
              <span>l=${(ac.l * 100).toFixed(0)}%</span>
              <span>D=${ac.D.toFixed(1)}s</span>
              ${ac.delayed ? '<span style="color:var(--danger)">지연</span>' : ''}
            </div>
          </div>
          <div class="ac-card-speed">${ac.v_act_knots.toFixed(0)} kt</div>
        </div>`;
    }
    acList.innerHTML = html;

    // Click handlers
    acList.querySelectorAll('.ac-card').forEach(card => {
      card.addEventListener('click', () => {
        const id = parseInt(card.dataset.id);
        selectAircraft(id);
      });
    });
  }

  function selectAircraft(id) {
    selectedId = id;
    renderer.selectedId = id;
    renderer.render();

    if (currentState) {
      const ac = currentState.aircraft?.find(a => a.id === id);
      updateDetail(ac);
    }

    // Update list selection
    acList.querySelectorAll('.ac-card').forEach(card => {
      card.classList.toggle('selected', parseInt(card.dataset.id) === id);
    });
  }

  function updateDetail(ac) {
    if (!ac) {
      acDetail.style.display = 'none';
      selectedId = null;
      renderer.selectedId = null;
      return;
    }

    acDetail.style.display = '';
    detailId.textContent = `AC #${ac.id}`;
    detailVAct.textContent = `${ac.v_act_knots.toFixed(1)} kt`;
    detailDelayRate.textContent = `${(ac.l * 100).toFixed(1)}%`;
    detailDelayTime.textContent = `${ac.D.toFixed(1)} s`;
    detailFwd.textContent = `${(ac.R * 100).toFixed(1)}%`;

    inputSpeed.value = ac.v_cmd_knots.toFixed(0);
    sliderSpeed.value = ac.v_cmd_knots;
  }

  function updateSummary(summary) {
    sumN.textContent = summary.N || 0;
    sumDR.textContent = `${((summary.DR || 0) * 100).toFixed(1)}%`;
    sumTD.textContent = `${(summary.TD_min || 0).toFixed(1)} min`;
  }

  // ---- Event Handlers ----
  btnPlay.addEventListener('click', () => {
    if (isRunning) {
      send({ action: 'pause' });
    } else {
      send({ action: 'start' });
    }
  });

  btnReset.addEventListener('click', () => {
    send({ action: 'reset' });
    selectedId = null;
    renderer.selectedId = null;
    acDetail.style.display = 'none';
  });

  btnStep.addEventListener('click', () => {
    send({ action: 'step' });
  });

  btnSpawn.addEventListener('click', () => {
    send({ action: 'spawn' });
  });

  btnDelete.addEventListener('click', () => {
    if (selectedId !== null) {
      send({ action: 'delete', id: selectedId });
      selectedId = null;
      renderer.selectedId = null;
      acDetail.style.display = 'none';
    }
  });

  // Speed control
  function sendSpeed() {
    if (selectedId === null) return;
    const v = parseFloat(inputSpeed.value);
    if (!isNaN(v)) {
      send({ action: 'set_speed', id: selectedId, speed: v });
      sliderSpeed.value = v;
    }
  }

  inputSpeed.addEventListener('change', sendSpeed);
  sliderSpeed.addEventListener('input', () => {
    inputSpeed.value = sliderSpeed.value;
    sendSpeed();
  });

  btnSpeedDown.addEventListener('click', () => {
    const v = Math.max(0, parseFloat(inputSpeed.value) - 5);
    inputSpeed.value = v;
    sliderSpeed.value = v;
    sendSpeed();
  });

  btnSpeedUp.addEventListener('click', () => {
    const v = Math.min(200, parseFloat(inputSpeed.value) + 5);
    inputSpeed.value = v;
    sliderSpeed.value = v;
    sendSpeed();
  });

  // Playback speed
  selSpeed.addEventListener('change', () => {
    const val = parseFloat(selSpeed.value);
    send({ action: 'update_params', params: { realtime_factor: val } });
  });

  // Visualization toggles
  chkSegments.addEventListener('change', () => { renderer.showSegments = chkSegments.checked; renderer.render(); });
  chkDensity.addEventListener('change', () => { renderer.showDensity = chkDensity.checked; renderer.render(); });
  chkCongestion.addEventListener('change', () => { renderer.showCongestion = chkCongestion.checked; renderer.render(); });
  chkSpeedLabels.addEventListener('change', () => { renderer.showSpeedLabels = chkSpeedLabels.checked; renderer.render(); });
  chkFollow.addEventListener('change', () => { renderer.followSelected = chkFollow.checked; });

  // Parameter inputs
  let paramDebounce = null;
  function sendParams() {
    const params = {};
    for (const [domId, cfg] of Object.entries(paramMap)) {
      const el = $(domId);
      if (!el) continue;
      let val = parseFloat(el.value);
      if (isNaN(val)) continue;
      if (cfg.factor) val *= cfg.factor;
      params[cfg.key] = val;
    }
    send({ action: 'update_params', params });
  }

  for (const domId of Object.keys(paramMap)) {
    const el = $(domId);
    if (!el) continue;
    el.addEventListener('change', () => {
      clearTimeout(paramDebounce);
      paramDebounce = setTimeout(sendParams, 300);
    });
  }

  // Renderer select callback
  renderer.onSelect = (id) => {
    selectedId = id;
    if (id === null) {
      acDetail.style.display = 'none';
      acList.querySelectorAll('.ac-card').forEach(c => c.classList.remove('selected'));
    } else {
      selectAircraft(id);
    }
  };

  // Theme toggle
  function setTheme(dark) {
    isDark = dark;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    renderer.setTheme(dark);

    // Update theme icon
    btnTheme.innerHTML = dark
      ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
      : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  }

  btnTheme.addEventListener('click', () => setTheme(!isDark));

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    switch (e.key) {
      case ' ':
        e.preventDefault();
        btnPlay.click();
        break;
      case 'n':
        btnSpawn.click();
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

  // ---- Init ----
  setTheme(true); // Start dark
  connect();
})();
