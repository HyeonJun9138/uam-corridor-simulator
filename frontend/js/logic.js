(function () {
  'use strict';

  let ws = null;
  let currentState = null;
  let currentAnalysis = null;
  let logicStatus = null;
  let reconnectTimer = null;
  let isDark = false;
  let isAnalyzing = false;
  let isActivating = false;
  let analysisCodeSnapshot = '';
  let activeCodeSnapshot = '';
  let autoDeactivating = false;

  const SAMPLE_CODE = `LOGIC_NAME = "500m Separation Guard"
LOGIC_DESCRIPTION = "앞 기체와 분리가 500m 아래로 줄면 지시 속도를 30% 낮춥니다."

PARAM_OVERRIDES = {
    "sep_min_m": 500,
}

def control_step(state):
    commands = []
    notes = []

    for ac in state.get("aircraft", []):
        data = ac.get("data", {})
        status = data.get("status", {})
        spacing = data.get("spacing", {})
        speed_ctrl = data.get("control", {}).get("speed", {})

        if status.get("action") is not None or status.get("wait_reason") is not None:
            continue
        if not speed_ctrl.get("can_issue_now", False):
            continue

        forward_gap = spacing.get("forward_flow_gap_m")
        if forward_gap is None or forward_gap >= 500:
            continue

        current_cmd = speed_ctrl.get("command_knots", ac.get("v_cmd_knots", 100))
        allowed_min = speed_ctrl.get("allowed_min_knots", 60)
        reduced = max(allowed_min, current_cmd * 0.7)

        commands.append({
            "action": "set_speed",
            "id": ac["id"],
            "speed": reduced,
        })

        notes.append(f'#{ac["id"]} forward gap {forward_gap:.1f}m -> speed {reduced:.1f}kt')

    return {"commands": commands, "notes": notes}
`;

  const $ = (id) => document.getElementById(id);

  const codeInput = $('logic-code');
  const fileInput = $('logic-file-input');
  const btnAnalyze = $('btn-logic-analyze');
  const btnActivate = $('btn-logic-activate');
  const btnApplyDetectedParams = $('btn-apply-detected-params');
  const btnLoadSample = $('btn-load-sample');
  const btnClearLog = $('btn-clear-log');
  const btnBackMain = $('btn-back-main');
  const btnTheme = $('btn-theme');
  const chkAutoApplyParams = $('chk-auto-apply-params');

  const connection = $('logic-connection');
  const logicActivePill = $('logic-active-pill');
  const logicAnalysisPill = $('logic-analysis-pill');
  const logicRunPill = $('logic-run-pill');
  const logicName = $('logic-name');
  const logicAnalysisState = $('logic-analysis-state');
  const logicFunctionName = $('logic-function-name');
  const logicSourceStats = $('logic-source-stats');
  const logicParamCount = $('logic-param-count');
  const logicHealthCounts = $('logic-health-counts');
  const logicDescriptionBox = $('logic-description-box');
  const logicLastRun = $('logic-last-run');
  const logicCommandCount = $('logic-command-count');
  const logicRuntimeMs = $('logic-runtime-ms');
  const logicCommandBreakdown = $('logic-command-breakdown');
  const logicNoteCount = $('logic-note-count');
  const logicParamApplyCount = $('logic-param-apply-count');
  const logicLastNotes = $('logic-last-notes');
  const logicLastParams = $('logic-last-params');
  const logicLastError = $('logic-last-error');
  const analysisSummary = $('logic-analysis-summary');
  const analysisText = $('logic-analysis-text');
  const operatorText = $('logic-operator-text');
  const errorsList = $('logic-errors');
  const warningsList = $('logic-warnings');
  const detectedParams = $('logic-detected-params');
  const detectedParamsText = $('logic-detected-params-text');
  const logOutput = $('logic-log');
  const simNow = $('sim-now');
  const simMode = $('sim-mode');
  const simCount = $('sim-count');
  const simDelayRate = $('sim-delay-rate');
  const simTotalDelay = $('sim-total-delay');

  function getCodeValue() {
    return String(codeInput.value || '');
  }

  function isCodeDirty() {
    if (!currentAnalysis) return !!getCodeValue().trim();
    return getCodeValue() !== analysisCodeSnapshot;
  }

  function appendLog(message, tone) {
    const ts = new Date().toLocaleTimeString('ko-KR', { hour12: false });
    const line = document.createElement('div');
    line.className = `studio-log-line studio-log-${tone || 'info'}`;
    line.textContent = `[${ts}] ${message}`;
    logOutput.appendChild(line);
    logOutput.scrollTop = logOutput.scrollHeight;
  }

  function clearLog() {
    logOutput.textContent = '';
  }

  function formatJson(value) {
    try {
      return JSON.stringify(value || {}, null, 2);
    } catch (_) {
      return '{}';
    }
  }

  function formatEpoch(seconds) {
    if (!Number.isFinite(seconds)) return '-';
    return new Date(seconds * 1000).toLocaleTimeString('ko-KR', { hour12: false });
  }

  function formatSummaryMode(mode) {
    if (mode === 'route') return 'Custom 항로';
    if (mode === 'corridor') return '직선 항로';
    return mode || '-';
  }

  function formatAnalysisState(status) {
    if (!status || !status.analysis) return '-';
    return status.analysis_ok ? '통과' : '검토 필요';
  }

  function formatSourceStats(status) {
    const lines = status && Number.isFinite(status.source_line_count) ? status.source_line_count : 0;
    const chars = status && Number.isFinite(status.source_length) ? status.source_length : 0;
    if (!lines && !chars) return '-';
    return `${lines} lines / ${chars} chars`;
  }

  function formatCommandBreakdown(map) {
    if (!map || typeof map !== 'object') return '-';
    const items = Object.keys(map).sort().map((key) => `${key} ${map[key]}`);
    return items.length ? items.join(', ') : '-';
  }

  function formatNotes(notes) {
    if (!Array.isArray(notes) || !notes.length) return '노트 없음';
    return notes.join('\n');
  }

  function updateActionButtons() {
    const analysisOk = !!(currentAnalysis && currentAnalysis.ok);
    const dirty = isCodeDirty();
    const active = !!(logicStatus && logicStatus.active);
    const readyToActivate = analysisOk && !dirty && !isAnalyzing && !isActivating;

    btnAnalyze.classList.remove('is-busy', 'is-ready', 'is-dirty');
    btnActivate.classList.remove('is-busy', 'is-active', 'is-waiting');

    if (isAnalyzing) {
      btnAnalyze.textContent = '분석 중';
      btnAnalyze.classList.add('is-busy');
    } else if (analysisOk && !dirty) {
      btnAnalyze.textContent = '분석 완료';
      btnAnalyze.classList.add('is-ready');
    } else if (dirty && currentAnalysis) {
      btnAnalyze.textContent = '다시 분석';
      btnAnalyze.classList.add('is-dirty');
    } else {
      btnAnalyze.textContent = '코드 분석';
    }

    if (isActivating) {
      btnActivate.textContent = '처리 중';
      btnActivate.classList.add('is-busy');
      btnActivate.disabled = true;
    } else if (active) {
      btnActivate.textContent = '로직 중지';
      btnActivate.classList.add('is-active');
      btnActivate.disabled = false;
    } else if (analysisOk && !dirty) {
      btnActivate.textContent = '로직 활성화';
      btnActivate.disabled = false;
    } else {
      btnActivate.textContent = analysisOk && dirty ? '다시 분석 후 활성화' : '로직 활성화';
      btnActivate.classList.add('is-waiting');
      btnActivate.disabled = !readyToActivate;
    }

    btnAnalyze.disabled = isAnalyzing || isActivating;
  }

  function maybeAutoDeactivateDueToEdit() {
    if (!logicStatus || !logicStatus.active) return;
    if (autoDeactivating) return;
    if (getCodeValue() === activeCodeSnapshot) return;
    autoDeactivating = true;
    isActivating = true;
    updateActionButtons();
    appendLog('코드가 변경되어 현재 활성 로직을 자동 중지합니다.', 'warn');
    send({ action: 'logic_deactivate' });
  }

  function renderStateSummary(state) {
    const summary = state && state.summary ? state.summary : {};
    simNow.textContent = state && state.t !== undefined ? `T=${Number(state.t).toFixed(1)}s` : '-';
    simMode.textContent = formatSummaryMode(state ? state.mode : null);
    simCount.textContent = String(summary.N || 0);
    simDelayRate.textContent = `${((Number(summary.DR || 0) * 100)).toFixed(1)}%`;
    simTotalDelay.textContent = `${Number(summary.TD_min || 0).toFixed(1)}분`;
  }

  function renderLogicStatus(status) {
    const analysis = status && status.analysis ? status.analysis : {};
    const lastResult = status && status.last_result ? status.last_result : {};
    const active = !!(status && status.active);
    const warningCount = status && Number.isFinite(status.warning_count) ? status.warning_count : ((analysis.warnings || []).length || 0);
    const errorCount = status && Number.isFinite(status.error_count) ? status.error_count : ((analysis.errors || []).length || 0);
    const paramCount = status && Number.isFinite(status.detected_param_count) ? status.detected_param_count : Object.keys(analysis.detected_params || {}).length;

    logicStatus = status || null;

    logicActivePill.textContent = active ? 'active' : 'inactive';
    logicActivePill.classList.toggle('studio-pill-live', active);
    logicActivePill.classList.toggle('studio-pill-muted', !active);

    logicRunPill.textContent = active ? 'running' : 'idle';
    logicRunPill.classList.toggle('studio-pill-live', active);
    logicRunPill.classList.toggle('studio-pill-muted', !active);

    logicName.textContent = status && status.logic_name ? status.logic_name : '-';
    logicAnalysisState.textContent = formatAnalysisState(status);
    logicFunctionName.textContent = status && status.function_name ? status.function_name : 'control_step';
    logicSourceStats.textContent = formatSourceStats(status);
    logicParamCount.textContent = String(paramCount);
    logicHealthCounts.textContent = `${warningCount} / ${errorCount}`;
    logicDescriptionBox.textContent = status && status.logic_description ? status.logic_description : '설명 없음';
    logicLastRun.textContent = formatEpoch(lastResult.last_run_s);
    logicCommandCount.textContent = String(lastResult.command_count || 0);
    logicRuntimeMs.textContent = Number.isFinite(lastResult.last_runtime_ms)
      ? `${Number(lastResult.last_runtime_ms).toFixed(3)} ms`
      : '-';
    logicCommandBreakdown.textContent = formatCommandBreakdown(lastResult.commands_by_action);
    logicNoteCount.textContent = String(lastResult.note_count || 0);
    logicParamApplyCount.textContent = String(Object.keys(lastResult.params_applied || {}).length);
    logicLastNotes.textContent = formatNotes(lastResult.notes);
    logicLastParams.textContent = formatJson(lastResult.params_applied || {});

    if (status && status.last_error) {
      logicLastError.textContent = status.last_traceback || status.last_error;
      logicLastError.classList.add('is-error');
    } else {
      logicLastError.textContent = '오류 없음';
      logicLastError.classList.remove('is-error');
    }

    updateActionButtons();
  }

  function renderIssues(listEl, items, emptyText) {
    const entries = Array.isArray(items) ? items : [];
    listEl.textContent = '';
    if (!entries.length) {
      const li = document.createElement('li');
      li.textContent = emptyText;
      listEl.appendChild(li);
      return;
    }
    entries.forEach((item) => {
      const li = document.createElement('li');
      li.textContent = item;
      listEl.appendChild(li);
    });
  }

  function renderAnalysis(analysis) {
    const ok = !!(analysis && analysis.ok);
    const summaryItems = analysis && Array.isArray(analysis.summary) && analysis.summary.length
      ? analysis.summary
      : ['아직 분석 결과가 없습니다.'];
    const explanation = analysis && analysis.explanation ? analysis.explanation : {};
    const explanationError = explanation && explanation.error ? String(explanation.error) : '';
    const logicEffectText = explanation && explanation.logic_effect_txt
      ? explanation.logic_effect_txt
      : '분석 요청 시 이 코드를 넣으면 시뮬레이터가 어떻게 동작할지 설명이 생성됩니다.';
    const operatorEffectText = explanation && explanation.operator_txt
      ? explanation.operator_txt
      : '분석 요청 시 운영 관점에서 어떤 명령과 제약이 생기는지 설명이 생성됩니다.';
    const paramsEffectText = explanation && explanation.detected_params_txt
      ? explanation.detected_params_txt
      : '감지한 파라미터는 코드의 PARAM_OVERRIDES 같은 literal override 값을 의미합니다.';

    currentAnalysis = analysis || null;
    if (analysis) {
      analysisCodeSnapshot = getCodeValue();
    }

    logicAnalysisPill.textContent = analysis ? (ok ? '통과' : '검토 필요') : '미분석';
    logicAnalysisPill.classList.toggle('studio-pill-live', !!analysis && ok);
    logicAnalysisPill.classList.toggle('studio-pill-muted', !analysis || !ok);

    analysisSummary.textContent = '';
    summaryItems.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'studio-summary-row';
      row.textContent = item;
      analysisSummary.appendChild(row);
    });

    renderIssues(errorsList, analysis ? analysis.errors : null, '오류 없음');
    renderIssues(warningsList, analysis ? analysis.warnings : null, '경고 없음');
    detectedParams.textContent = formatJson(analysis && analysis.detected_params ? analysis.detected_params : {});
    analysisText.textContent = logicEffectText;
    operatorText.textContent = explanationError
      ? `${operatorEffectText}\n\n[LLM 분석 참고]\n${explanationError}`
      : operatorEffectText;
    detectedParamsText.textContent = paramsEffectText;

    if (!logicStatus || !logicStatus.active) {
      renderLogicStatus({
        active: false,
        logic_name: logicStatus && logicStatus.logic_name ? logicStatus.logic_name : '사용자 로직',
        logic_description: analysis && analysis.logic_description ? analysis.logic_description : '',
        source_length: analysis && Number.isFinite(analysis.source_length) ? analysis.source_length : 0,
        source_line_count: getCodeValue() ? getCodeValue().split('\n').length : 0,
        analysis_ok: ok,
        function_name: analysis && analysis.function_name ? analysis.function_name : null,
        detected_param_count: Object.keys((analysis && analysis.detected_params) || {}).length,
        warning_count: analysis && Array.isArray(analysis.warnings) ? analysis.warnings.length : 0,
        error_count: analysis && Array.isArray(analysis.errors) ? analysis.errors.length : 0,
        analysis: analysis || {},
        last_result: logicStatus && logicStatus.last_result ? logicStatus.last_result : {},
        last_error: logicStatus ? logicStatus.last_error : null,
        last_traceback: logicStatus ? logicStatus.last_traceback : null,
      });
    } else {
      updateActionButtons();
    }
  }

  function handleLogicStatusResponse(status) {
    renderLogicStatus(status);
    if (status && status.last_error) {
      appendLog(`로직 오류: ${status.last_error}`, 'error');
    }
  }

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = function () {
      connection.textContent = '연결됨';
      connection.classList.add('studio-connection-live');
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      send({ action: 'logic_get_status' });
      appendLog('WebSocket 연결 완료');
    };

    ws.onclose = function () {
      connection.textContent = '재연결 중';
      connection.classList.remove('studio-connection-live');
      reconnectTimer = setTimeout(connect, 2000);
      appendLog('연결 종료. 재연결을 시도합니다.', 'warn');
    };

    ws.onerror = function () {
      connection.textContent = '연결 오류';
      connection.classList.remove('studio-connection-live');
      appendLog('WebSocket 오류', 'error');
    };

    ws.onmessage = function (event) {
      const msg = JSON.parse(event.data);
      if (msg.type === 'state') {
        currentState = msg;
        renderStateSummary(msg);
        handleLogicStatusResponse(msg.external_logic || logicStatus);
        return;
      }
      if (msg.type === 'logic_status') {
        isActivating = false;
        autoDeactivating = false;
        if (!(msg.logic && msg.logic.active)) {
          activeCodeSnapshot = '';
        }
        handleLogicStatusResponse(msg.logic);
        return;
      }
      if (msg.type === 'logic_analysis') {
        isAnalyzing = false;
        renderAnalysis(msg.analysis);
        appendLog(msg.analysis && msg.analysis.ok ? '코드 분석 통과' : '코드 분석 실패', msg.analysis && msg.analysis.ok ? 'info' : 'warn');
        return;
      }
      if (msg.type === 'logic_activation') {
        isActivating = false;
        autoDeactivating = false;
        renderAnalysis(msg.analysis);
        handleLogicStatusResponse(msg.logic);
        if (msg.ok) {
          activeCodeSnapshot = getCodeValue();
        }
        if (msg.param_report && msg.param_report.errors && msg.param_report.errors.length) {
          appendLog(`파라미터 자동 적용 일부 실패: ${msg.param_report.errors.join(' | ')}`, 'warn');
        }
        appendLog(msg.ok ? '외부 로직 활성화 완료' : '외부 로직 활성화 실패', msg.ok ? 'info' : 'error');
        return;
      }
      if (msg.type === 'logic_params_applied') {
        if (msg.report && msg.report.errors && msg.report.errors.length) {
          appendLog(`파라미터 적용 일부 실패: ${msg.report.errors.join(' | ')}`, 'warn');
        } else {
          appendLog('감지한 파라미터를 시뮬레이터에 적용했습니다.');
        }
      }
    };
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      appendLog('서버와 연결되지 않았습니다.', 'error');
      return;
    }
    ws.send(JSON.stringify(payload));
  }

  btnAnalyze.addEventListener('click', function () {
    isAnalyzing = true;
    updateActionButtons();
    send({ action: 'logic_analyze', code: getCodeValue() });
  });

  btnActivate.addEventListener('click', function () {
    if (logicStatus && logicStatus.active) {
      isActivating = true;
      updateActionButtons();
      send({ action: 'logic_deactivate' });
      return;
    }

    if (!currentAnalysis || !currentAnalysis.ok || isCodeDirty()) {
      appendLog('현재 코드를 먼저 분석한 뒤 활성화하세요.', 'warn');
      updateActionButtons();
      return;
    }

    isActivating = true;
    updateActionButtons();
    send({
      action: 'logic_activate',
      code: getCodeValue(),
      auto_apply_detected_params: chkAutoApplyParams.checked,
    });
  });

  btnApplyDetectedParams.addEventListener('click', function () {
    send({
      action: 'logic_apply_params',
      params: currentAnalysis && currentAnalysis.detected_params ? currentAnalysis.detected_params : {},
    });
  });

  btnLoadSample.addEventListener('click', function () {
    codeInput.value = SAMPLE_CODE;
    appendLog('샘플 코드를 불러왔습니다.');
    updateActionButtons();
    maybeAutoDeactivateDueToEdit();
  });

  btnClearLog.addEventListener('click', clearLog);

  btnBackMain.addEventListener('click', function () {
    window.location.href = '/';
  });

  btnTheme.addEventListener('click', function () {
    isDark = !isDark;
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
  });

  fileInput.addEventListener('change', async function (event) {
    const files = event.target.files;
    const file = files && files[0] ? files[0] : null;
    if (!file) return;
    codeInput.value = await file.text();
    appendLog(`파일을 불러왔습니다: ${file.name}`);
    updateActionButtons();
    maybeAutoDeactivateDueToEdit();
  });

  codeInput.addEventListener('input', function () {
    updateActionButtons();
    maybeAutoDeactivateDueToEdit();
  });

  if (!codeInput.value.trim()) {
    codeInput.value = SAMPLE_CODE;
  }

  renderAnalysis(null);
  updateActionButtons();
  connect();
})();
