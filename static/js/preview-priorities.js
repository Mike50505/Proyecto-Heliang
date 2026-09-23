(() => {
  const checks = [...document.querySelectorAll('.preview-priority-check')];
  const numberFor = check => document.getElementById(
    `priority-${check.name.replace('priority_check_', '')}`
  );
  let selected = checks.filter(check => check.checked).sort(
    (a, b) => Number(numberFor(a).value) - Number(numberFor(b).value)
  );
  const sync = () => {
    checks.forEach(check => { numberFor(check).value = ''; });
    selected.forEach((check, index) => { numberFor(check).value = String(index + 1); });
  };
  checks.forEach(check => check.addEventListener('change', () => {
    selected = selected.filter(item => item !== check);
    if (check.checked) selected.push(check);
    sync();
  }));
  sync();
})();
