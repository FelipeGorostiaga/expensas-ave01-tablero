# Tablero de expensas · Fideicomiso AVE 01

Lee las liquidaciones de expensas en PDF (formato Octopus) y arma un tablero con:
variación de precios por proveedor, morosidad por unidad, estado financiero y
controles automáticos sobre la administración.

## Archivos

- `parse_expensas.py` — lee todos los PDF de una carpeta y genera `data.json` y `data.js`.
- `index.html` — el tablero. Carga `data.js` y calcula todo en el navegador.
- `data.json` / `data.js` — datos extraídos (se regeneran; no editar a mano).
- `refresh.sh` — regenera los datos (crea el entorno virtual la primera vez). Deja un `refresh.log`.
- `encrypt_data.py` — cifra `data.json` → `data.enc` con la clave de `.password` para publicarlo.
- `data.enc` — datos cifrados que se publican; `data.js` queda solo para uso local.

## Regenerar cuando llega una liquidación nueva

Alcanza con copiar el PDF nuevo a la carpeta `Expensas` (la de arriba de esta).
Hay tres formas de que los datos se actualicen:

1. **Automática.** Un agente de `launchd` (`~/Library/LaunchAgents/com.felipegorostiaga.expensas-refresh.plist`)
   ejecuta cada 10 minutos `~/Applications/Expensas Refresh.app`, que corre `refresh.sh`. El script
   compara la lista de PDF (nombres, tamaños y fechas) con la última corrida y solo trabaja si
   cambió; si no, termina en silencio. La primera vez macOS pregunta si "Expensas Refresh" puede
   acceder a la carpeta Documentos: hay que aceptar (o darle permiso en Ajustes del Sistema →
   Privacidad y seguridad → Archivos y carpetas). Un PDF nuevo tarda como máximo 10 minutos en
   verse reflejado, más uno o dos minutos de despliegue en Cloudflare.
2. **Doble clic.** `Actualizar tablero.command` (en la carpeta `Expensas`) regenera los datos
   al instante (sin esperar los 10 minutos), muestra el resultado y abre el tablero.
3. **A mano.**

```bash
FORCE=1 ./refresh.sh
```

Todas escriben en `refresh.log` una línea por mes con `OK` o la lista de diferencias que
encontró. Cada mes se valida contra los propios totales impresos en el PDF: la suma de
facturas tiene que coincidir con el total de cada rubro y con el total general, y la suma de
las filas por unidad con la fila de totales del prorrateo. Si un mes no da `OK`, el tablero lo
muestra en la pestaña **Revisar**.

Después de regenerar, basta con recargar `index.html` en el navegador. La versión publicada
en claude.ai no se actualiza sola: hay que volver a publicar `index.html` junto con `data.js`
(pedírselo a Claude desde esta carpeta).

Para desactivar la actualización automática:

```bash
launchctl bootout gui/$(id -u)/com.felipegorostiaga.expensas-refresh && rm ~/Library/LaunchAgents/com.felipegorostiaga.expensas-refresh.plist
```

## Publicación para los vecinos

El tablero se publica en **GitHub Pages** desde el repositorio público
`github.com/FelipeGorostiaga/expensas-ave01-tablero` (cuenta personal), en
`https://felipegorostiaga.github.io/expensas-ave01-tablero/`.

Como el repositorio es público, los datos **no se suben en claro**: `refresh.sh` cifra
`data.json` con la clave guardada en `.password` (AES-256-GCM, clave derivada con PBKDF2)
y publica solo `data.enc`. La página pide la clave, descifra en el navegador y la recuerda
en ese dispositivo. Sin la clave, el repositorio solo expone el código del tablero.
Los PDF y `data.js` (sin cifrar) nunca se suben.

- **Cambiar la clave:** editar `.password`, ejecutar `FORCE=1 ./refresh.sh` y avisar al grupo.
- **Activar Pages (una vez):** en GitHub, Settings → Pages → Source: *Deploy from a branch*,
  Branch: `main`, carpeta `/ (root)`. Cada push redespliega en un minuto.

## Extractos bancarios

La liquidación imprime un saldo contable que descuenta las previsiones no pagadas. Cuando la
administración entrega un extracto bancario, cargá sus números en `bank_statements.json`
(un objeto por mes: `period`, `opening`, `closing`, `min_balance`, `deposits`, `sircreb`,
`sircreb_rate`, `ley25413`, `fees`, `iibb_payments`, `source`, `notes`) y regenerá con
`FORCE=1 ./refresh.sh`. El tablero muestra el saldo real en Caja, Resumen y
Revisar para esos meses. No hace falta tener el extracto de todos los meses.

## Qué calcula el tablero

Arriba de todo está el **selector de mes**: una línea con el gasto total de cada liquidación
(en el teléfono, flechas y puntos). El mes elegido manda sobre toda la página y se compara
siempre con el anterior. La **unidad** se elige con el botón "Mi unidad": no hay ninguna
elegida por defecto y la elección se guarda solo en ese dispositivo. El botón de al lado cambia
entre tema oscuro y claro.

Son seis pestañas, cada una responde una pregunta:

- **Resumen** (¿qué pasó este mes?): gasto del mes, cuota de la unidad elegida, cobranza,
  deuda, saldo de caja, gastos bancarios, costo de administrar, qué movió el gasto contra el
  mes anterior (cascada por proveedor), alertas del mes, reparto por rubro y gasto mensual
  por rubro. Plegado: novedades de proveedores, notas de la administración y tabla mes a mes.
- **Mi unidad** (¿cuánto pago yo?): cuota del mes, coeficiente y si cambió, cuota mes a mes
  (expensas, ABL, cargos particulares), a qué proveedores les paga la unidad y el reparto
  por rubro. Plegado: historial completo de la unidad con pagos y estado.
- **Gastos** (¿en qué se gasta?): explorador por rubro, cuánto subió cada proveedor en el
  período, ficha de cada proveedor (CUIT, alertas, facturas) y facturas del mes con búsqueda
  (o de todos los meses). Plegado: totales por rubro original y matriz proveedor por mes.
- **Morosidad** (¿quién no paga?): deuda y cobranza por mes, quién debe, mapa de pagos de
  cada unidad y qué cambió en el mes.
- **Caja** (¿hay plata?): saldo impreso contra el banco, ingresos contra gastos, desglose de
  los gastos bancarios según el extracto, extracto del mes y previsiones vigentes. Plegado:
  saldo de cada mes, previsiones y reintegros, estado financiero y patrimonial completo.
- **Revisar** (¿qué preguntar?): los controles automáticos (encadenamiento de saldos,
  aritmética del estado financiero, coeficientes, saltos de precio, posibles duplicados,
  proveedores sin CUIT, etc.) y las preguntas para la administración, con un botón para
  copiarlas.

Las tablas completas de la versión anterior siguen estando: aparecen como secciones
plegables ("Ver…") dentro de la pestaña que corresponde.

Las variaciones son nominales (sin ajustar por inflación).
