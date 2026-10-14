function statEscape(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
}

function formatPValue(value) {
  const number = Number(value);
  if (value === null || value === undefined || !isFinite(number)) return '—';
  if (number !== 0 && Math.abs(number) < 0.001) return number.toExponential(2);
  return number.toFixed(4);
}

function formatStatValue(value) {
  const number = Number(value);
  if (value === null || value === undefined || !isFinite(number)) return '—';
  return number.toPrecision(4);
}

function renderStatistics(results, pairwise) {
  if (!Array.isArray(results) || !results.length) {
    return '<h3>Statistical results</h3><p>No statistical results were returned.</p>';
  }
  const rows = results.map(result => {
    const groups = Array.isArray(result.summary) ? result.summary : [];
    const span = Math.max(1, groups.length);
    const geneCell = `<td class="gene-cell" rowspan="${span}">${statEscape(result.gene)}</td>`;
    const pCell = `<td class="num p-value" rowspan="${span}">${formatPValue(result.p_value)}</td>`;
    if (!groups.length) {
      return `<tr>${geneCell}<td>—</td><td class="num">—</td><td class="num">—</td><td class="num">—</td><td class="num">—</td>${pCell}</tr>`;
    }
    return groups.map((group, index) => {
      const cells = [];
      if (index === 0) cells.push(geneCell);
      cells.push(`<td>${statEscape(group.group)}</td>`);
      cells.push(`<td class="num">${group.count}</td>`);
      cells.push(`<td class="num">${formatStatValue(group.mean)}</td>`);
      cells.push(`<td class="num">${formatStatValue(group.median)}</td>`);
      cells.push(`<td class="num">${formatStatValue(group.std)}</td>`);
      if (index === 0) cells.push(pCell);
      return `<tr>${cells.join('')}</tr>`;
    }).join('');
  }).join('');

  const summary = `<div class="results-table"><table>
    <caption>Expression summary and omnibus test</caption>
    <thead><tr><th>Gene</th><th>Group</th><th class="num">n</th><th class="num">Mean</th><th class="num">Median</th><th class="num">Std</th><th class="num">p-value</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;

  let comparisons = '';
  if (Array.isArray(pairwise) && pairwise.length) {
    comparisons = `<h3>Pairwise comparisons</h3><div class="results-table"><table>
      <thead><tr><th>Gene</th><th>Group A</th><th>Group B</th><th class="num">p-value</th><th class="num">Adjusted p-value</th></tr></thead>
      <tbody>${pairwise.map(comparison => `<tr><td class="gene-cell">${statEscape(comparison.gene)}</td><td>${statEscape(comparison.group_a)}</td><td>${statEscape(comparison.group_b)}</td><td class="num">${formatPValue(comparison.p_value)}</td><td class="num">${formatPValue(comparison.adjusted_p_value)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  return `<h3>Statistical results</h3>${summary}${comparisons}`;
}
