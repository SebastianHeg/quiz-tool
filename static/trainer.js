// ═══════════════════════════════════════════════════════════
//  MOBILE NAV
// ═══════════════════════════════════════════════════════════
let mobileView = 'main'; // 'sidebar' | 'main' | 'stats'

function mobileToggle(view) {
  mobileView = view;
  const sidebar = document.getElementById('sidebar');
  const stats   = document.getElementById('stats-panel');

  sidebar.classList.toggle('mobile-open', view === 'sidebar');
  stats.classList.toggle('mobile-open',   view === 'stats');

  document.getElementById('mnav-sidebar').classList.toggle('active', view === 'sidebar');
  document.getElementById('mnav-main').classList.toggle('active',    view === 'main');
  document.getElementById('mnav-stats').classList.toggle('active',   view === 'stats');

  // When going back to main, close panels
  if (view === 'main') {
    sidebar.classList.remove('mobile-open');
    stats.classList.remove('mobile-open');
    // Reset scroll so the question + buttons are visible instead of
    // wherever the previous panel/question happened to be scrolled to.
    document.querySelector('main').scrollTop = 0;
  }
}

// Auto-navigate to main after making a selection on mobile
function mobileGoMain() {
  if (window.innerWidth <= 700) mobileToggle('main');
}

// ═══════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════
const sel = {
  field:  null,
  topic:  null,
  examen: null,
  set:    null,
};

let currentQuestion = null;
let questionRequest = 0;

// ═══════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════
async function init() {
  const fields = await fetch('/api/fields').then(r => r.json());
  renderFieldList(fields);

  const saved = localStorage.getItem('trainer_field');
  const initial = saved && fields.includes(saved) ? saved : fields[0];
  await selectField(initial);
}

// ═══════════════════════════════════════════════════════════
//  SELECTION HANDLERS
// ═══════════════════════════════════════════════════════════
async function selectField(fieldId) {
  sel.field  = fieldId;
  sel.topic  = null;
  sel.examen = null;
  sel.set    = null;
  localStorage.setItem('trainer_field', fieldId);

  highlightSel('field', fieldId);
  updateHeaderCtx();

  await Promise.all([
    loadTopics(fieldId),
    loadExamens(fieldId),
    loadSets(fieldId),
  ]);

  await Promise.all([refreshStats(), loadNextQuestion()]);
  mobileGoMain();
}

async function selectTopic(name) {
  if (sel.topic === name) {
    sel.topic = null;
  } else {
    sel.topic  = name;
    sel.examen = null;
    sel.set    = null;
  }
  highlightSel('topic', sel.topic);
  highlightSel('set', null);
  highlightSel('examen', null);
  updateHeaderCtx();
  await Promise.all([refreshStats(), loadNextQuestion()]);
  mobileGoMain();
}

async function selectExamen(examen) {
  if (sel.examen?.name === examen.name) {
    sel.examen = null;
  } else {
    sel.examen = examen;
    sel.topic  = null;
    sel.set    = null;
  }
  highlightSel('examen', sel.examen?.name ?? null);
  highlightSel('set', null);
  highlightSel('topic', null);
  updateHeaderCtx();
  await Promise.all([refreshStats(), loadNextQuestion()]);
  mobileGoMain();
}

async function selectSet(set) {
  if (sel.set?.name === set.name) {
    sel.set = null;
  } else {
    sel.set    = set;
    sel.topic  = null;
    sel.examen = null;
  }
  highlightSel('set', sel.set?.name ?? null);
  highlightSel('examen', null);
  highlightSel('topic', null);
  updateHeaderCtx();
  await Promise.all([refreshStats(), loadNextQuestion()]);
  mobileGoMain();
}

// ═══════════════════════════════════════════════════════════
//  SIDEBAR LOADERS
// ═══════════════════════════════════════════════════════════
function renderFieldList(fields) {
  const list = document.getElementById('fields-list');
  list.innerHTML = '';
  fields.forEach(f => {
    const btn = mkSelBtn(f, f, 'field', () => selectField(f));
    btn.dataset.selKey = f;
    list.appendChild(btn);
  });
}

