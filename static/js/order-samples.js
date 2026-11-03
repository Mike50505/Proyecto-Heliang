document.querySelectorAll('[data-new-sample-order]').forEach(form => {
  const check = form.querySelector('[name="is_sample"]');
  const quantity = form.querySelector('[name="quantity"]');
  if (!check || !quantity) return;
  quantity.required = true;
});

const sampleRows = [...document.querySelectorAll('[data-sample-preview]')];
const sampleAll = document.querySelector('[data-sample-all]');

const refreshSampleAll = () => {
  if (!sampleAll) return;
  const checks = sampleRows.map(row => row.querySelector('[data-sample-check]')).filter(Boolean);
  const checkedCount = checks.filter(check => check.checked).length;
  sampleAll.checked = checks.length > 0 && checkedCount === checks.length;
  sampleAll.indeterminate = checkedCount > 0 && checkedCount < checks.length;
};

sampleAll?.addEventListener('change', () => {
  sampleRows.forEach(row => {
    const check = row.querySelector('[data-sample-check]');
    if (check && !check.disabled) {
      check.checked = sampleAll.checked;
      check.dispatchEvent(new Event('change'));
    }
  });
});

sampleRows.forEach(row => {
  const check = row.querySelector('[data-sample-check]');
  const quantity = row.querySelector('[data-sample-quantity]');
  const label = row.querySelector('[data-sample-label]');
  if (!check || !quantity || !label) return;
  const update = () => {
    quantity.textContent = quantity.dataset.originalQuantity;
    label.hidden = !check.checked || label.dataset.existing === 'true';
  };
  check.addEventListener('change', update);
  check.addEventListener('change', refreshSampleAll);
  update();
});

refreshSampleAll();
