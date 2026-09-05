# Protocolo cliente-servidor

Este documento define o protocolo de texto usado pelo servidor. Cada mensagem é
uma linha UTF-8 terminada por `LF` (`\n`). Campos são separados por um ou mais
espaços. Um campo iniciado por `:` é um campo final (*trailing*) e pode conter
espaços até o `LF`.

## Convenções

```bnf
<line>          ::= <message> <LF>
<message>       ::= <request> | <response> | <broadcast>
<username>      ::= <token>
<lot-id>        ::= <integer>
<price>         ::= <decimal>
<seq>           ::= <positive-integer>
<epoch>         ::= <integer>
<nonce>         ::= 32 * <hex>
<mac>           ::= 64 * <hex>
<reason>        ::= <token>
<description>   ::= <text>
<winner>        ::= <username> | NONE
<LF>            ::= "\\n"
```

`<nonce>` é um valor hexadecimal de 16 bytes. `<mac>` é um HMAC-SHA256
codificado em hexadecimal minúsculo. Preços são enviados com duas casas
decimais. O relógio `<epoch>` é Unix time em segundos.

## Autenticação

O cliente deve autenticar antes de usar comandos de leilão.

```bnf
<login-request>       ::= "LOGIN" <SP> <username>
<challenge-response>  ::= "CHALLENGE" <SP> <nonce>
<auth-request>        ::= "AUTH" <SP> <mac>
<auth-response>       ::= "AUTH_OK" <SP> <username>
                        | "AUTH_FAIL" <SP> <auth-reason>
<auth-reason>         ::= "UNKNOWN_USER" | "NONCE_EXPIRED" | "BAD_MAC"
```

Depois de `LOGIN <username>`, o servidor responde com `CHALLENGE <nonce>`.
O cliente calcula:

```text
HMAC-SHA256(chave-do-usuario, nonce)
```

e envia o digest hexadecimal em `AUTH <mac>`. O challenge só pode ser usado
uma vez.

## Encerramento e manutenção

```bnf
<logout-request>      ::= "LOGOUT"
<keepalive-request>   ::= "KEEPALIVE"
<keepalive-response>  ::= "KEEPALIVE"
```

`LOGOUT` encerra a conexão sem resposta adicional. `KEEPALIVE` recebe um
`KEEPALIVE` de volta. O servidor também encerra conexões sem tráfego por mais
de 40 segundos.

## Listagem e inscrição

```bnf
<list-request>         ::= "LIST"
<list-response>        ::= "LIST_BEGIN" <SP> <integer> <LF>
                           0 * <lot-line>
                           "LIST_END" <LF>
<lot-line>             ::= "LOT" <SP> <lot-id> <SP> <status> <SP>
                           <price> <SP> <epoch> <SP> ":" <description> <LF>
<status>               ::= "OPEN" | "CLOSED"
<join-request>         ::= "JOIN" <SP> <lot-id>
<join-response>        ::= "JOIN_OK" <SP> <lot-id> <SP> <status> <SP>
                           <price> <SP> <epoch> <SP> ":" <description>
                         | "JOIN_REJECTED" <SP> <lot-id> <SP> <join-reason>
<join-reason>          ::= "UNKNOWN_LOTE" | "BAD_REQUEST"
```

O número de `LOT` emitido deve ser igual ao valor de `LIST_BEGIN`. O cliente
recebe atualizações de um lote depois de executar `JOIN` nesse lote.

## Lances

```bnf
<bid-request>          ::= "BID" <SP> <lot-id> <SP> <price> <SP>
                           <seq> <SP> <mac>
<bid-response>          ::= "BID_ACCEPTED" <SP> <lot-id> <SP> <price> <SP>
                            <epoch> <SP> <seq>
                          | "BID_REJECTED" <SP> <lot-id> <SP>
                            <bid-reason> <SP> <seq>
<bid-reason>            ::= "NO_SUCH_LOT" | "NOT_JOINED" | "BAD_SEQ"
                          | "BAD_MAC" | "CLOSED" | "LOW_BID"
```

O texto assinado pelo cliente é exatamente:

```text
LANCE <lot-id> <price-as-sent> <seq> <nonce>
```

O `<mac>` do `BID` é o HMAC-SHA256 desse texto usando a chave do usuário.
`<seq>` começa em `1` após `AUTH_OK` e só é incrementado quando o lance é
aceito.

## Broadcasts

Os broadcasts são enviados a todos os clientes inscritos no lote, incluindo o
cliente que fez o lance.

```bnf
<price-update>         ::= "PRICE_UPDATE" <SP> <lot-id> <SP> <price>
                            <SP> ":" <username>
<time-update>           ::= "TIME_UPDATE" <SP> <lot-id> <SP> <epoch>
<close>                 ::= "CLOSE" <SP> <lot-id> <SP> <price> <SP>
                            ":" <winner>
```

Após um lance aceito, o autor recebe `BID_ACCEPTED` e todos os inscritos
recebem `PRICE_UPDATE` e `TIME_UPDATE`. Quando o tempo termina, todos recebem
`CLOSE`, contendo o preço final e o vencedor; se não houver lances, o vencedor
é `NONE`.

## Fluxo mínimo

```text
Cliente -> LOGIN alice
Servidor -> CHALLENGE <nonce>
Cliente -> AUTH <mac>
Servidor -> AUTH_OK alice
Cliente -> LIST
Servidor -> LIST_BEGIN ... / LOT ... / LIST_END
Cliente -> JOIN 1
Servidor -> JOIN_OK ...
Cliente -> BID 1 150.00 1 <mac>
Servidor -> BID_ACCEPTED 1 150.00 <t_fim> 1
Servidor -> PRICE_UPDATE 1 150.00 :alice
Servidor -> TIME_UPDATE 1 <t_fim>
Servidor -> CLOSE 1 150.00 :alice
```
