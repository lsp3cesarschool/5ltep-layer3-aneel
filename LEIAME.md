# 5LTEP-L3 · instância ANEEL (experimento de controle)

[![Tests](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/tests.yml/badge.svg)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/tests.yml) [![Camada 3](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Flsp3cesarschool%2F5ltep-layer3-aneel%2Fmain%2Fdocs%2Fdata%2Fstatus-aneel-autos-infracao.pt.json)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/layer3.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) · **Português**

**Detecção de anomalias da Camada 3 do 5L-TEP aplicada aos autos de infração da ANEEL, a agência
reguladora do setor elétrico: uma segunda instância do [5ltep-layer3](https://github.com/lsp3cesarschool/5ltep-layer3/blob/main/LEIAME.md),
montada pelo autor como caso de controle do estudo do IBAMA.**

| Recurso | O que tem lá |
|---|---|
| 📊 **Painel** | [lsp3cesarschool.github.io/5ltep-layer3-aneel](https://lsp3cesarschool.github.io/5ltep-layer3-aneel/?lang=pt): anomalias, rótulos do LLM, decisões do gestor e a proveniência de cada resultado |
| 🧑‍⚖️ **Fila de revisão** | [![revisões abertas](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/layer3?label=revis%C3%B5es%20abertas&color=0366d6)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Alayer3) [![pendentes](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/review%3Apending?label=pendentes&color=d73a4a)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Areview%3Apending) [![recomendadas](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/review%3Aadvisory?label=recomendadas&color=fbca04)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Areview%3Aadvisory) [![mudança de nível](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/review%3Alevel-shift?label=mudan%C3%A7a%20de%20n%C3%ADvel&color=f9d0c4)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Areview%3Alevel-shift)<br>contagens ao vivo; cada selo abre sua lista de issues |
| 🏛️ **Instância principal** | [5ltep-layer3](https://github.com/lsp3cesarschool/5ltep-layer3/blob/main/LEIAME.md): IBAMA, e a documentação completa |
| 🧪 **Escolha do modelo** | [5ltep-layer3-modeltest](https://github.com/lsp3cesarschool/5ltep-layer3-modeltest/blob/main/LEIAME.md): o benchmark mensal que escolhe o LLM juiz |
| 🔒 **Segurança** | [SECURITY.md](SECURITY.md): o que não é confiável (o modelo, o portal de dados, fontes da web), como o kit o contém, e como relatar uma vulnerabilidade |

> **Situação: demonstração de pesquisa.** Este repositório não é operado pela ANEEL, não tem vínculo
> com ela nem aval dela; apenas lê os dados abertos da ANEEL. Ele mostra que o kit pode ser reutilizado
> em outro portal. Não pressupõe que a ANEEL vá revisar seus resultados ou adotá-lo. As issues de
> revisão abertas demonstram o fluxo: não há gestor designado.

## Caso de uso em um parágrafo

A ANEEL publica todos os autos de infração emitidos às empresas do setor elétrico (geração,
transmissão, distribuição) por suas áreas de fiscalização e pelas agências estaduais conveniadas.
Suponha que a agência, ou quem reutiliza esses dados, queira saber se o registro publicado é confiável
e por onde começar se algo estiver errado. Esta camada monta séries mensais (número de autos, valor
total das penalidades), encontra os meses que fogem do padrão e usa um modelo de IA local para
verificar quais desvios têm explicação conhecida (nova regulamentação, ciclo recorrente de
fiscalização) e quais parecem **problema nos dados** (mês sem registros numa série ativa, lote de autos
lançado de uma vez). Os não explicados vão primeiro para uma pessoa; a IA apenas propõe, e um gestor de
dados confirma ou corrige toda decisão que leve a uma ação.

## Por que um experimento de controle

O kit da Camada 3 da Pirâmide de Engenharia da Confiança em Cinco Camadas (5L-TEP) foi construído
sobre os dados abertos do IBAMA. Um método que funciona num conjunto de dados pode ter aprendido apenas
as peculiaridades desse conjunto. Este repositório roda **o mesmo código** num órgão, num portal e numa
escala diferentes, seguindo os passos que outra instituição seguiria para adotá-lo, e faz duas
perguntas:

1. **Reutilização (o *R* do FAIR):** o kit pode ser adotado escrevendo um perfil, sem mudar código?
2. **Transferência:** a detecção, o LLM-as-a-Judge e o protocolo de revisão se comportam da mesma forma
   num conjunto pequeno e esparso como no conjunto grande do IBAMA?

O que difere do repositório principal é apenas:

| Arquivo | Por quê |
|---|---|
| [`profiles/aneel-autos-infracao.json`](profiles/aneel-autos-infracao.json) | o conjunto de dados: portal, recurso, colunas, séries, texto de domínio para o LLM |
| [`profiles/events/brazil-electricity-regulation.json`](profiles/events/brazil-electricity-regulation.json) | o calendário de eventos, iniciado quase vazio e feito para ser preenchido com *Suggest events* e verificado por um gestor |
| este LEIAME e sua versão em inglês, [`README.md`](README.md) | |

Os perfis e resultados do IBAMA não estão incluídos. Todo o resto (detectores, LLM-as-a-Judge, revisão
humana, painel, workflows, testes) é idêntico a
[`5ltep-layer3@1554bc4`](https://github.com/lsp3cesarschool/5ltep-layer3/tree/1554bc497d64e5d49eb3e6fa1ea775a6134713a8),
e a instância montada passa na mesma suíte de testes antes de cada atualização.

## Termos-chave

| Termo | Significado aqui |
|---|---|
| **Anomalia** | um mês de uma série mensal (número de autos, total das penalidades) que foge do padrão habitual, sinalizado por pelo menos 2 de 4 detectores estatísticos |
| **Mudança de nível** | uma mudança duradoura de patamar (não um pico de um mês), detectada por um teste de Page-Hinkley |
| **LLM-as-a-Judge** | um modelo de linguagem pequeno, executado localmente e sem custo, que lê cada anomalia com seu contexto e diz qual das quatro causas abaixo a explica melhor |
| **Gestor de dados** (*data steward*) | a pessoa que confirma ou corrige o rótulo do juiz (por uma issue do GitHub) antes de qualquer ação |

As quatro causas (categorias) entre as quais o juiz escolhe:

| Código | Categoria | Exemplo (ANEEL) | O que significa |
|---|---|---|---|
| **PDC** | Mudança por política (*Policy-Driven Change*) | os autos mudam depois de uma nova resolução normativa ou de uma troca de governo | explicada por um evento conhecido: documentar |
| **SP** | Padrão sazonal (*Seasonal Pattern*) | um ciclo de fiscalização que se repete nos mesmos meses todo ano | comportamento esperado: nenhuma ação |
| **DQE** | Evento de qualidade de dados (*Data-Quality Event*) | um mês sem autos numa série que, fora isso, é ativa; centenas de autos lançados num único mês | um **problema nos dados**: sempre revisado por um gestor |
| **GES** | Mudança genuína de fiscalização (*Genuine Enforcement Shift*) | uma mudança duradoura na intensidade da fiscalização, sem evento e sem sinais nos dados | uma mudança real que ninguém explicou ainda |

## Como os dados da ANEEL diferem dos do IBAMA

| | IBAMA (estudo principal) | ANEEL (controle) |
|---|---|---|
| Registros | ~711.000 autos desde 1977 | ~1.600 autos desde 2018 |
| Recurso | zip com um CSV por ano | um CSV |
| Colunas de data / chave / valor | `DAT_HORA_AUTO_INFRACAO` / `SEQ_AUTO_INFRACAO` / `VAL_AUTO_INFRACAO` | `DatLavraturaAutoInfracao` / `NumAutoInfracao` / `VlrPenalidade` |
| Indicador de cancelamento | sim (excluídos, contados) | nenhum |
| Volume mensal | centenas a milhares | em geral menos de 20, com meses vazios |
| Moeda | várias moedas antes de 1994 (convertidas para Reais) | só Reais |
| Calendário de eventos | curado, ~14 eventos verificados | 3 eventos verificados, a ampliar |
| Licença dos dados | dados abertos do IBAMA | ODbL |

## Como funciona

O pipeline é o documentado no [LEIAME principal](https://github.com/lsp3cesarschool/5ltep-layer3/blob/main/LEIAME.md);
em resumo:

```
┌────────────────────────────────────────────────────────────┐
│  GitHub Actions: cron mensal + botão "Run workflow"        │
│  (runner de repositório público: 4 vCPU / 16 GB, gratuito) │
└─────────────────────────────┬──────────────────────────────┘
                              ▼
 ① Fonte      API CKAN de dadosabertos.aneel.gov.br → CSV (SHA-256 registrado)
 ② Agregar    só as colunas de data, identificador e penalidade (nenhum nome de empresa ou CNPJ guardado)
 ③ Detectar   Z-score · MAD · Isolation Forest · LSTM-ED (voto ≥ 2) + Page-Hinkley
 ④ Julgar     Ollama + o modelo aprovado pelo benchmark, 3 execuções com semente, resposta JSON
 ⑤ Revisar    issues do GitHub: rótulo steward:<CATEGORIA> + fechar (review:pending para DQE)
 ⑥ Relatório  layer3_summary.json (l3_rate, l3_pass, anomaly_flags) + painel
                              ▼
       Histórico Git de cada série, detecção, julgamento e revisão
```

- **Lotes:** cada execução julga até 25 anomalias, faz o commit e inicia o próximo lote até não sobrar
  nada pendente; um mês é tempo de sobra para todo o histórico.
- **Sem rejulgamento por padrão:** cada julgamento guarda uma impressão digital dos seus próprios dados
  e o modelo e a versão do prompt que o produziram. Só é julgado de novo se seus dados mudarem, ou se um
  gestor pedir (entrada `rejudge` = `stale` ou `all` do workflow, ou o botão **Re-judge** do painel).
- **Modelo:** `LLM_MODEL=auto` (padrão) usa o modelo que o
  [benchmark](https://github.com/lsp3cesarschool/5ltep-layer3-modeltest/blob/main/LEIAME.md) aprova no
  momento; uma variável de repositório pode fixar outro.
- **Revisão:** rótulos DQE sempre vão para um gestor; rótulos inconsistentes (as três execuções
  discordam) recebem revisão recomendada; cada mudança de nível sustentada vira uma issue para todos os
  meses em volta dela.
- **Calendário de eventos:** *Suggest events* pede ao LLM eventos ancorados nas páginas da Wikipédia
  "*ano* no Brasil" e abre um pull request; as sugestões ficam marcadas `suggested` até um gestor
  verificá-las.

## Primeiros resultados (30/09/2026)

*Um retrato para registro; o painel sempre mostra a situação atual.*

**Dados.** 1.601 linhas lidas; 11 números de auto duplicados descartados; 18 autos sem valor de
penalidade; janela de análise de 2018-06 a 2026-08 (99 meses). Uma data de decisão tem o ano "0209",
um erro de digitação do tipo que as Camadas 1-2 deveriam pegar.

**Detecção.** 10 meses anômalos (4 no número de autos, 6 no total das penalidades), nenhuma mudança de
nível sustentada. Um pico se destaca: 455 autos em dezembro de 2024, contra uma mediana habitual de
cerca de 6, muito provavelmente autos lançados em lote.

**Quão sensível é a detecção aqui.** O benchmark de injeção sintética de
[`evaluation/`](evaluation/) injeta anomalias de tipo conhecido (picos ×3, quedas, lacunas de dois
meses, mudanças de nível) nas séries reais. Na ANEEL, o *ensemble* encontrou 7% delas no número de
autos e 26% nas penalidades (número de autos do IBAMA: 80%). Com mediana de ~6 autos por mês e meses
vazios, uma mudança de três vezes fica dentro da variação normal: a Camada 3 é bem menos sensível em
séries pequenas e esparsas, e isso precisa ser informado por série.

**Juiz.** As mesmas 10 anomalias foram julgadas por dois modelos:

| | gemma3:4b (primeiro modelo) | qwen3:4b (escolha do benchmark desde 30/09/2026) |
|---|---|---|
| Rótulos | SP 6 · GES 2 · DQE 2 | DQE 7 · GES 3 |
| Concordância entre os dois | 2 de 10 anomalias | |

O qwen3:4b, que teve o melhor resultado no gabarito do benchmark, lê os meses com penalidade zero como
"quase zero numa série ativa" (um sinal de qualidade de dados) e os marca como DQE; o gemma3:4b chamou a
maioria deles de sazonal. Numa série em que meses vazios são normais, nenhuma das leituras é obviamente
certa: é exatamente o tipo de decisão que o desenho deixa para um gestor, e mostra que o gabarito do
benchmark, construído sobre as séries grandes do IBAMA, ainda não representa dados de baixo volume.

## O que o experimento de controle mostrou

- **Reutilização sem mudar código: sim, depois de duas correções.** Só foram escritos o perfil, o
  calendário e o README. Rodá-lo expôs duas suposições que valiam para o IBAMA mas não em geral, ambas
  corrigidas no código comum do repositório principal: (1) meses esparsos só no início de uma série (a
  regra original descartava 93 dos 99 meses da ANEEL); (2) um perfil padrão fixado no IBAMA.
- **A detecção se transfere mal para séries pequenas:** ver acima.
- **Os rótulos do juiz dependem mais do modelo em dados esparsos:** 2 de 10 concordâncias entre dois
  modelos, contra um quadro muito mais estável nas quedas de janeiro do IBAMA.
- **Mesmo custo:** zero, nos mesmos runners gratuitos.

## Como rodar, e adaptar de novo

| Workflow | Quando | O quê |
|---|---|---|
| `layer3.yml` | dia 5 de cada mês, e manual (painel *Run Layer 3 now*, *Re-judge*) | detectar → julgar em lotes → issues de revisão → relatório |
| `reviews.yml` | quando uma issue `layer3` é rotulada ou fechada | registra as decisões do gestor, atualiza o painel |
| `events.yml` | manual (painel *Suggest events*) | sugestões de eventos do LLM → pull request |
| `model-check.yml` | dia 22 de cada mês | só se o modelo estiver fixado: propõe a escolha do benchmark |
| `tests.yml` | push / pull request | suíte de testes |

Esta instância é, ela mesma, a receita para uma terceira: faça um fork do repositório principal,
substitua os perfis pelos seus (`python main.py check-profile profiles/<seu>.json` valida um perfil
contra o portal real), marque-o `"scheduled": true`, apague `data/`, `results/` e `docs/data/`,
habilite o Actions e o Pages, e rode o workflow uma vez. O LEIAME principal detalha cada passo e cada
campo do perfil.

## Reprodutibilidade

Cada execução registra o SHA-256 do arquivo analisado e do perfil, cada parâmetro do método, as versões
do Python e dos pacotes, e, para cada julgamento, o prompt completo, as três respostas com suas
sementes, o digest do modelo e a versão do prompt. As séries mensais são versionadas, então a detecção
pode ser refeita exatamente sobre os dados de qualquer commit passado com
`python main.py detect --from-series`, mesmo que o arquivo do portal mude com o tempo.

## Limitações

- Conjunto pequeno: 99 meses e 10 anomalias são poucos para estatísticas sobre a qualidade do juiz.
- O calendário de eventos está quase vazio: a maioria das anomalias é julgada sem o contexto que um
  especialista em regulação traria.
- A sensibilidade da detecção é baixa nesta série (ver *Primeiros resultados*).
- Nenhuma decisão de gestor, por desenho: o fluxo de revisão funciona e está pronto para ser adotado, e
  as métricas de revisão (concordância humano-LLM, tempo de revisão) se preenchem automaticamente se e
  quando um gestor o usar. O autor não faz o papel de gestor, o que seria autoavaliação.

## Documentação e referências

Método, parâmetros, protocolo de revisão humana, notas sobre FAIR e replicabilidade, e como adaptar o
kit: **<https://github.com/lsp3cesarschool/5ltep-layer3/blob/main/LEIAME.md>**. Escolha do modelo:
**<https://github.com/lsp3cesarschool/5ltep-layer3-modeltest/blob/main/LEIAME.md>**.

- Pinheiro, L. S., et al. (2026). *Towards Trust Engineering in Open Data Systems: A Layered Conceptual Framework Integrating Quality Assurance and Governance Perspectives*. SOFTENG 2026, IARIA, pp. 21–28.
- ANEEL. *Auto de Infração*. Portal de Dados Abertos da ANEEL. <https://dadosabertos.aneel.gov.br/dataset/auto-de-infracao>

## Licença

Código: MIT, ver [LICENSE](LICENSE). As séries mensais em `data/` são agregados derivados dos dados
abertos da ANEEL (ODbL); ao reutilizá-las, cite o portal de dados abertos da ANEEL como fonte original.
