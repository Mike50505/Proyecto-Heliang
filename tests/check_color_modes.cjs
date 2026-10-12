// Real GET templates, read-only fixtures; never submits operational forms.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const app = path.resolve(__dirname, '..');
const review = process.env.HEILIANG_COLOR_REVIEW || path.resolve(app, '../respaldos/heiliang/revision-colores');
const folder = path.join(review, 'vistas'), output = path.join(review, 'capturas');
const base = process.argv.find(arg => arg.startsWith('http')) || 'http://localhost';
const source = process.argv.includes('--source');
const modes = {classic:'light', pearl:'light', ivory:'light', sage:'light', slate:'dark', night:'dark'};
const labels = {classic:'Claro · azul MESA', pearl:'Perla · gris suave', ivory:'Marfil · tonos cálidos', sage:'Salvia · verde tenue', slate:'Pizarra · oscuro suave', night:'Oscuro · negro'};
const routes = JSON.parse(fs.readFileSync(path.join(folder, 'routes.json')));
routes.login = '/cuenta/ingresar/';
fs.mkdirSync(output, {recursive:true});
function rgb(hex) {let value=hex.replace('#','');if(value.length===3)value=value.split('').map(v=>v+v).join('');return value.match(/../g).map(v=>parseInt(v,16)/255);}
function luminance(hex) {return rgb(hex).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);}
function ratio(a,b) {const values=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (values[0]+.05)/(values[1]+.05);}

