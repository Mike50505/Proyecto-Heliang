const themeToggle = document.getElementById('theme-toggle');

function updateThemeButton() {
  const dark = document.documentElement.dataset.theme === 'dark';
  themeToggle.querySelector('span').textContent = dark ? '☀' : '☾';
  themeToggle.querySelector('b').textContent = dark ? 'Modo claro' : 'Modo oscuro';
  themeToggle.setAttribute('aria-label', dark ? 'Activar modo claro' : 'Activar modo oscuro');
}

themeToggle.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('mesa-theme', next);
  updateThemeButton();
});

updateThemeButton();
