# Registro de diálogos com a IA

## Objetivo

Este documento registra as principais conversas com a IA durante o desenvolvimento do EP. O conteúdo está limitado às decisões e implementações diretamente relacionadas ao exercício.

## Seção de Gabriel Trigueiro

### 1. Padronização do código Python

**Aluno:** Como garantir que a dupla siga uma boa formatação no código Python?

**IA:** A formatação deve ser automatizada e compartilhada pelo projeto. A recomendação foi utilizar o Ruff, configurar suas regras no `pyproject.toml`, ativar a formatação ao salvar no VS Code e executar as mesmas verificações para todos os integrantes.

**Resultado:** O projeto passou a usar:

- 88 caracteres por linha;
- indentação com espaços;
- aspas duplas;
- regras de lint `E`, `F` e `I`;
- organização automática de imports;
- formatação ao salvar no VS Code.

### 2. Integração contínua

**Aluno:** Como garantir que a formatação seja respeitada no GitHub?

**IA:** Foi criada uma GitHub Action para executar o Ruff em cada `push` e `pull request`. A Action deve verificar a formatação e o lint, sem alterar os arquivos automaticamente.

**Resultado:** O workflow `.github/workflows/quality.yml` executa:

```bash
ruff format --check .
ruff check .
```

Assim, uma alteração fora do padrão impede a validação do workflow.

### 3. Dependências de desenvolvimento

**Aluno:** Como facilitar a instalação do Ruff para a dupla?

**IA:** As ferramentas usadas no desenvolvimento devem ficar registradas em um arquivo compartilhado.

**Resultado:** Foi criado `requirements-dev.txt` com as dependências de desenvolvimento:

```text
ruff
```

Também foi criada uma recomendação de extensão no VS Code para a extensão oficial do Ruff.

### 4. Organização dos recursos do servidor

**Aluno:** Como configurar os caminhos dos arquivos de chaves e lotes?

**IA:** Os caminhos padrão devem apontar para `resources/keys`, mas não devem depender do diretório em que o comando foi executado. A raiz do projeto deve ser calculada a partir da localização do próprio arquivo do servidor.

**Resultado:** O servidor utiliza como padrão:

- `resources/keys/keys.conf` para as chaves;
- `resources/keys/lots.conf` para os lotes.

Os caminhos são resolvidos a partir da raiz do projeto, e não do diretório de trabalho atual.

### Registro do uso de inteligência artificial

Este documento de diálogos foi elaborado com auxílio de inteligência artificial
durante o desenvolvimento do EP.

- Assistente: GitHub Copilot;
- Modelo: a versão específica do modelo não é informada nesta interface;
- Uso: apoio à análise, documentação, padronização e implementação do projeto;
- Responsabilidade: as decisões finais e a revisão do código pertencem à dupla.

### 5. Contrato do protocolo

**Aluno:** Como evitar divergência entre cliente e servidor?

**IA:** O protocolo precisa ser documentado em um único arquivo, com a BNF completa, os campos e o formato exato de cada mensagem.

**Resultado:** Foi criado `PROTOCOLO.md`, contendo:

- regras gerais de framing das mensagens;
- tipos e formatos de campos;
- autenticação com `LOGIN`, `CHALLENGE` e `AUTH`;
- encerramento com `LOGOUT`;
- manutenção da conexão com `KEEPALIVE`;
- listagem com `LIST`;
- entrada em lote com `JOIN`;
- lances com `BID`;
- respostas `BID_ACCEPTED` e `BID_REJECTED`;
- motivos de rejeição;
- broadcasts `PRICE_UPDATE` e `TIME_UPDATE`;
- encerramento do lote com `CLOSE`;
- fluxo completo de exemplo.

### 6. Ajustes do servidor ao contrato

**Aluno:** Corrija o código para estar de acordo com o contrato.

**IA:** O servidor precisava deixar de usar nomes diferentes dos definidos no protocolo. Foram alinhadas as mensagens de autenticação, manutenção e broadcast.

**Resultado:** O servidor passou a utilizar:

| Comportamento | Mensagem definida |
|---|---|
| Desafio de autenticação | `CHALLENGE` |
| Manutenção da conexão | `KEEPALIVE` |
| Atualização do preço | `PRICE_UPDATE` |
| Atualização do tempo final | `TIME_UPDATE` |
| Encerramento do lote | `CLOSE` |

Também foram ajustados o parser de mensagens com campo final iniciado por `:`, a validação da quantidade de argumentos de `BID` e o controle da sequência dos lances.

### 7. Concorrência e comunicação

**Aluno:** Por que a leitura do socket usa um buffer de 4096 bytes?

**IA:** TCP entrega um fluxo de bytes, não mensagens prontas. O valor `4096` limita o tamanho de cada leitura e o `LineBuffer` recompõe mensagens completas ou fragmentadas até encontrar `\\n`. Esse tamanho é uma escolha prática de limite por leitura, não um limite do protocolo.

**Resultado:** O código contém comentários breves nos pontos em que a decisão não é evidente, incluindo:

- leitura fragmentada do TCP;
- proteção de acesso aos lotes com locks;
- extensão do tempo final na janela de encerramento;
- uso do challenge e da assinatura HMAC.

