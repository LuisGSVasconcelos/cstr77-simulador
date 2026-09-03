# 📚 GABARITO DO PROFESSOR — Operação TITÃ / Reator CSTR-77

Material de apoio para o docente aplicar a atividade gamificada e corrigir.
O aluno não deve ver o **item 3 (a sintonia)** — entregue junto apenas se quiser
"gabaritar" a Fase 4.

---

## 1. Objetivo pedagógico e mapeamento das fases

A atividade treina **controle de nível e temperatura de um CSTR não isotérmico**
crossando manual + PID, perturbações e rastreabilidade (POP-007). Cada fase cobra
uma competência:

| Fase | Enredo | Competência avaliada |
|---|---|---|
| 1. Partida fria | Tanque vazio e frio, segurar em MANUAL | Entender o processo (tanque integrador) e fazer a partida sem golpe de aríete / degradação térmica |
| 2. Fiscal / estabilidade | Migrar para AUTO e refinar o PID | Sintonizar P, I, D para assentar no setpoint com pouco overshoot |
| 3. Sexta-feira louca | Eventos aleatórios | Robustez: rejeitar perturbações sem sair da banda |
| 4. Volta do chefe | Relatório + justificativa | Comunicar escolhas e rastrear alterações (POP-007) |

---

## 2. Como reproduzir o "gabarito" (resposta certa)

```bash
python simulador_cstr77.py --demo 7
```

ou, no painel Streamlit, siga o roteiro do item 4. O resultado de referência
é **Qualidade ≥ 93 → Sucessor do Dr. Gustav** (e oscila até ~94).

---

## 3. A sintonia "gabarito" e a justificativa de cada ganho

### Controlador de NÍVEL — `pid n 1.5 0.05 0.1`

Controla a **válvula de entrada** `u_in ∈ [0,1]`; erro medido em **pontos % de nível (0–100)**.

| Ganho | Valor | Justificativa física |
|---|---|---|
| **Kp** | 1.5 | Proporcional (fração de válvula = 1.5·e). Tão rápido quanto daria: a 2 % de erro move a válvula ~3 %. Menor → lento; muito maior → satura e oscila em degraus grandes. |
| **Ki** | 0.05 | **Indispensável**: a saída é uma **bomba de descarga constante** (`q_out = q_max·u_out`), o tanque é um **integrador puro**. Proporcional puro deixa **offset** de regime (`e_ss = u_ss/Kp`); o integral zera o offset. Com DT = 10 s, 1 % de erro acumula ~0.5 % de válvula por tick. |
| **Kd** | 0.1 | Derivada **sobre a medida** (não sobre o setpoint): antecipa e amortiza o overshoot após degraus de carga (eventos "Operador do Tanque" e "Queda"). Sem Kd o nível ainda segura, mas oscila mais após perturbação. |

### Controlador de TEMPERATURA — `pid t 0.20 0.03 0.2`

Controla o **aquecedor bipolar** `u_heat ∈ [−1, 1]` (positivo aquece, negativo esfria via chiller); erro em **°C**.

| Ganho | Valor | Justificativa física |
|---|---|---|
| **Kp** | 0.20 | A 5 °C de erro → 100 % de potência. A temperatura é lenta (τ ≈ 11 min), então o P precisa dar potência suficiente em degraus. |
| **Ki** | 0.03 | Remove o erro de regime e ajusta a **potência de equilíbrio** (a que mantém 110 °C com a reação exotérmica e as perdas da jaqueta). Sem I, a temperatura assenta com offset. |
| **Kd** | 0.2 | Derivada sobre a medida: antecipa mudanças durante perturbações térmicas (Onda de Calor, Efeito Cafeteira, Falha do Refrigerante) e reduz overshoot. |

### Por que o "Dr. Gustav" (default) é ruim — e o que o aluno precisa corrigir

| | Default (ruim) | Problema ensinado |
|---|---|---|
| Nível | Kp=0.12, **Ki=0** | Ganho baixo **+ sem integral** → nível **lento e com OFFSET** (não assenta em 65 %) |
| Temperatura | Kp=2.0, **Ki=0.8** | Excesso de ganho e integral → **oscila** ao redor de 110 °C |

Correções esperadas: **aumentar o Kp do nível e ligar o I** (>> offset), **baixar o Kp/Ki da temperatura** para parar a oscilação e **adicionar Kd** para robustez nas perturbações.

---

## 4. Roteiro passo a passo para o aluno chegar ao gabarito

```text
# Partida manual: encha com a SAÍDA FECHADA (o tanque é integrador)
q 0
n 95
r 70
esp 28        # nível ~53%

# Abra a saída e equilibre
q 55
n 55
r 90
esp 6

# Modo automático
auto

# Refine o PID (gabarito)
pid n 1.5 0.05 0.1
pid t 0.20 0.03 0.2

# Deixe os eventos acontecerem e verifique a robustez
esp 20
status
relatorio
```

> **Dica de partida**: como a saída é uma bomba de descarga constante, abrir a saída
> antes de encher torna o enchimento lento. Encha com `q 0` e abra depois.

---

## 5. Métricas de avaliação (como pontuar)