async function loadTopics(field) {
  const topics = await fetch(`/api/fields/${field}/topics`).then(r => r.json());
  const list = document.getElementById('topic-list');
  list.innerHTML = '';
  topics.forEach(t => {
    const btn = mkSelBtn(t, t, 'topic', () => selectTopic(t));
    btn.dataset.selKey = t;
    list.appendChild(btn);
  });
}

async function loadExamens(field) {
  let examens = [];
  try { examens = await fetch(`/api/fields/${field}/examens`).then(r => r.json()); } catch {}
  const list = document.getElementById('examens-list');
  list.innerHTML = '';
  if (!examens.length) {
    list.innerHTML = '<div style="font-size:0.72rem;color:var(--muted);padding:4px 8px;font-style:italic">Keine Prüfungssätze</div>';
    return;
  }
  examens.forEach(e => {
    const btn = mkSelBtn(e.name, e.name, 'examen', () => selectExamen(e));
    btn.dataset.selKey = e.name;
    if (e.questions_count != null)
      btn.querySelector('.sel-badge').textContent = e.questions_count + ' Fragen';
    list.appendChild(btn);
  });
}

async function loadSets(field) {
  let sets = [];
  try { sets = await fetch(`/api/fields/${field}/sets`).then(r => r.json()); } catch {}
  const list = document.getElementById('sets-list');
  list.innerHTML = '';
  if (!sets.length) {
    list.innerHTML = '<div style="font-size:0.72rem;color:var(--muted);padding:4px 8px;font-style:italic">Keine eigenen Sets</div>';
    return;
  }
  sets.forEach(s => {
    const btn = mkSelBtn(s.name, s.name, 'set', () => selectSet(s));
    btn.dataset.selKey = s.name;
    if (s.questions_count != null)
      btn.querySelector('.sel-badge').textContent = s.questions_count + ' Fragen';
    list.appendChild(btn);
  });
}

// ═══════════════════════════════════════════════════════════
//  STATS PANEL
// ═══════════════════════════════════════════════════════════
async function refreshStats() {
  const scroll = document.getElementById('stats-scroll');
  scroll.innerHTML = '<div id="stats-loading"><div class="spinner"></div> Lade…</div>';

  const { ctxType, ctxName, url } = resolveStatsCtx();

  const strip = document.getElementById('stats-ctx-strip');
  strip.className = 'ctx-' + ctxType;
  document.getElementById('stats-ctx-title').textContent = CTX_LABELS[ctxType];
  document.getElementById('stats-ctx-name').textContent  = ctxName;

  document.getElementById('footer-ctx').textContent =
    ctxType === 'field' ? ctxName : sel.field + ' › ' + ctxName;

  let stats = null;
  try { stats = await fetch(url).then(r => r.json()); } catch {}
  if (!stats) { scroll.innerHTML = '<div style="padding:14px;font-size:0.72rem;color:var(--wrong)">Fehler beim Laden.</div>'; return; }

  renderStats(stats, ctxType, scroll);
}

function resolveStatsCtx() {
  const f = sel.field;
  if (sel.examen) return {
    ctxType: 'examen',
    ctxName: sel.examen.name,
    url: `/api/fields/${f}/examens/${encodeURIComponent(sel.examen.name)}/stats`,
  };
  if (sel.set) return {
    ctxType: 'set',
    ctxName: sel.set.name,
    url: `/api/fields/${f}/sets/${encodeURIComponent(sel.set.name)}/stats`,
  };
  if (sel.topic) return {
    ctxType: 'topic',
    ctxName: sel.topic,
    url: `/api/fields/${f}/topics/${encodeURIComponent(sel.topic)}/stats`,
  };
  return {
    ctxType: 'field',
    ctxName: f,
    url: `/api/fields/${f}/stats`,
  };
}

