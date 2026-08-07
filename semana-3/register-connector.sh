#!/usr/bin/env bash
# Registra el conector Debezium en Kafka Connect (bash / Git Bash).
# Con los contenedores ya levantados (docker compose up -d):
#   ./register-connector.sh
set -e
cd "$(dirname "$0")"

echo "Registrando conector en http://localhost:8083 ..."
curl -s -X POST -H "Content-Type: application/json" \
     --data @connectors/memorias-postgres.json \
     http://localhost:8083/connectors | tee /dev/stderr | grep -q '"name"' \
  && echo "  OK" \
  || { echo "  (quizas ya existe; actualizando config...)"; \
       curl -s -X PUT -H "Content-Type: application/json" \
            --data "$(python -c 'import json,sys;print(json.dumps(json.load(open("connectors/memorias-postgres.json"))["config"]))')" \
            http://localhost:8083/connectors/memorias-connector/config >/dev/null; }

echo
echo "Estado:"
curl -s http://localhost:8083/connectors/memorias-connector/status
echo
