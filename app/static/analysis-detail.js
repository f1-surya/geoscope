const $ = id => document.getElementById(id);
const analysisId = window.location.pathname.split('/').pop();
let paletteOptions = [];

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

function render(result) {
  $('analysis-meta').innerHTML = `<h2>${result.config.accession}</h2><dl class="metadata"><dt>Genes</dt><dd>${result.config.genes.join(', ')}</dd><dt>Platform</dt><dd>${result.config.platform_index + 1}</dd><dt>Grouping field</dt><dd>${result.config.group_column}</dd><dt>Samples</dt><dd>${result.config.selected_samples.length}</dd><dt>Statistical method</dt><dd>${result.method || result.config.method}</dd></dl>`;
  $('result-palette').innerHTML = paletteOptions.map(name => `<option>${name}</option>`).join('');
  $('result-palette').value = result.config.palette || 'Scientific';
  const groups = result.config.groups || [];
  const colors = result.config.colors || [];
  $('detail-colors').innerHTML = groups.length ? `<div class="color-controls"><h3>Group colours</h3>${groups.map((group, index) => `<div class="color-row"><label for="detail-color-${index}">${group}</label><input id="detail-color-${index}" data-group="${group}" type="color" value="${colors[index] || '#4DBBD5'}"><input class="hex-value" data-hex-for="detail-color-${index}" value="${colors[index] || '#4DBBD5'}"></div>`).join('')}</div>` : '';
  document.querySelectorAll('#detail-colors input[type="color"]').forEach(input => input.oninput = () => { document.querySelector(`[data-hex-for="${input.id}"]`).value = input.value; });
  document.querySelectorAll('#detail-colors input[data-hex-for]').forEach(input => input.onchange = () => { if (/^#[0-9a-f]{6}$/i.test(input.value)) document.getElementById(input.dataset.hexFor).value = input.value; });
  $('results-body').innerHTML = `<img id="result-image" src="${result.plot}"><p class="exports"><a href="/api/analyses/${result.id}/export/csv">CSV</a><a href="/api/analyses/${result.id}/export/tsv">TSV</a><a href="/api/analyses/${result.id}/export/xlsx">XLSX</a><a href="/api/analyses/${result.id}/export/png">PNG</a><a href="/api/analyses/${result.id}/export/svg">SVG</a><a href="/api/analyses/${result.id}/export/pdf">PDF report</a></p><h3>Statistical results</h3><pre>${JSON.stringify(result.results, null, 2)}</pre>`;
  $('analysis-report').hidden = false;
  $('status-panel').hidden = true;
}

async function updateChart() {
  $('update-chart').disabled = true;
  try {
    const colors = [...document.querySelectorAll('#detail-colors input[type="color"]')].map(input => input.value);
    const response = await request(`/api/analyses/${analysisId}/chart`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({palette: $('result-palette').value, colors})});
    $('result-image').src = response.plot + '&t=' + Date.now();
  } catch (error) {
    $('status-panel').hidden = false;
    $('status-panel').textContent = error.message;
  } finally {
    $('update-chart').disabled = false;
  }
}

async function load() {
  try {
    const [palettes, result] = await Promise.all([request('/api/palettes'), request(`/api/analyses/${analysisId}`)]);
    paletteOptions = Object.keys(palettes);
    render(result);
  } catch (error) {
    $('status-panel').textContent = error.message;
    $('status-panel').classList.add('error');
  }
}

$('update-chart').onclick = updateChart;
load();
