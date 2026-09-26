# Bateria de testes em três máquinas

**Princípio:** só o que o professor recebe: o cliente, o servidor e os arquivos de
configuração do repositório. Toda mensagem que chega ao servidor sai do cliente
oficial. `ss` e `tcpdump` apenas observam a rede.

| Máquina | SO | Papel | O que roda |
|---|---|---|---|
| **M1** | Linux | Servidor | servidor (log em arquivo), `tcpdump`, `ss` |
| **M2** | Windows | Cliente **alice** | cliente |
| **M3** | Linux | Cliente **bob** (e uma 2ª alice no T7) | cliente com `--debug` |

O bob fica numa máquina Linux porque o T5 usa Ctrl+Z para congelar o processo.
No Windows, Ctrl+Z seguido de Enter é fim de entrada, e o cliente faz `quit`.

Nos comandos abaixo, `<IP-M1>` é o IP do servidor. No Windows, troque `python3`
por `python` (ou `py`).

## Preparação (nas três máquinas)

Desligar a VPN (Mullvad), ou ligar "Local network sharing".

```bash
git clone https://github.com/melogtm/redes-ep1.git   # ou, se já tiver: git pull
cd redes-ep1
python3 --version                                    # 3.10 ou mais
```

Anote para o relatório:
- Linux: `hostname -I`, `uname -r` e `grep PRETTY /etc/os-release`
- Windows (PowerShell): `ipconfig` e `winver` (ou `Get-ComputerInfo OsName,OsVersion`)

`keys.conf` e `lots-bateria.conf` vêm pelo git; não copie nada à mão.

**Teste de alcance (M2 e M3), com o servidor da M1 já no ar:**
- Linux: `nc -vz <IP-M1> 8080`
- Windows: `Test-NetConnection <IP-M1> -Port 8080`

Se falhar, é firewall da M1: `sudo firewall-cmd --add-port=8080/tcp` (Fedora) ou
`sudo ufw allow 8080/tcp` (Ubuntu). A regra vale até o próximo reboot.

## Evidências

```bash
# M1: captura durante a bateria inteira (terminal próprio)
mkdir -p evidencias
sudo tcpdump -i any -nn 'tcp port 8080' -w evidencias/bateria.pcap
# M3: grava o terminal (encerrar com exit no fim da bateria)
mkdir -p evidencias && script -q evidencias/M3-terminal.txt
```

O log do servidor vai para arquivo pelo `tee` (ver T0). Na M2 (Windows), os prints
são a evidência: **Win+Shift+S**.

Nome dos prints: `T<nº>-M<máquina>-<descrição>.png`. A pasta `evidencias/` está no
`.gitignore`.

Comandos do cliente:
```bash
# M2 (Windows, PowerShell)
python src/client/main.py --host <IP-M1> --port 8080 --username alice --key-file resources/keys/keys.conf
# M3 (Linux)
python3 src/client/main.py --debug --host <IP-M1> --port 8080 --username bob --key-file resources/keys/keys.conf
```

## Bloco A: funcionalidades básicas

O lote 3 fecha **60 s** depois da subida do servidor. Deixe o comando da alice
digitado na M2 antes de subir o servidor.

**T0 (M1): servidor no ar**
```bash
cd src && python3 -m server.server --port 8080 --lots ../resources/keys/lots-bateria.conf 2>&1 | tee ../evidencias/servidor-A.log
```
Em outro terminal: `ss -ltnp | grep 8080`.
Esperado: `loaded 2 keys and 3 lots`, os 3 lotes com o horário de fechamento,
`listening on port 8080`; o `ss` mostra `0.0.0.0:8080`. Print: T0-M1.

**T1 (M2 + M3): conexão, autenticação e listagem**
1. M2 (alice), logo após o T0: `join 3`, `join 2`, `list all`.
2. M3 (bob): suba o cliente e só observe.

Esperado: `Conectado e autenticado.`, os 3 lotes e dois `Inscrito:` na alice. No
log da M1: `nova conexão de <IP-M2>`, `LOGIN -> CHALLENGE`, `autenticado -> AUTH_OK`
e os dois `JOIN`, depois o mesmo para o bob com o IP da M3. No bob (`--debug`),
a troca `-> LOGIN`, `<- CHALLENGE`, `-> AUTH`, `<- AUTH_OK` e, a cada 15 s,
`-> KEEPALIVE` / `<- KEEPALIVE`. Prints: T1-M2, T1-M3, T1-M1 (log).

