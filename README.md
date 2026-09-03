# OPERAÇÃO TITÃ — Simulador do Reator CSTR-77

Simulador em Python de um **reator CSTR não isotérmico** (nível + concentração + temperatura) com
controle **manual e automático (PID)**, perturbações aleatórias e **gamificação**, alinhado à atividade
didática "Operação TITÃ: O Desafio do Reator CSTR-77" (ver `docs/Simulador_CSTR.pdf`).

Projetado para sala de aula (Eng. Química / Automação): o aluno assume a operação do reator, leva a
planta do zero ao setpoint em modo manual e depois refina a sintonia PID para rejeitar perturbações,
pontuando por **qualidade do lote (IAE)** e pelo **estresse do chefe (Dr. Gustav)**.

> 👨‍🏫 Para o docente: veja `PROFESSOR.md` — o **gabarito** com a sintonia boa e a
> justificativa física de cada ganho, roteiro passo a passo, rubrica de correção e
> resultados validados (sem sintonia ≈ 42–53, boa sintonia ≈ 93–94).

## Instalação

```bash
pip install numpy matplotlib pillow
```

## Como executar

PowerShell / terminal:

```bash
python simulador_cstr77.py
```

Verificação rápida / gabarito automático (reproduzível pela semente):

```bash
python simulador_cstr77.py --demo 7
```

## Versão Streamlit (painel interativo)

Uma interface gráfica reutiliza o mesmo núcleo numérico (`app.py`):

```bash
pip install streamlit plotly
streamlit run app.py
```

Painel com sliders de válvula/aquecedor (manual), tuning de PID (nível e temperatura),
botões de avanço (1 / 10 / 30 ticks), medidor de estresse, gráficos interativos
(nível, temperatura, saídas de controle, qualidade/estresse) e relatório final
com título e download em CSV. Sem loops bloqueantes — cada interação avança a
simulação e re-renderiza.

## Comandos do jogo

| Comando                 | Ação                                   |
|-------------------------|----------------------------------------|
| `n 60`                  | vazão de entrada 60% (modo manual)     |
| `q 55`                  | válvula de saída 55%                   |
| `r 70`                  | aquecedor 70% (manual)                 |
| `auto` / `manual`       | alterna modo automático / manual       |
| `pid n <Kp> <Ki> <Kd>`  | ajusta PID do **nível**                |
| `pid t <Kp> <Ki> <Kd>`  | ajusta PID da **temperatura**          |
| `pid`                   | mostra sintonias atuais                |
| `pop`                   | log POP-007 (rastreabilidade)         |
| `esp [n]`               | avança `n` ticks (1 tick = 10 s)      |
| `status`                | estado atual                           |
| `relatorio`             | gera gráfico (PNG) + CSV + título final |
| `sair`                  | encerra                                |

## Roteiro de jogo sugerido

1. **Encha** com a saída fechada: `q 0`, `n 95`, `r 70`; `esp 28`
2. Abra a saída e equilibre: `q 55`, `n 55`, `r 90`; `esp 6`
3. `auto` → liga os PID (sintonia do Dr. Gustav, **ruim de propósito**)
4. Retune: `pid n 1.5 0.05 0.1` e `pid t 0.20 0.03 0.2`
5. `esp 20` → deixa surgir os eventos surpresa
6. `relatorio` → entrega o relatório

> **Dica de partida**: a saída é uma **bomba de descarga constante** (o tanque é um
> integrador). Se abrir a válvula de saída antes de encher, o enchimento fica lento —
> encha com `q 0` e só depois abra a saída.

## Modelo físico

- **Estados**: nível `h`, concentração `C_A`, temperatura `T`.
- **Balanço molar** `N = C·V`, `dN/dt = q_in·C_A0 − q_out·C − r·V` (robusto para `V→0`).
- **Energia**: aquecedor bipolar (aquecer/esfriar), reação exotérmica de 1ª ordem
  (`r = k₀·exp(−Ea/(R·T))·C`), remoção por alimentação e jaqueta.
- **Escorvamento de saída por bomba de descarga constante**: `q_out = q_max·u`
  (o tanque é um integrador puro; PID sem integral deixa offset — lição da Fase 2).
- **Controle**: PID posicional com anti-windup e derivada filtrada sobre a medição;
  saída bipolar de temperatura (`[-1,1]`). Sintonia default "do Dr. Gustav" ruim
  de propósito (nível com ganho baixo sem `I` → offset; temperatura agressiva → oscila).

## Gamificação

- **Qualidade do lote** por IAE (erro médio em `%` e `°C`) — medida **na fase AUTO**,
  com janela de graça inicial (15 ticks) para o PID assentar após a partida manual.
- **Estresse do chefe** (0–100) com período de graça de partida.
- **Eventos surpresa**: Queda da Matéria-Prima, Onda de Calor, Operador do Tanque,
  Efeito Cafeteira, Greve dos Fornecedores e Falha do Refrigerante.
  Perturbações dimensionadas para serem **rejeitáveis** pelo controle (abrir o inlet
  segura o nível; o atuador bipolar segura a temperatura) — um PID ruim lento/ sem
  integral não rejeita; um bom, sim.
- **Placar**: Mão de Anjo ⭐ / Sucessor do Dr. Gustav 🏆 / Operador TITÃ aprovado ✅ / Almoxarifado 📦
- **POP-007**: registrar toda alteração de PID (rastreabilidade 21 CFR Part 11).

## Saída

`sair`/`relatorio` gera `relatorio_cstr77.png` (4 subplots) e `relatorio_cstr77.csv`
(série temporal completa) no diretório atual. Exemplo de saída em `docs/relatorio_cstr77.png`.

## Licença

MIT — veja `LICENSE`. © Luis Gonzaga Sales Vasconcelos.