const CTX_LABELS = {
  field:  'Feld',
  topic:  'Thema',
  examen: 'Prüfungssatz',
  set:    'Eigenes Set',
};

function renderStats(s, ctxType, container) {
  const rate = s.total_attempts ? Math.round(s.success_rate) : null;
  const attemptedPct = s.total ? Math.round(s.attempted / s.total * 100) : 0;
  const rateClass = rate == null ? '' : rate >= 70 ? 'highlight' : rate >= 40 ? '' : 'warn';

  let html = '';

  html += `<div class="metric-grid">
    <div class="metric-box"><span class="m-val">${s.total}</span><span class="m-lbl">Fragen</span></div>
    <div class="metric-box"><span class="m-val">${s.attempted}</span><span class="m-lbl">Versucht</span></div>
    <div class="metric-box"><span class="m-val">${s.total_correct ?? 0}</span><span class="m-lbl">Richtig</span></div>
    <div class="metric-box ${rateClass}"><span class="m-val">${rate != null ? rate + '%' : '–'}</span><span class="m-lbl">Quote</span></div>
  </div>`;

  html += `<div>
    <div class="stats-section-label">Fortschritt</div>
    <div class="progress-row" style="margin-bottom:8px">
      <div class="pr-label"><span>Bearbeitet</span><span>${s.attempted} / ${s.total}</span></div>
      <div class="big-bar-wrap"><div class="big-bar-fill" style="width:${attemptedPct}%"></div></div>
    </div>`;
  if (rate != null) {
    html += `<div class="progress-row">
      <div class="pr-label"><span>Erfolgsquote</span><span>${rate}%</span></div>
      <div class="big-bar-wrap"><div class="big-bar-fill" style="width:${rate}%;background:linear-gradient(90deg,var(--wrong),var(--correct))"></div></div>
    </div>`;
  }
  html += `</div>`;

  if (s.best_streak != null && s.best_streak > 0) {
    html += `<div>
      <div class="stats-section-label">Streak</div>
      <span class="streak-badge"><span class="sb-val">${s.best_streak}</span><span class="sb-lbl">beste Serie</span></span>
    </div>`;
  }

  if (ctxType === 'field' && s.topics?.length) {
    html += `<div>
      <div class="stats-section-label">Nach Thema</div>`;
    s.topics.forEach(t => {
      const tr = t.attempted ? Math.round(t.correct / t.attempted * 100) : null;
      const barClass = tr == null ? 'zero' : tr >= 70 ? 'good' : tr >= 40 ? 'mid' : 'poor';
      const barW = tr ?? 0;
      html += `<div class="breakdown-row" onclick="clickTopicBreakdown(${esc(JSON.stringify(t.name))})">
        <div class="br-top">
          <span class="br-name">${esc(t.name)}</span>
          <span class="br-ratio">${t.attempted ? t.correct + '/' + t.attempted : '–'}</span>
        </div>
        <div class="mini-bar-wrap"><div class="mini-bar-fill ${barClass}" style="width:${barW}%"></div></div>
      </div>`;
    });
    html += `</div>`;
  }

  if ((ctxType === 'topic' || ctxType === 'set' || ctxType === 'examen') && s.questions?.length) {
    html += `<div>
      <div class="stats-section-label">Fragen</div>`;
    s.questions.forEach(q => {
      const dot = q.attempts === 0 ? 'none' : (q.last_result === 'correct' ? 'ok' : 'fail');
      html += `<div class="stats-q-item" onclick="jumpToQuestion(${esc(JSON.stringify(q.id))})">
        <div class="pdot ${dot}" style="margin-top:3px;flex-shrink:0"></div>
        <span class="sq-text">${esc(q.question)}</span>
        <span class="sq-ratio">${q.attempts > 0 ? q.correct + '/' + q.attempts : '–'}</span>
      </div>`;
    });
    html += `</div>`;
  }

  container.innerHTML = html;
}

