# Etapa 3 - Infraestructura CDC (Debezium + Kafka)

Objetivo: que cada cambio en la base `new_memorias` (INSERT/UPDATE/DELETE) se capture automáticamente y se publique en Kafka, sin tocar el portal. Esto es lo que después consume el `consumer.py` (Etapa 4) para actualizar el grafo.

Archivos de esta carpeta:

- `docker-compose.yml` - levanta Kafka, Kafka Connect (con Debezium), Kafka UI y GraphDB.
- `connectors/memorias-postgres.json` - configuración del conector Debezium para la base.
- `register-connector.sh` - registran el conector en Kafka Connect.

---

## Requisitos previos

- Docker Desktop instalado y corriendo.
- La base `new_memorias` ya restaurada en tu PostgreSQL local (Etapa 0, hecho).


---


## Paso 1 - Habilitar replicación lógica en PostgreSQL (una sola vez)

Debezium lee el WAL (log de transacciones), y para eso Postgres tiene que estar en modo de replicación lógica.

1. Abrir el archivo `postgresql.conf`. En una instalación estándar de Windows suele estar en:
   `C:\Program Files\PostgreSQL\18\data\postgresql.conf`
2. Buscar la línea `wal_level` y dejarla así (quitar el `#` si está comentada):
   ```
   wal_level = logical
   ```
3. Reiniciar el servicio de PostgreSQL (Servicios de Windows → "postgresql-x64-18" → Reiniciar; o `pg_ctl restart`).
4. Verificar desde pgAdmin o psql:
   ```sql
   SHOW wal_level;   -- debe devolver: logical
   ```

El usuario `postgres` ya tiene permiso de replicación, así que no hace falta crear otro usuario. Debezium crea solo el slot de replicación (`memorias_slot`) y la publicación (`memorias_pub`).


---


## Paso 2 - Levantar la infraestructura

Parado en esta carpeta:

```
docker compose up -d
```

Esperar 30 segundos. Se puede chequear que Kafka Connect está listo abriendo http://localhost:8083 (debería responder un JSON con la versión).

Servicios que quedan disponibles:

| Servicio | URL | Para qué |
|----------|-----|----------|
| Kafka Connect (API) | http://localhost:8083 | registrar y ver el conector |
| Kafka UI | http://localhost:8080 | ver TOPICs y mensajes en el navegador |
| GraphDB | http://localhost:7200 | el triplestore (Etapa 4) |

Nota sobre GraphDB: en este proyecto se usa el GraphDB que levanta este mismo `docker-compose`, en lugar del GraphDB Free de escritorio que se usó en la Etapa 2. Como es una instancia nueva y vacía, hay que crear el repo `memorias` e importar la ontología y `memorias.ttl` ahí (los mismos pasos que en `semana-2/graphdb/README.md`; sigue siendo `localhost:7200`, así que el resto no cambia).


---


## Paso 3 - Registrar el conector Debezium

```
./register-connector.sh         # Git Bash / WSL
```

Si sale bien, el estado del conector debería mostrar `"state": "RUNNING"`.


---


## Paso 4 - Verificar que captura cambios

1. Abrir Kafka UI (http://localhost:8080). Al arrancar, Debezium hace un snapshot inicial y crea un **TOPIC de Kafka** (un canal de mensajes con nombre) por cada tabla, con nombres como:
   `memorias.public.Member`, `memorias.public.Publication`, etc.
2. Hacer un cambio de prueba en pgAdmin, por ejemplo:
   ```sql
   UPDATE public."Member" SET "positionAtLab" = 'Investigador Senior'
   WHERE "firstName" = 'Gustavo';
   ```
3. En Kafka UI, entrar al TOPIC `memorias.public.Member` y mirar el último mensaje: se va a ver el evento con el valor viejo (`before`) y el nuevo (`after`) y la operación (`op": "u"`).


---


## Notas

- `snapshot.mode: initial` hace que Debezium, al arrancar, lea todas las filas actuales (snapshot) y después siga con los cambios en vivo. O sea, el consumidor puede reconstruir el grafo completo por sí solo; el `carga_inicial.py` de la Etapa 2 sigue sirviendo para una carga rápida sin todo el pipeline.
- Si se cambia el conector, se lo puede borrar con `DELETE http://localhost:8083/connectors/memorias-connector` y volver a registrarlo.
- Para bajar todo: `docker compose down` (agregar `-v` si se quiere borrar también los datos de GraphDB).
- Los nombres de tabla van con mayúscula (`public.Member`) porque así están definidos en la base -> respetar esa capitalización en el `table.include.list`.
