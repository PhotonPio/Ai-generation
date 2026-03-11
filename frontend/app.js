const API_BASE = (() => {
  const stored = localStorage.getItem('apiBase');
  if (stored) return stored;
  if (window.location.port === '8000' || (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1')) {
    return window.location.origin;
  }
  return 'http://localhost:8000';
})();

let currentJobId = null;
let pollTimer = null;
let ws = null;

const els = {
  prompt: document.getElementById('prompt'), minutes: document.getElementById('minutes'), sceneSeconds: document.getElementById('sceneSeconds'),
  voice: document.getElementById('voice'), model: document.getElementById('model'), style: document.getElementById('style'), language: document.getElementById('language'),
  transitionStyle: document.getElementById('transitionStyle'), sceneMediaMode: document.getElementById('sceneMediaMode'), steps: document.getElementById('steps'), seed: document.getElementById('seed'),
  clearCache: document.getElementById('clearCache'), autoSceneDuration: document.getElementById('autoSceneDuration'), profile: document.getElementById('profile'),
  useUploadedImages: document.getElementById('useUploadedImages'), uploadDropzone: document.getElementById('uploadDropzone'), uploadInput: document.getElementById('uploadInput'),
  pickFilesBtn: document.getElementById('pickFilesBtn'), clearUploadsBtn: document.getElementById('clearUploadsBtn'), uploadGallery: document.getElementById('uploadGallery'),
  uploadProgress: document.getElementById('uploadProgress'), uploadMessage: document.getElementById('uploadMessage'), progressBar: document.getElementById('progressBar'),
  downloadLink: document.getElementById('downloadLink'), renderStatus: document.getElementById('renderStatus'), logBox: document.getElementById('logBox'), previewVideo: document.getElementById('previewVideo')
};

const phaseBars = { script: document.getElementById('phaseScript'), images: document.getElementById('phaseImages'), audio: document.getElementById('phaseAudio'), render: document.getElementById('phaseRender') };

function authHeader() {
  const user = localStorage.getItem('apiUser') || '';
  const pass = localStorage.getItem('apiPass') || '';
  if (!user && !pass) return {};
  return { Authorization: `Basic ${btoa(`${user}:${pass}`)}` };
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeader() };
  return fetch(`${API_BASE}${path}`, { ...options, headers });
}

function setUploadMessage(message, isError = false) {
  els.uploadMessage.textContent = message;
  els.uploadMessage.className = `upload-message ${isError ? 'error' : 'ok'}`;
}

async function checkBackendHealth() {
  const banner = document.getElementById('statusBanner');
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error('Health check failed');
    banner.textContent = '✅ Backend connected — ready to generate.';
    banner.className = 'status-banner ok';
    setTimeout(() => banner.classList.add('hidden'), 4000);
  } catch {
    banner.innerHTML = '❌ Backend not running. Run <code>./start.sh</code> (Mac/Linux) or <code>start.bat</code> (Windows).';
    banner.className = 'status-banner error';
  }
  banner.classList.remove('hidden');
}

async function refreshUploadGallery() {
  try {
    const res = await api('/uploads');
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    els.uploadGallery.innerHTML = '';
    for (const upload of (data.uploads || [])) {
      const card = document.createElement('div');
      card.className = 'upload-card';
      card.innerHTML = `<img src="${API_BASE}${upload.url}?t=${Date.now()}" alt="${upload.filename}" class="upload-thumb" />
      <div class="upload-meta"><span>${upload.filename}</span><button type="button" class="btn-secondary delete-upload" data-file="${upload.filename}">Delete</button></div>`;
      els.uploadGallery.appendChild(card);
    }
  } catch (err) {
    setUploadMessage(`Could not load uploads: ${err.message}`, true);
  }
}

async function uploadFiles(files) {
  if (!files || !files.length) return;
  els.uploadProgress.classList.remove('hidden');
  let uploaded = 0;
  for (const file of files) {
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await api('/upload', { method: 'POST', body: fd });
      if (!res.ok) throw new Error(await res.text());
      uploaded += 1;
      els.uploadProgress.value = Math.round((uploaded / files.length) * 100);
    } catch (err) {
      setUploadMessage(`Upload failed for ${file.name}: ${err.message}`, true);
    }
  }
  setUploadMessage(`Uploaded ${uploaded}/${files.length} file(s).`);
  await refreshUploadGallery();
  setTimeout(() => { els.uploadProgress.classList.add('hidden'); els.uploadProgress.value = 0; }, 700);
}

