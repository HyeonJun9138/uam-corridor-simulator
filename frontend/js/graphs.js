(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const btnBackMain = $('btn-back-main');
  const btnTheme = $('btn-theme');
  const connection = $('graphs-connection');
  const routeSelect = $('graphs-route-select');
  const linkSelect = $('graphs-link-select');
  const paramsJson = $('graphs-params-json');
  const currentZip = $('graphs-current-zip');
  const scenarioList = $('graphs-scenario-list');

  const scenarioIdEl = $('graphs-scenario-id');
  const scenarioCreatedEl = $('graphs-scenario-created');
  const scenarioReasonEl = $('graphs-scenario-reason');
  const sampleCountEl = $('graphs-sample-count');

  const currentValues = {
    n: $('graphs-n-value'),
    dr: $('graphs-dr-value'),
    speed: $('graphs-speed-value'),
    congestion: $('graphs-congestion-value'),
    routeCount: $('graphs-route-count-value'),
    routeCongestion: $('graphs-route-congestion-value'),
    routeSpeed: $('graphs-route-speed-value'),
    routeDelay: $('graphs-route-delay-value'),
    linkCount: $('graphs-link-count-value'),
    linkScore: $('graphs-link-score-value'),
    linkSpeed: $('graphs-link-speed-value'),
    linkLevel: $('graphs-link-level-value'),
  };

  const charts = {
    summaryN: $('chart-summary-n'),
    summaryDR: $('chart-summary-dr'),
    summarySpeed: $('chart-summary-speed'),
    summaryCongestion: $('chart-summary-congestion'),
    routeCount: $('chart-route-count'),
    routeCongestion: $('chart-route-congestion'),
    routeSpeed: $('chart-route-speed'),
    routeDelay: $('chart-route-delay'),
    linkCount: $('chart-link-count'),
    linkScore: $('chart-link-score'),
    linkSpeed: $('chart-link-speed'),
    linkLevel: $('chart-link-level'),
  };

  const ALL_ROUTES_KEY = '__ALL_ROUTES__';
  const ALL_LINKS_KEY = '__ALL_LINKS__';

  let currentPayload = null;
  let pollTimer = null;
  let isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  let selectedRouteKey = ALL_ROUTES_KEY;
  let selectedLinkKey = ALL_LINKS_KEY;

  function formatNumber(value, digits = 1) {
    if (!Number.isFinite(value)) return '-';
    return Number(value).toFixed(digits);
  }

  function formatPercent(value) {
    if (!Number.isFinite(value)) return '-';
    return `${(Number(value) * 100).toFixed(1)}%`;
  }

  function setConnection(text, isOk) {
    connection.textContent = text;
    connection.classList.toggle('is-connected', !!isOk);
  }

  function toggleTheme() {
    isDark = !isDark;
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    if (currentPayload) {
      renderCharts(currentPayload);
    }
  }

  function drawLineChart(canvas, rows, valueKey, options) {
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const pad = { left: 42, right: 16, top: 18, bottom: 30 };
    const innerWidth = width - pad.left - pad.right;
    const innerHeight = height - pad.top - pad.bottom;

    const styles = getComputedStyle(document.documentElement);
    const secondary = styles.getPropertyValue('--text-secondary').trim() || '#6e6e73';
    const border = styles.getPropertyValue('--border').trim() || 'rgba(0,0,0,0.08)';
    const accent = options.color;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = isDark ? '#0d1016' : '#ffffff';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = border;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top);
    ctx.lineTo(pad.left, pad.top + innerHeight);
    ctx.lineTo(pad.left + innerWidth, pad.top + innerHeight);
    ctx.stroke();

    if (!rows || !rows.length) {
      ctx.fillStyle = secondary;
      ctx.font = '12px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No data', width / 2, height / 2);
      return;
    }

    const values = rows
      .map((row) => Number(row[valueKey]))
      .filter((value) => Number.isFinite(value));
    if (!values.length) {
      ctx.fillStyle = secondary;
      ctx.font = '12px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No data', width / 2, height / 2);
      return;
    }

    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
      const padValue = Math.max(1, Math.abs(min) * 0.1 || 1);
      min -= padValue;
      max += padValue;
    }

    const getX = (index) => pad.left + (rows.length <= 1 ? innerWidth : (index / (rows.length - 1)) * innerWidth);
    const getY = (value) => {
      const ratio = (value - min) / Math.max(max - min, 1e-9);
      return pad.top + innerHeight - ratio * innerHeight;
    };

    ctx.strokeStyle = border;
    ctx.fillStyle = secondary;
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 3; i += 1) {
      const y = pad.top + (innerHeight * i) / 3;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + innerWidth, y);
      ctx.stroke();
      const labelValue = max - ((max - min) * i) / 3;
      ctx.fillText(options.tickFormatter(labelValue), pad.left - 8, y + 4);
    }

    ctx.beginPath();
    rows.forEach((row, index) => {
      const x = getX(index);
      const y = getY(Number(row[valueKey]) || 0);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2.5;
    ctx.stroke();

    ctx.lineTo(getX(rows.length - 1), pad.top + innerHeight);
    ctx.lineTo(getX(0), pad.top + innerHeight);
    ctx.closePath();
    ctx.globalAlpha = 0.14;
    ctx.fillStyle = accent;
    ctx.fill();
    ctx.globalAlpha = 1;

    const last = rows[rows.length - 1];
    const lastX = getX(rows.length - 1);
    const lastY = getY(Number(last[valueKey]) || 0);
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fillStyle = accent;
    ctx.fill();

    ctx.fillStyle = secondary;
    ctx.textAlign = 'left';
    ctx.font = '11px Inter, sans-serif';
    ctx.fillText(options.tickFormatter(min), pad.left, height - 8);
    ctx.textAlign = 'right';
    ctx.fillText(options.tickFormatter(max), width - pad.right, height - 8);
  }

  function ensureSelectValue(select, options, previousValue) {
    select.textContent = '';
    if (!options.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'No data';
      select.appendChild(option);
      select.disabled = true;
      return '';
    }

    options.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.key;
      option.textContent = item.label;
      select.appendChild(option);
    });
    select.disabled = false;
    const nextValue = options.some((item) => item.key === previousValue)
      ? previousValue
      : options[0].key;
    select.value = nextValue;
    return nextValue;
  }

  function weightedMean(sum, weight) {
    return weight > 0 ? sum / weight : 0;
  }

  function aggregateRouteSeries(seriesMap) {
    const buckets = new Map();
    Object.values(seriesMap || {}).forEach((rows) => {
      (rows || []).forEach((row) => {
        const t = Number(row.t_s);
        if (!Number.isFinite(t)) return;
        let bucket = buckets.get(t);
        if (!bucket) {
          bucket = {
            t_s: t,
            aircraft_count: 0,
            delayed_count: 0,
            speed_sum: 0,
            congestion_sum: 0,
            delay_sum: 0,
            remaining_sum: 0,
          };
          buckets.set(t, bucket);
        }
        const count = Math.max(0, Number(row.aircraft_count) || 0);
        const delayedRatio = Number(row.delayed_ratio) || 0;
        bucket.aircraft_count += count;
        bucket.delayed_count += delayedRatio * count;
        bucket.speed_sum += (Number(row.mean_speed_knots) || 0) * count;
        bucket.congestion_sum += (Number(row.mean_congestion) || 0) * count;
        bucket.delay_sum += (Number(row.mean_delay_s) || 0) * count;
        bucket.remaining_sum += (Number(row.mean_remaining_m) || 0) * count;
      });
    });

    return Array.from(buckets.values())
      .sort((a, b) => a.t_s - b.t_s)
      .map((bucket) => {
        const weight = bucket.aircraft_count;
        return {
          t_s: bucket.t_s,
          route_key: ALL_ROUTES_KEY,
          route_label: '전체 노선',
          origin_node_id: null,
          destination_node_id: null,
          aircraft_count: bucket.aircraft_count,
          mean_speed_knots: weightedMean(bucket.speed_sum, weight),
          mean_congestion: weightedMean(bucket.congestion_sum, weight),
          mean_delay_s: weightedMean(bucket.delay_sum, weight),
          delayed_ratio: weightedMean(bucket.delayed_count, weight),
          mean_remaining_m: weightedMean(bucket.remaining_sum, weight),
        };
      });
  }

  function aggregateLinkSeries(seriesMap) {
    const buckets = new Map();
    Object.values(seriesMap || {}).forEach((rows) => {
      (rows || []).forEach((row) => {
        const t = Number(row.t_s);
        if (!Number.isFinite(t)) return;
        let bucket = buckets.get(t);
        if (!bucket) {
          bucket = {
            t_s: t,
            count: 0,
            speed_sum: 0,
            speed_weight: 0,
            score_sum: 0,
            score_count: 0,
            level_max: 0,
          };
          buckets.set(t, bucket);
        }
        const count = Math.max(0, Number(row.count) || 0);
        const score = Number(row.score);
        const level = Number(row.level);
        bucket.count += count;
        bucket.speed_sum += (Number(row.mean_speed_knots) || 0) * count;
        bucket.speed_weight += count;
        if (Number.isFinite(score)) {
          bucket.score_sum += score;
          bucket.score_count += 1;
        }
        if (Number.isFinite(level)) {
          bucket.level_max = Math.max(bucket.level_max, level);
        }
      });
    });

    return Array.from(buckets.values())
      .sort((a, b) => a.t_s - b.t_s)
      .map((bucket) => ({
        t_s: bucket.t_s,
        link_key: ALL_LINKS_KEY,
        link_label: '전체 구간',
        kind: 'aggregate_link',
        count: bucket.count,
        mean_speed_knots: weightedMean(bucket.speed_sum, bucket.speed_weight),
        score: weightedMean(bucket.score_sum, bucket.score_count),
        level: bucket.level_max,
      }));
  }

  function getSelectedRouteRows(payload) {
    if (selectedRouteKey === ALL_ROUTES_KEY) {
      return aggregateRouteSeries(payload.route_series || {});
    }
    return (payload.route_series || {})[selectedRouteKey] || [];
  }

  function getSelectedLinkRows(payload) {
    if (selectedLinkKey === ALL_LINKS_KEY) {
      return aggregateLinkSeries(payload.link_series || {});
    }
    return (payload.link_series || {})[selectedLinkKey] || [];
  }

  function updateSelectors(payload) {
    const routeOptions = [
      { key: ALL_ROUTES_KEY, label: '전체 노선' },
      ...Object.keys(payload.route_labels || {}).map((key) => ({
        key,
        label: payload.route_labels[key],
      })),
    ];
    const linkOptions = [
      { key: ALL_LINKS_KEY, label: '전체 구간' },
      ...Object.keys(payload.link_labels || {}).map((key) => ({
        key,
        label: payload.link_labels[key],
      })),
    ];

    selectedRouteKey = ensureSelectValue(routeSelect, routeOptions, selectedRouteKey || routeSelect.value || ALL_ROUTES_KEY);
    selectedLinkKey = ensureSelectValue(linkSelect, linkOptions, selectedLinkKey || linkSelect.value || ALL_LINKS_KEY);
  }

  function renderScenarioMeta(payload) {
    const scenario = payload.scenario || {};
    scenarioIdEl.textContent = scenario.scenario_id || '-';
    scenarioCreatedEl.textContent = scenario.created_at || '-';
    scenarioReasonEl.textContent = scenario.reason || '-';
    sampleCountEl.textContent = String((payload.summary_series || []).length);
    paramsJson.textContent = JSON.stringify(payload.params || {}, null, 2);
    currentZip.href = scenario.scenario_id ? `/api/analytics/scenario/${scenario.scenario_id}.zip` : '#';
    currentZip.classList.toggle('is-disabled', !scenario.scenario_id);
  }

  function renderScenarioDownloads(payload) {
    const scenarios = payload.scenarios || [];
    scenarioList.textContent = '';
    if (!scenarios.length) {
      const empty = document.createElement('div');
      empty.className = 'studio-textbox';
      empty.textContent = '저장된 시나리오가 없습니다.';
      scenarioList.appendChild(empty);
      return;
    }

    scenarios.forEach((scenario) => {
      const block = document.createElement('section');
      block.className = 'graphs-scenario-item';

      const head = document.createElement('div');
      head.className = 'graphs-scenario-item-head';
      head.innerHTML = `
        <div>
          <strong>${scenario.scenario_id}</strong>
          <p>${scenario.created_at || '-'} / ${scenario.reason || '-'}</p>
        </div>
        <a class="topbar-link-btn" href="/api/analytics/scenario/${scenario.scenario_id}.zip">ZIP</a>
      `;
      block.appendChild(head);

      const files = document.createElement('div');
      files.className = 'graphs-file-links';
      (scenario.files || []).forEach((filename) => {
        const link = document.createElement('a');
        link.className = 'studio-download-item';
        link.href = `/api/analytics/scenario/${scenario.scenario_id}/file/${encodeURIComponent(filename)}`;
        link.textContent = filename;
        files.appendChild(link);
      });
      block.appendChild(files);
      scenarioList.appendChild(block);
    });
  }

  function renderCurrentValues(payload) {
    const summarySeries = payload.summary_series || [];
    const summary = summarySeries[summarySeries.length - 1] || {};
    currentValues.n.textContent = String(summary.aircraft_count || 0);
    currentValues.dr.textContent = formatPercent(summary.delay_rate || 0);
    currentValues.speed.textContent = `${formatNumber(summary.mean_speed_knots || 0, 1)} kt`;
    currentValues.congestion.textContent = formatNumber(summary.mean_congestion || 0, 2);

    const routeRows = getSelectedRouteRows(payload);
    const route = routeRows[routeRows.length - 1] || {};
    currentValues.routeCount.textContent = String(route.aircraft_count || 0);
    currentValues.routeCongestion.textContent = formatNumber(route.mean_congestion || 0, 2);
    currentValues.routeSpeed.textContent = `${formatNumber(route.mean_speed_knots || 0, 1)} kt`;
    currentValues.routeDelay.textContent = `${formatNumber(route.mean_delay_s || 0, 1)} s`;

    const linkRows = getSelectedLinkRows(payload);
    const link = linkRows[linkRows.length - 1] || {};
    currentValues.linkCount.textContent = String(link.count || 0);
    currentValues.linkScore.textContent = formatNumber(link.score || 0, 2);
    currentValues.linkSpeed.textContent = `${formatNumber(link.mean_speed_knots || 0, 1)} kt`;
    currentValues.linkLevel.textContent = String(link.level || 0);
  }

  function renderCharts(payload) {
    const summarySeries = payload.summary_series || [];
    const routeRows = getSelectedRouteRows(payload);
    const linkRows = getSelectedLinkRows(payload);

    drawLineChart(charts.summaryN, summarySeries, 'aircraft_count', {
      color: '#34c759',
      tickFormatter: (value) => `${Math.round(value)}`,
    });
    drawLineChart(charts.summaryDR, summarySeries, 'delay_rate', {
      color: '#ff9500',
      tickFormatter: (value) => `${(value * 100).toFixed(0)}%`,
    });
    drawLineChart(charts.summarySpeed, summarySeries, 'mean_speed_knots', {
      color: '#007aff',
      tickFormatter: (value) => `${Math.round(value)}`,
    });
    drawLineChart(charts.summaryCongestion, summarySeries, 'mean_congestion', {
      color: '#8e44ad',
      tickFormatter: (value) => value.toFixed(2),
    });

    drawLineChart(charts.routeCount, routeRows, 'aircraft_count', {
      color: '#34c759',
      tickFormatter: (value) => `${Math.round(value)}`,
    });
    drawLineChart(charts.routeCongestion, routeRows, 'mean_congestion', {
      color: '#ff9500',
      tickFormatter: (value) => value.toFixed(2),
    });
    drawLineChart(charts.routeSpeed, routeRows, 'mean_speed_knots', {
      color: '#007aff',
      tickFormatter: (value) => `${Math.round(value)}`,
    });
    drawLineChart(charts.routeDelay, routeRows, 'mean_delay_s', {
      color: '#ff3b30',
      tickFormatter: (value) => `${Math.round(value)}s`,
    });

    drawLineChart(charts.linkCount, linkRows, 'count', {
      color: '#34c759',
      tickFormatter: (value) => `${Math.round(value)}`,
    });
    drawLineChart(charts.linkScore, linkRows, 'score', {
      color: '#ff9500',
      tickFormatter: (value) => value.toFixed(2),
    });
    drawLineChart(charts.linkSpeed, linkRows, 'mean_speed_knots', {
      color: '#007aff',
      tickFormatter: (value) => `${Math.round(value)}`,
    });
    drawLineChart(charts.linkLevel, linkRows, 'level', {
      color: '#8e44ad',
      tickFormatter: (value) => `${Math.round(value)}`,
    });
  }

  function renderPayload(payload) {
    currentPayload = payload;
    updateSelectors(payload);
    renderScenarioMeta(payload);
    renderScenarioDownloads(payload);
    renderCurrentValues(payload);
    renderCharts(payload);
  }

  async function loadAnalytics() {
    try {
      const response = await fetch('/api/analytics/current', { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      setConnection('연결됨', true);
      renderPayload(payload);
    } catch (error) {
      setConnection('연결 오류', false);
      if (!currentPayload) {
        renderPayload({
          scenario: null,
          summary_series: [],
          route_series: {},
          route_labels: {},
          link_series: {},
          link_labels: {},
          params: {},
          scenarios: [],
        });
      }
    }
  }

  routeSelect.addEventListener('change', () => {
    selectedRouteKey = routeSelect.value;
    if (currentPayload) {
      renderCurrentValues(currentPayload);
      renderCharts(currentPayload);
    }
  });

  linkSelect.addEventListener('change', () => {
    selectedLinkKey = linkSelect.value;
    if (currentPayload) {
      renderCurrentValues(currentPayload);
      renderCharts(currentPayload);
    }
  });

  btnBackMain.addEventListener('click', () => {
    window.location.href = '/';
  });
  btnTheme.addEventListener('click', toggleTheme);

  window.addEventListener('focus', loadAnalytics);
  loadAnalytics();
  pollTimer = window.setInterval(loadAnalytics, 1200);
})();
