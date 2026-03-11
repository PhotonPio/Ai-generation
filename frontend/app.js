const API_BASE = (() => {
  const stored = localStorage.getItem('apiBase');
  if (stored) return stored;
  // If served from the backend itself, use same origin
  if (window.location.port === '8000' || window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
    return window.location.origin;
  }
  return 'http://localhost:8000';
})();

let currentJobId = null;
let pollTimer = null;
let ws = null;

const promptEl = document.getElementById('prompt');
const minutesEl = document.getElementById('minutes');
const sceneSecondsEl = document.getElementById('sceneSeconds');
const voiceEl = document.getElementById('voice');
const modelEl = document.getElementById('model');
const styleEl = document.getElementById('style');
const languageEl = document.getElementById('language');
const transitionStyleEl = document.getElementById('transitionStyle');
const stepsEl = document.getElementById('steps');
const seedEl = document.getElementById('seed');
const clearCacheEl = document.getElementById('clearCache');
const autoSceneDurationEl = document.getElementById('autoSceneDuration');
const profileEl = document.getElementById('profile');

const progressBar = document.getElementById('progressBar');
const downloadLink = document.getElementById('downloadLink');
const renderStatus = document.getElementById('renderStatus');
const logBox = document.getElementById('logBox');
const previewVideo = document.getElementById('previewVideo');

const phaseBars = {
  script: document.getElementById('phaseScript'),
  images: document.getElementById('phaseImages'),
  audio: document.getElementById('phaseAudio'),
  render: document.getElementById('phaseRender'),
};


async function checkBackendHealth() {
  const banner = document.getElementById('statusBanner');
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      banner.textContent = '✅ Backend connected — ready to generate.';
      banner.className = 'status-banner ok';
      setTimeout(() => banner.classList.add('hidden'), 4000);
    } else {
      throw new Error('Non-200 response');
    }
  } catch {
    banner.innerHTML = `
      ❌ Backend not running. Open your terminal and run:<br>
      <code style="font-size:0.8rem">./start.sh</code> (Mac/Linux) &nbsp;or&nbsp;
      <code style="font-size:0.8rem">start.bat</code> (Windows)
    `;
    banner.className = 'status-banner error';
  }
  banner.classList.remove('hidden');
}

// Call on page load
checkBackendHealth();

function authHeader() {
  const user = localStorage.getItem('apiUser') || '';
  const pass = localStorage.getItem('apiPass') || '';
  if (!user && !pass) return {};
  return { Authorization: `Basic ${btoa(`${user}:${pass}`)}` };
}

document.getElementById('saveAuthBtn').addEventListener('click', () => {
  localStorage.setItem('apiUser', document.getElementById('apiUser').value);
  localStorage.setItem('apiPass', document.getElementById('apiPass').value);
});

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeader() };
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  return response;
}

function showStep(name) {
  document.querySelectorAll('.phase').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.phase').forEach(el => el.classList.remove('active'));
  const section = document.getElementById(`step-${name}`);
  if (section) {
    section.classList.remove('hidden');
    section.classList.add('active');
  }

  document.querySelectorAll('.step-item').forEach(el => {
    el.classList.toggle('active', el.dataset.step === name);
  });
}

function appendLog(line) {
  logBox.textContent += `${line}\n`;
  logBox.scrollTop = logBox.scrollHeight;
}

function startLogSocket(jobId) {
  if (ws) ws.close();
  const wsUrl = API_BASE.replace('http', 'ws') + `/ws/jobs/${jobId}/logs`;
  ws = new WebSocket(wsUrl);
  ws.onmessage = evt => {
    try {
      const data = JSON.parse(evt.data);
      (data.logs || []).forEach(appendLog);
    } catch {
      // ignore malformed frames
    }
  };
}

document.getElementById('generateBtn').addEventListener('click', async () => {
  const prompt = promptEl.value.trim();
  if (!prompt) {
    alert('Please enter a prompt.');
    return;
  }

  const payload = {
    prompt,
    minutes: Number(minutesEl.value),
    scene_seconds: Number(sceneSecondsEl.value),
    voice: voiceEl.value.trim(),
    model: modelEl.value.trim(),
    style: styleEl.value,
    language: languageEl.value,
    transition_style: transitionStyleEl.value,
    steps: Number(stepsEl.value || 20),
    seed: seedEl.value ? Number(seedEl.value) : null,
    clear_cache: clearCacheEl.checked,
    auto_scene_duration: autoSceneDurationEl.checked,
    profile: profileEl.checked,
  };

  const res = await api('/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    alert(`Failed to start: ${await res.text()}`);
    return;
  }

  const { job_id } = await res.json();
  currentJobId = job_id;
  logBox.textContent = '';
  startLogSocket(job_id);
  startPolling();
});