async function clearAllUploads() {
  try {
    const res = await api('/uploads');
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    await Promise.all((data.uploads || []).map(u => api(`/uploads/${encodeURIComponent(u.filename)}`, { method: 'DELETE' })));
    setUploadMessage('All uploads cleared.');
    await refreshUploadGallery();
  } catch (err) {
    setUploadMessage(`Could not clear uploads: ${err.message}`, true);
  }
}

function showStep(name) {
  document.querySelectorAll('.phase').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.phase').forEach(el => el.classList.remove('active'));
  document.getElementById(`step-${name}`)?.classList.remove('hidden');
  document.getElementById(`step-${name}`)?.classList.add('active');
  document.querySelectorAll('.step-item').forEach(el => el.classList.toggle('active', el.dataset.step === name));
}

function appendLog(line) { els.logBox.textContent += `${line}\n`; els.logBox.scrollTop = els.logBox.scrollHeight; }

function startLogSocket(jobId) {
  if (ws) ws.close();
  ws = new WebSocket(API_BASE.replace('http', 'ws') + `/ws/jobs/${jobId}/logs`);
  ws.onmessage = evt => { try { (JSON.parse(evt.data).logs || []).forEach(appendLog); } catch {} };
}

function setPhaseProgress(job) {
  const phase = job.phase || 'script';
  Object.keys(phaseBars).forEach(key => {
    if (key === phase) phaseBars[key].value = job.progress || 0;
    else if ((job.progress || 0) >= 100 || (['images', 'audio', 'render'].includes(phase) && key === 'script') || (['audio', 'render'].includes(phase) && key === 'images') || (phase === 'render' && key === 'audio')) phaseBars[key].value = 100;
  });
}

function startPolling() { stopPolling(); pollTimer = setInterval(pollStatus, 3000); }
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

async function pollStatus() {
  if (!currentJobId) return;
  try {
    const res = await api(`/status/${currentJobId}`);
    if (!res.ok) throw new Error(await res.text());
    const job = await res.json();
    els.progressBar.value = job.progress || 0;
    els.renderStatus.textContent = job.message || '';
    setPhaseProgress(job);
    if (job.status === 'failed') { stopPolling(); alert(`Job failed: ${job.message}`); return; }
    if (job.status === 'awaiting_approval') {
      stopPolling();
      if (job.phase === 'script') await enterScriptReview();
      if (job.phase === 'images') await enterImagesReview();
      if (job.phase === 'audio') await enterAudioReview();
    }
    if (job.status === 'generating' && job.phase === 'render') {
      showStep('render');
      const previewRes = await api(`/jobs/${currentJobId}/preview`);
      if (previewRes.ok) { els.previewVideo.src = `${API_BASE}/jobs/${currentJobId}/preview?t=${Date.now()}`; els.previewVideo.classList.remove('hidden'); }
    }
    if (job.status === 'completed') {
      stopPolling(); showStep('render'); els.progressBar.value = 100;
      els.downloadLink.href = `${API_BASE}${job.download_url}`; els.downloadLink.classList.remove('hidden');
    }
  } catch (err) { appendLog(`Status error: ${err.message}`); }
}

document.getElementById('saveAuthBtn').addEventListener('click', () => {
  localStorage.setItem('apiUser', document.getElementById('apiUser').value);
  localStorage.setItem('apiPass', document.getElementById('apiPass').value);
  setUploadMessage('Saved auth credentials.');
});

