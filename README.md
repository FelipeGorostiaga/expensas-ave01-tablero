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

## Qué calcula el tablero

- **Resumen**: gasto del mes, variación, deuda de propietarios, saldo de caja, costo de
  administrar y los hallazgos principales.
- **Precios**: importe neto por proveedor y mes (sin previsiones ni reintegros), variación
  entre el primer y el último mes, mayor salto mensual, índice base 100.
- **Proveedores**: CUIT, meses activos, promedio mensual, concentración del gasto,
  proveedores que dejaron de aparecer o que son nuevos.
- **Unidades y morosidad**: deudores, intereses, cobranza, historial de pago de las
  111 unidades y la evolución de la unidad de referencia.
- **Finanzas**: saldo al cierre, ingresos vs. gastos, estado financiero y patrimonial
  mes a mes, conciliación de previsiones y reintegros.
- **Controles**: encadenamiento de saldos, aritmética del estado financiero,
  coeficientes, saltos de precio, posibles duplicados, proveedores sin CUIT, etc.
- **Detalle**: todas las facturas con filtros por mes, rubro y texto.

Las variaciones son nominales (sin ajustar por inflación).
