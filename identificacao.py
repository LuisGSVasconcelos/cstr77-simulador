"""
Identificação de Funções de Transferência — CSTR-77
===================================================

Aplicativo didático que consome dados do simulador CSTR-77 e permite ao aluno:

1. escolher DUAS colunas (entrada u e saída y);
2. escolher o tipo de função de transferência
   (1ª ordem, 2ª ordem ou integrativo);
3. ligar/desligar tempo morto (θ) e resposta inversa (τa);
4. digitar os parâmetros e comparar o modelo com os dados do simulador;
5. ver métricas (FIT, R², RMSE, IAE) e pistas para corrigir o ajuste.

Execução:
    streamlit run identificacao.py
"""
from __future__ import annotations

import contextlib
import csv
import io
import math
import random

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import simulador_cstr77 as sim

# ----------------------------------------------------------------------------
# Experimentos que podem ser gerados direto pelo simulador
# ----------------------------------------------------------------------------
EXPERIMENTOS = {
    "temp": {
        "nome": "Degrau no AQUECEDOR → Temperatura",
        "u_col": "u_heat",
        "y_col": "T",
        "u_label": "Aquecedor (fração)",
        "y_label": "Temperatura (°C)",
        "u_base": 0.45,
        "u_step": 0.55,
        "n_pre": 15,
        "n_post": 300,
        "descricao": (
            "O reator parte em 65 % de nível e 110 °C. Depois de 150 s em regime, "
            "o aquecedor vai de 45 % para 55 % e fica lá por 3 000 s, até a "
            "temperatura parar de subir e estabilizar perto de 120 °C."
        ),
    },
    "nivel_in": {
        "nome": "Pulso na VÁLVULA DE ENTRADA → Nível",
        "u_col": "u_in",
        "y_col": "h",
        "u_label": "Válvula de entrada (fração)",
        "y_label": "Nível (%)",
        "u_base": 0.55,
        "u_step": 0.70,
        "n_pre": 12,
        "n_hold": 30,
        "n_post": 60,
        "descricao": (
            "Entrada e saída equilibradas em 55 %. A válvula de entrada vai a 70 % "
            "por 300 s e **volta a 55 %**. O nível sobe e FICA no patamar novo — "
            "assinatura de integrador."
        ),
    },
    "nivel_out": {
        "nome": "Pulso na VÁLVULA DE SAÍDA → Nível",
        "u_col": "u_out",
        "y_col": "h",
        "u_label": "Válvula de saída (fração)",
        "y_label": "Nível (%)",
        "u_base": 0.55,
        "u_step": 0.40,
        "n_pre": 12,
        "n_hold": 30,
        "n_post": 60,
        "descricao": (
            "Entrada e saída equilibradas em 55 %. A válvula de saída fecha para 40 % "
            "por 300 s e **volta a 55 %**. O nível sobe e FICA no patamar novo — "
            "assinatura de integrador."
        ),
    },
}


# ----------------------------------------------------------------------------
# Aquisição de dados
# ----------------------------------------------------------------------------
def gerar_experimento(chave: str, semente: int = 7) -> dict:
    """Roda o CSTR-77 em malha aberta e devolve t, u, y de um degrau."""
    cfg = EXPERIMENTOS[chave]
    _rnd = sim.random.random

    try:
        # ensaio de identificação não pode ser contaminado por eventos
        sim.random.random = lambda: 1.0

        with contextlib.redirect_stdout(io.StringIO()):
            g = sim.CSTR77(semente=semente)
            g.mode = "MANUAL"
            g.h = 0.65
            g.C = 0.60
            g.N = g.C * g.h * sim.P["V_max"]
            g.T = 110.0
            g.u_in = 0.55
            g.u_out = 0.55
            g.u_heat = 0.45

            # regime inicial
            g.tick_step(cfg["n_pre"])

            # degrau (ou pulso) no canal escolhido
            alvo = cfg["u_col"]
            setattr(g, alvo, cfg["u_step"])
            g.tick_step(cfg.get("n_hold", cfg["n_post"]))

            if "n_hold" in cfg:
                setattr(g, alvo, cfg["u_base"])
                g.tick_step(cfg["n_post"])
    finally:
        sim.random.random = _rnd

    t = np.asarray(g.hist["t"], dtype=float)
    u = np.asarray(g.hist[cfg["u_col"]], dtype=float)
    y = np.asarray(g.hist[cfg["y_col"]], dtype=float)
    return {
        "t": t,
        "u": u,
        "y": y,
        "u_label": cfg["u_label"],
        "y_label": cfg["y_label"],
        "nome": cfg["nome"],
        "i_step": cfg["n_pre"],
        "fonte": "simulador",
    }


