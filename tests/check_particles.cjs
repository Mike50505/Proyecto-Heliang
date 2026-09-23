// Browser verification: PLAYWRIGHT_MODULE can point to a temporary installation.
// Run: node tests/check_particles.cjs [base URL] [screenshot directory]
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440, height:900}, deviceScaleFactor:2});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.argv[2] || 'http://127.0.0.1/');
    // Optional preview of local assets before deployment. By default test served assets.
    if (process.env.PARTICLES_PREVIEW === '1') {
      await page.evaluate(() => {
        window.mesaParticles?.destroy();
        if (!document.querySelector('[data-particle-background]')) {
          const canvas = document.createElement('canvas');
          canvas.className = 'particle-background';
          canvas.dataset.particleBackground = '';
          canvas.setAttribute('aria-hidden', 'true');
          document.body.prepend(canvas);
        }
      });
      await page.addStyleTag({path:path.resolve('static/css/particles.css')});
      await page.addScriptTag({path:path.resolve('static/js/particles.js')});
    }
    await page.waitForFunction(() => window.mesaParticles?.particles.length > 0);
    await page.mouse.move(480, 400);
    await page.waitForTimeout(300);
    await page.mouse.move(1000, 440);
    await page.waitForTimeout(100);
    const lag = await page.evaluate(() => {
      const p = mesaParticles.pointer;
      return Math.hypot(p.targetX - p.x, p.targetY - p.y);
    });
    assert(lag > 250, `Cursor should lag perceptibly, got ${lag}`);

    const reversal = await page.evaluate(() => {
      const effect = mesaParticles;
      effect.stop();
      effect.pointer = {x:400,y:400,vx:0,vy:0,targetX:1000,targetY:400,
        active:true,strength:1,initialized:true};
      for (let i=0; i<24; i++) effect.step(1/120);
      const before = effect.pointer.vx;
      effect.pointer.targetX = 0;
      effect.step(1/120);
      const after = effect.pointer.vx;
      effect.refresh();
      return {before,after};
    });
    assert(reversal.before > 0 && reversal.after > 0 && reversal.after < reversal.before,
      'A reversal should first brake existing momentum instead of snapping direction');

    const physics = await page.evaluate(() => {
      const effect = mesaParticles;
      effect.stop();
      const center = {x:700, y:450};
      effect.particles = Array.from({length:40}, (_, i) => {
        const p = effect.createParticle();
        const angle = i / 40 * Math.PI * 2;
        return {...p, x:center.x + Math.cos(angle)*150,
          y:center.y + Math.sin(angle)*150, vx:0, vy:0};
      });
      effect.pointer = {x:center.x, y:center.y, targetX:center.x, targetY:center.y,
        strength:1, active:true, initialized:true};
      for (let i=0; i<120*20; i++) effect.step(1/120);
      const radii = effect.particles.map(p => Math.hypot(p.x-center.x, p.y-center.y));
      const cloud = {
        mean:radii.reduce((a,b) => a+b,0)/radii.length,
        dispersed:radii.filter(r => r>20).length,
        speed:Math.max(...effect.particles.map(p => Math.hypot(p.vx,p.vy))),
      };
      effect.release();
      for (let i=0; i<120*8; i++) effect.step(1/120);
      cloud.releasedStrength = effect.pointer.strength;
      cloud.idleSpeed = effect.particles.reduce((sum,p) => sum+Math.hypot(p.vx,p.vy),0)/40;

      // Replay identical initial conditions through the real RAF accumulator.
      const seed = JSON.parse(JSON.stringify(effect.particles));
      const pointer = {...effect.pointer};
      const simulate = fps => {
        effect.stop(); effect.time = 0;
        effect.particles = JSON.parse(JSON.stringify(seed));
        effect.pointer = {...pointer};
        effect.tick(0); cancelAnimationFrame(effect.frameId);
        for (let frame=1; frame<=fps*3; frame++) {
          effect.tick(frame*1000/fps); cancelAnimationFrame(effect.frameId);
        }
        return effect.particles.map(p => [p.x,p.y]);
      };
      const a = simulate(30), b = simulate(144);
      cloud.fpsDifference = Math.max(...a.map((p,i) => Math.hypot(p[0]-b[i][0],p[1]-b[i][1])));
      effect.particles = [];
      effect.pointer.active = false;
      effect.pointer.strength = 0;
      effect.resize();
      return cloud;
    });
    assert(physics.mean < 145 && physics.mean > 25, JSON.stringify(physics));
    assert(physics.dispersed >= 30, 'Particles must keep a loose cloud');
    assert(physics.speed <= 32.001);
    assert(physics.releasedStrength < 0.01);
    assert(physics.idleSpeed > 0.5 && physics.idleSpeed < 8);
    assert(physics.fpsDifference < 0.25);

    const layers = await page.evaluate(() => {
      const canvas = mesaParticles.canvas;
      const button = document.getElementById('theme-toggle');
      const rect = button.getBoundingClientRect();
      return {pixels:canvas.width*canvas.height, pointerEvents:getComputedStyle(canvas).pointerEvents,
        hit:button.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2))};
    });
    assert(layers.pixels <= 4000000);
    assert.equal(layers.pointerEvents, 'none');
    assert(layers.hit, 'Canvas must not intercept clicks');
    const directory = process.argv[3];
    if (directory) fs.mkdirSync(directory, {recursive:true});
    for (const theme of ['light','dark']) {
      await page.evaluate(theme => document.documentElement.dataset.theme=theme, theme);
      await page.waitForTimeout(100);
      if (directory) await page.screenshot({path:path.join(directory, `particles-${theme}.png`)});
    }
    const previousTheme = await page.locator('html').getAttribute('data-theme');
    await page.getByRole('button', {name:/Activar modo/}).click();
    assert.notEqual(await page.locator('html').getAttribute('data-theme'), previousTheme);
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForTimeout(100);
    const still = await page.evaluate(() => ({positions:JSON.stringify(mesaParticles.particles), frame:mesaParticles.frameId}));
    await page.waitForTimeout(150);
    assert.equal(await page.evaluate(() => JSON.stringify(mesaParticles.particles)), still.positions);
    assert.equal(still.frame, null);
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.setViewportSize({width:390, height:844});
    await page.waitForTimeout(150);
    assert(await page.evaluate(() => mesaParticles.particles.length <= mesaParticles.options.mobileCount && mesaParticles.frameId !== null));
    assert(await page.evaluate(() => {
      const ys = mesaParticles.particles.map(p => p.y);
      return Math.max(...ys) - Math.min(...ys) > mesaParticles.height * 0.65;
    }), 'Mobile particles must fill the viewport, not only its top rows');
    if (directory) await page.screenshot({path:path.join(directory, 'particles-mobile.png')});
    await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true})));
    assert(await page.evaluate(() => mesaParticles.destroyed && mesaParticles.frameId === null));
    await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true})));
    await page.waitForFunction(() => !mesaParticles.destroyed && mesaParticles.frameId !== null);
    await page.evaluate(() => mesaParticles.canvas.remove());
    await page.waitForTimeout(50);
    assert(await page.evaluate(() => mesaParticles.destroyed && mesaParticles.frameId === null && mesaParticles.abort.signal.aborted));
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({lag, physics, layers, reducedMotion:'OK', mobile:'OK', cleanup:'OK', errors},null,2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
