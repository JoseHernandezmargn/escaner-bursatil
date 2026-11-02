# -*- coding: utf-8 -*-
"""
BUSCADOR MULTIFACTOR (horizonte 12 meses, rebalanceo trimestral)

Califica cada acción con cinco ingredientes que tienen evidencia académica de largo plazo:
  - Momentum 12-1: rendimiento de los últimos 12 meses sin el último mes (30%)
  - Calidad: ROE, margen neto y deuda baja (30%)
  - Crecimiento: crecimiento de ingresos y utilidades (20%)
  - Valuación: rendimiento de utilidades (1/PU) y de EBITDA (1/EV-EBITDA) (20%)
  - Filtros: precio arriba de su media de 200 días y sin volatilidad extrema (10% más volátil fuera)
Arma un portafolio equiponderado con tope por sector y lleva un seguimiento SIMULADO contra el índice.
"""

import json
import math
import os
import time

import numpy as np
import pandas as pd

PESOS = {"momentum": 0.30, "calidad": 0.30, "crecimiento": 0.20, "valuacion": 0.20}
DOBLE_SERIE = {"GOOG", "FOX", "NWS"}  # se queda GOOGL, FOXA, NWSA
CAMPOS = ["shortName", "sector", "returnOnEquity", "profitMargins", "debtToEquity", "forwardPE",
          "trailingPE", "enterpriseToEbitda", "revenueGrowth", "earningsGrowth", "marketCap"]


def _z(s):
    s = pd.to_numeric(s, errors="coerce").astype(float)
    if s.notna().sum() < 5:
        return pd.Series(0.0, index=s.index)
    lo, hi = s.quantile([0.05, 0.95])
    s = s.clip(lo, hi)
    sd = s.std()
    return ((s - s.mean()) / sd if sd > 0 else s * 0).fillna(0.0)


def factores_precio(precios):
    p = precios.ffill(limit=5)
    suficiente = p.iloc[-260:].notna().sum() >= 240
    p = p.loc[:, suficiente]
    ult = p.iloc[-1]
    mom = p.iloc[-22] / p.iloc[-253] - 1
    sma200 = p.iloc[-200:].mean()
    vol = np.log(p).diff().iloc[-252:].std() * math.sqrt(252)
    df = pd.DataFrame({"precio": ult, "momentum_12_1": mom, "sobre_sma200": ult > sma200, "vol_anual": vol})
    return df.drop(index=[t for t in df.index if t in DOBLE_SERIE], errors="ignore")


def fundamentales(tickers, ruta_cache, dias_vigencia=7, log=print):
    import yfinance as yf

    cache = {}
    if os.path.exists(ruta_cache):
        with open(ruta_cache, encoding="utf-8") as fh:
            cache = json.load(fh)
    hoy = pd.Timestamp.today()
    pendientes = [t for t in tickers
                  if t not in cache or (hoy - pd.Timestamp(cache[t].get("_fecha", "2000-01-01"))).days > dias_vigencia]
    for k, t in enumerate(pendientes):
        for intento in range(3):
            try:
                info = yf.Ticker(t).info or {}
                cache[t] = {c: info.get(c) for c in CAMPOS}
                cache[t]["_fecha"] = hoy.strftime("%Y-%m-%d")
                break
            except Exception as e:
                time.sleep(5 * (intento + 1))
                if intento == 2:
                    log(f"  sin fundamentales para {t}: {e}")
        time.sleep(0.4)
        if (k + 1) % 25 == 0:
            log(f"  fundamentales {k + 1}/{len(pendientes)}")
    os.makedirs(os.path.dirname(ruta_cache) or ".", exist_ok=True)
    with open(ruta_cache, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)
    return pd.DataFrame({t: cache.get(t, {}) for t in tickers}).T


def _rendimiento(pe):
    pe = pd.to_numeric(pe, errors="coerce")
    return pd.Series(np.where(pe > 0, 1 / pe, np.where(pe <= 0, -0.05, np.nan)), index=pe.index)


