const form = document.getElementById('summarize-form');
const submitBtn = document.getElementById('submit-btn');
const outputPanel = document.getElementById('output-panel');
const errorPanel = document.getElementById('error-panel');
const summaryText = document.getElementById('summary-text');
const errorText = document.getElementById('error-text');
const engineBadge = document.getElementById('engine-badge');

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? 'Generating...' : 'Generate Summary';
}

function showError(message) {
  errorText.textContent = message || 'Failed to summarize text.';
  errorPanel.hidden = false;
  outputPanel.hidden = true;
}

function showResult(summary, engine) {
  summaryText.textContent = summary;
  engineBadge.textContent = engine;
  outputPanel.hidden = false;
  errorPanel.hidden = true;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = {
    text: document.getElementById('input-text').value,
    domain: document.getElementById('domain').value,
    length: document.getElementById('length').value,
    format: document.getElementById('format').value,
  };

  if (!payload.text || payload.text.trim().length < 30) {
    showError('Please provide at least 30 characters of text.');
    return;
  }

  setLoading(true);

  try {
    const response = await fetch('/summarize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Unable to generate summary.');
    }

    showResult(data.summary, data.engine);
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
});
