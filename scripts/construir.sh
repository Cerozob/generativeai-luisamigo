#!/usr/bin/env bash
# Pasos de construcción que ejecuta CodeBuild durante el despliegue (ver mundial_agente/construccion.py).
#   agente: empaqueta el código del agente con sus dependencias Linux ARM64 y lo sube a S3.
#   web:    compila el frontend, lo publica, sube los documentos, carga las tablas y lanza la primera ingesta.
set -euo pipefail

case "$1" in
agente)
  # AgentCore Runtime (despliegue directo de código) pide un zip con el código y las dependencias para
  # Linux ARM64. pip descarga esas wheels aunque la máquina de CodeBuild sea x86: no hace falta Docker.
  rm -rf build && mkdir -p build/agente
  python3 -m pip install --quiet --target build/agente \
    --platform manylinux2014_aarch64 --implementation cp --python-version 3.13 --only-binary=:all: \
    -r agent/requirements.txt
  cp agent/main.py agent/acciones.py agent/herramientas.py agent/prompt.md build/agente/
  python3 -c "import shutil; shutil.make_archive('build/agente', 'zip', 'build/agente')"
  aws s3 cp build/agente.zip "s3://${BUCKET_ARTEFACTOS}/${CLAVE_AGENTE}"
  ;;
web)
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
  # La configuración del frontend sale de los recursos del stack (Cognito, runtime).
  echo "${CONFIG_FRONTEND}" > frontend/dist/config.json
  aws s3 sync frontend/dist "s3://${BUCKET_WEB}" --delete
  # Sin --delete: los documentos que suben los usuarios (mundial/subidos/) se conservan.
  aws s3 sync assets/knowledge-base "s3://${BUCKET_DOCS}/mundial/"
  python3 -m pip install --quiet boto3
  python3 scripts/cargar_datos.py --tabla-album "${TABLA_ALBUM}" --tabla-catalogo "${TABLA_CATALOGO}" \
    --usuario "${USUARIO_DEMO}" --kb "${KB_ID}" --ds "${DS_ID}"
  aws cloudfront create-invalidation --distribution-id "${DISTRIBUCION}" --paths "/*" > /dev/null
  ;;
*)
  echo "Uso: $0 agente|web" >&2
  exit 1
  ;;
esac