def calificar(precios, ruta_cache, n=25, max_sector=5, log=print):
    fp = factores_precio(precios)
    cand = fp[fp["sobre_sma200"] & fp["momentum_12_1"].notna()]
    cand = cand[cand["vol_anual"] <= fp["vol_anual"].quantile(0.90)]
    # Solo se piden fundamentales a las que pasan los filtros de precio y están en la mitad alta de momentum
    cand = cand[cand["momentum_12_1"] >= cand["momentum_12_1"].quantile(0.40)] if len(cand) > 3 * n else cand
    log(f"  candidatas tras filtros de precio: {len(cand)} de {len(fp)}")
    fu = fundamentales(list(cand.index), ruta_cache, log=log)
    df = cand.join(fu, how="left")

    calidad = pd.concat([_z(df["returnOnEquity"]), _z(df["profitMargins"]), -_z(df["debtToEquity"])], axis=1).mean(axis=1)
    crec = pd.concat([_z(df["revenueGrowth"]), _z(df["earningsGrowth"])], axis=1).mean(axis=1)
    pe = pd.to_numeric(df["forwardPE"], errors="coerce").fillna(pd.to_numeric(df["trailingPE"], errors="coerce"))
    valuacion = pd.concat([_z(_rendimiento(pe)), _z(_rendimiento(df["enterpriseToEbitda"]))], axis=1).mean(axis=1)
    df["z_momentum"] = _z(df["momentum_12_1"])
    df["z_calidad"], df["z_crecimiento"], df["z_valuacion"] = calidad, crec, valuacion
    cobertura = df[["returnOnEquity", "profitMargins", "revenueGrowth", "forwardPE", "trailingPE"]].notna().sum(axis=1)
    df["cobertura_fund"] = cobertura
    df["puntaje"] = (PESOS["momentum"] * df["z_momentum"] + PESOS["calidad"] * calidad
                     + PESOS["crecimiento"] * crec + PESOS["valuacion"] * valuacion)
    df.loc[cobertura < 2, "puntaje"] -= 0.5  # sin datos fundamentales suficientes: castigo
    df = df.sort_values("puntaje", ascending=False)

    elegidas, por_sector = [], {}
    for t, fila in df.iterrows():
        sec = fila.get("sector") or "Sin sector"
        if por_sector.get(sec, 0) >= max_sector:
            continue
        elegidas.append(t)
        por_sector[sec] = por_sector.get(sec, 0) + 1
        if len(elegidas) == n:
            break
    df["seleccionada"] = df.index.isin(elegidas)
    return df


# ---------------------------------------------------------------------------
# Seguimiento simulado (paper trading)
# ---------------------------------------------------------------------------
def _trimestre(fecha):
    f = pd.Timestamp(fecha)
    return f"{f.year}T{(f.month - 1) // 3 + 1}"


def _precio_en(serie, fecha):
    s = serie.dropna()
    s = s[s.index <= pd.Timestamp(fecha)]
    return float(s.iloc[-1]) if len(s) else np.nan