- **Qualidade do lote** (forma a nota principal):
  `Q = 100 − 10·avg|Δnível|% − 5·avg|Δtemperatura|°C − 15·mean|Δu_aquecedor|`
  contada **somente na fase AUTO**, com **janela de graça de 15 ticks** para o PID
  assentar após a partida manual (o ponto de partida do manual não pune a nota).
  O último termo penaliza a **oscilação do atuador** (o "fiscal reclama que a
  viscosidade está variando"): um controlador que fica alternando aquecedor entre
  +100%/−100% acumula `mean|Δu| ≈ 1–1.5` e perde 15–23 pontos — assim **é preciso
  estabilizar a temperatura de verdade** para chegar ao topo, não só mantê-la na média.
- **Placar final**:

| Qualidade | Título | Leitura para a nota |
|---|---|---|
| ≥ 95 | Mão de Anjo ⭐ | Excelente (assinatura quase perfeita + robustez) |
| 85–94 | Sucessor do Dr. Gustav 🏆 | **Gabarito típico (93–94)** |
| 70–84 | Operador TITÃ aprovado ✅ | Controlou, mas com folgas/overshoot |
| < 70 (ou estresse = 100) | Almoxarifado 📦 | Não sintonizou: default do Gustav |

- **Estresse do chefe** (ferramenta de gestão): +3/tick fora da banda
  (`|Δnível| > 10 %` ou `|Δtemp| > 15 °C`) após o tick 25; −1/tick dentro; +1 extra
  se ainda em MANUAL após ~10 min. Estresse = 100 ⇒ Almoxarifado (mesmo com boa nota).
- **POP-007**: exija o log de quantas vezes o aluno alterou o PID e a justificativa
  (rastreabilidade 21 CFR Part 11). "Alterações = 0" é um forte indício de que ele
  não sintonizou. No painel Streamlit, **cada alteração de sintonia também é
  registrada** (antes→depois) — mexe no slider, entra no POP-007.

---

## 6. Resultados validados (referência para calibração)

Validado em **6 sementes** (eventos aleatórios), mesma partida manual:

| Cenário | Qualidade | Título | Comentário |
|---|---|---|---|
| **Sem sintonia** (default) | **27 – 39** | Almoxarifado | Offset no nível + temperatura oscilando (atuador bang-bang); não rejeita as perturbações |
| **Só o nível afinado** (temp default) | **75 – 78** | Operador TITÃ aprovado | Nível 0.8–1 %; temperatura ainda oscila → penalidade de `mean|Δu|` segura a nota |
| **Ambos afinados** (item 3) | **86 – 90** | Sucessor do Dr. Gustav | Assenta em 65 % / 110 °C com atuador suave e rejeita os eventos |

Ou seja: **é preciso corrigir os DOIS loops** para chegar ao "Sucessor". Corrigir só o
nível rende "Aprovado"; deixar tudo no default é "Almoxarifado". Não há "sorte de semente".

Se algum aluno relatar nota ≥ 85 sem mexer no PID, verifique a coluna
**`oscilacao_heat`** no CSV exportado (é `|Δu_aquecedor|` por tick) — calcule a
média dela na fase AUTO: acima de ~0.3 o aquecedor está oscilando (default), então
a nota não passaria de "Aprovado". Boa sintonia de temperatura fica ~0.03–0.10.

---

## 7. Armadilhas comuns e como corrigi-las

| Sintoma do aluno | Causa provável | Orientação |
|---|---|---|
| Nível não assenta em 65 % (fica em ~60 %) | PID de nível **sem integral** (offset) | Ligar o `Ki` (ex.: 0.05) |
| Nível sobe/desce devagar na partida | Abriu a saída antes de encher | Encher com `q 0`, abrir depois |
| Temperatura "respira" em torno de 110 °C | `Ki` da temperatura grande (default 0.8) | Baixar `Ki` (ex.: 0.03) e ajustar `Kp` |
| Oscila muito após um evento | Falta `Kd` (derivada) | Adicionar `Kd` moderado (ex.: 0.1–0.2) |
| "Eu não mexi em nada e passei" | (não deve acontecer) | Conferir se saiu da banda/estresse; revalidar dificuldade |

---

## 8. Parâmetros do modelo (referência rápida)

| Parâmetro | Valor | Significado |
|---|---|---|
| V_max | 10 L | Capacidade do reator |
| C_A0 / T_in | 1.0 mol/L / 60 °C | Alimentação (pré-aquecida) |
| q_max | 0.02 L/s | Vazão máx. (entrada/saída) |
| Q_max | 2000 W | Aquecedor bipolar (aquecer/esfriar) |
| UA | 5 W/K | Jaqueta (trocador) |
| rho_cp | 1500 J/(L·K) | Solvente |
| dH / k0 / Ea | −50 kJ/mol / 3e5 / 60 kJ/mol | Cinética exotérmica de 1ª ordem |
| Setpoints | 65 % / 110 °C | Nível / temperatura alvo |

Saída por **bomba de descarga constante** (`q_out = q_max·u`), tanque **integrador**;
balanço **molar** `N = C·V` (robusto p/ V→0).

---

## 9. Extensões possíveis (além do mínimo)

- Pedir ao aluno que **projete** os ganhos por um método clássico (Ziegler–Nichols,
  reação em malha aberta) e compare com o empírico.
- Fazer o aluno **exportar o CSV** (`relatorio`) e plotar em Excel para calcular
  sobre-elevação e tempo de assentamento.
- Debater **ação unilateral**: por que a temperatura usa atuador bipolar (aquecer/esfriar)
  e o que aconteceria com só um aquecedor — conecta com sistemas reais.
- Usar o **estresse** como "custo operacional" e pedir uma análise custo-benefício
  entre assentar rápido (mais agressivo, mais estresse) e suave (mais devagar).