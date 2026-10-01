# Security policy · Política de segurança

[English](#english) · [Português](#português)

## English

This toolkit is a research demonstration, maintained by its author. It is meant to run unattended
on GitHub Actions, so it treats as **untrusted** everything that does not come from this repository's
own code: the open data portal, the language model (its weights and every word it writes), web sources
such as Wikipedia, the inputs of manual runs, and anyone who can open an issue or a pull request.

### Reporting a vulnerability

Use **Security → Report a vulnerability** on GitHub (private), or write to `lsp3@cesar.school`. Please
do not open a public issue for a vulnerability.

### Threats considered and what the toolkit does about them

| Threat | Mitigation | Where |
|---|---|---|
| A **malicious or tampered model**, e.g. tuned to pass the public gold set and to write harmful text in new situations | Its output is data, never code: the category must be one of the profile's codes; the reasoning is bounded and stripped of control characters; in GitHub Issues it is neutralised (no HTML, links, images, @mentions, #references); the dashboard escapes everything and only follows http(s) links. Data-quality labels go to a steward. | `src/safety.py`, `src/judge.py`, `src/review.py`, `docs/app.js` |
| **Code execution through a model file** (a crafted GGUF exploiting the inference engine) | The model runs in a job with a **read-only token** and no stored credentials; it hands its results over as an artifact. A separate job, which never runs the model, accepts only this profile's data and results, with the expected structure and bounded sizes, and is the only one that writes. | `layer3.yml` (jobs `analyse` / `publish`), `main.py accept-artifact` |
| **Model supply chain**: a new or swapped model reaching production | Production follows the [model benchmark](https://github.com/lsp3cesarschool/5ltep-layer3-modeltest) only for Ollama models from the official library or the curated list; the benchmark adopts a build only after **30 days** in observation; the approved **digest** is checked after every download, so a tag that changes under the same name is refused until the benchmark approves the new build. In the benchmark, each candidate's result is accepted only from its own job. | `src/model_select.py`, `setup-ollama`, the benchmark repository |
| **Script injection in workflows** (a crafted model name, profile or input) | Values reach the shell through environment variables, never pasted into scripts with `${{ }}` (a test fails otherwise); model names, digests and options must match strict patterns before reaching a shell or `$GITHUB_ENV`. | all workflows, `tests/` |
| **Prompt injection through the data** | From the records, only aggregated monthly numbers reach the model. Event suggestions (from Wikipedia, editable by anyone) are **not given to the judge** until a steward verifies them, and arrive only through a pull request that may only append entries marked "suggested". | `src/profile.py`, `events.yml`, `main.py accept-events` |
| **Software supply chain** | Ollama is installed from a pinned release checked against its SHA-256 (no `curl … \| sh`); llama.cpp and the PrismML fork are pinned (release checksum, commit); GGUF files are checked against their hash; Python dependencies are pinned to exact versions; cached model files are re-verified against their hashes. | `setup-ollama`, `setup-llamacpp`, `requirements.txt` |
| **Forged review decisions** | Only issues opened by the workflow itself count; a decision is a label, which only people with triage rights can apply. | `src/review.py` |
| **The repository itself** | Each job gets only the permissions it needs; the default workflow token is read-only; force pushes and deletion of `main` are blocked; Dependabot alerts and security updates, secret scanning and code scanning are on. | repository settings |
| **Personal data** | Raw files are never committed; only the columns a profile needs are read, and only monthly aggregates are published. | `src/aggregate.py` |

### Residual risks (not solved, by nature)

- A model that answers the gold set well but mislabels other cases on purpose can still produce wrong
  **labels**. The harm is bounded (a category and a text that are never executed), data-quality labels
  go to a person, and the waiting period gives others time to notice a bad release; a hidden hold-out
  test set would make tuning to the benchmark harder (not implemented).
- The toolkit trusts GitHub, the GitHub-hosted runners, the official Ollama library and the pinned
  releases it downloads.
- When a model tag changes upstream, production stops judging until the benchmark approves the new
  build (it fails loudly on purpose); run the benchmark manually to resume sooner.
- Suggested events are only as good as the person who reviews the pull request.

### What maintainers can do (optional)

- Enable two-factor authentication on the account, and *Settings → Notifications → Actions → Only
  notify for failed workflows*.
- Update pinned versions deliberately, with their checksums: `setup-ollama` (Ollama version and
  SHA-256), `setup-llamacpp` in the benchmark repository, `requirements.txt`.
- Review event pull requests before merging; a `verified` event reaches the judge.

## Português

Este kit é uma demonstração de pesquisa, mantida pelo seu autor. Ele foi feito para rodar sem
supervisão no GitHub Actions, então trata como **não confiável** tudo o que não vem do próprio código
deste repositório: o portal de dados abertos, o modelo de linguagem (seus pesos e cada palavra que ele
escreve), fontes da web como a Wikipédia, as entradas das execuções manuais e qualquer pessoa que possa
abrir uma issue ou um pull request.

### Como relatar uma vulnerabilidade

Use **Security → Report a vulnerability** no GitHub (privado), ou escreva para `lsp3@cesar.school`. Por
favor, não abra uma issue pública para uma vulnerabilidade.

### Ameaças consideradas e o que o kit faz contra elas

| Ameaça | Mitigação | Onde |
|---|---|---|
| Um **modelo malicioso ou adulterado**, por exemplo ajustado para passar no gabarito público e escrever texto nocivo em situações novas | A saída dele é dado, nunca código: a categoria precisa ser um dos códigos do perfil; o raciocínio é limitado em tamanho e sem caracteres de controle; nas issues do GitHub é neutralizado (sem HTML, links, imagens, @menções, #referências); o painel escapa tudo e só segue links http(s). Rótulos de qualidade de dados vão para um gestor. | `src/safety.py`, `src/judge.py`, `src/review.py`, `docs/app.js` |
| **Execução de código por um arquivo de modelo** (um GGUF forjado explorando o motor de inferência) | O modelo roda num job com **token somente leitura** e sem credenciais guardadas; entrega os resultados como artefato. Um job separado, que nunca roda o modelo, aceita só os dados e resultados deste perfil, com a estrutura esperada e tamanhos limitados, e é o único que escreve. | `layer3.yml` (jobs `analyse` / `publish`), `main.py accept-artifact` |
| **Cadeia de suprimentos de modelos**: um modelo novo ou trocado chegando à produção | A produção segue o [benchmark de modelos](https://github.com/lsp3cesarschool/5ltep-layer3-modeltest) só para modelos do Ollama da biblioteca oficial ou da lista curada; o benchmark só adota uma build depois de **30 dias** em observação; o **digest** aprovado é conferido após cada download, então uma tag que muda sob o mesmo nome é recusada até o benchmark aprovar a nova build. No benchmark, o resultado de cada candidato só é aceito do próprio job. | `src/model_select.py`, `setup-ollama`, o repositório do benchmark |
| **Injeção de script nos workflows** (nome de modelo, perfil ou entrada forjados) | Os valores chegam ao shell por variáveis de ambiente, nunca colados nos scripts com `${{ }}` (um teste falha se isso acontecer); nomes de modelo, digests e opções precisam seguir padrões estritos antes de chegar a um shell ou ao `$GITHUB_ENV`. | todos os workflows, `tests/` |
| **Injeção de prompt pelos dados** | Dos registros, só números mensais agregados chegam ao modelo. Sugestões de eventos (da Wikipédia, editável por qualquer pessoa) **não vão para o juiz** até um gestor verificá-las, e chegam só por um pull request que pode apenas acrescentar entradas marcadas "suggested". | `src/profile.py`, `events.yml`, `main.py accept-events` |
| **Cadeia de suprimentos de software** | O Ollama é instalado de uma release fixada e conferida pelo SHA-256 (sem `curl … \| sh`); o llama.cpp e o fork PrismML são fixados (checksum da release, commit); os arquivos GGUF são conferidos pelo hash; as dependências Python têm versões exatas; os arquivos de modelo em cache são reconferidos pelo hash. | `setup-ollama`, `setup-llamacpp`, `requirements.txt` |
| **Decisões de revisão forjadas** | Só contam as issues abertas pelo próprio workflow; uma decisão é um rótulo, que só pessoas com permissão de triagem podem aplicar. | `src/review.py` |
| **O próprio repositório** | Cada job recebe só as permissões de que precisa; o token padrão dos workflows é somente leitura; push forçado e exclusão do `main` são bloqueados; alertas e atualizações de segurança do Dependabot, varredura de segredos e varredura de código estão ligados. | configurações do repositório |
| **Dados pessoais** | Arquivos brutos nunca são commitados; só as colunas de que o perfil precisa são lidas, e só agregados mensais são publicados. | `src/aggregate.py` |

### Riscos residuais (não resolvidos, por natureza)

- Um modelo que responde bem ao gabarito mas rotula outros casos errado de propósito ainda pode
  produzir **rótulos** errados. O dano é limitado (uma categoria e um texto que nunca são executados),
  rótulos de qualidade de dados vão para uma pessoa, e o período de espera dá tempo para outros
  perceberem uma release ruim; um conjunto de teste oculto dificultaria o ajuste ao benchmark (não
  implementado).
- O kit confia no GitHub, nos runners hospedados pelo GitHub, na biblioteca oficial do Ollama e nas
  releases fixadas que baixa.
- Quando uma tag de modelo muda na origem, a produção para de julgar até o benchmark aprovar a nova
  build (falha de propósito, visivelmente); rode o benchmark manualmente para retomar antes.
- Eventos sugeridos são tão bons quanto a pessoa que revisa o pull request.

### O que os mantenedores podem fazer (opcional)

- Ligar a autenticação em dois fatores na conta, e *Settings → Notifications → Actions → Only notify
  for failed workflows*.
- Atualizar as versões fixadas de forma deliberada, com seus checksums: `setup-ollama` (versão e
  SHA-256 do Ollama), `setup-llamacpp` no repositório do benchmark, `requirements.txt`.
- Revisar os pull requests de eventos antes do merge; um evento `verified` chega ao juiz.