document.getElementById('generateBtn').addEventListener('click', async () => {
  const prompt = els.prompt.value.trim();
  if (!prompt) { alert('Please enter a prompt.'); return; }
  const payload = {
    prompt, minutes: Number(els.minutes.value), scene_seconds: Number(els.sceneSeconds.value), voice: els.voice.value.trim(), model: els.model.value.trim(),
    style: els.style.value, language: els.language.value, transition_style: els.transitionStyle.value, scene_media_mode: els.sceneMediaMode.value, steps: Number(els.steps.value || 20),
    seed: els.seed.value ? Number(els.seed.value) : null, clear_cache: els.clearCache.checked, auto_scene_duration: els.autoSceneDuration.checked,
    profile: els.profile.checked, use_uploaded_images: els.useUploadedImages.checked
  };
  try {
    const res = await api('/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!res.ok) throw new Error(await res.text());
    const { job_id } = await res.json();
    currentJobId = job_id; els.logBox.textContent = ''; startLogSocket(job_id); startPolling();
  } catch (err) { alert(`Failed to start: ${err.message}`); }
});

document.getElementById('approveScriptBtn').addEventListener('click', async () => {
  const scenes = [];
  document.querySelectorAll('.scene-card').forEach(card => scenes.push({
    index: Number(card.querySelector('.scene-narration').dataset.index),
    narration: card.querySelector('.scene-narration').value.trim(),
    visual_description: card.querySelector('.scene-visual').value.trim(),
  }));
  try {
    await api(`/jobs/${currentJobId}/script/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenes }) });
    startPolling();
  } catch (err) { alert(`Script approval failed: ${err.message}`); }
});

document.getElementById('approveImagesBtn').addEventListener('click', async () => { try { await api(`/jobs/${currentJobId}/images/approve`, { method: 'POST' }); startPolling(); } catch (err) { alert(err.message); } });
document.getElementById('approveAudioBtn').addEventListener('click', async () => { try { await api(`/jobs/${currentJobId}/audio/approve`, { method: 'POST' }); showStep('render'); startPolling(); } catch (err) { alert(err.message); } });

async function enterScriptReview() { const data = await (await api(`/jobs/${currentJobId}/script`)).json(); const c = document.getElementById('scriptScenes'); c.innerHTML = ''; (data.scenes || []).forEach(scene => { const card = document.createElement('div'); card.className = 'scene-card'; card.innerHTML = `<div class="scene-number">Scene ${scene.index}</div><label>Narration</label><textarea class="scene-narration" rows="3" data-index="${scene.index}">${scene.narration}</textarea><label>Visual description</label><textarea class="scene-visual" rows="2" data-index="${scene.index}">${scene.visual_description}</textarea>`; c.appendChild(card); }); showStep('script'); }
async function enterImagesReview() { const data = await (await api(`/jobs/${currentJobId}/images`)).json(); const grid = document.getElementById('imageGrid'); const thumb = document.getElementById('thumbnailGrid'); grid.innerHTML=''; thumb.innerHTML=''; (data.thumbnails || []).forEach(url => { const img = document.createElement('img'); img.className='thumbnail-choice'; img.src=`${API_BASE}${url}`; thumb.appendChild(img); }); (data.images || []).forEach(img => { const card = document.createElement('div'); card.className='review-card'; const badge = img.is_video ? '<span class="video-badge">Video clip</span>' : ''; card.innerHTML = `<div class="review-scene-label">Scene ${img.scene} ${badge}</div><img src="${API_BASE}${img.url}?t=${Date.now()}" alt="Scene ${img.scene}" class="review-img" /><p class="review-narration">${img.narration}</p>`; grid.appendChild(card); }); showStep('images'); }
async function enterAudioReview() { const data = await (await api(`/jobs/${currentJobId}/audio`)).json(); const list = document.getElementById('audioList'); list.innerHTML=''; (data.audio || []).forEach(clip => { const item = document.createElement('div'); item.className='audio-item'; item.innerHTML = `<div class="audio-scene-label">Scene ${clip.scene}</div><p class="review-narration">${clip.narration}</p><audio controls src="${API_BASE}${clip.url}"></audio>`; list.appendChild(item); }); showStep('audio'); }

els.pickFilesBtn.addEventListener('click', () => els.uploadInput.click());
els.uploadInput.addEventListener('change', async (e) => uploadFiles([...e.target.files]));
els.uploadDropzone.addEventListener('dragover', (e) => { e.preventDefault(); els.uploadDropzone.classList.add('dragover'); });
els.uploadDropzone.addEventListener('dragleave', () => els.uploadDropzone.classList.remove('dragover'));
els.uploadDropzone.addEventListener('drop', async (e) => { e.preventDefault(); els.uploadDropzone.classList.remove('dragover'); await uploadFiles([...e.dataTransfer.files]); });
els.clearUploadsBtn.addEventListener('click', async () => clearAllUploads());
els.uploadGallery.addEventListener('click', async (e) => {
  const btn = e.target.closest('.delete-upload');
  if (!btn) return;
  try { const res = await api(`/uploads/${encodeURIComponent(btn.dataset.file)}`, { method: 'DELETE' }); if (!res.ok) throw new Error(await res.text()); await refreshUploadGallery(); }
  catch (err) { setUploadMessage(`Delete failed: ${err.message}`, true); }
});

checkBackendHealth();
refreshUploadGallery();
