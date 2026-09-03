# -*- coding: utf-8 -*-
"""
OPERAÇÃO TITÃ — CSTR-77 (versão Streamlit)
==========================================
Painel interativo do simulador de reator CSTR não isotérmico. Reaproveita o
núcleo numérico do simulador_cstr77.py; a UI é orientada a eventos (cada
clique avança a simulação) — sem loops bloqueantes.

Executar (na pasta do projeto):
    streamlit run app.py
"""
import io
import csv
import contextlib

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import simulador_cstr77 as sim

st.set_page_config(page_title="OPERAÇÃO TITÃ — CSTR-77", layout="wide")

S = st.session_state

# ------------------------- estado persistente -------------------------
if "sim" not in S:
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        S.sim = sim.CSTR77(semente="streamlit")
    S.log = []
    S.prev_modo = "MANUAL"
    S.n_ticks = 0

# ------------------------- funções auxiliares -------------------------
def avancar(n):
    """Avança a simulação e captura as mensagens (eventos/alarmes/status)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        S.sim.tick_step(n)
        if S.sim.tick % 10 == 0:
            S.sim._imprime_status()
    txt = buf.getvalue().strip()
    if txt:
        S.log.append(txt)
        S.log = S.log[-40:]          # janela deslizante
def alternar_modo(novo):
    if novo != S.sim.mode:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            if novo == "AUTO":
                S.sim.executar("auto")      # liga qualidade + reseta PID
            else:
                S.sim.mode = "MANUAL"
        S.log.append(buf.getvalue().strip())

# --------------------------- barra lateral ---------------------------
with st.sidebar:
    st.header("🎛️ Controle do Operador")
    modo = st.radio("Modo de operação", ["MANUAL", "AUTO"],
                    index=0 if S.sim.mode == "MANUAL" else 1)
    alternar_modo(modo)

    st.markdown("---")
    st.subheader("🎚️ Válvulas (manual)")
    u_in = st.slider("Válvula de entrada (n)", 0, 100, int(S.sim.u_in * 100))
    u_out = st.slider("Válvula de saída (q)", 0, 100, int(S.sim.u_out * 100))
    u_heat = st.slider("Aquecedor (r)", 0, 100, int(S.sim.u_heat * 100))
    if S.sim.mode == "MANUAL":
        S.sim.u_in, S.sim.u_out, S.sim.u_heat = u_in / 100, u_out / 100, u_heat / 100

    st.markdown("---")
    st.subheader("🎯 Sintonia PID")
    with st.expander("PID do NÍVEL (erro em %)", expanded=False):
        kl_p, kl_i, kl_d = S.sim.pid_l.ganhos
        c1, c2, c3 = st.columns(3)
        kp_l = c1.number_input("Kp", value=float(kl_p), step=0.1, format="%.3f")
        ki_l = c2.number_input("Ki", value=float(kl_i), step=0.001, format="%.3f")
        kd_l = c3.number_input("Kd", value=float(kl_d), step=0.01, format="%.3f")
    with st.expander("PID da TEMPERATURA (erro em °C)", expanded=False):
        kt_p, kt_i, kt_d = S.sim.pid_t.ganhos
        c1, c2, c3 = st.columns(3)
        kp_t = c1.number_input("Kp_", value=float(kt_p), step=0.01, format="%.3f")
        ki_t = c2.number_input("Ki_", value=float(kt_i), step=0.001, format="%.3f")
        kd_t = c3.number_input("Kd_", value=float(kt_d), step=0.01, format="%.3f")
    S.sim.pid_l.kp, S.sim.pid_l.ki, S.sim.pid_l.kd = kp_l, ki_l, kd_l
    S.sim.pid_t.kp, S.sim.pid_t.ki, S.sim.pid_t.kd = kp_t, ki_t, kd_t

    st.markdown("---")
    if st.button("▶️ Avançar 1 tick (10 s)", width="stretch"):
        avancar(1); st.rerun()
    if st.button("⏩ Avançar 10 ticks (100 s)", width="stretch"):
        avancar(10); st.rerun()
    if st.button("⏭️ Avançar 30 ticks (300 s)", width="stretch"):
        avancar(30); st.rerun()
    if st.button("♻️ Reiniciar simulação", width="stretch"):
        with contextlib.redirect_stdout(io.StringIO()):
            S.sim = sim.CSTR77(semente="streamlit")
        S.log, S.prev_modo, S.n_ticks = [], "MANUAL", 0
        st.rerun()

# --------------------------- área principal ---------------------------
qual = S.sim.qualidade()
e_l = sim.P["sp_level"] - S.sim.h * 100.0
e_t = sim.P["sp_temp"] - S.sim.T

st.title("OPERAÇÃO TITÃ — Reator CSTR-77")
atev = ", ".join(sim.EVENTOS[k]["nome"] for k in S.sim.eventos_ativos) or "—"
st.caption(f"Modo **{S.sim.mode}** · tick {S.sim.tick} · t = {S.sim.tick*sim.DT:.0f} s · evento ativo: {atev}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Nível", f"{S.sim.h*100:6.2f} %", f"{e_l:+.2f} vs 65%")
m2.metric("Temperatura", f"{S.sim.T:6.2f} °C", f"{e_t:+.2f} vs 110°C")
m3.metric("Cₐ", f"{S.sim.C:5.3f} mol/L")
m4.metric("Qualidade do lote", f"{qual:.1f}")
m5.metric("Título (atual)", "—")

st.progress(int(S.sim.stress), text=f"Estresse do Dr. Gustav: {S.sim.stress:.0f}/100")

col_left, col_right = st.columns([2, 1])
with col_right:
    st.subheader("📜 Histórico de eventos/alarmes")
    for linha in reversed(S.log[-12:]):
        st.code(linha if len(linha) < 400 else linha[:397] + "...", language=None)
with col_left:
    # ----------------- gráficos (janela deslizante) -----------------
    t = S.sim.hist["t"]
    n = len(t)
    win = max(0, n - 300)
    fig = make_subplots(rows=2, cols=2, shared_xaxes=True,
                        subplot_titles=("Nível (%)", "Temperatura (°C)",
                                        "Saídas de controle", "Qualidade & Estresse"))
    fig.add_trace(go.Scatter(x=t[win:], y=S.sim.hist["h"][win:], name="Nível"),
                  1, 1)
    fig.add_hline(y=sim.P["sp_level"], line_dash="dot", line_color="#58a6ff",
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=t[win:], y=S.sim.hist["T"][win:], name="Temp"),
                  1, 2)
    fig.add_hline(y=sim.P["sp_temp"], line_dash="dot", line_color="#f781bf",
                  row=1, col=2)
    fig.add_trace(go.Scatter(x=t[win:], y=S.sim.hist["u_in"][win:], name="Válv. entrada"), 2, 1)
    fig.add_trace(go.Scatter(x=t[win:], y=S.sim.hist["u_out"][win:], name="Válv. saída"), 2, 1)
    fig.add_trace(go.Scatter(x=t[win:], y=S.sim.hist["u_heat"][win:], name="Aquecedor"), 2, 1)
    fig.add_trace(go.Scatter(x=t[win:], y=S.sim.hist["q"][win:], name="Qualidade"), 2, 2)
    fig.add_trace(go.Scatter(x=t[win:], y=S.sim.hist["stress"][win:], name="Estresse"), 2, 2)
    for tick_ev, _nome in S.sim.marcos_eventos:
        fig.add_vline(x=tick_ev * sim.DT, line_dash="dot", line_color="#ff4d4d",
                      opacity=0.5, row="all", col="all")
    fig.update_layout(height=620, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
    fig.update_xaxes(title="t (s)", row=2)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# --------------------------- relatório --------------------------------
st.markdown("---")
st.subheader("📋 Relatório final")
if st.button("🏁 Gerar relatório (qualidade + título)"):
    titulo = sim.titulo_final(qual, S.sim.stress_max)
    avg_l, avg_t = S.sim.medias()
    st.success(f"**{titulo}**")
    st.write(f"- Qualidade: **{qual:.1f}**/100 (erro médio nível {avg_l:.2f} %, temp {avg_t:.2f} °C)")
    st.write(f"- Estresse máximo: {S.sim.stress_max:.0f}/100  ·  Eventos: "
             f"{', '.join(n for _, n in S.sim.marcos_eventos) or 'nenhum'}")
    st.write(f"- Alterações de PID (POP-007): {len(S.sim.pop007)}")
    if S.sim.pop007:
        for r in S.sim.pop007:
            st.write(f"  tick {r['tick']}: {r['alvo']} antes {r['antes']} → depois {r['depois']}")

if S.sim.hist["t"]:
    rows = zip(S.sim.hist["t"], S.sim.hist["h"], S.sim.hist["T"], S.sim.hist["C"],
               S.sim.hist["u_in"], S.sim.hist["u_out"], S.sim.hist["u_heat"],
               S.sim.hist["e_l"], S.sim.hist["e_t"], S.sim.hist["stress"],
               S.sim.hist["q"])
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf)
    w.writerow(["t_s", "nivel_pct", "temp_C", "conc_molL", "u_entrada", "u_saida",
                "u_aquecedor", "erro_nivel_pct", "erro_temp_C", "estresse", "qualidade"])
    w.writerows(rows)
    st.download_button("⬇️ Baixar dados (CSV)", data=csv_buf.getvalue(),
                       file_name="relatorio_cstr77.csv", mime="text/csv",
                       width="stretch")

st.caption("Núcleo numérico: simulador_cstr77.py • modelo molar CSTR não isotérmico com "
           "controle manual/PID, perturbações e gamificação (Operação TITÃ).")