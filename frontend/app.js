const API_BASE = localStorage.getItem('apiBase') || 'http://localhost:8000';

const promptEl = document.getElementById('prompt');
const minutesEl = document.getElementById('minutes');
const sceneSecondsEl = document.getElementById('sceneSeconds');
const voiceEl = document.getElementById('voice');
const generateBtn = document.getElementById('generateBtn');
const statusText = document.getElementById('statusText');
const progressBar = document.getElementById('progressBar');
const downloadLink = document.getElementById('downloadLink');

// ── Photo upload ──────────────────────────────────────────────────────────────
const dropArea    = document.getElementById('dropArea');
const fileInput   = document.getElementById('fileInput');
const browseBtn   = document.getElementById('browseBtn');
const uploadStatus = document.getElementById('uploadStatus');
const uploadedGrid = document.getElementById('uploadedGrid');
const uploadCount  = document.getElementById('uploadCount');

browseBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => uploadFiles(fileInput.files));

dropArea.addEventListener('dragover', (e) => { e.preventDefault(); dropArea.classList.add('drag-over'); });
dropArea.addEventListener('dragleave', () => dropArea.classList.remove('drag-over'));
dropArea.addEventListener('drop', (e) => {
  e.preventDefault();
  dropArea.classList.remove('drag-over');
  uploadFiles(e.dataTransfer.files);
});

async function uploadFiles(files) {
  if (!files || files.length === 0) return;
  showUploadStatus(`Uploading ${files.length} file(s)...`, 'info');

  let uploaded = 0;
  let failed = 0;

  for (const file of files) {
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form });
      if (res.ok) {
        uploaded++;
      } else {
        const err = await res.json();
        failed++;
        console.warn('Upload failed:', err.error);
      }
    } catch {
      failed++;
    }
  }

  const msg = failed === 0
    ? `${uploaded} photo(s) uploaded successfully.`
    : `${uploaded} uploaded, ${failed} failed.`;
  showUploadStatus(msg, failed === 0 ? 'success' : 'error');
  await refreshUploadedGrid();
}

async function refreshUploadedGrid() {
  try {
    const res = await fetch(`${API_BASE}/uploads`);
    const data = await res.json();
    const uploads = data.uploads || [];

    uploadCount.textContent = `${uploads.length} uploaded`;
    uploadedGrid.innerHTML = '';

    uploads.forEach((photo) => {
      const card = document.createElement('div');
      card.className = 'photo-card';
      card.innerHTML = `
        <img src="${API_BASE}${photo.url}" alt="${photo.filename}" />
        <div class="photo-card-name">${photo.filename}</div>
        <button class="photo-delete-btn" data-filename="${photo.filename}" title="Remove">&#10005;</button>
      `;
      card.querySelector('.photo-delete-btn').addEventListener('click', async (e) => {
        const fn = e.currentTarget.dataset.filename;
        await fetch(`${API_BASE}/uploads/${fn}`, { method: 'DELETE' });
        await refreshUploadedGrid();
      });
      uploadedGrid.appendChild(card);
    });
  } catch {
    // backend may not be running yet
  }
}

function showUploadStatus(msg, type) {
  uploadStatus.textContent = msg;
  uploadStatus.className = `upload-status upload-status--${type}`;
}

// Load existing uploads on page load
refreshUploadedGrid();

// ── Video generation ──────────────────────────────────────────────────────────
async function startGeneration() {
  const prompt = promptEl.value.trim();
  if (!prompt) {
    statusText.textContent = 'Status: please enter a prompt';
    return;
  }

  generateBtn.disabled = true;
  downloadLink.classList.add('hidden');
  statusText.textContent = 'Status: submitting job...';
  progressBar.value = 1;

  const response = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      minutes: Number(minutesEl.value),
      scene_seconds: Number(sceneSecondsEl.value),
      voice: voiceEl.value,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    statusText.textContent = `Status: failed to start (${text})`;
    generateBtn.disabled = false;
    return;
  }

  const data = await response.json();
  pollStatus(data.job_id);
}

async function pollStatus(jobId) {
  const timer = setInterval(async () => {
    const response = await fetch(`${API_BASE}/status/${jobId}`);
    if (!response.ok) {
      statusText.textContent = 'Status: failed to read job status';
      clearInterval(timer);
      generateBtn.disabled = false;
      return;
    }

    const job = await response.json();
    statusText.textContent = `Status: ${job.message}`;
    progressBar.value = Number(job.progress || 0);

    if (job.status === 'completed') {
      clearInterval(timer);
      statusText.textContent = 'Status: completed';
      downloadLink.href = `${API_BASE}${job.download_url}`;
      downloadLink.classList.remove('hidden');
      generateBtn.disabled = false;
    }
  }, 4000);
}

generateBtn.addEventListener('click', startGeneration);
