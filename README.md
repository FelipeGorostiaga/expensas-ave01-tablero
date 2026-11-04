# Tablero de expensas · Fideicomiso AVE 01

Lee las liquidaciones de expensas en PDF (formato Octopus) y arma un tablero con:
variación de precios por proveedor, morosidad por unidad, estado financiero y
controles automáticos sobre la administración.

## Archivos

- `parse_expensas.py` — lee todos los PDF de una carpeta y genera `data.json` y `data.js`.
- `index.html` — el tablero. Carga `data.js` y calcula todo en el navegador.
- `data.json` / `data.js` — datos extraídos (se regeneran; no editar a mano).
- `refresh.sh` — regenera los datos (crea el entorno virtual la primera vez). Deja un `refresh.log`.

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

El tablero se publica en Cloudflare Pages a partir del repositorio privado
`github.com/FelipeGorostiaga/expensas-ave01` (cuenta personal). `refresh.sh` hace
commit y push de `data.js` cada vez que cambia, y Cloudflare redespliega solo en uno
o dos minutos. Los PDF nunca se suben: `.gitignore` los excluye.

Configuración en Cloudflare (una sola vez, con la cuenta personal):

1. Workers & Pages → Create → Pages → Connect to Git → autorizar la app de GitHub
   solo para el repo `expensas-ave01` → Framework preset: None, Build command: vacío,
   Build output directory: `/` → Save and Deploy. Queda en `https://<nombre>.pages.dev`.
2. Para que solo entren los vecinos: Zero Trust → Access → Applications → Add an
   application → Self-hosted → dominio `<nombre>.pages.dev` → política *Allow* con
   regla *Emails* (la lista de mails de los vecinos) → listo. Cada vecino entra con un
   código que le llega por mail; no hace falta cuenta de Cloudflare. El plan gratuito
   cubre hasta 50 personas.

Para dar de alta o baja a un vecino, se edita la lista de mails de esa política.

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
