from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigCliente:
    """Parâmetros de transporte do cliente.

    HOST e PORTA não têm valor padrão porque os arquivos fornecidos não
    informam em qual endereço o processo servidor faz bind/listen.
    """

    host: str
    porta: int
    timeout_conexao: float = 8.0
    timeout_resposta: float = 8.0
    tamanho_recv: int = 4096

    # O servidor encerra a conexão depois de 40 s sem tráfego.
    intervalo_keepalive: float = 15.0

    atraso_reconexao_inicial: float = 0.5
    atraso_reconexao_maximo: float = 8.0

    # Proteção do cliente contra uma linha recebida crescendo indefinidamente.
    tamanho_maximo_linha: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.host or not self.host.strip():
            raise ValueError("host não pode ser vazio")

        if not (1 <= self.porta <= 65535):
            raise ValueError("porta deve estar entre 1 e 65535")

        if self.timeout_conexao <= 0 or self.timeout_resposta <= 0:
            raise ValueError("timeouts devem ser positivos")

        if self.tamanho_recv <= 0:
            raise ValueError("tamanho_recv deve ser positivo")

        if not (0 < self.intervalo_keepalive < 40):
            raise ValueError(
                "intervalo_keepalive deve ser maior que 0 e menor que 40 segundos"
            )

        if self.atraso_reconexao_inicial <= 0:
            raise ValueError("atraso_reconexao_inicial deve ser positivo")

        if self.atraso_reconexao_maximo < self.atraso_reconexao_inicial:
            raise ValueError(
                "atraso_reconexao_maximo deve ser >= atraso_reconexao_inicial"
            )

        if self.tamanho_maximo_linha < 1024:
            raise ValueError("tamanho_maximo_linha muito pequeno")
