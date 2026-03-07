const API_BASE = localStorage.getItem('apiBase') || 'http://localhost:8000';

let currentJobId = null;
let pollTimer = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const promptEl       = document.getElementById('prompt');
const minutesEl      = document.getElementById('minutes');
const sceneSecondsEl = document.getElementById('sceneSeconds');
const voiceEl        = document.getElementById('voice');
const generateBtn    = document.getElementById('generateBtn');
const progressBar    = document.getElementById('progressBar');
const downloadLink   = document.getElementById('downloadLink');

const dropArea     = document.getElementById('dropArea');
const fileInput    = document.getElementById('fileInput');
const browseBtn    = document.getElementById('browseBtn');
const uploadStatus = document.getElementById('uploadStatus');
const uploadedGrid = document.getElementById('uploadedGrid');
const uploadCount  = document.getElementById('uploadCount');

// ── Step navigation ───────────────────────────────────────────────────────────
function showStep(name) {
  document.querySelectorAll('.phase').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.phase').forEach(el => el.classList.remove('active'));
  const section = document.getElementById(`step-${name}`);
  if (section) { section.classList.remove('hidden'); section.classList.add('active'); }

  document.querySelectorAll('.step-item').forEach(el => {
    el.classList.toggle('active', el.dataset.step === name);
    el.classList.toggle('done',
      ['setup','script','images','audio','render'].indexOf(el.dataset.step) <
      ['setup','script','images','audio','render'].indexOf(name));
  });
}

// ── Photo upload ──────────────────────────────────────────────────────────────
browseBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => uploadFiles(fileInput.files));
dropArea.addEventListener('dragover', e => { e.preventDefault(); dropArea.classList.add('drag-over'); });
dropArea.addEventListener('dragleave', () => dropArea.classList.remove('drag-over'));
dropArea.addEventListener('drop', e => {
  e.preventDefault(); dropArea.classList.remove('drag-over');
  uploadFiles(e.dataTransfer.files);
});

async function uploadFiles(files) {
  if (!files || !files.length) return;
  showUploadStatus(`Uploading ${files.length} file(s)…`, 'info');
  let ok = 0, fail = 0;
  for (const file of files) {
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form });
      res.ok ? ok++ : fail++;
    } catch { fail++; }
  }
  showUploadStatus(fail === 0 ? `${ok} photo(s) uploaded.` : `${ok} uploaded, ${fail} failed.`,
    fail === 0 ? 'success' : 'error');
  await refreshUploadedGrid();
}

async function refreshUploadedGrid() {
  try {
    const data = await (await fetch(`${API_BASE}/uploads`)).json();
    const uploads = data.uploads || [];
    uploadCount.textContent = `${uploads.length} uploaded`;
    uploadedGrid.innerHTML = '';
    uploads.forEach(photo => {
      const card = document.createElement('div');
      card.className = 'photo-card';
      card.innerHTML = `
        <img src="${API_BASE}${photo.url}" alt="${photo.filename}" />
        <div class="photo-card-name">${photo.filename}</div>
        <button class="photo-delete-btn" data-filename="${photo.filename}" title="Remove">&#10005;</button>
      `;
      card.querySelector('.photo-delete-btn').addEventListener('click', async e => {
        await fetch(`${API_BASE}/uploads/${e.currentTarget.dataset.filename}`, { method: 'DELETE' });
        await refreshUploadedGrid();
      });
      uploadedGrid.appendChild(card);
    });
  } catch { /* backend may not be running */ }
}

function showUploadStatus(msg, type) {
  uploadStatus.textContent = msg;
  uploadStatus.className = `upload-status upload-status--${type}`;
}

refreshUploadedGrid();

// ── Step 1 → Generate script ──────────────────────────────────────────────────
generateBtn.addEventListener('click', async () => {
  const prompt = promptEl.value.trim();
  if (!prompt) { alert('Please enter a prompt.'); return; }

  generateBtn.disabled = true;
  generateBtn.textContent = 'Generating script…';

  const res = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      minutes: Number(minutesEl.value),
      scene_seconds: Number(sceneSecondsEl.value),
      voice: voiceEl.value,
    }),
  });

  if (!res.ok) {
    alert(`Failed to start: ${await res.text()}`);
    generateBtn.disabled = false;
    generateBtn.textContent = 'Generate Script';
    return;
  }

  const { job_id } = await res.json();
  currentJobId = job_id;
  startPolling();
});

// ── Polling ───────────────────────────────────────────────────────────────────
function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollStatus, 3000);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function pollStatus() {
  if (!currentJobId) return;
  try {
    const job = await (await fetch(`${API_BASE}/status/${currentJobId}`)).json();
    progressBar.value = job.progress || 0;

    if (job.status === 'failed') {
      stopPolling();
      alert(`Job failed: ${job.message}`);
      generateBtn.disabled = false;
      generateBtn.textContent = 'Generate Script';
      showStep('setup');
      return;
    }

    if (job.status === 'awaiting_approval') {
      stopPolling();
      if (job.phase === 'script')  await enterScriptReview();
      if (job.phase === 'images')  await enterImagesReview();
      if (job.phase === 'audio')   await enterAudioReview();
    }

    if (job.status === 'completed') {
      stopPolling();
      showStep('render');
      document.getElementById('renderStatus').textContent = 'Your video is ready!';
      progressBar.value = 100;
      downloadLink.href = `${API_BASE}${job.download_url}`;
      downloadLink.classList.remove('hidden');
    }

    // Keep render step updated while generating
    if (job.status === 'generating' && job.phase === 'render') {
      showStep('render');
      document.getElementById('renderStatus').textContent = job.message;
    }
  } catch { /* ignore transient errors */ }
}