**T2 (M2): lote fecha sem lances, e lance em lote fechado.** Espere o lote 3
acabar (60 s desde o T0), depois `bid 3 20.00`.
Esperado: `[PUSH/fechado] lote 3 fechado em 10.00; vencedor: NONE`, depois
`BID rejeitada: CLOSED`. No log: `lote 3 fechado: vencedor NONE ... CLOSE para [alice]`
e `BID no lote 3 -> BID_REJECTED CLOSED`. Print: T2-M2.

**T3 (M2): lance válido e lances recusados**
```
bid 2 60.00    # aceito
bid 2 55.00    # LOW_BID
bid 2 60.00    # LOW_BID: igual ao atual também é recusado
bid 2 60.001   # recusado pelo próprio cliente: mais de duas casas decimais
```
Print: T3-M2 e o trecho do log da M1.

**T4 (M3 + M2): cliente entrando no meio do leilão.** No bob: `join 2` (deve
mostrar R$ 60.00, líder já definido), `bid 2 75.00`.
Esperado: a alice recebe na hora `[PUSH/preco] lote 2: novo preço 75.00 por bob`;
no log, `PRICE_UPDATE e TIME_UPDATE para [alice, bob]`. Prints: T4-M3 e T4-M2.

**T5 (M3 + M1): cliente que some sem LOGOUT (timeout de 40 s)**
1. M1: `watch -n1 "ss -tn state established '( sport = :8080 )'"` mostra 2 conexões.
2. M3: **Ctrl+Z** no cliente do bob. O processo congela: não envia nem FIN nem KEEPALIVE.
3. M1: print com 2 conexões; após uns 40 s o log mostra
   `sessão bob@<IP-M3>:... encerrada: timeout: 40 s sem tráfego` e o `ss` cai para 1.
4. M3: `fg` e Enter. O cliente percebe a queda, reconecta e refaz o `join 2` sozinho
   (`[PUSH/reconectado]`, `[PUSH/reinscrito]`).

Prints: T5a-M1 (2 conexões), T5b-M1 (log do timeout + 1 conexão), T5c-M3.
Não use `kill -9`: o kernel manda FIN e o timeout nunca entra em jogo.

**T6 (M2): entradas inválidas.** Abra um **segundo** PowerShell, sem fechar a alice.
```powershell
# a) servidor inexistente
python src/client/main.py --host 192.168.1.250 --port 8080 --username alice --key-file resources/keys/keys.conf
# b) chave errada: sem --key-file, digite qualquer coisa no prompt "Chave HMAC:"
python src/client/main.py --host <IP-M1> --port 8080 --username alice
# c) usuário não cadastrado: digite qualquer coisa no prompt
python src/client/main.py --host <IP-M1> --port 8080 --username mallory
```
d) No cliente da alice (1º PowerShell): `bid 1 150.00` sem ter feito `join 1`.

Esperado: a) `Erro ao iniciar: ...` em até 8 s · b) `AUTH recusado: BAD_MAC` ·
c) `LOGIN recusado: UNKNOWN_USER` · d) `Erro: é necessário executar JOIN antes de enviar BID`
(o cliente barra antes de enviar). No log: `AUTH com MAC incorreto -> AUTH_FAIL BAD_MAC`
e `LOGIN mallory -> AUTH_FAIL UNKNOWN_USER`. Prints: T6-M2 e T6-M1.

**T7 (M3 + M2): mesmo usuário em duas máquinas.** Num terminal novo da M3:
```bash
python3 src/client/main.py --host <IP-M1> --port 8080 --username alice --key-file resources/keys/keys.conf
```
`join 2`, `bid 2 90.00`.
Esperado (comportamento atual): o servidor aceita as duas sessões; o log mostra
`PRICE_UPDATE e TIME_UPDATE para [alice, alice, bob]` e a M2 recebe
`[PUSH/preco] ... por alice`. Vai para a seção de limitações (não há sessão única
por usuário). Prints: T7-M3, T7-M2 e T7-M1. Feche esse cliente extra com `quit`.

