const BACKEND_URL = 'http://127.0.0.1:5000';

const videoForm = document.getElementById('videoForm');
const promptInput = document.getElementById('prompt');
const minutesSelect = document.getElementById('minutes');
const generateBtn = document.getElementById('generateBtn');

const progressSection = document.getElementById('progressSection');
const statusLabel = document.getElementById('statusLabel');
const progressValue = document.getElementById('progressValue');
const progressFill = document.getElementById('progressFill');
const spinner = document.getElementById('spinner');

const downloadSection = document.getElementById('downloadSection');
const downloadBtn = document.getElementById('downloadBtn');
const thumbnailPreview = document.getElementById('thumbnailPreview');

const errorSection = document.getElementById('errorSection');
const errorMessage = document.getElementById('errorMessage');

let pollTimer = null;

function setProgress(progress, message) {
  const safeProgress = Math.max(0, Math.min(100, Number(progress) || 0));
  progressFill.style.width = `${safeProgress}%`;
  progressValue.textContent = `${safeProgress}%`;
  statusLabel.textContent = message || 'Working...';
}

function showError(message) {
  errorMessage.textContent = message || 'Unknown error';
  errorSection.classList.remove('hidden');
}

function resetUIForRun() {
  errorSection.classList.add('hidden');
  downloadSection.classList.add('hidden');
  thumbnailPreview.classList.add('hidden');
  thumbnailPreview.removeAttribute('src');

  progressSection.classList.remove('hidden');
  spinner.classList.remove('hidden');
  setProgress(0, 'Starting job...');

  generateBtn.disabled = true;
}

function finishRun() {
  generateBtn.disabled = false;
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollJob(jobId) {
  stopPolling();

  pollTimer = setInterval(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/jobs/${jobId}`);
      if (!response.ok) {
        throw new Error(`Status request failed (${response.status})`);
      }

      const job = await response.json();
      setProgress(job.progress, job.message || `Status: ${job.status}`);

      if (job.status === 'complete') {
        stopPolling();
        progressSection.classList.add('hidden');
        spinner.classList.add('hidden');

        downloadBtn.href = `${BACKEND_URL}/download/${jobId}`;
        if (job.thumbnail_url) {
          thumbnailPreview.src = `${BACKEND_URL}${job.thumbnail_url}`;
          thumbnailPreview.classList.remove('hidden');
        }
        downloadSection.classList.remove('hidden');
        finishRun();
      }

      if (job.status === 'failed') {
        stopPolling();
        spinner.classList.add('hidden');
        showError(job.error || job.message || 'Video generation failed.');
        finishRun();
      }
    } catch (error) {
      stopPolling();
      spinner.classList.add('hidden');
      showError(error.message);
      finishRun();
    }
  }, 2000);
}

videoForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const prompt = promptInput.value.trim();
  const minutes = Number(minutesSelect.value);

  if (!prompt) {
    showError('Please enter a prompt before generating.');
    return;
  }

  resetUIForRun();

  try {
    const response = await fetch(`${BACKEND_URL}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        minutes,
        scene_seconds: 8,
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Could not create job: ${text}`);
    }

    const data = await response.json();
    if (!data.job_id) {
      throw new Error('Backend response missing job_id.');
    }

    setProgress(2, 'Job queued...');
    pollJob(data.job_id);
  } catch (error) {
    progressSection.classList.add('hidden');
    spinner.classList.add('hidden');
    showError(error.message);
    finishRun();
  }
});
