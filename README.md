# OPERAÇÃO TITÃ — Simulador do Reator CSTR-77

Simulador em Python de um **reator CSTR não isotérmico** (nível + concentração + temperatura) com
controle **manual e automático (PID)**, perturbações aleatórias e **gamificação**, alinhado à atividade
didática "Operação TITÃ: O Desafio do Reator CSTR-77" (ver `docs/Simulador_CSTR.pdf`).

Projetado para sala de aula (Eng. Química / Automação): o aluno assume a operação do reator, leva a
planta do zero ao setpoint em modo manual e depois refina a sintonia PID para rejeitar perturbações,
pontuando por **qualidade do lote (IAE)** e pelo **estresse do chefe (Dr. Gustav)**.

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

1. `q 55`, `n 85`, `r 70` → enche e aquece no manual
2. `esp 25` → observa nível/temperatura subirem
3. `auto` → liga os PID (sintonia "do Dr. Gustav", ruins de propósito)
4. `pid n 1.4 0.02 0.1` e `pid t 0.12 0.01 0.1` → retune
5. `esp 20` → deixa surgir os eventos surpresa
6. `relatorio` → entrega o relatório

## Modelo físico

- **Estados**: nível `h`, concentração `C_A`, temperatura `T`.
- **Balanço molar** `N = C·V`, `dN/dt = q_in·C_A0 − q_out·C − r·V` (robusto para `V→0`).
- **Energia**: aquecedor bipolar (aquecer/esfriar), reação exotérmica de 1ª ordem
  (`r = k₀·exp(−Ea/(R·T))·C`), remoção por alimentação e jaqueta.
- **Escorvento de saída por gravidade**: `q_out = K·√h·u`.
- **Controle**: PID posicional com anti-windup e derivada filtrada sobre a medição;
  saída bipolar de temperatura (`[-1,1]`).

## Gamificação

- **Qualidade do lote** por IAE (erro médio em `%` e `°C`) — medida **na fase AUTO**.
- **Estresse do chefe** (0–100) com período de graça de partida.
- **Eventos surpresa**: Queda da Matéria-Prima, Onda de Calor, Operador do Tanque,
  Efeito Cafeteira e Greve dos Fornecedores.
- **Placar**: Mão de Anjo ⭐ / Sucessor do Dr. Gustav 🏆 / Operador TITÃ aprovado ✅ / Almoxarifado 📦
- **POP-007**: registrar toda alteração de PID (rastreabilidade 21 CFR Part 11).

## Saída

`sair`/`relatorio` gera `relatorio_cstr77.png` (4 subplots) e `relatorio_cstr77.csv`
(série temporal completa) no diretório atual. Exemplo de saída em `docs/relatorio_cstr77.png`.

## Licença

MIT — veja `LICENSE`. © Luis Gonzaga Sales Vasconcelos.