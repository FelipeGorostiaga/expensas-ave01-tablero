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
muestra en la pestaña **Controles**.

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
`FORCE=1 ./refresh.sh`. El tablero muestra el saldo real en Finanzas, Resumen, Novedades y
Controles para esos meses. No hace falta tener el extracto de todos los meses.

## Qué calcula el tablero

Arriba de todo hay dos selectores: el **mes** (por defecto, el último) y la **unidad**. El mes
elegido se compara siempre con el anterior y manda sobre Resumen, Novedades, Precios,
Unidades, Finanzas y el filtro de Detalle. La unidad elegida se recuerda en el dispositivo.

- **Resumen**: gasto del mes elegido, variación contra el mes anterior, deuda de propietarios,
  saldo de caja, costo de administrar, tabla mes a mes (clic en una fila cambia el mes),
  hallazgos del período y preguntas para la administración.
- **Novedades**: todo lo que cambió en el mes elegido: proveedores nuevos o que dejaron de
  facturar, subas y bajas, gastos puntuales, unidades que dejaron de pagar o se pusieron al
  día, previsiones, notas de la administración.
- **Precios**: importe neto por proveedor y mes, qué cambió contra el mes anterior, índice
  base 100, variación del período y mayor salto.
- **Proveedores**: CUIT, meses activos, promedio mensual, concentración del gasto,
  proveedores que dejaron de aparecer o que son nuevos (todo el período).
- **Unidades y morosidad**: deudores al cierre del mes elegido, cobranza, historial de pago
  de todas las unidades, y para la unidad elegida: **qué pagás vos** (la cuota del mes
  desglosada por proveedor y rubro según el coeficiente) y su historial.
- **Finanzas**: saldo al cierre (impreso y más previsiones), ingresos vs. gastos, y para el
  mes elegido: gasto por rubro, estado financiero y patrimonial comparado con el mes
  anterior, previsiones hechas y reintegradas.
- **Controles**: encadenamiento de saldos, aritmética del estado financiero, coeficientes,
  saltos de precio, posibles duplicados, proveedores sin CUIT, etc.
- **Detalle**: todas las facturas con filtros por mes, rubro y texto.

Las variaciones son nominales (sin ajustar por inflación).
