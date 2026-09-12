const $ = id => document.getElementById(id);

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

function setStatus(message, busy = false, error = false) {
  const status = $('status');
  status.textContent = message;
  status.classList.toggle('busy', busy);
  status.classList.toggle('error', error);
  document.querySelector('button[type="submit"]').disabled = busy;
}

async function startAnalysis(event) {
  event.preventDefault();
  const accession = $('accession').value.trim();
  if (!accession) {
    setStatus('Enter a GEO accession.', false, true);
    return;
  }
  setStatus('Preparing analysis...', true);
  window.location.href = `/analysis/new?accession=${encodeURIComponent(accession)}`;
}

async function loadHistory() {
  try {
    const rows = await request('/api/history');
    $('history').innerHTML = rows.length
      ? rows.map(row => `<a class="history-item" href="/analysis/${row.id}"><strong>${row.config.accession}</strong><span>${row.config.genes.join(', ')} · ${row.config.group_column}</span><small>${new Date(row.created_at).toLocaleString()}</small></a>`).join('')
      : '<p>No previous analyses.</p>';
  } catch (error) {
    $('history').textContent = error.message;
  }
}

$('start-form').addEventListener('submit', startAnalysis);
loadHistory();
