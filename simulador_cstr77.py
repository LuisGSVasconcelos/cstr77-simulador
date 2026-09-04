# -*- coding: utf-8 -*-
"""
OPERAÇÃO TITÃ — Simulador do Reator CSTR-77
=============================================
Reator CSTR não-isotérmico (nível + concentração + temperatura),
controle manual e automático (PID), perturbações aleatórias e
gamificação, alinhado ao briefing "Operação TITÃ".

Executar:   python simulador_cstr77.py
Auto-teste: python simulador_cstr77.py --demo <semente>
Dependências: pip install numpy matplotlib
"""
import os
import sys
import csv
import random
import numpy as np

import matplotlib
if "--demo" not in sys.argv:
    try:
        matplotlib.use("TkAgg")
    except Exception:
        matplotlib.use("Agg")
else:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    os.makedirs(os.path.dirname(os.path.abspath(__file__)), exist_ok=True)
except Exception:
    pass

R_GAS = 8.314          # J/mol.K
DT = 10.0              # s simulados por "tick"
T_MAX_TICKS = 400      # ~67 min simulados
GRACE_AUTO = 15        # ticks de AUTO sem contar IAE (deixa o PID assentar após o manual)
W_VAR = 8              # peso da oscilação do atuador (mean|Δu_heat|) na qualidade

# Nudges do Dr. Gustav: lembra o aluno de mexer no PID se ficou parado em AUTO
NUDGES = [
    (60,  "📞 Gustav: 'Tá olhando o quê, novato? Mexa nos PIDs! "
              "Use \033[1mpid n <Kp> <Ki> <Kd>\033[0m e \033[1mpid t ...\033[0m.'"),
    (120, "📞 Gustav: '2 minutos e nada? Olha a oscilação do aquecedor — "
              "precisa de Kd. Vai!'"),
    (200, "📞 Gustav (irritado): 'Se você não mexer no PID, vai pro "
              "almoxarifado. Mãos à obra!'"),
]

# ----------------------- Parâmetros da planta -----------------------
P = {
    "V_max":  10.0,     # L
    "C_A0":    1.0,     # mol/L alimentação
    "T_in":   60.0,     # °C (alimentação pré-aquecida)
    "T_cool": 25.0,     # °C água de refrigeração (jaqueta)
    "q_max":   0.02,    # L/s vazão máxima (entrada/saída)
    "Q_max": 2000.0,    # W aquecedor (e resfriador ativo)
    "UA":      5.0,     # W/K jaqueta
    "rho_cp": 1500.0,   # J/(L.K) solvente
    "dH":  -50_000.0,   # J/mol (exotérmica)
    "k0":    3.0e5,     # 1/s
    "Ea":    60_000.0,  # J/mol
    "sp_level": 65.0,   # %
    "sp_temp": 110.0,   # °C
}
V_MIN_THERM = 0.8                  # L: volume de imersão do aquecedor (evita V->0 explodir)

EVENTOS = {
    "queda":     dict(nome="QUEDA DA MATÉRIA-PRIMA", dur=40,
                      msg="📉 A pressão da linha caiu: vazão de entrada -35%."),
    "calor":     dict(nome="ONDA DE CALOR", dur=40,
                      msg="🌡️ Água de torre quente: +18 °C na jaqueta."),
    "tanque":    dict(nome="OPERADOR DO TANQUE", dur=30,
                      msg="🚨 Alguém abriu a válvula de saída (+30% de vazão)!"),
    "cafeteira": dict(nome="EFEITO CAFETERIA", dur=30,
                      msg="☕ Equipamento de alta potência na rede: alimentação 20 °C mais fria."),
    "greve":     dict(nome="GREVE DOS FORNECEDORES", dur=50,
                      msg="🛑 Greve dos fornecedores: a vazão de entrada diminui lentamente (-35%)."),
    "chiller":   dict(nome="FALHA DO REFRIGERANTE", dur=35,
                      msg="🧊 Falha no chiller: perda temporária da refrigeração ativa (+12 °C na jaqueta)."),
}