def ler_csv(bruto: bytes) -> dict:
    """Lê um CSV exportado pelo simulador e devolve colunas numéricas."""
    texto = bruto.decode("utf-8-sig", errors="replace")
    amostra = texto[:4096]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=",;")
    except csv.Error:
        dialeto = csv.excel

    linhas = [ln for ln in csv.reader(io.StringIO(texto), dialeto) if ln]
    if len(linhas) < 3:
        raise ValueError("CSV vazio ou sem linhas de dados.")

    cabecalho = [c.strip() for c in linhas[0]]
    colunas: dict[str, list[float]] = {}
    for j, nome in enumerate(cabecalho):
        vals = []
        for ln in linhas[1:]:
            if j >= len(ln):
                continue
            try:
                vals.append(float(str(ln[j]).replace(",", ".").strip()))
            except ValueError:
                vals.append(np.nan)
        arr = np.asarray(vals, dtype=float)
        if np.isfinite(arr).sum() >= 3:
            colunas[nome] = arr

    if len(colunas) < 2:
        raise ValueError("O CSV precisa de pelo menos duas colunas numéricas.")

    # coluna de tempo: primeiro por nome (mesmo fora de ordem), depois por monotonicidade
    nomes_tempo = ("t", "t_s", "tempo", "time", "timestamp")
    # so aceita por nome se sobrarem ao menos duas colunas de sinal
    # (evita confundir a coluna 'T' de temperatura com o eixo do tempo)
    t_nome = next((n for n in colunas if len(colunas) >= 3
                   and n.strip().lower() in nomes_tempo), None)
    if t_nome is None:
        t_nome = next((n for n, a in colunas.items() if len(colunas) >= 3
                       and np.all(np.diff(a[np.isfinite(a)]) > 0)), None)
    if t_nome is None:
        t_nome = next((n for n, a in colunas.items() if len(colunas) >= 3
                       and np.all(np.diff(a[np.isfinite(a)]) >= 0)), None)

    if t_nome is not None:
        base = colunas[t_nome]
        n = len(base)
        colunas = {k: v[:n] for k, v in colunas.items()}
        t = np.asarray(base, dtype=float)
        colunas.pop(t_nome, None)
        # descarta amostras sem tempo e ordena por tempo (CSV fora de ordem)
        ok = np.isfinite(t)
        if not ok.all():
            t = t[ok]
            colunas = {k: v[ok] for k, v in colunas.items()}
        if len(t) > 1 and np.any(np.diff(t) < 0):
            ordem = np.argsort(t, kind="stable")
            t = t[ordem]
            colunas = {k: v[ordem] for k, v in colunas.items()}
    else:
        n = min(len(v) for v in colunas.values())
        colunas = {k: v[:n] for k, v in colunas.items()}
        t = np.arange(n, dtype=float) * 10.0

    return {"t": t, "colunas": colunas, "t_nome": t_nome}


# ----------------------------------------------------------------------------
# Preparação da série
# ----------------------------------------------------------------------------
def preparar_serie(t, u, y):
    """Ordena, remove amostras inválidas/duplicadas e devolve dt."""
    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(t) & np.isfinite(u) & np.isfinite(y)
    t, u, y = t[ok], u[ok], y[ok]

    ordem = np.argsort(t)
    t, u, y = t[ordem], u[ordem], y[ordem]
    manter = np.concatenate(([True], np.diff(t) > 1e-9))
    t, u, y = t[manter], u[manter], y[manter]

    if len(t) < 8:
        raise ValueError("Poucos pontos válidos para identificar o modelo.")

    dt = float(np.median(np.diff(t)))
    if not np.isfinite(dt) or dt <= 0:
        dt = 1.0
    return t, u, y, dt