(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 const errors=[],missing=[],posts=[],contrasts={},checks=[];
 context.on('page',page=>page.on('pageerror',e=>errors.push(e.message)));
 context.on('response',r=>{if(r.status()>=400&&r.url().includes('/static/'))missing.push(r.url());});
 await context.route('**/*',r=>{if(r.request().method()!=='GET'){posts.push(r.request().url());return r.abort();}return r.continue();});
 for(const[name,url]of Object.entries(routes))await context.route(base+url,r=>r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(folder,name+'.html'))}));
 if(source)await context.route(base+'/static/**',r=>{
  let file=path.join(app,'static',new URL(r.request().url()).pathname.slice('/static/'.length));
  if(!fs.existsSync(file))file=file.replace(/\.[0-9a-f]{12}\.(css|js|svg)$/,'.$1');
  if(!fs.existsSync(file))return r.continue();
  return r.fulfill({contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'image/svg+xml',body:fs.readFileSync(file)});
 });
 const page=await context.newPage();
 async function choose(key){
  if(await page.locator('#color-picker-panel').isHidden())await page.getByRole('button',{name:'Elegir colores',exact:true}).click();
  const combo=page.getByRole('combobox',{name:'Paleta de colores',exact:true});
  await combo.click();await page.getByRole('option',{name:labels[key],exact:true}).click();
  assert.equal(await page.locator('html').getAttribute('data-palette'),key);
  assert.equal(await page.locator('html').getAttribute('data-theme'),modes[key]);
  assert.equal(await page.evaluate(()=>localStorage.getItem('heiliang-color-mode')),key);
 }
 try {
  // Choosing, reload and direct navigation with a single appearance control.
  await page.goto(base+'/cuenta/ingresar/');
  await choose('pearl');
  for(const key of Object.keys(modes)){
   await choose(key);await page.keyboard.press('Escape');
   assert(await page.locator('#color-picker-panel').isHidden());
   await page.reload();assert.equal(await page.locator('html').getAttribute('data-palette'),key);
   await page.goto(base+'/heliang/');assert.equal(await page.locator('html').getAttribute('data-palette'),key);
   await page.goto(base+'/cuenta/ingresar/');
  }
  await choose('ivory');await page.keyboard.press('Escape');
  assert.equal(await page.locator('#theme-toggle').count(),0);
  assert.equal(await page.locator('#color-picker-toggle').count(),1);
  // Escape first closes Glide, then the appearance panel and returns focus.
  await page.getByRole('button',{name:'Elegir colores',exact:true}).click();
  const combo=page.getByRole('combobox',{name:'Paleta de colores',exact:true});
  await combo.click();await combo.press('Escape');assert(await page.locator('#color-picker-panel').isVisible());
  await combo.press('Escape');assert(await page.locator('#color-picker-panel').isHidden());assert(await page.locator('#color-picker-toggle').evaluate(e=>e===document.activeElement));
  // Every real page, all modes, desktop/mobile, meaningful text/button contrast.
  for(const[key,theme]of Object.entries(modes)){
   await page.addInitScript(({key,theme})=>{localStorage.setItem('heiliang-color-mode',key);localStorage.setItem('mesa-theme',theme);}, {key,theme});
   for(const[name,url]of Object.entries(routes)){
    for(const width of [1440,375]){
     await page.setViewportSize({width,height:width===375?812:1000});await page.goto(base+url);
     await page.waitForTimeout(70);
     assert.equal(await page.locator('html').getAttribute('data-palette'),key,name+' palette');
     const fits=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
     if(!fits)console.log(await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,elements:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&!e.closest('.table-wrap,.preview-table-wrap,#site-nav')).slice(0,10).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))})));
     assert(fits,`${key}/${name}/${width} page overflow`);
     if(width===1440&&name!=='login'){
      const nav=await page.locator('#site-nav').evaluate(e=>{const box=e.getBoundingClientRect(),parent=e.closest('.site-header-inner').getBoundingClientRect();return {offset:(box.left+box.right-parent.left-parent.right)/2,full:e.scrollWidth<=e.clientWidth+2};});
      assert(Math.abs(nav.offset)<=1,`${key}/${name}: navigation not centered`);
      assert(nav.full,`${key}/${name}: modules clipped at desktop width`);
     }
     if(['home','production','login','progress','line'].includes(name))await page.screenshot({path:path.join(output,`${name}-${key}-${width}.png`)});
     checks.push(`${key}/${name}/${width}`);
    }
   }
   const tokens=await page.evaluate(()=>{
    const style=getComputedStyle(document.documentElement);const colors={};
    for(const name of ['bg','surface','subtle','ink','muted','accent','action','action-hover','tint'])colors[name]=style.getPropertyValue('--h-'+name).trim();
    return colors;
   });
   const pairs=[['ink','bg'],['ink','surface'],['ink','subtle'],['muted','bg'],['muted','surface'],['muted','subtle'],['accent','tint']];
   contrasts[key]={};
   for(const[a,b]of pairs){const value=ratio(tokens[a],tokens[b]);contrasts[key][a+'/'+b]=+value.toFixed(2);assert(value>=4.5,`${key}: ${a}/${b} contrast ${value}`);}
   for(const bg of ['action','action-hover']){const value=ratio('#ffffff',tokens[bg]);contrasts[key]['button/'+bg]=+value.toFixed(2);assert(value>=4.5,`${key}: white/${bg} contrast ${value}`);}
   await page.getByRole('button',{name:'Elegir colores',exact:true}).click();
   const bounds=await page.locator('#color-picker-panel').boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=375&&bounds.y+bounds.height<=812);
   await page.keyboard.press('Escape');
  }
  // Same-origin line iframe updates without reload and header survives fullscreen.
  await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/tablero-linea/');
  await choose('sage');await page.keyboard.press('Escape');
  const frame=page.frameLocator('#progress-screen-frame');await frame.locator('html').waitFor();
  await page.waitForFunction(()=>document.getElementById('progress-screen-frame').contentDocument.documentElement.dataset.palette==='sage');
  await page.getByRole('button',{name:'Mostrar tablero en pantalla completa',exact:true}).click();await page.waitForFunction(()=>Boolean(document.fullscreenElement));
  assert.equal(await page.locator('.site-header').isVisible(),false);
  await page.getByRole('button',{name:'Salir de pantalla completa (Esc)',exact:true}).click();await page.waitForFunction(()=>!document.fullscreenElement);assert(await page.locator('.site-header').isVisible());
  assert.deepEqual(errors,[]);assert.deepEqual(missing,[]);assert.deepEqual(posts,[]);
  fs.writeFileSync(path.join(review,'color-checks.json'),JSON.stringify({modes,view_checks:checks.length,contrasts,errors,missing,posts,persistence:true,iframe_sync:true,keyboard_escape:true},null,2));
  console.log('PASS:',checks.length,'view checks, six palettes, contrast, persistence, single appearance control, keyboard, picker bounds, iframe sync and fullscreen; no errors/assets missing/POST requests.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
