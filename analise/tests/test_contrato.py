import re
from pathlib import Path

import analise

PPG_H = Path(__file__).resolve().parents[2] / "Core/Inc/pds/comum/ppg.h"


def test_taxa_igual_ao_ppg_h():
    """A taxa do Python tem que ser a mesma do contrato em C."""
    texto = PPG_H.read_text(encoding="utf-8")
    fs_c = int(re.search(r"#define PPG_FS_HZ (\d+)u", texto).group(1))
    assert analise.FS_HZ == fs_c