# Títulos do placar (estilo do briefing)
def titulo_final(qual, stress_max):
    if stress_max >= 100.0:
        return "ALMOXARIFADO 📦 (Dr. Gustav te rebaixou!)"
    if qual >= 95.0:
        return "MÃO DE ANJO ⭐ (Placar de Sintonista)"
    if qual >= 85.0:
        return "SUCESSOR DO DR. GUSTAV 🏆"
    if qual >= 70.0:
        return "OPERADOR TITÃ APROVADO ✅"
    return "ALMOXARIFADO 📦"


class PID:
    """PID posicional com anti-windup (integração condicional) e
    derivada filtrada sobre a medição (sem derivação de setpoint)."""
    def __init__(self, kp, ki, kd, out_min=0.0, out_max=1.0, nf=0.3):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_min, self.out_max = out_min, out_max
        self.nf = nf
        self.reset()

    def reset(self):
        self.integral = 0.0
        self.last_pv = None
        self.last_d = 0.0

    def update(self, sp, pv, dt):
        e = sp - pv
        self.integral += self.ki * e * dt
        if self.last_pv is None:
            dterm = 0.0
        else:
            d_raw = (pv - self.last_pv) / dt
            self.last_d = self.nf * d_raw + (1.0 - self.nf) * self.last_d
            dterm = self.last_d
        self.last_pv = pv                    # corrigido: sempre atualiza
        out = self.kp * e + self.integral - self.kd * dterm
        out_c = min(self.out_max, max(self.out_min, out))
        if out != out_c and self.ki != 0.0:  # anti-windup (integração condicional)
            self.integral -= self.ki * e * dt
        return out_c

    @property
    def ganhos(self):
        return (self.kp, self.ki, self.kd)


def passo_cstr(N, T, h, u_in, u_out, u_heat, p,
               qf=1.0, dT_cool=0.0, dT_in=0.0):
    """Avança o CSTR em DT. Estado molar (N = mols de A) evita divisão por
    volume ~0. u_in,u_out em [0,1]; u_heat em [-1,1]."""
    V = max(h * p["V_max"], 1e-9)
    # vlv de saída = demanda CONSTANTE (bomba de descarga): tanque vira
    # integrador puro -> PID P-only deixa offset real, precisa da ação integral.
    q_in = p["q_max"] * u_in * qf
    q_out = min(p["q_max"] * u_out, V / DT + 1e-9)

    # ---- nível (volume)
    h_n = min(1.0, max(0.0, h + (q_in - q_out) * DT / p["V_max"]))
    V_n = max(h_n * p["V_max"], 1e-9)

    # ---- espécie (forma molar, robusta p/ V pequeno)
    C = N / max(V_n, 1e-9)
    k = p["k0"] * np.exp(-p["Ea"] / (R_GAS * (T + 273.15)))
    r = k * C                                    # mol/(L.s)
    N_n = max(0.0, N + (q_in * p["C_A0"] - q_out * C - r * V_n) * DT)
    C_n = N_n / max(V_n, 1e-9)

    # ---- energia (volume térmico = imersão do aquecedor p/ imverter V->0)
    V_th = max(V_n, V_MIN_THERM)
    Q = (u_heat * p["Q_max"]                        # atuador bipolar
         + (-p["dH"]) * r * V_n                     # reação exotérmica
         + q_in * p["rho_cp"] * ((p["T_in"] + dT_in) - T)   # alimentação
         + p["UA"] * ((p["T_cool"] + dT_cool) - T))          # jaqueta
    T_n = T + Q * DT / (p["rho_cp"] * V_th)
    return h_n, N_n, C_n, T_n


