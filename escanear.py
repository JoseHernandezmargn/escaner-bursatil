#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESCÁNER SEMANAL
Corre cada viernes después del cierre. Para cada universo (IPC, S&P 500, Nasdaq-100):
  1. Toma las estrategias que pasaron la validación (validacion.json).
  2. Dice qué acciones ENTRAN (compra) y SALEN (venta) de la cartera de la estrategia la próxima semana.
  3. Revisa tu lista personal (cartera.txt): cruces de la media de 200 días y movimientos inusuales.
Genera reporte_semanal.md (cuerpo del correo) y reporte_semanal.html.
"""

import argparse
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd

import estrategias as E
import multifactor as MF
import universo as U

NIVEL = {"VALIDADA": 2, "PROMETEDORA": 1, "RECHAZADA": 0}


def leer_cartera(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as fh:
        return [l.split("#")[0].strip().upper() for l in fh if l.split("#")[0].strip()]


def alertas_cartera(precios, tickers):
    filas = []
    for t in tickers:
        if t not in precios.columns:
            filas.append((t, "sin datos en Yahoo", ""))
            continue
        p = precios[t].dropna()
        if len(p) < 210:
            filas.append((t, "historia insuficiente", ""))
            continue
        sma200 = p.rolling(200).mean()
        w = p.resample("W-FRI").last()
        s = sma200.resample("W-FRI").last()
        rw = w.pct_change().dropna()
        sig = rw.iloc[-53:-1].std()
        ult = rw.iloc[-1]
        notas = []
        if w.iloc[-2] <= s.iloc[-2] and w.iloc[-1] > s.iloc[-1]:
            notas.append("cruzó ARRIBA de su media de 200 días (cambio a tendencia alcista)")
        elif w.iloc[-2] >= s.iloc[-2] and w.iloc[-1] < s.iloc[-1]:
            notas.append("cruzó ABAJO de su media de 200 días (cambio a tendencia bajista)")
        if sig > 0 and abs(ult) > 2 * sig:
            notas.append(f"movimiento inusual en la semana: {ult*100:+.1f}% (más de 2 desviaciones)")
        estado = "arriba" if w.iloc[-1] > s.iloc[-1] else "abajo"
        filas.append((t, "; ".join(notas) or "sin cambios relevantes",
                      f"{w.iloc[-1]:,.2f} | semana {ult*100:+.1f}% | {estado} de su media 200d"))
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validacion", default="resultados/validacion.json")
    ap.add_argument("--cartera", default="cartera.txt")
    ap.add_argument("--salida", default="resultados")
    ap.add_argument("--anios", type=int, default=11)
    ap.add_argument("--seguimiento", default="seguimiento", help="Carpeta del portafolio simulado (se guarda en el repo)")
    ap.add_argument("--max-lista", type=int, default=15, help="Máximo de acciones listadas por señal")
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)

    ver = {}
    if os.path.exists(a.validacion):
        with open(a.validacion, encoding="utf-8") as fh:
            ver = json.load(fh).get("veredictos", {})

    hoy = dt.date.today()
    md = [f"# Escáner semanal — {hoy.strftime('%d/%m/%Y')}", ""]
    md.append("> Herramienta de análisis personal, no asesoría de inversión. Las señales son de mediano plazo "
              "(semanas). Revisa el riesgo y el tamaño de cada posición antes de operar.")
    md.append("")

    todos = {}
    resumen_senales = 0
    for nombre_u, tickers in U.universos().items():
        precios = U.descargar(tickers, anios=a.anios)
        if precios.shape[1] < 10:
            continue
        todos[nombre_u] = precios
        pan = E.panel_semanal(precios)
        fecha_dato = pan["precio"].index[-1].date()
        md.append(f"## {nombre_u} ({precios.shape[1]} emisoras, datos al {fecha_dato.strftime('%d/%m/%Y')})")
        usadas = [(e, ver.get(f"{nombre_u}|{e}", "SIN VALIDAR")) for e in E.SEMANALES]
        activas = [(e, v) for e, v in usadas if NIVEL.get(v, 0) >= 1]
        if not activas:
            md.append("Ninguna estrategia pasó la validación en este universo. **No hay señales de compra/venta.** "
                      "(Así se evita operar con señales que no han demostrado ventaja.)")
            md.append("")
            continue
        for est, v in activas:
            cartera, altas, bajas = E.senales_actuales(est, pan)
            resumen_senales += len(altas) + len(bajas)
            etiqueta = "✅ VALIDADA" if v == "VALIDADA" else "🟡 PROMETEDORA (sin significancia estadística)"
            md.append(f"### {est} — {etiqueta}")
            md.append(f"_{E.ESTRATEGIAS[est]}_")
            md.append("")

            def lista(xs):
                if not xs:
                    return "ninguna"
                extra = f" … y {len(xs) - a.max_lista} más" if len(xs) > a.max_lista else ""
                return ", ".join(f"`{x}`" for x in xs[: a.max_lista]) + extra

            md.append(f"- **COMPRAR (entran):** {lista(altas)}")
            md.append(f"- **VENDER (salen):** {lista(bajas)}")
            md.append(f"- Cartera completa de la estrategia ({len(cartera)}): {lista(cartera)}")
            md.append("")

    # ---------------- Buscador multifactor (trimestral, operación simulada) ----------------
    md.append("## Buscador multifactor — operación simulada")
    md.append("_Portafolio de 12 meses: momentum, calidad, crecimiento y valuación, con filtro de tendencia y volatilidad. "
              "Se rebalancea cada trimestre. Es SIMULADO: sirve para medir si funciona antes de invertir dinero real._")
    md.append("")
    v_mf = {k.split("|")[0]: v for k, v in ver.items() if k.endswith("|MULTIFACTOR_PRECIO")}
    mercados = []
    eeuu = [todos[k] for k in ("S&P 500", "Nasdaq-100") if k in todos]
    if eeuu:
        p_us = pd.concat(eeuu, axis=1)
        mercados.append(("EE.UU.", p_us.loc[:, ~p_us.columns.duplicated()], 25, 4, ["SPY"], v_mf.get("S&P 500")))
    if "IPC" in todos:
        mercados.append(("México", todos["IPC"], 8, 3, ["NAFTRACISHRS.MX", "^MXX"], v_mf.get("IPC")))
    for nombre_m, precios_m, n, max_sec, benchs, v_precio in mercados:
        try:
            print(f"\n=== Multifactor {nombre_m} ===", flush=True)
            rk = MF.calificar(precios_m, os.path.join("cache", "fundamentales.json"), n=n, max_sector=max_sec)
            bench, bname = None, ""
            for b in benchs:
                bp = U.descargar([b], anios=2)
                if b in bp.columns and bp[b].notna().sum() > 100:
                    bench, bname = bp[b], b
                    break
            if bench is None:
                raise ValueError("no se pudo descargar el índice de referencia")
            s = MF.seguimiento(nombre_m, rk, precios_m, bench, a.seguimiento)
            rk.to_csv(os.path.join(a.salida, f"ranking_multifactor_{nombre_m.replace('.', '')}.csv"), encoding="utf-8-sig")
            dif = (s["valor"] / s["valor_indice"] - 1) * 100
            md.append(f"### {nombre_m} — {n} acciones (referencia: {bname})")
            if v_precio:
                md.append(f"Backtest de la parte de precio (2017-2026): **{v_precio}**.")
            md.append(f"- Simulación desde {s['inicio']}: portafolio **{s['valor'] - 100:+.1f}%** vs índice "
                      f"**{s['valor_indice'] - 100:+.1f}%** (diferencia {dif:+.1f} pts, {s['semanas']} semanas registradas).")
            if s["rebalanceo"]:
                md.append(f"- **Rebalanceo de este trimestre.** Entran: {', '.join(f'`{t}`' for t in s['altas']) or 'ninguna'}. "
                          f"Salen: {', '.join(f'`{t}`' for t in s['bajas']) or 'ninguna'}.")
            else:
                md.append(f"- Sin cambios hasta el {s['siguiente_rebalanceo']}.")
            md.append("")
            md.append("| Acción | Empresa | Sector | Precio | Desde entrada | Mom. 12-1 | Puntaje |")
            md.append("|---|---|---|---|---|---|---|")
            def pct(x, dec=1):
                return f"{x*100:+.{dec}f}%" if isinstance(x, (int, float)) and np.isfinite(x) else "s/d"

            for t, p1, r, nom, sec in s["posiciones"]:
                f = rk.loc[t] if t in rk.index else pd.Series(dtype=object)
                mom, pun = f.get("momentum_12_1", np.nan), f.get("puntaje", np.nan)
                precio = f"{p1:,.2f}" if np.isfinite(p1) else "s/d"
                pun_txt = f"{pun:+.2f}" if isinstance(pun, (int, float)) and np.isfinite(pun) else "fuera del top"
                md.append(f"| `{t}` | {nom[:28]} | {sec} | {precio} | {pct(r)} | {pct(mom, 0)} | {pun_txt} |")
            md.append("")
        except Exception as e:
            md.append(f"### {nombre_m}: no se pudo calcular ({e})")
            md.append("")

    cartera = leer_cartera(a.cartera)
    if cartera:
        faltan = [t for t in cartera if not any(t in p.columns for p in todos.values())]
        extra = U.descargar(faltan, anios=a.anios) if faltan else pd.DataFrame()
        precios_todos = pd.concat([*todos.values(), extra], axis=1)
        precios_todos = precios_todos.loc[:, ~precios_todos.columns.duplicated()]
        md.append("## Tu lista personal (cartera.txt)")
        md.append("| Acción | Alerta | Precio / semana / tendencia |")
        md.append("|---|---|---|")
        for t, alerta, info in alertas_cartera(precios_todos, cartera):
            md.append(f"| `{t}` | {alerta} | {info} |")
        md.append("")

    md.append("---")
    md.append("Estados: ✅ VALIDADA = superó a comprar y mantener fuera de muestra con significancia estadística "
              "(corregida por pruebas múltiples). 🟡 PROMETEDORA = mejor rendimiento ajustado por riesgo en ambos "
              "periodos, pero sin significancia; úsala con posiciones pequeñas.")

    texto = "\n".join(md)
    with open(os.path.join(a.salida, "reporte_semanal.md"), "w", encoding="utf-8") as fh:
        fh.write(texto)
    with open(os.path.join(a.salida, "titulo.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Escáner semanal {hoy.strftime('%d/%m/%Y')}: {resumen_senales} señales")
    print(texto)


if __name__ == "__main__":
    main()
