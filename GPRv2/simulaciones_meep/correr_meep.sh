#!/usr/bin/env bash
# Corre escena.py adentro del env conda `meep` de WSL.
#
# Desde Windows:
#   wsl -d Ubuntu -- bash /mnt/c/Users/mogic/Tesis/gpr/GPRv2/simulaciones_meep/correr_meep.sh
#
# Se le pueden pasar escenas: `correr_meep.sh placa` o `correr_meep.sh vacio`.
# Sin argumentos corre las dos.
set -euo pipefail

source ~/miniconda3/etc/profile.d/conda.sh
conda activate meep
cd "$(dirname "$(readlink -f "$0")")"
exec python escena.py "$@"
