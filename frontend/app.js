const API_BASE = localStorage.getItem('apiBase') || 'http://localhost:8000';

const promptEl = document.getElementById('prompt');
const minutesEl = document.getElementById('minutes');
const sceneSecondsEl = document.getElementById('sceneSeconds');
const generateBtn = document.getElementById('generateBtn');
const statusText = document.getElementById('statusText');
const progressBar = document.getElementById('progressBar');
const downloadLink = document.getElementById('downloadLink');

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
