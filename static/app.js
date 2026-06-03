const form = document.getElementById('summarize-form');
const submitBtn = document.getElementById('submit-btn');
const inputFile = document.getElementById('input-file');
const outputPanel = document.getElementById('output-panel');
const comparePanel = document.getElementById('compare-panel');
const compareGrid = document.getElementById('compare-grid');
const statusPanel = document.getElementById('status-panel');
const statusText = document.getElementById('status-text');
const statusPercent = document.getElementById('status-percent');
const progressFill = document.getElementById('progress-fill');
const errorPanel = document.getElementById('error-panel');
const summaryText = document.getElementById('summary-text');
const errorText = document.getElementById('error-text');
const engineBadge = document.getElementById('engine-badge');
const compareLengthsCheckbox = document.getElementById('compare-lengths');
const copyBtn = document.getElementById('copy-btn');
const downloadBtn = document.getElementById('download-btn');

function hidePanels() {
  errorPanel.hidden = true;
  outputPanel.hidden = true;
  comparePanel.hidden = true;
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? 'Generating...' : 'Generate Summary';
}

function setStatus(message, progress) {
  statusPanel.hidden = false;
  statusText.textContent = message;
  const safeProgress = Math.max(0, Math.min(100, Number(progress || 0)));
  statusPercent.textContent = `${Math.round(safeProgress)}%`;
  progressFill.style.width = `${safeProgress}%`;
}

function showError(message) {
  errorText.textContent = message || 'Failed to summarize text.';
  errorPanel.hidden = false;
  outputPanel.hidden = true;
  comparePanel.hidden = true;
}

function showResult(summary, engine) {
  summaryText.textContent = summary;
  engineBadge.textContent = engine;
  outputPanel.hidden = false;
  comparePanel.hidden = true;
  errorPanel.hidden = true;
}

function renderCompare(compareResult) {
  compareGrid.innerHTML = '';
  Object.entries(compareResult).forEach(([length, result]) => {
    const card = document.createElement('article');
    card.className = 'compare-card';
    card.innerHTML = `
      <h3>${length}</h3>
      <p class="compare-engine">${result.engine}</p>
      <p class="compare-summary">${result.summary}</p>
    `;
    compareGrid.appendChild(card);
  });

  comparePanel.hidden = false;
  outputPanel.hidden = true;
  errorPanel.hidden = true;
}

async function extractTextFromFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('/extract-text', {
    method: 'POST',
    body: formData,
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || 'Unable to extract text from file.');
  }

  return data.text;
}

async function waitForJob(jobId) {
  while (true) {
    const response = await fetch(`/summarize-job/${jobId}`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Failed to fetch job status.');
    }

    setStatus(data.message || data.status || 'Processing...', data.progress || 0);

    if (data.status === 'completed') {
      return data.result;
    }

    if (data.status === 'failed') {
      throw new Error(data.error || 'Summarization job failed.');
    }

    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

function getVisibleSummaryText() {
  if (!outputPanel.hidden) {
    return summaryText.textContent.trim();
  }

  if (!comparePanel.hidden) {
    const entries = [];
    compareGrid.querySelectorAll('.compare-card').forEach((card) => {
      const title = card.querySelector('h3')?.textContent || 'summary';
      const body = card.querySelector('.compare-summary')?.textContent || '';
      entries.push(`${title.toUpperCase()}\n${body}`);
    });
    return entries.join('\n\n');
  }

  return '';
}

copyBtn.addEventListener('click', async () => {
  const text = getVisibleSummaryText();
  if (!text) {
    showError('No summary available to copy yet.');
    return;
  }

  await navigator.clipboard.writeText(text);
});

downloadBtn.addEventListener('click', () => {
  const text = getVisibleSummaryText();
  if (!text) {
    showError('No summary available to download yet.');
    return;
  }

  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `summary-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  hidePanels();

  let text = document.getElementById('input-text').value;
  const file = inputFile.files?.[0];

  if (file) {
    try {
      setStatus('Extracting text from uploaded file...', 8);
      text = await extractTextFromFile(file);
      document.getElementById('input-text').value = text;
    } catch (error) {
      showError(error.message);
      return;
    }
  }

  const payload = {
    text,
    domain: document.getElementById('domain').value,
    length: document.getElementById('length').value,
    format: document.getElementById('format').value,
    compare_lengths: compareLengthsCheckbox.checked,
  };

  if (!payload.text || payload.text.trim().length < 30) {
    showError('Please provide at least 30 characters of text.');
    return;
  }

  setLoading(true);
  setStatus('Submitting job...', 10);

  try {
    const response = await fetch('/summarize-job', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Unable to generate summary.');
    }

    const result = await waitForJob(data.job_id);
    setStatus('Completed', 100);

    if (result.compare) {
      renderCompare(result.compare);
    } else {
      showResult(result.summary, result.engine);
    }
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
});
