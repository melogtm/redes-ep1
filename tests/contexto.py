"""Deixa o servidor e o cliente importáveis pelos testes.

Os programas rodam a partir de src/ (servidor) e src/client/ (cliente); os
testes reproduzem o mesmo sys.path.
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src"
CHAVES = RAIZ / "resources" / "keys" / "keys.conf"

for caminho in (SRC, SRC / "client"):
    if str(caminho) not in sys.path:
        sys.path.insert(0, str(caminho))
