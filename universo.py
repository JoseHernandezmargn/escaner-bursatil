# -*- coding: utf-8 -*-
"""Universo de acciones: IPC (BMV), S&P 500 y Nasdaq-100, y descarga de precios desde Yahoo Finance."""

import io
import os
import time

import pandas as pd

# Muestra del S&P/BMV IPC (ranking Monex, ago-2026, más candidatas). Los tickers que Yahoo
# no reconozca se omiten automáticamente y se reportan en el log.
IPC = [
    "GFNORTEO.MX", "AMXB.MX", "FEMSAUBD.MX", "CEMEXCPO.MX", "PE&OLES.MX", "GAPB.MX", "ASURB.MX",
    "AC.MX", "KOFUBL.MX", "SIGMAFA.MX", "BIMBOA.MX", "CHDRAUIB.MX", "OMAB.MX", "Q.MX", "KIMBERA.MX",
    "GENTERA.MX", "GRUMAB.MX", "GFINBURO.MX", "PINFRA.MX", "BBAJIOO.MX", "VESTA.MX", "GCARSOA1.MX",
    "RA.MX", "MEGACPO.MX", "ALSEA.MX", "GMEXICOB.MX", "ORBIA.MX", "GCC.MX", "ALPEKA.MX", "WALMEX.MX",
    "BOLSAA.MX", "LABB.MX", "TLEVISACPO.MX", "VOLARA.MX", "LACOMERUBC.MX", "LIVEPOLC-1.MX",
]

URL_SP500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
URLS_NDX = ["https://en.wikipedia.org/wiki/List_of_Nasdaq-100_companies",
            "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
            "https://en.wikipedia.org/wiki/Nasdaq-100"]
UA = {"User-Agent": "Mozilla/5.0 (escaner-bursatil; uso personal)"}


def _yahoo(sym):
    return sym.replace(".", "-")  # BRK.B -> BRK-B


def sp500():
    import requests

    r = requests.get(URL_SP500, headers=UA, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    return sorted({_yahoo(s) for s in df["Symbol"].dropna()})


def nasdaq100():
    import requests

    errores = []
    for url in URLS_NDX:
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            for t in pd.read_html(io.StringIO(r.text)):
                for c in t.columns:
                    nombre = " ".join(map(str, c)) if isinstance(c, tuple) else str(c)
                    if ("ticker" in nombre.lower() or "symbol" in nombre.lower()) and 80 <= len(t) <= 120:
                        vals = [str(v).strip() for v in t[c].dropna()]
                        vals = [v for v in vals if v.replace(".", "").replace("-", "").isalpha() and v.isupper() and len(v) <= 6]
                        if len(vals) >= 80:
                            return sorted({_yahoo(v) for v in vals})
            errores.append(f"{url}: sin tabla de componentes")
        except Exception as e:
            errores.append(f"{url}: {e}")
    raise ValueError("; ".join(errores))


def universos(log=print):
    u = {"IPC": IPC}
    for nombre, fn in (("S&P 500", sp500), ("Nasdaq-100", nasdaq100)):
        try:
            u[nombre] = fn()
            log(f"{nombre}: {len(u[nombre])} emisoras")
        except Exception as e:
            log(f"AVISO: no se pudo obtener la lista de {nombre} ({e}); se omite.")
    return u


def descargar(tickers, anios=11, cache_dir="cache", log=print, lote=60):
    """Precios de cierre ajustados (diarios). Usa caché del día para no repetir descargas."""
    import yfinance as yf

    os.makedirs(cache_dir, exist_ok=True)
    hoy = pd.Timestamp.today().strftime("%Y%m%d")
    ruta = os.path.join(cache_dir, f"precios_{hoy}_{anios}a.pkl")
    previo = pd.read_pickle(ruta) if os.path.exists(ruta) else pd.DataFrame()
    faltan = [t for t in dict.fromkeys(tickers) if t not in previo.columns]
    partes = [previo] if not previo.empty else []
    for i in range(0, len(faltan), lote):
        grupo = faltan[i : i + lote]
        for intento in range(4):
            try:
                d = yf.download(grupo, period=f"{anios}y", auto_adjust=True, progress=False, threads=True)
                c = d["Close"] if isinstance(d.columns, pd.MultiIndex) else d[["Close"]].rename(columns={"Close": grupo[0]})
                partes.append(c)
                break
            except Exception as e:
                log(f"  reintento {intento + 1} lote {i // lote + 1}: {e}")
                time.sleep(10 * (intento + 1))
        log(f"  descargadas {min(i + lote, len(faltan))}/{len(faltan)}")
        time.sleep(2)
    precios = pd.concat(partes, axis=1) if partes else pd.DataFrame()
    precios = precios.loc[:, ~precios.columns.duplicated()]
    if precios.index.tz is not None:
        precios.index = precios.index.tz_localize(None)
    precios = precios.dropna(axis=1, how="all").sort_index()
    todo = pd.concat([previo, precios], axis=1) if not previo.empty else precios
    todo.loc[:, ~todo.columns.duplicated()].to_pickle(ruta)
    precios = precios[[t for t in dict.fromkeys(tickers) if t in precios.columns]]  # solo lo pedido
    sin_datos = [t for t in tickers if t not in precios.columns]
    if sin_datos:
        log(f"  sin datos en Yahoo ({len(sin_datos)}): {', '.join(sin_datos[:30])}")
    return precios
