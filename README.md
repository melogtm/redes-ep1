# Leilão online: EP 1 de Redes de Computadores

Servidor e cliente de leilão sobre TCP, com autenticação por desafio HMAC-SHA256,
lances assinados e *soft close*. O protocolo está descrito em
[PROTOCOLO.md](PROTOCOLO.md).

## Requisitos

- Python 3.10 ou mais recente. Nenhuma biblioteca externa.
- Linux, macOS ou Windows.

No Windows, use `python` (ou `py`) no lugar de `python3` nos comandos abaixo.

## Obter o código

```bash
git clone https://github.com/melogtm/redes-ep1.git
cd redes-ep1
```

Os arquivos de configuração já vêm no repositório:

| Arquivo | Conteúdo |
|---|---|
| `resources/keys/keys.conf` | usuários e chaves (`alice` e `bob`) |
| `resources/keys/lots.conf` | lotes padrão do servidor |
| `resources/keys/lots-bateria.conf` | lotes usados na bateria de testes |

## Servidor

A partir da raiz do repositório:

```bash
cd src
python3 -m server.server --port 8080
```

Opções:

| Opção | Padrão | Descrição |
|---|---|---|
| `--port` | `8080` | porta TCP |
| `--keys` | `resources/keys/keys.conf` | arquivo de chaves |
| `--lots` | `resources/keys/lots.conf` | arquivo de lotes |
| `--debug` | desligado | mostra também cada mensagem recebida e enviada |

O servidor escuta em todas as interfaces (`0.0.0.0`). O log mostra conexões,
autenticações, `JOIN`, lances aceitos e recusados (com o motivo), prorrogações de
*soft close*, fechamento de lotes e o motivo de cada desconexão. A duração dos
lotes conta a partir da subida do servidor, e o estado não é guardado entre
reinícios.

Para descobrir o IP que os clientes devem usar: `hostname -I` (Linux) ou
`ipconfig` (Windows). Se os clientes estão em outras máquinas, o firewall do
servidor precisa aceitar conexões na porta escolhida.

## Cliente

A partir da raiz do repositório, em outra máquina ou em outro terminal:

```bash
python3 src/client/main.py --host <IP-do-servidor> --port 8080 --username alice --key-file resources/keys/keys.conf
```

| Opção | Obrigatória | Descrição |
|---|---|---|
| `--host` | sim | IP ou nome do servidor |
| `--port` | sim | porta TCP do servidor |
| `--username` | sim | usuário cadastrado no arquivo de chaves do servidor |
| `--key-file` | não | arquivo `usuario chave`; sem ele, a chave é pedida no terminal |
| `--debug` | não | mostra as mensagens do protocolo com horário (`->` enviada, `<-` recebida) |

Comandos dentro do cliente:

| Comando | Efeito |
|---|---|
| `list` / `list all` | lotes abertos / todos os lotes |
| `join <id>` | entra no lote e passa a receber as notificações dele |
| `bid <id> <preço>` | envia um lance, ex.: `bid 1 150.00` |
| `show` | estado local dos lotes conhecidos |
| `help` | ajuda |
| `quit` | envia `LOGOUT` e encerra |

Notificações do servidor aparecem na hora, com o prefixo `[PUSH/...]`. Se a
conexão cair, o cliente reconecta sozinho e refaz os `join`.

## Exemplo rápido numa máquina só

```bash
# terminal 1
cd src && python3 -m server.server --port 8080
# terminal 2
python3 src/client/main.py --host 127.0.0.1 --port 8080 --username alice --key-file resources/keys/keys.conf
# terminal 3
python3 src/client/main.py --host 127.0.0.1 --port 8080 --username bob --key-file resources/keys/keys.conf
```

No cliente da alice: `join 1` e `bid 1 150.00`. O bob, depois de `join 1`, recebe
`[PUSH/preco] lote 1: novo preço 150.00 por alice`.

## Testes automatizados

A partir da raiz do repositório:

```bash
python3 -m unittest discover -s tests -v
```

São 31 testes, que rodam em poucos segundos e usam só a biblioteca padrão.
Os unitários cobrem o parser, o buffer de linhas, os preços e a regra do
lance (inclusive o soft close). Os de integração sobem um servidor de
verdade numa porta livre e mandam mensagens cruas pelo socket, para cobrir
o que o cliente oficial não gera: `AUTH` e `BID` repetidos, forjados ou
copiados de outra sessão.

## Formato dos arquivos

`keys.conf`: um usuário por linha, `#` inicia comentário.

```text
alice a1b2c3d4e5f60718293a4b5c6d7e8f90
```

`lots.conf`: `id | descrição | preço inicial | duração em segundos`.

```text
1 | Quadro Guernica (replica) | 100.00 | 180
```