## Bloco B: temporização

M1: Ctrl+C no servidor e suba de novo, agora gravando em outro arquivo:
```bash
python3 -m server.server --port 8080 --lots ../resources/keys/lots-bateria.conf 2>&1 | tee ../evidencias/servidor-B.log
```
Não feche os clientes: eles reconectam e refazem os `join` sozinhos (print desse
momento nas duas: T8pre-M2, T8pre-M3). O lote 1 dura **120 s**: comece o T8 logo.

**T8 (M2 + M3): soft close e convergência do fim**
1. Nos dois clientes: `join 1`.
2. M3: `bid 1 150.00` cedo. O `fim:` não muda (faltam mais de 10 s).
3. M2: `show` de tempos em tempos; com menos de 10 s restantes, `bid 1 200.00`.
4. M3: assim que chegar o `[PUSH/tempo]`, `bid 1 250.00`.
5. Espere o lote fechar.

Esperado: cada lance dos passos 3 e 4 empurra o fim para "chegada + 10 s", e o log
mostra `(soft close: faltavam X s)`; o epoch do `[PUSH/tempo]` é o mesmo nas duas
máquinas; no fim, `[PUSH/fechado] lote 1 fechado em 250.00; vencedor: bob` nas duas.
Prints: T8-M2, T8-M3 (a sequência inteira) e T8-M1.

**T9 (M2 + M3): lances concorrentes no mesmo preço**
1. As duas máquinas lado a lado, as duas no lote 2 (os `join` foram refeitos na reconexão).
2. Digite nas duas, sem Enter, um preço acima do atual: `bid 2 300.00`.
3. Enter nas duas ao mesmo tempo; depois `show` nas duas. Repita com 310 e 320.

Esperado: por rodada, um `Lance aceito` e um `LOW_BID`; o `show` das duas mostra o
mesmo líder e o mesmo preço. O log da M1 mostra a ordem de chegada com milissegundos.
Envio manual não é simultâneo de verdade: o teste mostra consistência; a exclusão
mútua se argumenta pelo `lote.lock`. Prints: T9-M2, T9-M3 e T9-M1.

Fim da bateria: `quit` nos clientes, Ctrl+C no servidor e no `tcpdump`, `exit` no `script` da M3.

## Bloco C: segurança

**T10 (M1): nonce novo a cada login e chave fora do fio**
```bash
tcpdump -r evidencias/bateria.pcap -A 2>/dev/null | grep -oE "(CHALLENGE|AUTH) [0-9a-f]+"
tcpdump -r evidencias/bateria.pcap -A 2>/dev/null | grep -cE "a1b2c3d4e5f60718293a4b5c6d7e8f90|0102030405060708090a0b0c0d0e0f10"   # esperado: 0
```
Esperado: um par CHALLENGE/AUTH por login (inclusive os das reconexões), todos
diferentes entre si; as chaves aparecem 0 vezes. Print: T10-M1.

## Depois da bateria

Traga para a máquina onde o relatório será escrito: `evidencias/` da M1 (os dois logs
do servidor e o pcap), `evidencias/M3-terminal.txt` e todos os prints.

## Para o relatório

- Para cada teste: objetivo, comandos e máquinas, resultado esperado × obtido, figuras.
- Declarar o princípio: os testes usam só o cliente e o servidor entregues.
- Seção de máquinas: SO e versão das três, IPs, e a frase de que o requisito de
  computadores diferentes (e sistemas diferentes: Linux e Windows) está atendido.
- Limitações: replay de AUTH/BID e lances realmente simultâneos não foram
  exercitados, porque o cliente oficial não produz essas mensagens. As defesas
  (nonce consumido, `seq`, HMAC, `lote.lock`) são argumentadas pelo código.
- Persistência: o servidor não guarda estado entre reinícios.
- Bugs e limitações: mesmo usuário em duas sessões (T7); `PRICE_UPDATE` com
  `<epoch>` fora do PROTOCOLO.md; os dois bugs corrigidos antes da bateria (PR #2).