class CSTR77:
    def __init__(self, semente=None):
        random.seed(semente)                     # corrigido: placa reproduzível
        self.semente = semente
        self.h, self.N, self.C, self.T = 0.0, 0.0, 0.0, 25.0
        self.tick = 0
        self.mode = "MANUAL"
        self.u_in = self.u_out = self.u_heat = 0.0
        # Sintonia "do Dr. Gustav" (propositalmente RUIM): nível com ganho baixo
        # e SEM integral -> offset visível no tanque integrador; temperatura com
        # excesso de ganho/integral -> oscila. A Fase 2 existe para corrigir isso.
        self.pid_l = PID(0.12, 0.0, 0.0)          # nível: saída [0,1], sem I -> offset
        self.pid_t = PID(2.0, 0.8, 0.0, out_min=-1.0, out_max=1.0)  # temp: bipolar, oscila forte
        self.eventos_ativos = {}                 # nome -> ticks restantes
        self.last_event = None                   # dedup: não repete o último evento
        self.iae_l = self.iae_t = 0.0            # brutos: %·s e °C·s (fase AUTO)
        self.var_u = 0.0                     # oscilação do atuador (Σ|Δu_heat|, fase AUTO)
        self._nq = 0                         # nº de ticks AUTO contados p/ qualidade
        self._prev_uh = None
        self._qual_start = False                 # qualidade conta a partir do AUTO
        self._t_auto = 0
        self._grace = 0                          # conta regressiva de graça da IAE
        self.stress = 0.0
        self.stress_max = 0.0
        self.aviso_deadline = False
        self.alarme_grito = False
        self._flag_crit = False
        self._flag_overflow = False
        self._flag_empty = False
        self._nudge_stage = 0                 # 0/1/2/3 = quantos avisos do Gustav já saíram
        self._game_over = False               # estresse 100 -> fim de jogo (para de avançar)
        self.pop007 = []                         # log de alterações de PID
        self.marcos_eventos = []                 # (tick, nome)
        self.hist = {k: [] for k in
                     ("t", "h", "T", "C", "u_in", "u_out", "u_heat",
                      "e_l", "e_t", "stress", "q")}
        self._imprime_abertura()

    # ------------------------- interface -------------------------
    def _imprime_abertura(self):
        print("=" * 62)
        print("OPERAÇÃO TITÃ — Sala de Controle do Reator CSTR-77")
        print("=" * 62)
        print("Bem-vindo, Operador TITÃ. O CSTR-77 está partindo agora.")
        print(f"  Setpoint NÍVEL : {P['sp_level']:.0f} %")
        print(f"  Setpoint TEMP  : {P['sp_temp']:.0f} °C")
        print("Você tem ~10 min (60 ticks) para estabilizar em MANUAL,")
        print("ou o alarme de 'ALTA VARIAÇÃO' vai despertar o gerente.")
        print("Quando estiver estável, mude para AUTO e refine o PID")
        print("(a sintonia do Dr. Gustav é ruim de propósito — o jogo te força")
        print(" a achar os ganhos certos).")
        print("Cuidado com variações na linha... o filtro está sendo trocado.")
        print("Comandos: n <0-100> | q <0-100> | r <0-100> | auto | manual |")
        print("          pid [N|T <Kp> <Ki> <Kd>] | pop | esp [n] | status |")
        print("          relatorio | sair\n")

    def _tick(self):
        if self.tick >= T_MAX_TICKS:
            print("⏱️ Tempo máximo de simulação atingido. Gere seu relatório.")
            return
        # ----- controle
        e_l = P["sp_level"] - self.h * 100.0
        e_t = P["sp_temp"] - self.T
        if self.mode == "AUTO":
            u_in_c = self.pid_l.update(P["sp_level"], self.h * 100.0, DT)
            u_heat_c = self.pid_t.update(P["sp_temp"], self.T, DT)
        else:
            u_in_c, u_heat_c = self.u_in, self.u_heat
        # ----- perturbações (eventos) — efeitos FORTES p/ exigirem robustez
        qf = 1.0; dTc = 0.0; dTi = 0.0; u_out_eff = self.u_out; greve = 0.0; chiller = 0
        for ev in list(self.eventos_ativos):
            self.eventos_ativos[ev] -= 1
            if self.eventos_ativos[ev] <= 0:
                del self.eventos_ativos[ev]
                continue
            if ev == "queda":
                qf = 0.65
            elif ev == "calor":
                dTc = 18.0
            elif ev == "cafeteira":
                dTi = -20.0
            elif ev == "tanque":
                u_out_eff = min(1.0, self.u_out + 0.3)
            elif ev == "greve":
                greve = 1.0   # rampa: qf cai gradualmente
            elif ev == "chiller":
                chiller = 1   # perde a refrigeração ativa (aq não pode esfriar) + jaqueta quente
        if greve:
            # rampa lenta: cada tick 1% menos, até 65%
            qf = max(0.65, qf - 0.01 * greve)
        if chiller:
            u_heat_c = max(u_heat_c, 0.0)   # só aquece; sem capacidade de esfriar
            dTc = max(dTc, 12.0)             # jaqueta mais quente
        # novo evento a partir do tick 40 (1 por vez; sem repetir o último)
        if (self.tick >= 40 and not self.eventos_ativos
                and random.random() < 0.06):
            ativos = set(self.eventos_ativos)
            proib = ativos | ({self.last_event} if self.last_event else set())
            opcoes = [k for k in EVENTOS if k not in proib] or list(EVENTOS)
            nome = random.choice(opcoes)
            self.last_event = nome
            self.eventos_ativos[nome] = EVENTOS[nome]["dur"]
            self.marcos_eventos.append((self.tick, EVENTOS[nome]["nome"]))
            print("  ⚡ " + EVENTOS[nome]["msg"])
        # ----- planta
        self.h, self.N, self.C, self.T = passo_cstr(
            self.N, self.T, self.h, u_in_c, u_out_eff, u_heat_c, P,
            qf=qf, dT_cool=dTc, dT_in=dTi)
        self.tick += 1

        # ----- gamificação (qualidade conta na fase AUTO, com graça de asserção)
        if self._qual_start:
            if self._grace > 0:
                self._grace -= 1
            else:
                self.iae_l += abs(e_l) * DT            # %·s
                self.iae_t += abs(e_t) * DT            # °C·s
                # custo da oscilação do atuador (fiscal: "viscosidade variando")
                if self._prev_uh is None:
                    self._prev_uh = u_heat_c
                else:
                    self.var_u += abs(u_heat_c - self._prev_uh)
                    self._prev_uh = u_heat_c
                self._nq += 1
        fora = (abs(e_l) > 10.0) or (abs(e_t) > 15.0)
        # graça de partida: só estressa por fora-da-banda após o tick 25
        incr = 3.0 if (fora and self.tick > 25) else (-1.0 if not fora else 0.0)
        # deadline: passou de 10 min ainda em MANUAL
        if self.mode == "MANUAL" and self.tick > 60:
            if not self.aviso_deadline:
                print("  \033[91m⚠️ ALTA VARIAÇÃO\033[0m — O gerente foi avisado! Estabilize logo.")
                self.aviso_deadline = True
            incr += 1.0
        self.stress = min(100.0, max(0.0, self.stress + incr))
        self.stress_max = max(self.stress_max, self.stress)
        if self.stress >= 100 and not self.alarme_grito:
            self.alarme_grito = True
            self._game_over = True
            print("  📢 Dr. Gustav gritou pelo telefone: "
                  "'Vou te rebaixar para o almoxarifado!'")
            print("  🛑 FIM DE JOGO — a simulação parou aqui. "
                  "Use 'relatorio' para o balanço ou reinicie (não gira mais nada).")

        # ----- alarmes (sem spam: avisa uma vez por episódio)
        h_pct = self.h * 100
        if h_pct > 95:
            if not self._flag_overflow:
                self._flag_overflow = True
                print("  ⚠️ Transbordamento! Risco de golpe de aríete na base.")
        elif h_pct < 5:
            if not self._flag_empty and self.tick > 5:
                self._flag_empty = True
                print("  ⚠️ Reator quase vazio.")
        elif self._flag_overflow:
            self._flag_overflow = False
        if self.T > 130:
            if not self._flag_crit:
                self._flag_crit = True
                print("  🔥 CRÍTICO: degradação do produto (T > 130 °C)!")
        elif self._flag_crit and self.T < 125:
            self._flag_crit = False

        # ----- nudges do Dr. Gustav: lembra o aluno de mexer no PID se ficou parado em AUTO
        # (qualquer alteração nos PIDs via `pid` ou POP-007 desativa definitivamente)
        if (self._qual_start and not self.pop007
                and self._nudge_stage < len(NUDGES)):
            tick_in_auto = self.tick - self._t_auto
            for i, (tg, msg) in enumerate(NUDGES):
                if self._nudge_stage < i + 1 and tick_in_auto >= tg:
                    self._nudge_stage = i + 1
                    print("  " + msg)

        # ----- histórico
        t = self.tick * DT
        self.hist["t"].append(t); self.hist["h"].append(h_pct)
        self.hist["T"].append(self.T); self.hist["C"].append(self.C)
        self.hist["u_in"].append(u_in_c); self.hist["u_out"].append(u_out_eff)
        self.hist["u_heat"].append(u_heat_c)
        self.hist["e_l"].append(e_l); self.hist["e_t"].append(e_t)
        self.hist["stress"].append(self.stress)
        self.hist["q"].append(self.qualidade())

    def tick_step(self, n=1):
        if self._game_over:
            print("  🛑 Fim de jogo — a simulação já terminou (Dr. Gustav te rebaixou). "
                  "Use 'relatorio' para o balanço ou reinicie.")
            return
        for _ in range(n):
            self._tick()
            if self._game_over:
                break

    def qualidade(self):
        if not self._qual_start:
            return 100.0
        t_run = max((self.tick - self._t_auto) * DT, 1.0)
        avg_l = self.iae_l / t_run          # média |erro nível| em %
        avg_t = self.iae_t / t_run          # média |erro temperatura| em °C
        var_avg = self.var_u / max(self._nq, 1)   # média |Δu_heat| por tick
        return max(0.0, round(100.0 - 10.0 * avg_l - 5.0 * avg_t - W_VAR * var_avg, 2))

    def medias(self):
        if not self._qual_start:
            return (0.0, 0.0)
        t_run = max((self.tick - self._t_auto) * DT, 1.0)
        return (self.iae_l / t_run, self.iae_t / t_run)

    def _imprime_status(self):
        e_l = P["sp_level"] - self.h * 100.0
        e_t = P["sp_temp"] - self.T
        ativos = ", ".join(EVENTOS[k]["nome"] for k in self.eventos_ativos) or "-"
        print(f"\n--- Tick {self.tick} | t = {self.tick*DT:5.0f} s | Modo: {self.mode} "
              f"| Evento: {ativos}")
        print(f"  Nível: {self.h*100:6.2f} %  (SP {P['sp_level']:.0f} %   |e| {abs(e_l):5.2f} %)")
        print(f"  Temp : {self.T:6.2f} °C (SP {P['sp_temp']:.0f} °C   |e| {abs(e_t):5.2f} °C)")
        print(f"  C_A  : {self.C:5.3f} mol/L | Qualidade: {self.qualidade():5.1f} | "
              f"Estresse: {self.stress:5.1f}/100")

    # ------------------------- comandos -------------------------
    def executar(self, linha):
        partes = linha.strip().lower().split()
        if not partes:
            return
        cmd = partes[0]
        # fim de jogo: só relatório/estado/sair ainda valem
        if self._game_over and cmd not in ("relatorio", "status", "pop", "sair"):
            print("  🛑 Fim de jogo — Dr. Gustav te rebaixou. "
                  "A simulação parou; use 'relatorio', 'status' ou 'sair'.")
            return
        try:
            if cmd == "n" and self.mode == "MANUAL" and len(partes) > 1:
                self.u_in = max(0.0, min(1.0, float(partes[1]) / 100.0))
                print(f"  → Válvula de entrada em {self.u_in*100:.0f} %")
            elif cmd == "q" and len(partes) > 1:
                self.u_out = max(0.0, min(1.0, float(partes[1]) / 100.0))
                print(f"  → Válvula de saída em {self.u_out*100:.0f} %")
            elif cmd == "r" and self.mode == "MANUAL" and len(partes) > 1:
                self.u_heat = max(0.0, min(1.0, float(partes[1]) / 100.0))
                print(f"  → Aquecedor em {self.u_heat*100:.0f} %")
            elif cmd == "auto":
                self.mode = "AUTO"
                self._qual_start = True
                self._t_auto = self.tick
                self.iae_l = self.iae_t = 0.0
                self.var_u = 0.0; self._nq = 0; self._prev_uh = None
                self._grace = GRACE_AUTO
                self.pid_l.reset(); self.pid_t.reset()
                print("  → Modo AUTOMÁTICO (PID do Dr. Gustav). Sintonia agressiva; refine-a.")
                print("    pid N <Kp> <Ki> <Kd>  e  pid T <Kp> <Ki> <Kd>")
            elif cmd == "manual":
                self.mode = "MANUAL"
                print("  → Modo MANUAL. (n=entrada, r=aquecedor, q=saída)")
            elif cmd == "pid":
                if len(partes) == 1:
                    print("  Nível : Kp={:.3g} Ki={:.3g} Kd={:.3g}".format(*self.pid_l.ganhos))
                    print("  Temp  : Kp={:.3g} Ki={:.3g} Kd={:.3g}".format(*self.pid_t.ganhos))
                elif len(partes) == 5 and partes[1] in ("n", "t"):
                    kp, ki, kd = float(partes[2]), float(partes[3]), float(partes[4])
                    alvo = self.pid_l if partes[1] == "n" else self.pid_t
                    # POP-007: registrar antes de alterar
                    self.pop007.append({
                        "tick": self.tick, "alvo": ("NÍVEL" if partes[1] == "n" else "TEMP"),
                        "antes": alvo.ganhos, "depois": (kp, ki, kd)})
                    alvo.kp, alvo.ki, alvo.kd = kp, ki, kd
                    alvo.reset()
                    print("  → PID ajustado (registrado no POP-007).")
                else:
                    print("  Uso: pid | pid N <Kp> <Ki> <Kd> | pid T <Kp> <Ki> <Kd>")
            elif cmd == "pop":
                if not self.pop007:
                    print("  Nenhuma alteração de PID registrada ainda.")
                else:
                    print("  --- POP-007 (rastreabilidade de sintonia) ---")
                    for i, r in enumerate(self.pop007, 1):
                        print(f"  {i:2d} tick {r['tick']:4d} {r['alvo']:5s}  antes {r['antes']}  ->  depois {r['depois']}")
            elif cmd == "esp":
                n = int(partes[1]) if len(partes) > 1 else 1
                self.tick_step(n)
            elif cmd == "status":
                self._imprime_status()
            elif cmd == "relatorio":
                self.relatorio()
            elif cmd == "sair":
                print("  Você abandonou o posto. Dr. Gustav não vai esquecer isso. ☠️")
                return "sair"
            else:
                print("  Comando inválido. Digite 'status' para ver os comandos.")
        except (ValueError, IndexError):
            print("  Argumento inválido.")
        if self.mode == "MANUAL":
            self._imprime_status()

    # ------------------------- relatório -------------------------
    def relatorio(self):
        if not self.hist["t"]:
            print("  Nada para reportar.")
            return
        qual = self.qualidade()
        avg_l, avg_t = self.medias()
        titulo = titulo_final(qual, self.stress_max)

        base = os.path.dirname(os.path.abspath(__file__))
        nome_csv = os.path.join(base, "relatorio_cstr77.csv")
        uh = self.hist["u_heat"]
        duh = [0.0] + [abs(uh[i] - uh[i - 1]) for i in range(1, len(uh))]
        with open(nome_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "nivel_pct", "temp_C", "conc_molL",
                        "u_entrada", "u_saida", "u_aquecedor", "oscilacao_heat",
                        "erro_nivel_pct", "erro_temp_C", "estresse", "qualidade"])
            for i in range(len(self.hist["t"])):
                w.writerow([self.hist["t"][i], self.hist["h"][i], self.hist["T"][i],
                            self.hist["C"][i], self.hist["u_in"][i], self.hist["u_out"][i],
                            self.hist["u_heat"][i], duh[i],
                            self.hist["e_l"][i], self.hist["e_t"][i],
                            self.hist["stress"][i], self.hist["q"][i]])

        fig, ax = plt.subplots(2, 2, figsize=(12, 8))
        fig.patch.set_facecolor("#1a1a2e")
        for a in ax.ravel():
            a.set_facecolor("#1a1a2e"); a.tick_params(colors="#e0e0e0")
            for s in a.spines.values():
                s.set_color("#e0e0e0")
        t = self.hist["t"]
        lbl = "#58a6ff"; temp = "#f781bf"; ql = "#56d364"; fs = "#d4a373"
        ax[0,0].plot(t, self.hist["h"], color=lbl, lw=1.6, label="Nível")
        ax[0,0].axhline(P["sp_level"], color=lbl, ls="--", lw=0.8, alpha=0.6, label="SP")
        ax[0,0].set_ylabel("Nível (%)"); ax[0,0].legend(loc="best")
        ax[0,1].plot(t, self.hist["T"], color=temp, lw=1.6, label="Temp")
        ax[0,1].axhline(P["sp_temp"], color=temp, ls="--", lw=0.8, alpha=0.6, label="SP")
        ax[0,1].set_ylabel("Temp (°C)"); ax[0,1].legend(loc="best")
        ax[1,0].plot(t, self.hist["u_in"], color="#56d364", lw=1.4, label="Válv. entrada")
        ax[1,0].plot(t, self.hist["u_out"], color="#e3b341", lw=1.4, label="Válv. saída")
        ax[1,0].plot(t, self.hist["u_heat"], color="#a371f7", lw=1.4, label="Aquecedor")
        ax[1,0].set_ylabel("Saídas"); ax[1,0].set_ylim(-1.1, 1.1)
        ax[1,0].legend(loc="best")
        ax[1,1].plot(t, self.hist["q"], color=ql, lw=1.6, label="Qualidade")
        ax[1,1].plot(t, self.hist["stress"], color=fs, lw=1.6, label="Estresse")
        ax[1,1].set_ylim(0, 100); ax[1,1].legend(loc="best")
        for tick_ev, nome in self.marcos_eventos:
            ax[0,0].axvline(tick_ev*DT, color="#ff4d4d", ls=":", lw=0.8, alpha=0.6)
        for a in ax.ravel():
            a.set_xlabel("t (s)")
            a.grid(True, color="#2a2a4a", lw=0.4)
        fig.suptitle(f"CSTR-77 — {titulo}  (Qualidade {qual:.1f} | Estresse max {self.stress_max:.0f})",
                     color="#e0e0e0", fontsize=13)

        nome_png = os.path.join(base, "relatorio_cstr77.png")
        fig.tight_layout(rect=[0,0,1,0.96])
        fig.savefig(nome_png, dpi=110, facecolor="#1a1a2e")
        plt.close(fig)

        print("\n" + "═" * 62)
        print("RELATÓRIO FINAL — " + titulo)
        print("═" * 62)
        print(f"  Duração      : {self.tick*DT:.0f} s")
        print(f"  Erro médio   : nível {avg_l:.2f} %  |  temp {avg_t:.2f} °C")
        var_avg = self.var_u / max(self._nq, 1)
        print(f"  Oscilação    : mean|Δu_aquecedor| = {var_avg:.3f}  (pesa -{W_VAR*var_avg:.1f} na qualidade)")
        q_str = f"{qual:.1f}/100" if self._qual_start else "— (não chegou à fase AUTO)"
        print(f"  Qualidade    : {q_str}")
        print(f"  Estresse máx.: {self.stress_max:.0f}/100")
        print(f"  Eventos      : {', '.join(n for _, n in self.marcos_eventos) or 'nenhum'}")
        print(f"  Alterações   : {len(self.pop007)} (POP-007)")
        if self.pop007:
            self.executar("pop")
        print(f"\n  Gráfico salvo em: {nome_png}")
        print(f"  Dados salvos em: {nome_csv}")
        return titulo


