// Run with PLAYWRIGHT_MODULE pointing to Playwright if it is not installed locally.
// This checks the live login plus read-only fixtures for native form interoperability.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '..');
const base = process.argv[2] || 'http://localhost';
const screenshots = process.argv[3];

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(8000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('[data-text-type]')?.textContent === 'Todo tu proceso.\nEn un solo lugar.');
    assert.equal(await page.locator('h1').getAttribute('aria-label'), 'Todo tu proceso. En un solo lugar.');
    assert.equal(await page.locator('.login-card button').evaluate(el => getComputedStyle(el).borderRadius), '999px');
    await page.locator('.login-card button').hover();
    await page.waitForTimeout(220);
    assert.notEqual(await page.locator('.login-card button').evaluate(el => getComputedStyle(el).transform), 'none');
    if (screenshots) {
      fs.mkdirSync(screenshots, { recursive: true });
      await page.screenshot({ path: path.join(screenshots, 'login-desktop.png'), fullPage: true });
    }
    await page.setViewportSize({ width: 375, height: 812 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile login overflows');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.reload();
    assert.equal(await page.locator('[data-text-type]').textContent(), 'Todo tu proceso.\nEn un solo lugar.');
    await page.locator('#theme-toggle').click();
    if (screenshots) await page.screenshot({ path: path.join(screenshots, 'login-mobile.png'), fullPage: true });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.setViewportSize({ width: 1440, height: 900 });

    const fixture = `<!doctype html><html lang="es"><head><meta charset="utf-8"></head><body>
      <header class="site-header"><div class="site-header-inner"><nav id="site-nav"><a href="/">Inicio</a><a href="/qa-controls/">Producción</a></nav></div></header>
      <main><section class="form-card" style="height:145px;overflow:hidden">
      <form id="qa-form"><p><label for="qa-select">Máquina</label><select id="qa-select" name="machine" required>
      <option value="">Selecciona una máquina</option><option value="a">Alpha</option><option value="b" disabled>Beta</option>
      <option value="c">Gamma</option><option value="d">Una opción larga con información suficiente para ocupar varias líneas sin recortes</option>
      </select><small id="qa-help">Selecciona una máquina disponible</small></p>
      <button type="submit">Guardar</button><button type="reset">Restablecer</button></form></section>
      <label>Cliente<select id="qa-wrapped" name="client"><option value="1">Uno</option><option value="2">Dos</option></select></label>
      <select multiple id="qa-multiple"><option>Uno</option></select>
      </main></body></html>`;
    await page.route('**/qa-controls/', route => route.fulfill({ contentType: 'text/html', body: fixture }));
    await page.goto(`${base}/qa-controls/`);
    for (const file of ['app.css', 'theme.css', 'apple-design.css', 'suite-controls.css']) {
      await page.addStyleTag({ path: path.join(root, 'static/css', file) });
    }
    for (const file of ['glide-select.js', 'jelly-controls.js']) {
      await page.addScriptTag({ path: path.join(root, 'static/js', file) });
    }
    const trigger = page.getByRole('combobox', { name: 'Máquina', exact: true });
    assert.equal(await page.getByRole('combobox', { name: 'Cliente', exact: true }).count(), 1);
    assert.equal(await page.locator('.glide-select').count(), 2, 'Multiple selects must stay native');
    assert.equal(await page.locator('#site-nav a[aria-current="page"]').textContent(), 'Producción');
    await trigger.click();
    await page.waitForTimeout(240);
    assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
    const menu = page.locator('.glide-select__menu');
    const bounds = await menu.boundingBox();
    assert(bounds.height > 140, 'Menu was clipped by the production panel');
    assert.equal(await menu.evaluate(el => el.parentElement.tagName), 'BODY');
    await trigger.press('ArrowDown');
    await trigger.press('ArrowDown');
    await trigger.press('Enter');
    assert.equal(await page.locator('#qa-select').inputValue(), 'c', 'Keyboard should skip disabled options');
    assert.equal(await page.evaluate(() => new FormData(document.getElementById('qa-form')).get('machine')), 'c');
    await trigger.click();
    await trigger.press('Home');
    await trigger.press('g');
    await trigger.press('Enter');
    assert.equal(await page.locator('#qa-select').inputValue(), 'c', 'Typeahead must find Gamma');
    await page.getByRole('button', { name: 'Restablecer' }).click();
    await page.waitForTimeout(50);
    assert.equal(await trigger.innerText(), 'Selecciona una máquina\n⌄');
    await page.getByRole('button', { name: 'Guardar' }).click();
    assert.equal(await trigger.getAttribute('aria-invalid'), 'true');
    assert(await page.locator('.error-text').first().isVisible());
    assert.equal(await trigger.getAttribute('aria-expanded'), 'true', 'Invalid required selects should open for correction');
    await page.getByRole('option', { name: 'Alpha', exact: true }).click();
    assert.equal(await trigger.getAttribute('aria-invalid'), null);
    await page.evaluate(() => { document.getElementById('qa-select').disabled = true; });
    await page.waitForTimeout(20);
    assert(await trigger.isDisabled(), 'Native disabled state must synchronize');
    await page.evaluate(() => { document.getElementById('qa-select').disabled = false; });
    await trigger.click();
    await trigger.press('Escape');
    assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
      await trigger.click();
      await page.waitForTimeout(250);
      assert.notEqual(await menu.evaluate(el => getComputedStyle(el).backgroundColor), 'rgba(0, 0, 0, 0)');
      if (screenshots) await page.screenshot({ path: path.join(screenshots, `select-${theme}.png`), fullPage: true });
      await trigger.press('Escape');
    }
    await page.setViewportSize({ width: 375, height: 812 });
    await trigger.click();
    await page.waitForTimeout(240);
    const mobileBounds = await menu.boundingBox();
    assert(mobileBounds.x >= 0 && mobileBounds.x + mobileBounds.width <= 375, 'Mobile menu exceeds viewport');
    await trigger.press('Escape');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await trigger.click();
    assert.equal(await menu.evaluate(el => getComputedStyle(el).transitionDuration), '0s');
    if (process.env.HEILIANG_RENDERED_HTML) {
      const html = fs.readFileSync(process.env.HEILIANG_RENDERED_HTML, 'utf8');
      await page.route('**/heliang/', route => route.fulfill({ contentType: 'text/html', body: html }));
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${base}/heliang/`);
      await page.waitForFunction(() => document.querySelectorAll('main .glide-select').length === document.querySelectorAll('main select:not([multiple]):not([size])').length);
      const actual = page.getByRole('combobox', { name: 'Máquina disponible:', exact: true });
      assert.equal(await actual.count(), 1, 'The real assignment form should use Glide Select');
      const machineColor = await actual.evaluate(el => getComputedStyle(el).backgroundColor);
      assert.equal(await page.getByRole('combobox', { name: 'Orden procesando:', exact: true }).evaluate(el => getComputedStyle(el).backgroundColor), machineColor, 'Production styles must not recolor Glide Select triggers');
      await actual.click();
      await page.waitForTimeout(240);
      assert.equal(await actual.getAttribute('aria-expanded'), 'true');
      assert.equal(await page.locator('#site-nav a[aria-current="page"]').textContent(), 'Producción');
      if (screenshots) await page.screenshot({ path: path.join(screenshots, 'production-desktop.png') });
      await actual.press('Escape');
      await page.setViewportSize({ width: 375, height: 812 });
      await actual.click();
      await page.waitForTimeout(240);
      const actualBounds = await page.locator('.glide-select__menu').boundingBox();
      assert(actualBounds.x >= 0 && actualBounds.x + actualBounds.width <= 375);
      if (screenshots) await page.screenshot({ path: path.join(screenshots, 'production-mobile.png') });
      await actual.press('Escape');
    }
    if (process.env.HEILIANG_LINE_HTML) {
      const html = fs.readFileSync(process.env.HEILIANG_LINE_HTML, 'utf8');
      await page.route('**/tablero-linea/', route => route.fulfill({ contentType: 'text/html', body: html }));
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${base}/tablero-linea/`);
      await page.waitForFunction(() => document.querySelector('#site-nav a[aria-current="page"]'));
      assert(await page.locator('.site-header').isVisible(), 'Normal line board must keep the app header');
      assert.equal(await page.locator('#site-nav a[aria-current="page"]').textContent(), 'Tablero de línea');
      assert.equal(await page.locator('#theme-toggle').count(), 1, 'The shared header should own the theme control');
      if (screenshots) await page.screenshot({ path: path.join(screenshots, 'line-normal.png') });
      await page.getByRole('button', { name: 'Mostrar tablero en pantalla completa', exact: true }).click();
      await page.waitForFunction(() => document.fullscreenElement === document.documentElement);
      assert.equal(await page.locator('.site-header').isVisible(), false, 'Header should hide only in fullscreen');
      assert(await page.locator('.line-header').isVisible());
      if (screenshots) await page.screenshot({ path: path.join(screenshots, 'line-fullscreen.png') });
      await page.getByRole('button', { name: 'Salir de pantalla completa (Esc)', exact: true }).click();
      await page.waitForFunction(() => !document.fullscreenElement);
      assert(await page.locator('.site-header').isVisible(), 'Leaving fullscreen must restore the header');
      await page.setViewportSize({ width: 375, height: 812 });
      await page.getByRole('button', { name: 'Abrir menú', exact: true }).click();
      assert(await page.getByRole('link', { name: 'Producción', exact: true }).isVisible());
      assert(await page.getByRole('link', { name: 'Tablero de línea', exact: true }).isVisible());
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Line navigation must fit mobile');
      if (screenshots) await page.screenshot({ path: path.join(screenshots, 'line-mobile.png') });
      console.log('PASS: line board navigation, active module, fullscreen entry/exit, restored header and mobile menu.');
    }
    assert.deepEqual(errors, [], 'Unexpected JavaScript errors');
    console.log('PASS: live login, desktop/mobile, themes, reduced motion, keyboard, typeahead, disabled options, native form values, reset, validation and unclipped menus.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