def seguimiento(nombre, ranking, precios, bench, carpeta, costo=0.0029):
    """
    Lleva un portafolio simulado equiponderado. Se rebalancea en la primera corrida de cada trimestre.
    Guarda estado en carpeta/cartera_<nombre>.json e historial en carpeta/historial_<nombre>.csv.
    Devuelve dict con el resumen para el reporte.
    """
    os.makedirs(carpeta, exist_ok=True)
    import unicodedata

    clave = "".join(c for c in unicodedata.normalize("NFKD", nombre.lower()) if c.isalnum())
    ruta_e = os.path.join(carpeta, f"cartera_{clave}.json")
    ruta_h = os.path.join(carpeta, f"historial_{clave}.csv")
    fecha = precios.index[-1]
    estado = json.load(open(ruta_e, encoding="utf-8")) if os.path.exists(ruta_e) else None

    def valor_actual(est):
        tot = 0.0
        for t, pos in est["posiciones"].items():
            p0 = _precio_en(precios[t], est["fecha_entrada"]) if t in precios.columns else np.nan
            p1 = _precio_en(precios[t], fecha) if t in precios.columns else np.nan
            r = p1 / p0 if (p0 and p1 and np.isfinite(p0) and np.isfinite(p1)) else 1.0
            tot += pos["peso"] * r
        b0, b1 = _precio_en(bench, est["fecha_entrada"]), _precio_en(bench, fecha)
        return est["valor_entrada"] * tot, est["bench_entrada"] * (b1 / b0 if b0 else 1.0)

    nuevas = list(ranking.index[ranking["seleccionada"]])
    altas, bajas, rebalanceo = nuevas, [], estado is None
    if estado is None:
        valor, valor_b = 100.0, 100.0
        inicio = str(fecha.date())
    else:
        valor, valor_b = valor_actual(estado)
        inicio = estado["inicio"]
        rebalanceo = _trimestre(fecha) != estado["trimestre"]
        if rebalanceo:
            viejas = set(estado["posiciones"])
            altas, bajas = sorted(set(nuevas) - viejas), sorted(viejas - set(nuevas))
            rotacion = (len(altas) + len(bajas)) / max(len(nuevas), 1)
            valor *= 1 - costo * rotacion

    if rebalanceo and nuevas:
        estado = {
            "inicio": inicio, "trimestre": _trimestre(fecha), "fecha_entrada": str(fecha.date()),
            "valor_entrada": valor, "bench_entrada": valor_b,
            "posiciones": {t: {"peso": 1 / len(nuevas),
                               "nombre": str(ranking.at[t, "shortName"] or "") if "shortName" in ranking else "",
                               "sector": str(ranking.at[t, "sector"] or "") if "sector" in ranking else ""}
                           for t in nuevas},
        }
        with open(ruta_e, "w", encoding="utf-8") as fh:
            json.dump(estado, fh, ensure_ascii=False, indent=2)

    hist = pd.read_csv(ruta_h) if os.path.exists(ruta_h) else pd.DataFrame(columns=["fecha", "portafolio", "indice"])
    hist = hist[hist["fecha"] != str(fecha.date())]
    hist = pd.concat([hist, pd.DataFrame([{"fecha": str(fecha.date()), "portafolio": round(valor, 4),
                                           "indice": round(valor_b, 4)}])], ignore_index=True)
    hist.to_csv(ruta_h, index=False)

    posiciones = []
    for t in (estado or {}).get("posiciones", {}):
        p0 = _precio_en(precios[t], estado["fecha_entrada"]) if t in precios.columns else np.nan
        p1 = _precio_en(precios[t], fecha) if t in precios.columns else np.nan
        info = estado["posiciones"][t]
        posiciones.append((t, p1, p1 / p0 - 1 if p0 else np.nan, info.get("nombre", ""), info.get("sector", "")))
    return {
        "inicio": inicio, "fecha": str(fecha.date()), "rebalanceo": rebalanceo,
        "altas": altas if rebalanceo else [], "bajas": bajas if rebalanceo else [],
        "valor": valor, "valor_indice": valor_b, "semanas": len(hist),
        "posiciones": sorted(posiciones, key=lambda x: -(x[2] if np.isfinite(x[2]) else -9)),
        "siguiente_rebalanceo": _siguiente_trimestre(fecha),
    }


def _siguiente_trimestre(fecha):
    f = pd.Timestamp(fecha)
    mes = ((f.month - 1) // 3 + 1) * 3 + 1
    anio = f.year + (1 if mes > 12 else 0)
    return f"primer viernes de {['enero','abril','julio','octubre'][((mes - 1) % 12) // 3]} {anio}"