def detectar_degrau(u, fracao=0.20) -> int:
    """Índice aproximado onde a entrada sai da linha de base."""
    n = len(u)
    k = max(3, n // 10)
    u0 = float(np.median(u[:k]))
    desvio = np.abs(u - u0)
    amplitude = float(np.max(desvio))
    if amplitude < 1e-12:
        return max(1, k)
    idx = int(np.argmax(desvio > fracao * amplitude))
    return int(np.clip(idx, 1, n - 5))


def estimar_features(t, u, y, i0) -> dict:
    """Pistas quantitativas para o aluno escolher os parâmetros."""
    t = np.asarray(t, float)
    u = np.asarray(u, float)
    y = np.asarray(y, float)
    i0 = int(np.clip(i0, 1, len(t) - 2))
    dt = float(np.median(np.diff(t)))

    u0 = float(np.mean(u[:i0]))
    y0 = float(np.mean(y[:i0]))
    # patamar de entrada: média só dos pontos no alto do degrau/pulso
    desvio = np.abs(u - u0)
    pico = float(np.max(desvio)) if len(desvio) else 0.0
    if pico > 1e-9:
        u_pos = float(np.mean(u[desvio >= 0.5 * pico]))
    else:
        u_pos = float(np.mean(u[i0:]))
    k_tail = max(3, len(y) // 10)
    y_ss = float(np.mean(y[-k_tail:]))

    du = u_pos - u0
    dy = y_ss - y0
    K = dy / du if abs(du) > 1e-9 else float("nan")

    frac = (y - y0) / dy if abs(dy) > 1e-9 else np.zeros_like(y)

    # tempo morto aparente: 2 % da variação total
    idx_theta = np.where((frac > 0.02) & (np.arange(len(t)) >= i0))[0]
    theta = float(t[idx_theta[0]] - t[i0]) if len(idx_theta) else 0.0

    # constante de tempo aparente: 63,2 %
    idx_tau = np.where((frac >= 0.632) & (np.arange(len(t)) >= i0))[0]
    tau = float(t[idx_tau[0]] - t[i0]) if len(idx_tau) else float("nan")
    if not np.isfinite(tau) or tau <= 0:
        tau = float(max(dt, (t[-1] - t[i0]) / 3.0))

    # sobressinal
    pos = int(np.argmax(frac)) if len(frac) else 0
    sobressinal = float(max(0.0, (frac[pos] - 1.0) * 100.0))
    zeta = float("nan")
    if sobressinal > 0.5:
        ln = math.log(sobressinal / 100.0)
        zeta = -ln / math.sqrt(math.pi**2 + ln**2)

    # taxa para o integrador: Ki = Δy / ∫(u-u0)dt  (funciona para degrau e pulso)
    janela = t[-1] - t[i0]
    taxa = dy / janela if janela > 0 else float("nan")
    area = float(np.trapezoid(np.asarray(u[i0:], float) - u0, t[i0:])) if len(t) > i0 + 1 else 0.0
    Ki = dy / area if abs(area) > 1e-9 else float("nan")

    return {
        "u0": u0, "y0": y0, "du": du, "dy": dy,
        "K": K, "tau": tau, "theta": theta,
        "sobressinal": sobressinal, "zeta": zeta,
        "taxa": taxa, "Ki": Ki, "dt": dt,
        "i0": i0, "t0": float(t[i0]),
    }


# ----------------------------------------------------------------------------
# Modelos
# ----------------------------------------------------------------------------
def _atrasar(x: np.ndarray, n: int) -> np.ndarray:
    if n <= 0:
        return x
    out = np.zeros_like(x)
    out[n:] = x[:-n]
    return out


def resposta_base(ud: np.ndarray, estrutura: str, dyn: dict, dt: float) -> np.ndarray:
    """Resposta ao degrau de um modelo com ganho 1 (a entrada já vem atrasada)."""
    n = len(ud)
    A = np.zeros(n)

    if estrutura == "primeira":
        tau = max(float(dyn["tau"]), 1e-9)
        a = math.exp(-dt / tau)
        for k in range(1, n):
            A[k] = A[k - 1] * a + ud[k] * (1.0 - a)
        return A

    if estrutura == "segunda":
        wn = max(float(dyn["wn"]), 1e-9)
        zeta = max(float(dyn["zeta"]), 1e-4)
        sub = int(np.clip(math.ceil(dt * wn * 2.0), 4, 200))
        h = dt / sub
        yv, v = 0.0, 0.0

        def f(y_, v_, uu):
            return v_, wn * wn * (uu - y_) - 2.0 * zeta * wn * v_

        for k in range(1, n):
            uu = ud[k]
            for _ in range(sub):
                k1y, k1v = f(yv, v, uu)
                k2y, k2v = f(yv + 0.5 * h * k1y, v + 0.5 * h * k1v, uu)
                k3y, k3v = f(yv + 0.5 * h * k2y, v + 0.5 * h * k2v, uu)
                k4y, k4v = f(yv + h * k3y, v + h * k3v, uu)
                yv += h * (k1y + 2 * k2y + 2 * k3y + k4y) / 6.0
                v += h * (k1v + 2 * k2v + 2 * k3v + k4v) / 6.0
            A[k] = yv
        return A

    if estrutura == "integrativo":
        for k in range(1, n):
            A[k] = A[k - 1] + ud[k] * dt
        return A

    raise ValueError(f"Estrutura desconhecida: {estrutura}")


def montar_saida(t, u, y, i0, estrutura, dyn, theta, tau_a=0.0):
    """Devolve y0, yhat e o vetor de resposta normalizada B."""
    dt = float(np.median(np.diff(t)))
    u0 = float(np.mean(u[:i0]))
    y0 = float(np.mean(y[:i0]))

    ud = np.asarray(u, float) - u0
    ud = _atrasar(ud, int(round(max(theta, 0.0) / dt)))

    A = resposta_base(ud, estrutura, dyn, dt)

    if tau_a and tau_a > 0:
        dB = np.gradient(A, dt) if len(A) > 1 else np.zeros_like(A)
        B = A - tau_a * dB
        # a resposta inversa parte de zero
        B = B - B[0]
    else:
        B = A

    K = float(dyn.get("K", 1.0))
    yhat = y0 + K * B
    return y0, yhat, B


def metricas(t, y, yhat, i0) -> dict:
    sl = slice(int(i0), None)
    tt = np.asarray(t, float)[sl]
    yy = np.asarray(y, float)[sl]
    yh = np.asarray(yhat, float)[sl]
    e = yy - yh

    rmse = float(np.sqrt(np.mean(e**2)))
    ss_res = float(np.sum(e**2))
    ss_tot = float(np.sum((yy - np.mean(yy)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")
    norma = float(np.linalg.norm(yy - np.mean(yy)))
    fit = 100.0 * (1.0 - float(np.linalg.norm(e)) / norma) if norma > 1e-12 else float("nan")
    iae = float(np.trapezoid(np.abs(e), tt)) if len(tt) > 1 else float("nan")

    return {"fit": fit, "r2": r2, "rmse": rmse, "iae": iae}


def tempo_63(t, y, i0) -> float:
    """Instante em que a saída atinge 63,2 % da variação total."""
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    y0 = float(np.mean(y[:i0]))
    y_ss = float(np.mean(y[-max(3, len(y) // 10):]))
    dy = y_ss - y0
    if abs(dy) < 1e-9:
        return float("nan")
    frac = (y - y0) / dy
    idx = np.where((frac >= 0.632) & (np.arange(len(t)) >= i0))[0]
    return float(t[idx[0]] - t[i0]) if len(idx) else float("nan")


# ----------------------------------------------------------------------------
# Ajuste automático (gabarito)
# ----------------------------------------------------------------------------
def auto_ajuste(t, u, y, i0, estrutura, com_morto, com_inv) -> dict:
    """Busca em grade + K por mínimos quadrados (modelo linear em K)."""
    t, u, y, dt = preparar_serie(t, u, y)
    feat = estimar_features(t, u, y, i0)
    i0 = feat["i0"]
    y0 = feat["y0"]
    y_dev = np.asarray(y, float) - y0
    sl = slice(i0, None)

    thetas = [0.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0] if com_morto else [0.0]
    thetas = [th for th in thetas if th <= max(120.0, 0.3 * (t[-1] - t[i0]))]

    if estrutura == "primeira":
        base = feat["tau"] if np.isfinite(feat["tau"]) else (t[-1] - t[i0]) / 3
        taus = np.geomspace(max(dt, base * 0.15), max(dt * 2, base * 10), 14)
        dyns = [{"tau": float(tau)} for tau in taus]
    elif estrutura == "segunda":
        base = feat["tau"] if np.isfinite(feat["tau"]) else (t[-1] - t[i0]) / 3
        wn0 = 1.0 / max(base, dt)
        wns = np.geomspace(wn0 * 0.25, wn0 * 4.0, 9)
        zetas = [0.2, 0.35, 0.5, 0.7, 0.9, 1.2, 1.6]
        dyns = [{"wn": float(w), "zeta": float(z)} for w in wns for z in zetas]
    else:
        dyns = [{}]

    tau_as = [0.0]
    if com_inv:
        escala = feat["tau"] if np.isfinite(feat["tau"]) else (t[-1] - t[i0]) / 4
        tau_as = [0.05, 0.10, 0.20, 0.35, 0.50]
        tau_as = [float(f * escala) for f in tau_as]

    melhor = None

    for dyn in dyns:
        for theta in thetas:
            for tau_a in tau_as:
                _, _, B = montar_saida(t, u, y, i0, estrutura, {**dyn, "K": 1.0}, theta, tau_a)
                bb = B[sl]
                den = float(np.dot(bb, bb))
                if den < 1e-14:
                    continue
                K = float(np.dot(y_dev[sl], bb) / den)
                yhat = y0 + K * B
                m = metricas(t, y, yhat, i0)
                if melhor is None or m["fit"] > melhor["fit"]:
                    melhor = {
                        "K": K, "theta": float(theta), "tau_a": float(tau_a),
                        **dyn, **m,
                    }

    if melhor is None:
        raise RuntimeError("Não foi possível ajustar o modelo.")

    # refino local em torno do melhor ponto
    for _ in range(2):
        if estrutura == "primeira":
            chaves = ["tau"]
        elif estrutura == "segunda":
            chaves = ["wn", "zeta"]
        else:
            chaves = []
        for ch in chaves:
            atual = melhor[ch]
            for fator in (0.7, 0.85, 1.15, 1.4):
                cand = dict(melhor)
                cand[ch] = atual * fator
                _, _, B = montar_saida(
                    t, u, y, i0, estrutura,
                    {k: cand[k] for k in ("tau", "wn", "zeta") if k in cand} | {"K": 1.0},
                    cand["theta"], cand["tau_a"],
                )
                bb = B[sl]
                den = float(np.dot(bb, bb))
                if den < 1e-14:
                    continue
                K = float(np.dot(y_dev[sl], bb) / den)
                yhat = y0 + K * B
                m = metricas(t, y, yhat, i0)
                if m["fit"] > melhor["fit"]:
                    melhor.update({**m, "K": K, ch: cand[ch]})

    return melhor


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------
def _num(valor, padrao):
    try:
        v = float(valor)
        return v if np.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def _sorteio_inicial(feat):
    """Valores iniciais ALEATÓRIOS — de propósito, longe da resposta.

    A ordem de grandeza vem das features do experimento (para o aluno não
    começar em 10^6 quando a resposta é 0,2), mas o sorteio fica SEMPRE a pelo
    menos ~1,8x de distância do valor correto: a faixa "quase certo" é
    proibida, senão de vez em quando o aluno abriria o app já com FIT alto.
    O sorteio é por sessão: dois alunos não veem os mesmos números, então não
    adianta copiar o procedimento do colega.
    """
    rng = random.Random()
    k_ref = _num(feat.get("K"), 1.0)
    ki_ref = _num(feat.get("Ki"), 0.01)
    tau_ref = max(0.1, abs(_num(feat.get("tau"), 100.0)))

    def _longe(baixo, fino_baixo, fino_alto, alto):
        """Fator log-uniforme em [baixo, fino_baixo] ou [fino_alto, alto]."""
        if rng.random() < 0.5:
            return 10 ** rng.uniform(math.log10(baixo), math.log10(fino_baixo))
        return 10 ** rng.uniform(math.log10(fino_alto), math.log10(alto))

    def _escala(valor, fator):
        base = abs(valor) if abs(valor) > 1e-12 else 1.0
        return base * fator

    fator_k = _longe(0.2, 0.55, 1.8, 5.0)      # 0,2–0,55x ou 1,8–5,0x
    fator_tau = _longe(0.2, 0.56, 1.78, 5.0)   # ±0,25 a ±0,7 década

    return {
        "K": math.copysign(_escala(k_ref, fator_k), k_ref or 1.0),
        "tau": tau_ref * fator_tau,
        "wn": 1.0 / (tau_ref * fator_tau),
        "zeta": rng.uniform(0.15, 1.60),
        "Ki": math.copysign(_escala(ki_ref, fator_k), ki_ref or 1.0),
        "theta": rng.choice([0.0, 0.0, 5.0, 10.0, 20.0, 40.0]),
        "taua": tau_ref * rng.uniform(0.05, 0.40),
    }


def main():
    st.set_page_config(
        page_title="Identificação de FT — CSTR-77",
        page_icon="🔎",
        layout="wide",
    )

    st.title("🔎 Identificação de Funções de Transferência — CSTR-77")
    st.caption(
        "Escolha duas colunas de dados do simulador, escolha a estrutura da função "
        "de transferência, digite os parâmetros e compare com a resposta real."
    )

    # ------------------------------------------------------------------ dados
    with st.sidebar:
        st.header("1 · Dados")
        fonte = st.radio(
            "Fonte",
            ["Gerar no simulador", "Enviar CSV do simulador"],
            help="Gerar roda um degrau em malha aberta no CSTR-77.",
        )

        dados = None
        erro = None

        if fonte == "Gerar no simulador":
            chave = st.selectbox(
                "Experimento",
                list(EXPERIMENTOS),
                format_func=lambda k: EXPERIMENTOS[k]["nome"],
            )
            st.info(EXPERIMENTOS[chave]["descricao"])
            try:
                dados = gerar_experimento(chave)
            except Exception as exc:  # pragma: no cover
                erro = str(exc)

            u_col_nome = EXPERIMENTOS[chave]["u_label"]
            y_col_nome = EXPERIMENTOS[chave]["y_label"]

        else:
            up = st.file_uploader("Arquivo CSV", type=["csv"])
            if up is not None:
                try:
                    lido = ler_csv(up.getvalue())
                    cols = lido["colunas"]
                    nomes = list(cols)
                    c1, c2 = st.columns(2)
                    with c1:
                        u_col_nome = st.selectbox("Coluna de ENTRADA (u)", nomes, index=0)
                    with c2:
                        idx_y = 1 if len(nomes) > 1 else 0
                        y_col_nome = st.selectbox("Coluna de SAÍDA (y)", nomes, index=idx_y)
                    dados = {
                        "t": lido["t"],
                        "u": cols[u_col_nome],
                        "y": cols[y_col_nome],
                        "u_label": u_col_nome,
                        "y_label": y_col_nome,
                        "nome": up.name,
                        "i_step": None,
                        "fonte": "csv",
                    }
                except Exception as exc:
                    erro = f"Falha ao ler o CSV: {exc}"
            else:
                st.warning("Envie um CSV exportado pelo simulador.")

        if erro:
            st.error(erro)

        st.header("2 · Janela do degrau")
        if dados is not None:
            try:
                t, u, y, dt = preparar_serie(dados["t"], dados["u"], dados["y"])
                i_auto = dados.get("i_step") or detectar_degrau(u)
                i_auto = int(np.clip(i_auto, 1, len(t) - 5))
                i0 = st.slider(
                    "Início do degrau (amostra)",
                    min_value=1,
                    max_value=len(t) - 5,
                    value=i_auto,
                    help=f"t = {t[i_auto]:.1f} s detectado automaticamente.",
                )
            except Exception as exc:
                st.error(f"Série inválida: {exc}")
                dados = None

        st.header("3 · Estrutura")
        estrutura = st.radio(
            "Tipo de função de transferência",
            ["Primeira ordem", "Segunda ordem", "Integrativo"],
        )
        com_morto = st.checkbox("Com tempo morto (θ)", value=True)
        com_inv = st.checkbox("Com resposta inversa (τa)", value=False)

    if dados is None:
        st.info("Configure os dados na barra lateral para começar.")
        return

    # ------------------------------------------------------------- parâmetros
    feat = estimar_features(t, u, y, i0)
    chave_mod = "primeira" if estrutura.startswith("Primeira") else (
        "segunda" if estrutura.startswith("Segunda") else "integrativo"
    )

    # reinicia os widgets quando muda a fonte/janela/estrutura
    data_id = f"{dados['nome']}|{u_col_nome}|{y_col_nome}|{i0}|{chave_mod}"
    if st.session_state.get("_data_id") != data_id:
        st.session_state["_data_id"] = data_id
        for k in [k for k in st.session_state if k.startswith("p_")]:
            st.session_state.pop(k, None)

    # valores iniciais SORTEADOS (nunca a resposta): o aluno tem de encontrar
    chave_sorteio = (data_id, st.session_state.get("_draw", 0))
    if st.session_state.get("_sorteio_id") != chave_sorteio:
        st.session_state["_sorteio_id"] = chave_sorteio
        sorteio = _sorteio_inicial(feat)
        st.session_state["p_K"] = float(sorteio["K"])
        st.session_state["p_tau"] = float(max(0.1, sorteio["tau"]))
        st.session_state["p_wn"] = float(max(1e-4, sorteio["wn"]))
        st.session_state["p_zeta"] = float(max(0.05, sorteio["zeta"]))
        st.session_state["p_Ki"] = float(sorteio["Ki"])
        st.session_state["p_theta"] = float(max(0.0, sorteio["theta"]))
        st.session_state["p_taua"] = float(max(0.0, sorteio["taua"]))

    with st.sidebar:
        st.header("4 · Parâmetros")
        dyn = {}
        if chave_mod == "primeira":
            dyn["K"] = st.number_input(
                "Ganho K (unid. y / unid. u)", format="%.4f", key="p_K",
            )
            dyn["tau"] = st.number_input(
                "Constante de tempo τ (s)", min_value=0.1,
                step=5.0, format="%.1f", key="p_tau",
            )
        elif chave_mod == "segunda":
            dyn["K"] = st.number_input(
                "Ganho K (unid. y / unid. u)", format="%.4f", key="p_K",
            )
            dyn["wn"] = st.number_input(
                "Frequência natural ωn (rad/s)",
                min_value=1e-4, step=0.0005, format="%.5f", key="p_wn",
            )
            dyn["zeta"] = st.number_input(
                "Amortecimento ζ (–)",
                min_value=0.05, step=0.05, format="%.2f", key="p_zeta",
            )
        else:
            dyn["K"] = st.number_input(
                "Ganho do integrador Ki (unid. y / (s·unid. u))",
                format="%.5f", key="p_Ki",
            )

        theta = st.number_input(
            "Tempo morto θ (s)", min_value=0.0,
            step=5.0, format="%.1f", key="p_theta",
            disabled=not com_morto,
        ) if com_morto else 0.0

        tau_a = st.number_input(
            "Constante da resposta inversa τa (s)", min_value=0.0,
            step=5.0, format="%.1f", key="p_taua",
        ) if com_inv else 0.0

        if st.button("🎲 Sortear outros valores"):
            st.session_state["_draw"] = st.session_state.get("_draw", 0) + 1
            st.rerun()
        st.caption(
            "🎲 **Os valores acima são sorteados** — não são a resposta. "
            "Ajuste-os até o modelo aderir aos dados; use o painel de pistas "
            "para saber em que direção mexer."
        )
        modo_prof = st.checkbox(
            "Modo professor (mostrar pistas numéricas e gabarito)",
            value=False,
            help="Ligado, o app volta a mostrar os valores estimados dos "
                 "parâmetros e o ajuste automático. Deixe desligado durante a "
                 "atividade: o aluno deve encontrar os valores.",
        )

    # ---------------------------------------------------------------- modelo
    y0, yhat, _ = montar_saida(t, u, y, i0, chave_mod, dyn, theta, tau_a)
    met = metricas(t, y, yhat, i0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FIT", f"{met['fit']:.1f} %", help="100 % = modelo perfeito (critério de Ljung).")
    c2.metric("R²", f"{met['r2']:.3f}")
    c3.metric("RMSE", f"{met['rmse']:.3g}")
    c4.metric("IAE", f"{met['iae']:.3g}")

    # ----------------------------------------------------------------- gráfico
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.22, 0.53, 0.25], vertical_spacing=0.07,
        subplot_titles=("Entrada (degrau)", "Saída: dados do simulador × modelo", "Erro (dados − modelo)"),
    )
    fig.add_trace(go.Scatter(x=t, y=u, mode="lines", name="u", line=dict(color="#8ab4f8")), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=t, y=y, mode="lines", name="Dados do simulador",
                   line=dict(color="#f2f2f2", width=2)),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=t, y=yhat, mode="lines", name="Modelo",
                   line=dict(color="#ff9f43", width=2, dash="dash")),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=t, y=np.asarray(y) - yhat, mode="lines", name="erro",
                   line=dict(color="#e57373")),
        row=3, col=1,
    )
    fig.add_vline(x=t[i0], line_dash="dot", line_color="#9e9e9e")
    fig.update_xaxes(title_text="tempo (s)", row=3, col=1)
    fig.update_yaxes(title_text=dados["u_label"], row=1, col=1)
    fig.update_yaxes(title_text=dados["y_label"], row=2, col=1)
    fig.update_layout(
        height=620, margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # -------------------------------------------------------------- feedback
    col_a, col_b = st.columns([3, 2])
    with col_a:
        if met["fit"] >= 90:
            st.success("Excelente: o modelo reproduz os dados com erro pequeno.")
        elif met["fit"] >= 70:
            st.warning("Bom começo. Ajuste fino dos parâmetros para passar de 90 %.")
        else:
            st.error("Ainda longe. Compare as pistas ao lado e corrija um parâmetro por vez.")

        t63_dados = tempo_63(t, y, i0)
        t63_modelo = tempo_63(t, yhat, i0)
        if np.isfinite(t63_dados) and np.isfinite(t63_modelo):
            rapido = t63_modelo < 0.85 * t63_dados
            lento = t63_modelo > 1.15 * t63_dados
            if rapido or lento:
                if modo_prof:
                    st.write(
                        f"⏱️ O modelo chega a 63 % em **{t63_modelo:.0f} s**; os dados em "
                        f"**{t63_dados:.0f} s**. O modelo está "
                        f"{'rápido' if rapido else 'lento'} demais → "
                        f"**{'aumente' if rapido else 'reduza'} τ**."
                    )
                else:
                    st.write(
                        "⏱️ Pela velocidade da resposta, o modelo "
                        f"{'chega cedo demais' if rapido else 'demora demais'} ao regime "
                        f"→ **{'aumente' if rapido else 'reduza'} τ**."
                    )

    with col_b:
        with st.expander("🧭 Pistas dos dados", expanded=True):
            if modo_prof:
                if chave_mod == "integrativo":
                    st.write(f"Ganho aparente Ki ≈ **{feat['Ki']:.4g}** unid./(s·unid. u)")
                    st.write(f"Variação total: **{feat['dy']:+.3g}** em {t[-1] - feat['t0']:.0f} s")
                else:
                    st.write(f"Ganho aparente K ≈ **{feat['K']:.4g}**")
                    st.write(f"Constante de tempo aparente τ ≈ **{feat['tau']:.0f} s**")
                    st.write(f"Sobressinal ≈ **{feat['sobressinal']:.1f} %**"
                             + (f" → ζ ≈ {feat['zeta']:.2f}" if np.isfinite(feat["zeta"]) else ""))
                st.write(f"Tempo morto aparente θ ≈ **{feat['theta']:.0f} s**")
            else:
                # só a DIREÇÃO da correção — os valores o aluno tem de achar
                dy_d = y[-1] - y[i0]
                dy_m = yhat[-1] - y[i0]
                if abs(dy_m - dy_d) > 0.10 * max(abs(dy_d), 1e-9):
                    if np.sign(dy_m) != np.sign(dy_d):
                        st.write("🔁 O modelo vai para o **lado oposto** dos dados → "
                                 "o sinal do ganho está trocado.")
                    elif abs(dy_m) < abs(dy_d):
                        st.write("📈 O modelo anda **menos** que os dados → "
                                 "**aumente o ganho**.")
                    else:
                        st.write("📉 O modelo anda **mais** que os dados → "
                                 "**reduza o ganho**.")
                else:
                    st.write("✅ A variação total do modelo bate com a dos dados: "
                             "o ganho está no caminho certo.")
                if chave_mod == "segunda":
                    st.write("〰️ Oscilou nos dados e não no modelo → **reduza ζ**; "
                             "o contrário → **aumente ζ**.")
                st.write("⏱️ Modelo reagindo **antes** dos dados → **aumente θ**; "
                         "**depois** → **reduza θ**.")
                st.caption("As pistas dão só a direção. Os valores numéricos ficam "
                           "no modo professor.")

    # --------------------------------------------------------------- gabarito
    with st.expander("🎓 Gabarito — ajuste automático"):
        if not modo_prof:
            st.info(
                "🔒 **Modo avaliação.** Aqui ficaria o ajuste automático, que "
                "entrega a resposta. Ligue o **modo professor** na barra "
                "lateral para usá-lo."
            )
        else:
            st.caption(
                "O app varre as estruturas e resolve o ganho por mínimos quadrados. "
                "Use para conferir a resposta do aluno."
            )
            if st.button("Calcular melhor ajuste desta estrutura"):
                with st.spinner("Ajustando..."):
                    best = auto_ajuste(t, u, y, i0, chave_mod, com_morto, com_inv)
                st.session_state["_best"] = best
                st.session_state["_best_id"] = data_id

            best = st.session_state.get("_best")
            if best and st.session_state.get("_best_id") == data_id:
                st.write(
                    f"**K = {best['K']:.4g}** · θ = {best['theta']:.0f} s · τa = {best['tau_a']:.0f} s"
                )
                if "tau" in best:
                    st.write(f"τ = {best['tau']:.1f} s")
                if "wn" in best:
                    st.write(f"ωn = {best['wn']:.5f} rad/s · ζ = {best['zeta']:.2f}")
                st.write(f"FIT = {best['fit']:.1f} % · R² = {best['r2']:.3f} · RMSE = {best['rmse']:.3g}")

                _, yhat_best, _ = montar_saida(
                    t, u, y, i0, chave_mod,
                    {k: best[k] for k in ("K", "tau", "wn", "zeta") if k in best},
                    best["theta"], best["tau_a"],
                )
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=t, y=y, name="dados", line=dict(color="#f2f2f2")))
                fig2.add_trace(go.Scatter(x=t, y=yhat_best, name="gabarito",
                                          line=dict(color="#4caf50", dash="dash")))
                fig2.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                   hovermode="x unified")
                st.plotly_chart(fig2, use_container_width=True)
                st.session_state["_best_id"] = data_id

    # ------------------------------------------------------------------ CSV
    st.divider()
    d1, d2 = st.columns(2)
    exp = np.column_stack([t, u, y])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([dados.get("t_nome") or "t_s", dados["u_label"], dados["y_label"]])
    for linha in exp:
        w.writerow([f"{v:.6g}" for v in linha])
    d1.download_button(
        "⬇️ Baixar experimento (CSV)",
        data=buf.getvalue().encode("utf-8"),
        file_name="experimento_cstr77.csv",
        mime="text/csv",
    )

    res = np.column_stack([t, u, y, yhat, np.asarray(y) - yhat])
    buf2 = io.StringIO()
    w2 = csv.writer(buf2)
    w2.writerow(["t_s", "u", "y_dados", "y_modelo", "erro"])
    for linha in res:
        w2.writerow([f"{v:.6g}" for v in linha])
    d2.download_button(
        "⬇️ Baixar comparação (CSV)",
        data=buf2.getvalue().encode("utf-8"),
        file_name="comparacao_modelo.csv",
        mime="text/csv",
    )

    # --------------------------------------------------------------- teoria
    with st.expander("📘 Equações das estruturas"):
        st.markdown(
            r"""
**Primeira ordem**  
$$G(s)=\frac{K}{\tau s+1}$$

**Segunda ordem**  
$$G(s)=\frac{K\,\omega_n^2}{s^2+2\zeta\omega_n s+\omega_n^2}$$

**Integrativo**  
$$G(s)=\frac{K_i}{s}$$

**Tempo morto** — multiplica qualquer estrutura por $e^{-\theta s}$.

**Resposta inversa** — multiplica por $(1-\tau_a s)$; a saída inicialmente
vai no sentido oposto e depois corrige.
"""
        )


if __name__ == "__main__":
    main()