# ------------------------- fluxo interativo / demo -------------------------
def demo():
    """Execução de referência ('gabarito') para verificação do professor.
    Joga bem: enche com saída fechada, abre/equilibra, AUTO com boa sintonia."""
    semente = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    g = CSTR77(semente=semente)
    # Fase 1: partida manual — enche com a saída fechada (integrator)
    g.executar("q 0")
    g.executar("n 95")
    g.executar("r 70")
    g.tick_step(28)                     # ~53% de nível
    g.executar("q 55"); g.executar("n 55"); g.executar("r 90")
    g.tick_step(6)
    g.executar("status")
    # Fase 2: automático + boa sintonia (gabarito)
    g.executar("auto")
    g.executar("pid n 1.5 0.05 0.1")
    g.executar("pid t 0.20 0.03 0.2")
    for _ in range(20):
        g.tick_step(5)
    # Fase 3: eventos surpresa
    for _ in range(20):
        g.tick_step(5)
    g.executar("status")
    g.relatorio()
    return g


def main():
    if "--demo" in sys.argv:
        demo()
        return
    g = CSTR77(semente=input("Nº/ nome do aluno (para o placar): ").strip() or "anon")
    while True:
        try:
            linha = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if g.executar(linha) == "sair":
            break


if __name__ == "__main__":
    main()