function clickTopicBreakdown(name) {
  const btn = [...document.querySelectorAll('#topic-list .sel-btn')]
    .find(b => b.dataset.selKey === name);
  if (btn) btn.click();
}

function jumpToQuestion(qid) {
  fetch(`/api/fields/${sel.field}/questions`)
    .then(r => r.json())
    .then(questions => {
      const q = questions.find(q => q.id === qid);
      if (q) { displayQuestion(q); mobileGoMain(); }
    });
}

// ═══════════════════════════════════════════════════════════
//  QUESTION LOADING
// ═══════════════════════════════════════════════════════════
async function loadNextQuestion() {
  const requestId = ++questionRequest;
  currentQuestion = null;
  document.getElementById('reveal-btn').disabled = true;
  setAnswerPending(false);
  resetResultCard();
  document.getElementById('answer-input').value    = '';
  document.getElementById('answer-input').disabled = false;
  document.getElementById('answer-input').style.height = '';
  document.getElementById('submit-btn').disabled   = false;

  const url = resolveQuestionUrl();
  const q = await fetch(url).then(r => r.json()).catch(() => ({ error: 'Netzwerkfehler' }));
  if (requestId !== questionRequest) return;
  if (q.error) { document.getElementById('question-text').textContent = q.error; return; }
  displayQuestion(q);
  // New content can change main's scroll height; always start at the top
  // so the question card and the buttons below it are both in view.
  document.querySelector('main').scrollTop = 0;
}

function resolveQuestionUrl() {
  const f = sel.field;
  const filter = sel.examen?.name ?? sel.set?.name ?? '';
  const topic  = sel.topic || '';
  return `/api/fields/${encodeURIComponent(f)}/question` +
         `?filter=${encodeURIComponent(filter)}` +
         `&topic=${encodeURIComponent(topic)}`;
}

function displayQuestion(q) {
  currentQuestion = q;
  document.getElementById('reveal-btn').disabled = false;
  document.getElementById('q-topic').textContent    = q.topic;
  document.getElementById('q-subtopic').textContent = q.subtopic || '';
  document.getElementById('q-id').textContent       = q.id;
  document.getElementById('question-text').textContent = q.question;
  document.getElementById('answer-input').focus();
}

// ═══════════════════════════════════════════════════════════
//  SUBMIT
// ═══════════════════════════════════════════════════════════
async function submitAnswer() {
  const answer = document.getElementById('answer-input').value.trim();
  if (!answer) return;
  await requestAnswerResult('/api/assess', { answer }, true);
}

async function revealAnswer() {
  await requestAnswerResult('/api/reveal-answer');
}

async function requestAnswerResult(endpoint, extraFields = {}, updateStats = false) {
  if (!currentQuestion) return;
  const question = currentQuestion;
  const field = sel.field;
  setAnswerPending(true);
  resetResultCard();

  const isCurrentQuestion = () => currentQuestion === question && sel.field === field;
  try {
    const result = await postJson(endpoint, { field, id: question.id, ...extraFields });
    if (!isCurrentQuestion()) return;
    showResult(result);
    if (updateStats) await refreshStats();
  } catch (error) {
    if (!isCurrentQuestion()) return;
    showRequestError(error);
    setAnswerPending(false);
  } finally {
    if (isCurrentQuestion()) {
      document.getElementById('loading').classList.remove('visible');
    }
  }
}

async function postJson(endpoint, body) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok || result.error) {
    throw new Error(result.error || 'Anfrage fehlgeschlagen.');
  }
  return result;
}

function setAnswerPending(pending) {
  document.getElementById('submit-btn').disabled = pending;
  document.getElementById('answer-input').disabled = pending;
  document.getElementById('loading').classList.toggle('visible', pending);
}

