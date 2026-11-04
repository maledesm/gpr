#!/usr/bin/env bash
# Corre escena.py (la copia de banda ancha) adentro del env conda `meep` de WSL.
#
# En la maquina de Martin el C: esta lleno, asi que Miniforge y el env viven
# en D:\WSL\miniforge3 (instalado el 2026-11-02). En la de Santiago esta en
# ~/miniconda3: se usa el que exista.
#
# Desde Windows (lo hace GPRv2/simular_armonicos.bat):
#   wsl -d Ubuntu --cd <esta carpeta> -- bash correr_meep.sh barrido
set -euo pipefail

for base in /mnt/d/WSL/miniforge3 ~/miniconda3; do
    if [ -f "$base/etc/profile.d/conda.sh" ]; then
        source "$base/etc/profile.d/conda.sh"
        break
    fi
done
conda activate meep
cd "$(dirname "$(readlink -f "$0")")"
exec python escena.py "$@"