function setPhaseProgress(job) {
  const phase = job.phase || 'script';
  Object.keys(phaseBars).forEach(key => {
    if (key === phase) {
      phaseBars[key].value = job.progress || 0;
    } else if ((job.progress || 0) >= 100 || ['images', 'audio', 'render'].includes(phase) && key === 'script' || ['audio', 'render'].includes(phase) && key === 'images' || phase === 'render' && key === 'audio') {
      phaseBars[key].value = 100;
    }
  });
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollStatus, 3000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollStatus() {
  if (!currentJobId) return;

  const res = await api(`/status/${currentJobId}`);
  const job = await res.json();
  progressBar.value = job.progress || 0;
  renderStatus.textContent = job.message || '';
  setPhaseProgress(job);

  if (job.status === 'failed') {
    stopPolling();
    alert(`Job failed: ${job.message}`);
    return;
  }

  if (job.status === 'awaiting_approval') {
    stopPolling();
    if (job.phase === 'script') await enterScriptReview();
    if (job.phase === 'images') await enterImagesReview();
    if (job.phase === 'audio') await enterAudioReview();
  }

  if (job.status === 'generating' && job.phase === 'render') {
    showStep('render');
    const previewRes = await api(`/jobs/${currentJobId}/preview`);
    if (previewRes.ok) {
      previewVideo.src = `${API_BASE}/jobs/${currentJobId}/preview?t=${Date.now()}`;
      previewVideo.classList.remove('hidden');
    }
  }

  if (job.status === 'completed') {
    stopPolling();
    showStep('render');
    progressBar.value = 100;
    downloadLink.href = `${API_BASE}${job.download_url}`;
    downloadLink.classList.remove('hidden');
  }
}

async function enterScriptReview() {
  const data = await (await api(`/jobs/${currentJobId}/script`)).json();
  const container = document.getElementById('scriptScenes');
  container.innerHTML = '';

  (data.scenes || []).forEach(scene => {
    const card = document.createElement('div');
    card.className = 'scene-card';
    card.innerHTML = `
      <div class="scene-number">Scene ${scene.index}</div>
      <label>Narration</label>
      <textarea class="scene-narration" rows="3" data-index="${scene.index}">${scene.narration}</textarea>
      <label>Visual description</label>
      <textarea class="scene-visual" rows="2" data-index="${scene.index}">${scene.visual_description}</textarea>
    `;
    container.appendChild(card);
  });

  showStep('script');
}

document.getElementById('approveScriptBtn').addEventListener('click', async () => {
  const scenes = [];
  document.querySelectorAll('.scene-card').forEach(card => {
    scenes.push({
      index: Number(card.querySelector('.scene-narration').dataset.index),
      narration: card.querySelector('.scene-narration').value.trim(),
      visual_description: card.querySelector('.scene-visual').value.trim(),
    });
  });

  await api(`/jobs/${currentJobId}/script/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenes }),
  });

  startPolling();
});

async function enterImagesReview() {
  const data = await (await api(`/jobs/${currentJobId}/images`)).json();
  const grid = document.getElementById('imageGrid');
  const thumbGrid = document.getElementById('thumbnailGrid');
  grid.innerHTML = '';
  thumbGrid.innerHTML = '';

  (data.thumbnails || []).forEach(url => {
    const img = document.createElement('img');
    img.className = 'thumbnail-choice';
    img.src = `${API_BASE}${url}`;
    thumbGrid.appendChild(img);
  });

  (data.images || []).forEach(img => {
    const card = document.createElement('div');
    card.className = 'review-card';
    card.innerHTML = `
      <div class="review-scene-label">Scene ${img.scene}</div>
      <img src="${API_BASE}${img.url}?t=${Date.now()}" alt="Scene ${img.scene}" class="review-img" />
      <p class="review-narration">${img.narration}</p>
    `;
    grid.appendChild(card);
  });

  showStep('images');
}

document.getElementById('approveImagesBtn').addEventListener('click', async () => {
  await api(`/jobs/${currentJobId}/images/approve`, { method: 'POST' });
  startPolling();
});

async function enterAudioReview() {
  const data = await (await api(`/jobs/${currentJobId}/audio`)).json();
  const list = document.getElementById('audioList');
  list.innerHTML = '';

  (data.audio || []).forEach(clip => {
    const item = document.createElement('div');
    item.className = 'audio-item';
    item.innerHTML = `
      <div class="audio-scene-label">Scene ${clip.scene}</div>
      <p class="review-narration">${clip.narration}</p>
      <audio controls src="${API_BASE}${clip.url}"></audio>
    `;
    list.appendChild(item);
  });

  showStep('audio');
}

document.getElementById('approveAudioBtn').addEventListener('click', async () => {
  await api(`/jobs/${currentJobId}/audio/approve`, { method: 'POST' });
  showStep('render');
  startPolling();
});