function showRequestError(error) {
  document.getElementById('result-feedback').textContent =
    error.message || 'Bewertung fehlgeschlagen. Bitte erneut versuchen.';
  document.getElementById('result-verdict').textContent = 'Fehler';
  document.getElementById('expected-answer-text').textContent = '';
  document.getElementById('result-card').style.display = 'block';
}

// ═══════════════════════════════════════════════════════════
//  UI HELPERS
// ═══════════════════════════════════════════════════════════
function showResult(res) {
  const card = document.getElementById('result-card');
  const resultType = getResultType(res);
  card.className     = resultType;
  card.style.display = 'block';

  const verdict = document.getElementById('result-verdict');
  if (resultType === 'correct') {
    verdict.textContent = '✓ Richtig';
    verdict.className   = 'result-verdict ok';
  } else if (resultType === 'partial') {
    verdict.textContent = '~ Teilweise';
    verdict.className   = 'result-verdict';
  } else if (resultType === 'revealed') {
    verdict.textContent = '👁 Lösung gezeigt';
    verdict.className   = 'result-verdict';
  } else {
    verdict.textContent = '✗ Falsch';
    verdict.className   = 'result-verdict fail';
  }

  const bar = document.getElementById('score-bar');
  if (resultType === 'revealed') {
    bar.style.width = '0%';
    bar.className = 'score-bar';
  } else {
    bar.style.width = (res.score * 100) + '%';
    bar.className = 'score-bar ' + (resultType === 'correct' ? 'ok' : resultType === 'partial' ? 'partial' : 'fail');
  }

  document.getElementById('result-feedback').textContent      = res.feedback;
  document.getElementById('expected-answer-text').textContent = res.answer;
}

function getResultType(res) {
  if (res.result === 'revealed') return 'revealed';
  if (res.is_sks == true) {
    if (res.sks_punkte == 2) return 'correct';
    if (res.sks_punkte == 1) return 'partial';
    return 'wrong';
  }
  switch (res.result) {
    case "fully_correct":      return "correct";
    case "correct":            return "correct";
    case "mostly_correct":
    case "partially_correct":
    case "minimally_correct":  return "partial";
    default:                   return "wrong";
  }
}

function resetResultCard() {
  const card = document.getElementById('result-card');
  card.style.display = 'none';
  card.className = '';
}

function highlightSel(type, activeKey) {
  const listId = { field: 'fields-list', topic: 'topic-list', examen: 'examens-list', set: 'sets-list' }[type];
  document.querySelectorAll(`#${listId} .sel-btn`).forEach(b => {
    b.classList.toggle('active', activeKey != null && b.dataset.selKey === activeKey);
  });
}

function updateHeaderCtx() {
  document.getElementById('hctx-field').textContent = sel.field || '–';
  document.querySelectorAll('#header-ctx .ctx-sep, #header-ctx .ctx-sub').forEach(el => el.remove());

  const subName = sel.examen?.name ?? sel.set?.name ?? sel.topic ?? null;
  if (subName) {
    const ctx = document.getElementById('header-ctx');
    const sep = document.createElement('span');
    sep.className = 'ctx-sep'; sep.textContent = '›';
    const sub = document.createElement('span');
    sub.className = 'ctx-sub'; sub.textContent = subName;
    ctx.appendChild(sep);
    ctx.appendChild(sub);
  }
}

function mkSelBtn(key, label, type, onClick) {
  const btn = document.createElement('button');
  btn.className = `sel-btn type-${type}`;
  btn.dataset.selKey = key;
  btn.innerHTML = `<span class="sel-label">${esc(label)}</span><span class="sel-badge"></span>`;
  btn.onclick = onClick;
  return btn;
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Strg+Enter to submit
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.ctrlKey) return;
  const resultCard = document.getElementById('result-card');
  const visible = getComputedStyle(resultCard).display !== 'none';
  e.preventDefault();
  if (visible) loadNextQuestion();
  else submitAnswer();
});

init();
