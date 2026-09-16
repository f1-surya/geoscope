const $ = id => document.getElementById(id);

async function request(url, options) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch (_) { data = {}; }
  if (!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
}

function formatBytes(bytes) {
  if (!bytes || bytes < 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return `${value.toFixed(index === 0 || value >= 10 ? 0 : 1)} ${units[index]}`;
}

function fact(label, value) {
  if (value === null || value === undefined || value === '') return '';
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd></div>`;
}

function render(data) {
  const rows = data.datasets || [];
  $('storage-total').textContent = rows.length
    ? `${rows.length} dataset${rows.length === 1 ? '' : 's'} using ${formatBytes(data.total_bytes)}`
    : 'No datasets stored on disk.';
  if (!rows.length) {
    $('dataset-storage').innerHTML = '<p class="storage-empty">Load a dataset from a new analysis and it will appear here.</p>';
    return;
  }
  $('dataset-storage').innerHTML = rows.map(row => `
    <div class="storage-item">
      <div class="storage-head">
        <div class="storage-ident">
          <strong>${escapeHtml(row.accession)}</strong>
          <span class="storage-title">${escapeHtml(row.title || 'Untitled dataset')}</span>
        </div>
        <span class="storage-badge storage-badge-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span>
      </div>
      <dl class="storage-meta">
        ${fact('Organism', row.organism)}
        ${fact('Samples', row.sample_count !== null && row.sample_count !== undefined ? Number(row.sample_count).toLocaleString() : null)}
        ${fact('Probes', row.probe_count !== null && row.probe_count !== undefined ? Number(row.probe_count).toLocaleString() : null)}
        ${fact('Platforms', (row.platform_ids || []).join(', '))}
        ${fact('Analyses', row.analyses_count)}
        ${fact('Cache', formatBytes(row.dataset_size))}
        ${fact('Raw download', formatBytes(row.raw_size))}
        <div><dt>Total</dt><dd>${formatBytes(row.total_size)}</dd></div>
      </dl>
      <button type="button" class="danger" data-accession="${escapeHtml(row.accession)}">Delete dataset</button>
    </div>
  `).join('');
  document.querySelectorAll('[data-accession]').forEach(button => button.onclick = () => remove(button));
}

async function remove(button) {
  const accession = button.dataset.accession;
  if (!window.confirm(`Delete ${accession}? This removes its cached files, raw download, and saved analyses.`)) return;
  const status = $('storage-status');
  button.disabled = true;
  status.classList.remove('error');
  status.textContent = `Deleting ${accession}...`;
  try {
    const result = await request(`/api/datasets/${encodeURIComponent(accession)}`, {method: 'DELETE'});
    status.textContent = `Deleted ${accession}, freed ${formatBytes(result.freed_bytes)}.`;
    await load();
  } catch (error) {
    status.classList.add('error');
    status.textContent = error.message;
    button.disabled = false;
  }
}

async function load() {
  try {
    render(await request('/api/datasets'));
  } catch (error) {
    $('storage-total').textContent = '';
    $('dataset-storage').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

load();
