#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VALIDACIÓN DE ESTRATEGIAS SEMANALES
Prueba cada estrategia en cada universo (IPC, S&P 500, Nasdaq-100) contra comprar y mantener
equiponderado del mismo universo. Divide la historia en:
  - Dentro de muestra (hasta 2021): donde "se diseñó" la estrategia.
  - Fuera de muestra (2022 en adelante): la prueba que cuenta.
Corrige por comparaciones múltiples (Holm) porque se prueban varias combinaciones a la vez.
Resultado: validacion.json (lo usa el escáner) y validacion.html.
"""

import argparse
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats

import estrategias as E
import universo as U

CORTE = "2021-12-31"
SEMANAS = 52


def impuestos_anuales(r, isr):
    """ISR aproximado: isr% sobre la ganancia positiva de cada año calendario (la estrategia realiza ganancias)."""
    out = r.copy()
    for _, idx in r.groupby(r.index.year).groups.items():
        g = (1 + r.loc[idx]).prod() - 1
        if g > 0:
            out.loc[idx[-1]] = (1 + out.loc[idx[-1]]) * (1 - isr * g / (1 + g)) - 1
    return out


def impuesto_final(r, isr):
    out = r.copy()
    g = (1 + r).prod() - 1
    if g > 0 and len(r):
        out.iloc[-1] = (1 + out.iloc[-1]) * (1 - isr * g / (1 + g)) - 1
    return out


def metricas(r):
    r = r.dropna()
    if len(r) < 20:
        return dict(CAGR=np.nan, Vol=np.nan, Sharpe=np.nan, MaxDD=np.nan)
    eq = (1 + r).cumprod()
    anios = len(r) / SEMANAS
    return dict(
        CAGR=eq.iloc[-1] ** (1 / anios) - 1,
        Vol=r.std() * math.sqrt(SEMANAS),
        Sharpe=r.mean() / r.std() * math.sqrt(SEMANAS) if r.std() > 0 else np.nan,
        MaxDD=(eq / eq.cummax() - 1).min(),
    )


def prueba_activa(r, b):
    """¿La estrategia supera a la referencia? t de la diferencia semanal (H1: media > 0)."""
    d = (r - b).dropna()
    if len(d) < 20 or d.std() == 0:
        return np.nan, 1.0
    t = d.mean() / d.std() * math.sqrt(len(d))
    return t, float(stats.t.sf(t, len(d) - 1))


def holm(pvals):
    p = np.array(pvals, dtype=float)
    orden = np.argsort(p)
    ajust = np.empty_like(p)
    m, acum = len(p), 0.0
    for k, i in enumerate(orden):
        acum = max(acum, (m - k) * p[i])
        ajust[i] = min(1.0, acum)
    return ajust


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--costo", type=float, default=0.29, help="Comisión %% por lado")
    ap.add_argument("--isr", type=float, default=10.0)
    ap.add_argument("--anios", type=int, default=11)
    ap.add_argument("--salida", default="resultados")
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)

    filas, curvas = [], {}
    for nombre_u, tickers in U.universos().items():
        print(f"\n=== {nombre_u}: descargando {len(tickers)} emisoras ===", flush=True)
        precios = U.descargar(tickers, anios=a.anios)
        if precios.shape[1] < 10:
            print("  muy pocas emisoras con datos; se omite")
            continue
        pan = E.panel_semanal(precios)
        bench = E.referencia(pan)
        inicio = pan["sma200"].dropna(how="all").index[0] + pd.Timedelta(weeks=52)
        bench = bench.loc[inicio:]
        curvas[(nombre_u, "REFERENCIA")] = bench
        for est in E.ESTRATEGIAS:
            w = E.pesos(est, pan)
            r, rot = E.rendimientos(w, pan["ret"], costo=a.costo / 100)
            r = r.loc[inicio:]
            curvas[(nombre_u, est)] = r
            for periodo, sl in (("DENTRO", slice(None, CORTE)), ("FUERA", slice("2022-01-01", None))):
                rs = impuestos_anuales(r.loc[sl], a.isr / 100)
                bs = impuesto_final(bench.loc[sl], a.isr / 100)
                me, mb = metricas(rs), metricas(bs)
                t, p = prueba_activa(rs, bs)
                filas.append(dict(
                    universo=nombre_u, estrategia=est, periodo=periodo,
                    desde=str(rs.index[0].date()), hasta=str(rs.index[-1].date()),
                    CAGR=me["CAGR"], CAGR_ref=mb["CAGR"], Sharpe=me["Sharpe"], Sharpe_ref=mb["Sharpe"],
                    MaxDD=me["MaxDD"], MaxDD_ref=mb["MaxDD"], Vol=me["Vol"], Vol_ref=mb["Vol"],
                    t=t, p=p, rotacion_anual=float(rot.loc[sl].mean() * SEMANAS),
                    emisoras=int(precios.shape[1]),
                ))
            f = [x for x in filas if x["universo"] == nombre_u and x["estrategia"] == est]
            print(f"  {est:14s} fuera de muestra: CAGR {f[1]['CAGR']*100:6.1f}% vs ref {f[1]['CAGR_ref']*100:6.1f}% | "
                  f"Sharpe {f[1]['Sharpe']:.2f} vs {f[1]['Sharpe_ref']:.2f} | p={f[1]['p']:.3f}", flush=True)

    df = pd.DataFrame(filas)
    fuera = df["periodo"] == "FUERA"
    df.loc[fuera, "p_holm"] = holm(df.loc[fuera, "p"].values)
    df.loc[~fuera, "p_holm"] = np.nan

    # Veredicto por combinación
    veredictos = {}
    for (u, e), g in df.groupby(["universo", "estrategia"]):
        di, fu = g[g.periodo == "DENTRO"].iloc[0], g[g.periodo == "FUERA"].iloc[0]
        mejor_riesgo = (fu.Sharpe > fu.Sharpe_ref) and (di.Sharpe > di.Sharpe_ref)
        menor_caida = fu.MaxDD > fu.MaxDD_ref + 0.05
        if fu.p_holm < 0.05 and mejor_riesgo:
            v = "VALIDADA"
        elif mejor_riesgo or (menor_caida and fu.Sharpe >= fu.Sharpe_ref - 0.05):
            v = "PROMETEDORA"
        else:
            v = "RECHAZADA"
        veredictos[f"{u}|{e}"] = v
    df["veredicto"] = [veredictos[f"{u}|{e}"] for u, e in zip(df.universo, df.estrategia)]

    df.to_csv(os.path.join(a.salida, "validacion.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(a.salida, "validacion.json"), "w", encoding="utf-8") as fh:
        json.dump({"fecha": dt.date.today().isoformat(), "veredictos": veredictos,
                   "costo": a.costo, "isr": a.isr}, fh, ensure_ascii=False, indent=2)
    pd.DataFrame(curvas).to_pickle(os.path.join(a.salida, "curvas.pkl"))

    print("\n=== VEREDICTOS ===")
    for k, v in veredictos.items():
        print(f"  {k:32s} {v}")
    print("\nResultados en", os.path.abspath(a.salida))


if __name__ == "__main__":
    main()
