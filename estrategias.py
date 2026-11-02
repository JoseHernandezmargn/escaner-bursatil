# -*- coding: utf-8 -*-
"""
Estrategias semanales. Todas usan solo información disponible al cierre del viernes (semana t)
y se aplican a la semana siguiente (t+1). Devuelven una matriz de pesos por semana.
"""

import numpy as np
import pandas as pd

ESTRATEGIAS = {
    "TENDENCIA": "Mantener acciones con precio > media de 200 días y media 50 > media 200; el resto en efectivo.",
    "MOMENTUM": "Cada 4 semanas, comprar el 20% de acciones con mayor rendimiento de 12 meses (sin el último mes).",
    "MOMENTUM+TEND": "Momentum, pero solo acciones en tendencia alcista (precio > media 200 días).",
    "RETROCESO": "Cada semana, comprar acciones en tendencia alcista que cayeron más en la semana (10% peor); vender a la semana.",
    "MULTIFACTOR_PRECIO": "Parte de precio del buscador multifactor: cada trimestre, 25 acciones (8 en el IPC) con mejor momentum 12-1 "
                          "y menor volatilidad, en tendencia alcista y sin el 10% más volátil.",
}

# Estrategias que generan señales semanales de compra/venta (el multifactor se reporta aparte, cada trimestre)
SEMANALES = ["TENDENCIA", "MOMENTUM", "MOMENTUM+TEND", "RETROCESO"]


def panel_semanal(precios_diarios):
    p = precios_diarios.sort_index()
    sma50 = p.rolling(50, min_periods=45).mean()
    sma200 = p.rolling(200, min_periods=180).mean()
    w = p.resample("W-FRI").last()
    # Si la última semana aún no termina (p. ej. se corre un lunes), se descarta para no usar datos parciales
    if len(w) and pd.Timestamp.today().normalize() < w.index[-1]:
        w = w.iloc[:-1]
    return {
        "precio": w,
        "sma50": sma50.resample("W-FRI").last().reindex(w.index),
        "sma200": sma200.resample("W-FRI").last().reindex(w.index),
        "ret": w.pct_change(fill_method=None),
    }


def _equiponderar(mask):
    m = mask.astype(float)
    n = m.sum(axis=1).replace(0, np.nan)
    return m.div(n, axis=0).fillna(0.0)


def pesos(nombre, pan, top=0.20, cada=4, cola=0.10):
    precio, s50, s200, ret = pan["precio"], pan["sma50"], pan["sma200"], pan["ret"]
    valido = precio.notna() & s200.notna()
    tend = (precio > s200) & (s50 > s200) & valido
    if nombre == "TENDENCIA":
        return _equiponderar(tend)

    if nombre in ("MOMENTUM", "MOMENTUM+TEND"):
        mom = precio.shift(4) / precio.shift(52) - 1
        if nombre == "MOMENTUM+TEND":
            mom = mom.where(precio > s200)
        rank = mom.rank(axis=1, pct=True, ascending=False)
        sel = (rank <= top) & mom.notna()
        w = _equiponderar(sel)
        # solo rebalancea cada `cada` semanas: entre rebalanceos se conserva la cartera
        idx = np.arange(len(w)) % cada == 0
        w = w.where(pd.Series(idx, index=w.index), np.nan).ffill().fillna(0.0)
        return w

    if nombre == "MULTIFACTOR_PRECIO":
        n = 25 if precio.shape[1] > 100 else 8
        mom = precio.shift(4) / precio.shift(52) - 1
        vol = ret.rolling(52, min_periods=40).std()
        ok = (precio > s200) & mom.notna() & vol.notna() & (vol.rank(axis=1, pct=True) <= 0.90)

        def zfila(df):
            df = df.where(ok)
            return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)

        score = (zfila(mom) - 0.5 * zfila(vol)).where(ok)
        sel = score.rank(axis=1, ascending=False) <= n
        w = _equiponderar(sel)
        idx = np.arange(len(w)) % 13 == 0
        return w.where(pd.Series(idx, index=w.index), np.nan).ffill().fillna(0.0)

    if nombre == "RETROCESO":
        r_tend = ret.where(precio > s200)
        rank = r_tend.rank(axis=1, pct=True, ascending=True)
        return _equiponderar((rank <= cola) & r_tend.notna())

    raise ValueError(nombre)


def senales_actuales(nombre, pan, **kw):
    """Acciones que la estrategia tendría la próxima semana, y altas/bajas vs la semana anterior."""
    w = pesos(nombre, pan, **kw)
    ultimo, previo = w.iloc[-1], w.iloc[-2]
    tiene = set(ultimo[ultimo > 0].index)
    tenia = set(previo[previo > 0].index)
    return sorted(tiene), sorted(tiene - tenia), sorted(tenia - tiene)


def rendimientos(w, ret, costo=0.0029):
    """Rendimiento semanal neto de comisiones. Pesos de la semana t se aplican a la semana t+1."""
    r = ret.fillna(0.0)
    w_lag = w.shift(1).fillna(0.0)
    bruto = (w_lag * r).sum(axis=1)
    rotacion = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).shift(1).fillna(0.0)
    return bruto - rotacion * costo, rotacion


def referencia(pan):
    """Comprar y mantener equiponderado del mismo universo (sin costos)."""
    valido = pan["precio"].notna() & pan["sma200"].notna()
    return rendimientos(_equiponderar(valido), pan["ret"], costo=0.0)[0]
