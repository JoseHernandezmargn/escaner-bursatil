# Escáner bursátil semanal

Corre solo cada **viernes a las 4:40 p.m. (hora de CDMX)** en GitHub Actions y te avisa por **correo** (a través de un *issue* de GitHub).

## Qué hace cada semana

1. **Valida estrategias** con 11 años de historia del IPC, S&P 500 y Nasdaq-100, separando 2017-2021 (dentro de muestra) y 2022-hoy (fuera de muestra), con comisiones e ISR, y corrigiendo por pruebas múltiples.
2. **Señales semanales de compra/venta**: solo de las estrategias que pasan la validación. Si ninguna pasa, el correo lo dice y no da señales.
3. **Buscador multifactor (operación simulada)**: portafolio de 25 acciones de EE.UU. y 8 de México que combina momentum, calidad, crecimiento y valuación, con filtros de tendencia y volatilidad, y tope por sector. Se rebalancea cada trimestre y se compara contra SPY y NAFTRAC. El historial se guarda en la carpeta `seguimiento/`.
4. **Tu lista personal** (`cartera.txt`): alerta si una acción cruza su media de 200 días o tiene un movimiento inusual en la semana.

## Archivos

| Archivo | Para qué |
|---|---|
| `cartera.txt` | Tus acciones a vigilar (edítalo en GitHub: lápiz ✏️ → *Commit changes*) |
| `validar.py` | Backtest y validación de estrategias |
| `escanear.py` | Genera el reporte semanal |
| `multifactor.py` | Buscador multifactor y seguimiento simulado |
| `estrategias.py`, `universo.py` | Estrategias y descarga de datos |
| `.github/workflows/escaner.yml` | Programa la ejecución semanal y el aviso |
| `seguimiento/` | Historial del portafolio simulado (lo actualiza el robot) |

## Cómo recibir el correo

GitHub te notifica por correo cuando se crea un *issue* en tu repositorio. Verifica en GitHub → **Settings → Notifications** que tengas activado **Email** para *Issues* y que el repositorio esté en **Watching**.

## Correrlo a mano

Pestaña **Actions** → *Escaner semanal* → **Run workflow**.

## Cómo interpretar

- **VALIDADA**: superó a comprar y mantener fuera de muestra con significancia estadística.
- **PROMETEDORA**: mejor rendimiento ajustado por riesgo en ambos periodos, sin significancia. Solo posiciones pequeñas.
- **RECHAZADA**: no da señales.
- **Multifactor**: es una simulación. Deja pasar al menos 2-3 trimestres antes de decidir si inviertes dinero real en él, y compáralo siempre contra el índice.

## Limitaciones

- Datos gratuitos de Yahoo Finance: pueden tener huecos; los fundamentales son los actuales (no históricos), por eso el multifactor solo se puede validar hacia adelante.
- Sesgo de supervivencia: el backtest usa las emisoras que están hoy en los índices.
- No es asesoría de inversión. La decisión y el riesgo son tuyos.
