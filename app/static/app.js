const state = { accession: '', platform: 0, assignmentColumn: 'gene_assignment', valueColumn: null, samples: [], fields: [], metadata: [], genes: [], selectedGenes: [], group: '', palette: 'Scientific', analysisId: '', paletteOptions: [], paletteMap: {}, datasetInfo: {} };
const $ = id => document.getElementById(id);

function show(step) {
  document.querySelectorAll('.step').forEach(x => x.classList.toggle('active', x.id === step));
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('active', x.dataset.step === step));
}

function setBusy(message, busy) {
  const status = $('status');
  status.textContent = message;
  status.classList.remove('busy', 'error');
  $('load').disabled = busy;
  $('platform-load').disabled = busy;
}

function showError(error) {
  const status = $('status');
  status.textContent = error.message || String(error);
  status.classList.remove('busy');
  status.classList.add('error');
}

document.querySelectorAll('nav button').forEach(button => button.onclick = () => show(button.dataset.step));

async function request(url, options) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch (_) { data = {}; }
  if (!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

const progress = { timer: null, key: '', view: null, depth: 0, token: 0 };

function progressView(id) {
  const root = $(id);
  return {
    root,
    stage: root.querySelector('[data-role="stage"]'),
    percent: root.querySelector('[data-role="percent"]'),
    track: root.querySelector('.progress-track'),
    bar: root.querySelector('[data-role="bar"]'),
    detail: root.querySelector('[data-role="detail"]'),
    eta: root.querySelector('[data-role="eta"]'),
  };
}

function startProgress(key, id) {
  progress.key = key;
  progress.view = progressView(id);
  progress.view.root.hidden = false;
  progress.depth += 1;
  if (!progress.timer) {
    pollProgress();
    progress.timer = setInterval(pollProgress, 600);
  }
}

function stopProgress() {
  progress.depth = Math.max(0, progress.depth - 1);
  if (progress.depth > 0) return;
  const view = progress.view;
  const token = ++progress.token;
  clearInterval(progress.timer);
  progress.timer = null;
  setTimeout(() => {
    if (progress.token === token && !progress.timer && view) view.root.hidden = true;
  }, 1200);
}

async function pollProgress() {
  if (!progress.key || !progress.view) return;
  try {
    renderProgress(await request(`/api/datasets/progress/${encodeURIComponent(progress.key)}`));
  } catch (_) {}
}

function renderProgress(data) {
  const view = progress.view;
  if (!view) return;
  if (!data || !data.stage) {
    view.stage.textContent = 'Preparing…';
    view.track.classList.add('indeterminate');
    view.percent.textContent = '';
    view.detail.textContent = '';
    view.eta.textContent = '';
    return;
  }
  view.stage.textContent = data.message || data.stage;
  const fraction = typeof data.fraction === 'number' ? data.fraction : null;
  if (fraction === null) {
    view.track.classList.add('indeterminate');
    view.bar.style.width = '';
    view.percent.textContent = '';
  } else {
    view.track.classList.remove('indeterminate');
    const percent = Math.round(fraction * 100);
    view.bar.style.width = `${percent}%`;
    view.percent.textContent = `${percent}%`;
  }
  view.detail.textContent = data.detail || '';
  view.eta.textContent = formatEta(data, fraction);
  mergeDatasetInfo(data.info);
}

function hasValue(value) {
  if (value === null || value === undefined || value === '') return false;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function mergeDatasetInfo(info) {
  if (!info) return;
  Object.entries(info).forEach(([key, value]) => {
    if (hasValue(value)) state.datasetInfo[key] = value;
  });
  renderDatasetInfo();
}

function renderDatasetInfo() {
  const info = state.datasetInfo;
  if (!hasValue(info.title) && !hasValue(info.accession)) return;
  const rows = [];
  const push = (label, value) => { if (hasValue(value)) rows.push([label, value]); };
  push('Accession', info.accession);
  push('Organism', info.organism);
  push('Experiment type', info.experiment_type);
  push('Platforms', (info.platform_ids || info.platforms || []).map(x => x && typeof x === 'object' ? x.id : x).filter(Boolean).join(', '));
  push('Samples', info.sample_count !== undefined && info.sample_count !== null ? Number(info.sample_count).toLocaleString() : null);
  push('Probes', info.probe_count !== undefined && info.probe_count !== null ? Number(info.probe_count).toLocaleString() : null);
  push('Public', info.public_date);
  push('Last updated', info.last_update_date);
  const links = [];
  (info.pubmed_ids || []).forEach(id => links.push(`<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(id)}/" target="_blank" rel="noopener">PubMed ${escapeHtml(id)}</a>`));
  if (hasValue(info.bioproject)) links.push(`<a href="https://www.ncbi.nlm.nih.gov/bioproject/${encodeURIComponent(info.bioproject)}" target="_blank" rel="noopener">BioProject</a>`);
  if (hasValue(info.ftp_link)) links.push(`<a href="${escapeHtml(info.ftp_link)}" target="_blank" rel="noopener">FTP</a>`);
  const parts = [`<h3 class="dataset-title">${escapeHtml(info.title || info.accession)}</h3>`];
  if (rows.length) parts.push(`<dl class="dataset-meta">${rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('')}</dl>`);
  if (hasValue(info.summary)) parts.push(`<details class="dataset-text"><summary>Summary</summary><p>${escapeHtml(info.summary)}</p></details>`);
  if (hasValue(info.overall_design)) parts.push(`<details class="dataset-text"><summary>Overall design</summary><p>${escapeHtml(info.overall_design)}</p></details>`);
  if (links.length) parts.push(`<p class="dataset-links">${links.join('')}</p>`);
  $('dataset-info').innerHTML = parts.join('');
}

async function fetchDatasetInfo(accession) {
  if (!accession) return;
  try {
    const data = await request(`/api/datasets/${encodeURIComponent(accession)}/info`);
    mergeDatasetInfo(data.info);
  } catch (_) {}
}

function formatEta(data, fraction) {
  if (fraction === null) return data.elapsed_seconds ? `${formatDuration(data.elapsed_seconds)} elapsed` : '';
  if (data.eta_seconds === null || data.eta_seconds === undefined) return '';
  if (data.eta_seconds <= 1) return 'almost done';
  return `~${formatDuration(data.eta_seconds)} remaining`;
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
}

async function load() {
  const accession = state.accession;
  if (!accession) {
    showError(new Error('No accession provided.'));
    return;
  }
  setBusy('Downloading and preparing dataset...', true);
  startProgress(accession, 'load-progress');
  fetchDatasetInfo(accession);
  try {
    const data = await request('/api/datasets/load', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({accession})
    });
    state.accession = data.accession;
    $('accession-value').textContent = data.accession;
    mergeDatasetInfo(data.info || {accession: data.accession, title: data.title, sample_count: data.sample_count});
    $('platform').innerHTML = data.platforms.map(p => `<option value="${p.index}">${p.id}</option>`).join('');
    show('dataset');
    setBusy(data.cached ? 'Cached dataset loaded. Preparing platform...' : 'Download complete. Preparing platform...', true);
    if (data.platforms.length === 1) {
      await usePlatform();
    } else {
      setBusy('Select a platform, then choose Use platform.', false);
    }
  } catch (error) {
    showError(error);
  } finally {
    $('load').disabled = false;
    stopProgress();
  }
}

async function usePlatform() {
  setBusy('Reading expression matrix and phenotype metadata...', true);
  startProgress(state.accession, 'load-progress');
  try {
    state.platform = Number($('platform').value);
    const selectedColumn = $('annotation-column').value;
    const selectedValue = $('value-column').value;
    const params = [];
    if (selectedColumn) params.push(`assignment_column=${encodeURIComponent(selectedColumn)}`);
    if (selectedValue) params.push(`value_column=${encodeURIComponent(selectedValue)}`);
    const query = params.length ? `?${params.join('&')}` : '';
    const data = await request(`/api/datasets/${state.accession}/platforms/${state.platform}${query}`);
    if (data.requires_annotation_column) {
      $('annotation-column').innerHTML = data.annotation_columns.map(column => `<option value="${column}">${column}</option>`).join('');
      $('annotation-column-controls').hidden = false;
      setBusy('Choose the gene assignment column, then use the platform.', false);
      return;
    }
    state.assignmentColumn = data.assignment_column;
    state.valueColumn = data.value_column || null;
    $('annotation-column-controls').hidden = false;
    $('annotation-column').innerHTML = data.annotation_columns.map(column => `<option value="${column}">${column}</option>`).join('');
    $('annotation-column').value = state.assignmentColumn;
    let valueColumns = data.value_columns || [];
    if (state.valueColumn && !valueColumns.includes(state.valueColumn)) valueColumns = [state.valueColumn, ...valueColumns];
    if (valueColumns.length > 1) {
      $('value-column').innerHTML = valueColumns.map(column => `<option value="${column}">${column}</option>`).join('');
      $('value-column').value = state.valueColumn || valueColumns[0];
      $('value-column-controls').hidden = false;
      $('value-column').onchange = usePlatform;
    } else {
      $('value-column-controls').hidden = true;
    }
    state.samples = data.samples;
    state.fields = data.phenotype_fields;
    state.metadata = data.phenotype_values;
    state.genes = data.genes;
    $('phenotype').innerHTML = data.phenotype_fields.map(x => `<option>${x}</option>`).join('');
    $('sample-count').textContent = `${data.samples.length} samples, ${data.rows.toLocaleString()} expression observations`;
    $('sample-list').innerHTML = data.samples.map(s => `<label class="gene"><input type="checkbox" value="${s}" checked> ${s}</label>`).join('');
    $('gene-list').innerHTML = data.genes.map(g => `<label class="gene"><input type="checkbox" value="${g}"> ${g}</label>`).join('');
    state.paletteMap = await request('/api/palettes');
    state.paletteOptions = Object.keys(state.paletteMap);
    $('palette').innerHTML = state.paletteOptions.map(x => `<option>${x}</option>`).join('');
    $('palette').onchange = updateColorControls;
    $('analysis-summary').textContent = 'Select genes and a phenotype field, then run the analysis.';
    $('phenotype').onchange = updatePhenotype;
    updatePhenotype();
    setBusy(`Loaded ${data.samples.length} samples and ${data.genes.length} mapped genes.`, false);
    show('samples');
  } catch (error) {
    showError(error);
  } finally {
    $('platform-load').disabled = false;
    stopProgress();
  }
}

function updatePhenotype() {
  state.group = $('phenotype').value;
  const counts = {};
  const selectedSamples = new Set([...document.querySelectorAll('#sample-list input:checked')].map(x => x.value));
  state.metadata.forEach(row => {
    if (!selectedSamples.has(row.sample)) return;
    const value = row[state.group];
    if (value !== null && value !== undefined && String(value).trim()) counts[value] = (counts[value] || 0) + 1;
  });
  const entries = Object.entries(counts);
  $('group-counts').innerHTML = entries.length
    ? `<div class="group-summary"><table><thead><tr><th>Group</th><th>Included samples</th></tr></thead><tbody>${entries.map(([name, count]) => `<tr><td class="group-name">${name}</td><td class="group-count">${count}</td></tr>`).join('')}</tbody></table></div>`
    : '<p>No group values are available for this field.</p>';
  $('analysis-summary').textContent = `Grouping by ${state.group || 'the selected phenotype field'}. Select genes and run the analysis.`;
  updateColorControls();
}

function currentGroups() {
  const selected = new Set([...document.querySelectorAll('#sample-list input:checked')].map(x => x.value));
  return [...new Set(state.metadata.filter(row => selected.has(row.sample)).map(row => row[state.group]).filter(value => value !== null && value !== undefined && String(value).trim()).map(String))];
}

function updateColorControls(existing = {}) {
  const groups = currentGroups();
  const colors = state.paletteMap[$('palette').value] || [];
  $('color-controls').innerHTML = groups.length ? `<div class="color-controls"><h3>Group colours</h3>${groups.map((group, index) => `<div class="color-row"><label for="color-${index}">${group}</label><input id="color-${index}" data-group="${group}" type="color" value="${existing[group] || colors[index] || '#4DBBD5'}"><input class="hex-value" data-hex-for="color-${index}" value="${existing[group] || colors[index] || '#4DBBD5'}"></div>`).join('')}</div>` : '';
  document.querySelectorAll('#color-controls input[type="color"]').forEach(input => input.oninput = () => { const hex = document.querySelector(`[data-hex-for="${input.id}"]`); hex.value = input.value; });
  document.querySelectorAll('#color-controls input[data-hex-for]').forEach(input => input.onchange = () => { const color = document.getElementById(input.dataset.hexFor); if (/^#[0-9a-f]{6}$/i.test(input.value)) color.value = input.value; });
}

function selectedColors() {
  return currentGroups().map((_, index) => document.getElementById(`color-${index}`)?.value || '#4DBBD5');
}

async function runAnalysis() {
  try {
    state.group = $('phenotype').value;
    state.selectedGenes = [...document.querySelectorAll('#gene-list input:checked')].map(x => x.value);
    const selectedSamples = [...document.querySelectorAll('#sample-list input:checked')].map(x => x.value);
    if (!state.selectedGenes.length) throw Error('Select at least one gene.');
    if (selectedSamples.length < 2) throw Error('Select at least two samples.');
    $('run').disabled = true;
    setBusy('Running statistical analysis and creating plots...', true);
    startProgress(state.accession, 'run-progress');
    const result = await request('/api/analyses', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({accession: state.accession, platform_index: state.platform, assignment_column: state.assignmentColumn, value_column: state.valueColumn, genes: state.selectedGenes, group_column: state.group, selected_samples: selectedSamples, palette: $('palette').value, colors: selectedColors()})
    });
    renderAnalysis(result);
    setBusy('Analysis complete.', false);
    show('results');
    loadHistory();
  } catch (error) {
    $('run').disabled = false;
    showError(error);
  } finally {
    stopProgress();
  }
}

function renderAnalysis(result) {
  state.analysisId = result.id;
  if (result.config && result.config.accession) state.accession = result.config.accession;
  $('result-palette').innerHTML = (state.paletteOptions.length ? state.paletteOptions : ['Scientific', 'Colorblind-safe', 'Muted', 'High contrast', 'Monochrome']).map(x => `<option>${x}</option>`).join('');
  if (result.config?.palette) $('result-palette').value = result.config.palette;
  $('results-body').innerHTML = `<dl class="metadata"><dt>Dataset</dt><dd>${state.accession}</dd><dt>Genes</dt><dd>${(result.config?.genes || []).join(', ')}</dd><dt>Grouping</dt><dd>${result.config?.group_column || 'Unknown'}</dd><dt>Method</dt><dd>${result.method || result.config?.method || 'Unknown'}</dd></dl><img id="result-image" src="${result.plot}"><p class="exports"><a href="/api/analyses/${result.id}/export/csv">CSV</a><a href="/api/analyses/${result.id}/export/tsv">TSV</a><a href="/api/analyses/${result.id}/export/xlsx">XLSX</a><a href="/api/analyses/${result.id}/export/png">PNG</a><a href="/api/analyses/${result.id}/export/svg">SVG</a><a href="/api/analyses/${result.id}/export/pdf">PDF report</a></p><h3>Statistical results</h3><pre>${JSON.stringify(result.results, null, 2)}</pre>`;
}

async function updateChart() {
  try {
    setBusy('Updating chart...', true);
    const result = await request(`/api/analyses/${state.analysisId}/chart`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({palette: $('result-palette').value})});
    $('result-image').src = result.plot + '&t=' + Date.now();
    setBusy('Chart updated without rerunning analysis.', false);
  } catch (error) {
    showError(error);
  }
}

async function loadHistory() {
  try {
    if (!state.paletteOptions.length) state.paletteOptions = Object.keys(await request('/api/palettes'));
    const rows = await request('/api/history');
    $('history').innerHTML = rows.length ? rows.map(row => `<button class="history-item" data-analysis-id="${row.id}">${row.config.accession} · ${row.config.genes.join(', ')} · ${row.config.group_column}</button>`).join('') : 'No analyses yet.';
    document.querySelectorAll('.history-item').forEach(item => item.onclick = () => openAnalysis(item.dataset.analysisId));
  } catch (_) {}
}

async function openAnalysis(analysisId) {
  try {
    setBusy('Opening saved analysis...', true);
    const result = await request(`/api/analyses/${analysisId}`);
    renderAnalysis(result);
    setBusy('Saved analysis opened.', false);
    show('results');
  } catch (error) {
    showError(error);
  }
}

function filterGenes() {
  const query = $('gene-search').value.toLowerCase();
  document.querySelectorAll('.gene').forEach(x => x.style.display = x.textContent.toLowerCase().includes(query) ? 'inline-block' : 'none');
}

$('load').onclick = load;
$('platform-load').onclick = usePlatform;
$('run').onclick = runAnalysis;
$('update-chart').onclick = updateChart;
$('gene-search').oninput = filterGenes;
$('sample-list').onchange = updatePhenotype;
loadHistory();

const initialAccession = new URLSearchParams(window.location.search).get('accession');
if (initialAccession) {
  state.accession = initialAccession;
  $('accession-value').textContent = initialAccession;
  fetchDatasetInfo(initialAccession);
} else {
  $('load-section').hidden = true;
  $('workspace').hidden = true;
  $('no-accession').hidden = false;
}