// ── Step 2: Script review ─────────────────────────────────────────────────────
async function enterScriptReview() {
  const data = await (await fetch(`${API_BASE}/jobs/${currentJobId}/script`)).json();
  const container = document.getElementById('scriptScenes');
  container.innerHTML = '';

  data.scenes.forEach((scene, i) => {
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

  document.getElementById('scriptStatus').textContent = 'Approved! Starting image generation…';
  document.getElementById('approveScriptBtn').disabled = true;

  await fetch(`${API_BASE}/jobs/${currentJobId}/script/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenes }),
  });
  startPolling();
});

document.getElementById('ownScriptBtn').addEventListener('click', () => {
  document.getElementById('customScriptArea').classList.toggle('hidden');
});

document.getElementById('submitCustomScriptBtn').addEventListener('click', async () => {
  let scenes;
  try {
    const raw = JSON.parse(document.getElementById('customScript').value);
    scenes = raw.map((s, i) => ({
      index: s.index || i + 1,
      narration: s.narration || '',
      visual_description: s.visual_description || '',
    }));
  } catch {
    alert('Invalid JSON — please check your script format.');
    return;
  }

  document.getElementById('scriptStatus').textContent = 'Custom script submitted! Starting image generation…';
  document.getElementById('submitCustomScriptBtn').disabled = true;

  await fetch(`${API_BASE}/jobs/${currentJobId}/script/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenes }),
  });
  startPolling();
});

// ── Step 3: Image review ──────────────────────────────────────────────────────
async function enterImagesReview() {
  const data = await (await fetch(`${API_BASE}/jobs/${currentJobId}/images`)).json();
  const grid = document.getElementById('imageGrid');
  grid.innerHTML = '';

  data.images.forEach(img => {
    const card = document.createElement('div');
    card.className = 'review-card';
    card.id = `img-card-${img.scene}`;
    card.innerHTML = `
      <div class="review-scene-label">Scene ${img.scene}</div>
      <img src="${API_BASE}${img.url}?t=${Date.now()}" alt="Scene ${img.scene}" class="review-img" />
      <p class="review-narration">${img.narration}</p>
      <label class="btn-replace">
        Replace Image
        <input type="file" accept=".jpg,.jpeg,.png,.webp" hidden data-scene="${img.scene}" />
      </label>
    `;
    card.querySelector('input[type=file]').addEventListener('change', async e => {
      const n = e.target.dataset.scene;
      const form = new FormData();
      form.append('file', e.target.files[0]);
      document.getElementById('imagesStatus').textContent = `Uploading replacement for scene ${n}…`;
      const res = await fetch(`${API_BASE}/jobs/${currentJobId}/images/${n}/replace`, { method: 'POST', body: form });
      if (res.ok) {
        const imgEl = document.querySelector(`#img-card-${n} .review-img`);
        imgEl.src = `${API_BASE}/jobs/${currentJobId}/images/${n}?t=${Date.now()}`;
        document.getElementById('imagesStatus').textContent = `Scene ${n} image replaced.`;
      }
    });
    grid.appendChild(card);
  });

  showStep('images');
}

document.getElementById('approveImagesBtn').addEventListener('click', async () => {
  document.getElementById('imagesStatus').textContent = 'Approved! Starting audio generation…';
  document.getElementById('approveImagesBtn').disabled = true;
  await fetch(`${API_BASE}/jobs/${currentJobId}/images/approve`, { method: 'POST' });
  startPolling();
});

// ── Step 4: Audio review ──────────────────────────────────────────────────────
async function enterAudioReview() {
  const data = await (await fetch(`${API_BASE}/jobs/${currentJobId}/audio`)).json();
  const list = document.getElementById('audioList');
  list.innerHTML = '';

  data.audio.forEach(clip => {
    const item = document.createElement('div');
    item.className = 'audio-item';
    item.id = `audio-item-${clip.scene}`;
    item.innerHTML = `
      <div class="audio-scene-label">Scene ${clip.scene}</div>
      <p class="review-narration">${clip.narration}</p>
      <audio controls src="${API_BASE}${clip.url}"></audio>
      <label class="btn-replace">
        Replace Audio
        <input type="file" accept=".wav,.mp3,.m4a,.ogg" hidden data-scene="${clip.scene}" />
      </label>
    `;
    item.querySelector('input[type=file]').addEventListener('change', async e => {
      const n = e.target.dataset.scene;
      const form = new FormData();
      form.append('file', e.target.files[0]);
      document.getElementById('audioStatus').textContent = `Uploading replacement for scene ${n}…`;
      const res = await fetch(`${API_BASE}/jobs/${currentJobId}/audio/${n}/replace`, { method: 'POST', body: form });
      if (res.ok) {
        const audioEl = document.querySelector(`#audio-item-${n} audio`);
        audioEl.src = `${API_BASE}/jobs/${currentJobId}/audio/${n}?t=${Date.now()}`;
        document.getElementById('audioStatus').textContent = `Scene ${n} audio replaced.`;
      }
    });
    list.appendChild(item);
  });

  showStep('audio');
}

document.getElementById('approveAudioBtn').addEventListener('click', async () => {
  document.getElementById('audioStatus').textContent = 'Approved! Rendering final video…';
  document.getElementById('approveAudioBtn').disabled = true;
  await fetch(`${API_BASE}/jobs/${currentJobId}/audio/approve`, { method: 'POST' });
  showStep('render');
  document.getElementById('renderStatus').textContent = 'Rendering…';
  startPolling();
});
