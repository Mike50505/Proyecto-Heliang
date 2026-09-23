# Fondo de partículas

Canvas 2D en la plantilla común de Django (`templates/base.html`). Su tamaño
es el área visible, incluso cuando la página contiene tablas largas. Las tarjetas
conservan su fondo y el lienzo decorativo no recibe clics ni foco.

Los parámetros están en `static/js/particles.js`, en `DEFAULTS`. También se pueden
sobrescribir definiendo `window.MESA_PARTICLES_CONFIG` antes de cargar el script:

```js
window.MESA_PARTICLES_CONFIG = {
  count: 950, mobileCount: 140,
  colors: ['#4967ff', '#7156dd', '#bd4590', '#ff4b62', '#ff843c', '#ffb900'],
  darkColors: ['#8195ff', '#a28aff', '#e17bc0', '#ff7b8b', '#ffab77', '#ffd268'],
  minSize: 0.8, maxSize: 1.5,
  minOpacity: 0.55, maxOpacity: 0.95,
  influenceRadius: 520,
  attraction: 0.65,
  damping: 1.15,
  maxSpeed: 32,
  idleSpeed: 2.5,
  cursorLag: 0.7,
  cursorDamping: 0.95,
  turnTime: 0.35,
  releaseTime: 1.2,
  dispersion: 160,
  swirl: 0.09,
  minLength: 0.5, maxLength: 3.8,
};
```

Distancias en píxeles CSS y tiempos en segundos. `count` es un máximo; la densidad
y `mobileCount` reducen la cantidad en pantallas pequeñas. La velocidad máxima se
expresa en píxeles por segundo; mayor `cursorLag` añade retraso, mayor `damping`
reduce la inercia. El objetivo del cursor usa un resorte amortiguado que conserva
velocidad al cambiar de dirección (`cursorDamping`). `turnTime` suaviza la
orientación de los trazos. El color cambia continuamente y los trazos se desvanecen
en los bordes antes de reaparecer al otro lado.
Se integra la física en pasos de 1/120 s y se limita el tiempo
acumulado al reanudar una pestaña. Cada partícula tiene un objetivo desplazado
del cursor para mantener dispersión. `swirl` añade una fuerza tangencial suave.
Se dibujan microtrazos orientados en curvas, con un degradado espacial de azul a
ámbar y mayor presencia alrededor del cursor. Una onda ambiental lenta mantiene
el efecto visible en reposo. `minLength` y `maxLength` controlan la longitud de
los trazos. `maxDpr` y `maxPixels` limitan el bitmap.

Con movimiento reducido se dibuja una imagen estática. El cambio de tema sigue
funcionando. La animación se pausa fuera de pantalla y en pestañas ocultas.
`window.mesaParticles.destroy()` cancela RAF, eventos y observadores; también se
ejecuta al retirar el canvas o salir de la página. `pageshow` restaura el efecto
al volver mediante la caché de navegación. Para una sección específica se puede
crear `new ParticleBackground(canvas, options)` con un canvas posicionado dentro
de su contenedor, y llamar a `destroy()` al desmontarlo.

Verificación en Chrome con Playwright instalado fuera de las dependencias del
sitio: `node tests/check_particles.cjs http://127.0.0.1/`. Opcionalmente, definir
`PLAYWRIGHT_MODULE` con la ruta de una instalación temporal y pasar como tercer
argumento una carpeta para capturas. Comprueba inercia, dispersión, retorno al
reposo, 30/144 Hz, resolución, clics, temas, móvil, movimiento reducido y limpieza.
