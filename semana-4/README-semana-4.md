# Semana 4 - Consumidor: de eventos Kafka a RDF en GraphDB

El `consumer.py` cierra el pipeline: lee los eventos que Debezium publica en Kafka (Etapa 3), los traduce a tripletas con el mapeo compartido (`mapping.py`) y mantiene el grafo en GraphDB sincronizado con la base en vivo.

Archivos:

- `mapping.py` - el mapeo relacional → RDF (única fuente de verdad; el `carga_inicial.py` de la semana 2 usa la misma lógica).
- `consumer.py` - el consumidor de Kafka que actualiza GraphDB.

---

## Cómo maneja cada cambio

| Operación Debezium | Qué hace en el grafo |
|--------------------|----------------------|
| `c` / `r` (create / snapshot) | inserta las tripletas de la fila nueva |
| `u` (update) | borra solo los atributos propios del recurso y reinserta los nuevos (no toca las relaciones que vienen de tablas de unión) |
| `d` (delete) | borra el recurso por completo, incluidas sus relaciones entrantes y salientes |

Para las tablas de unión, un create agrega la propiedad de objeto entre los dos recursos y un delete la quita.

---

## Requisitos previos

1. Etapa 3 andando (Kafka + Debezium publicando eventos) y GraphDB levantado.
2. Tener el repositorio `memorias-repo` creado en GraphDB, con la ontología y los datos ya importados. Los pasos están en el README de `semana-2/graphdb/` (crear el repo con un ruleset RDFS/OWL e importar `ontologia_memorias_lifia.ttl` y `memorias.ttl`).
3. Instalar dependencias (mismas que semana-3):
   ```
   pip install -r requirements.txt
   ```

---

## Ejecutar

```
python consumer.py
```

Config opcional por variables de entorno: `KAFKA_BOOTSTRAP` (localhost:9092), `GRAPHDB_URL` (http://localhost:7200), `GRAPHDB_REPO` (memorias-repo).

Al arrancar, como el conector está en `snapshot.mode: initial`, Debezium primero manda todas las filas actuales (el consumer reconstruye el grafo completo) y después sigue con los cambios en vivo.

---

## Demo de sincronización

1. Con el `consumer.py` corriendo, hacer un cambio en pgAdmin (o por `psql`):
   ```sql
   UPDATE public."Member" SET "positionAtLab" = 'Investigador Senior'
   WHERE "firstName" = 'Gustavo';
   ```
2. En la consola del consumer se va a ver la línea `u  Member  ok`.
3. En GraphDB (http://localhost:7200 → SPARQL, repo `memorias-repo`) hacer la siguiente consulta para ver el cargo actualizado (ojo: los miembros son `foaf:Person` (no existe `lifia:Member`) y el nombre va en `foaf:givenName`):
   ```sparql
   PREFIX lifia: <http://lifia.info.unlp.edu.ar/ontology#>
   PREFIX foaf: <http://xmlns.com/foaf/0.1/>
   SELECT ?p ?nombre ?cargo WHERE {
     ?p foaf:givenName ?nombre ; lifia:positionAtLab ?cargo .
     FILTER(?nombre = "Gustavo")
   }
   ```
   Devuelve `res:persona/gustavo-rossi` con `positionAtLab = "Investigador Senior"`.

Con esto, un cambio en la base se refleja en el grafo en segundos, sin reprocesar todo.
