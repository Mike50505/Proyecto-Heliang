document.querySelectorAll('[data-new-sample-order]').forEach(form => {
  const check = form.querySelector('[name="is_sample"]');
  const quantity = form.querySelector('[name="quantity"]');
  if (!check || !quantity) return;
  let original = quantity.value;
  const update = () => {
    if (check.checked) {
      if (!quantity.readOnly) original = quantity.value;
      quantity.value = '5';
      quantity.readOnly = true;
    } else {
      if (quantity.readOnly) quantity.value = original;
      quantity.readOnly = false;
    }
    quantity.required = !check.checked;
  };
  check.addEventListener('change', update);
  update();
});

document.querySelectorAll('[data-sample-preview]').forEach(row => {
  const check = row.querySelector('[data-sample-check]');
  const quantity = row.querySelector('[data-sample-quantity]');
  const label = row.querySelector('[data-sample-label]');
  if (!check || !quantity || !label) return;
  const update = () => {
    quantity.textContent = check.checked ? '5' : quantity.dataset.originalQuantity;
    label.hidden = !check.checked || label.dataset.existing === 'true';
  };
  check.addEventListener('change', update);
  update();
});
