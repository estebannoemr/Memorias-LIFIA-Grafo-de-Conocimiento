# Memorias del Centro LIFIA - Grafo de Conocimiento

Trabajo Final - Web Semántica (UNLP).

**Esteban Noé Manzano Reynoso**.

---

## Objetivo

Construir una representación en un **grafo de conocimiento** de las memorias académicas del Centro LIFIA: los trabajos publicados, las direcciones, los proyectos, las tesis, las becas y el material que describe la trayectoria de las personas que investigan en el centro.

---

## Punto de partida

Hoy las memorias viven en **Memorias@LIFIA**, un portal web con CRUD sobre una base **PostgreSQL** (modelo relacional). Tiene 5 entidades principales:

- **Member** - investigadores: nombres, cargos, categorías, perfiles (ORCID, DBLP, Scholar), CVs e intereses.
- **Project** - proyectos: título, código, fechas, directores, agencias y etiquetas.
- **Publication** - publicaciones: tipo, título, autores, año, ranking y datos en BibTeX.
- **Thesis** - tesis de grado y posgrado: nivel, estudiante, directores, asesores y resumen.
- **Scholarship** - becas: tipo, estudiante, director y agencia de financiamiento.

El modelo relacional no expresa semántica ni permite inferencia. Además, los datos quedan aislados entre sí (poca interoperabilidad).

---

## Propuesta

Modelar a las personas del LIFIA, su producción y sus vínculos como una **red de datos enlazados con significado semántico** (RDF), describiendo las entidades y relaciones con **ontologías en OWL**. Así se puede:

- consultar con **SPARQL** recorriendo el grafo, sin JOINs anidados.
- **inferir** relaciones que no están explícitas, gracias al razonador OWL/RDFS.
- **vincular** los datos con el ecosistema de Linked Open Data.

Además, como el portal cambia constantemente, el grafo se mantiene sincronizado ante cada `INSERT`/`UPDATE`/`DELETE` mediante **captura de cambios (CDC)**, sin reprocesar toda la base.

---

## Vocabularios

- **VIVO** - red académica (personas, proyectos, becas y sus relaciones).
- **DBLP** y **BIBO** - producciones científicas y metadatos bibliográficos.
- **CSO** (con **SKOS**) - clasificación temática de intereses, proyectos y publicaciones.
- **FOAF**, **Dublin Core**, **OWL** - datos de personas, títulos/fechas/autoría, y alineaciones/inferencia.
- **`lifia:`** - términos propios, solo para lo específico del LIFIA que no tiene equivalente estándar.

---

## Arquitectura (pipeline)

```
 PostgreSQL    ->   Debezium + Kafka    ->      Script Python      ->      GraphDB
(cambios en        (captura el cambio          (traduce a RDF          (guarda el grafo,
  el WAL)            y lo publica)           con las ontologías)     consultable por SPARQL)
```

---

La carga inicial se hace con un script de carga que vuelca toda la base al grafo de una vez -> a partir de ahí, el CDC mantiene la sincronización en vivo.

---

## Estructura del repositorio

```

Memorias-LIFIA-Grafo-de-Conocimiento/
|- dump/
|    |- new_memorias_para_kgsw.dump  Dump de la base
|
|- semana-1/                    MAPEO DE LAS ENTIDADES
|    |- mapeo_ontologico.md     Mapeo ontológico
|    |- ontologia.ttl           Ontología OWL
|
|- semana-2/                    CARGA INICIAL
|    |- carga_inicial.py        Script ETL
|    |- mapping.py              Mapeo de entidades a RDF
|    |- memorias.ttl            Grafo RDF
|    |
|    |- graphdb
|        |- README.md                       Instrucciones para cargar en GraphDB
|        |- Tripletas con inferencia.png    Cantidad de tripletas con inferencia
|        |- Tripletas sin inferencia.png    Cantidad de tripletas sin inferencia
|    
|- semana-3/                    PIPELINE CDC
|    |- docker-compose.yml      Configuración de Docker
|    |- README-semana-3.md      Descripción del pipeline
|    |- register-connector.sh   Registra el conector en Kafka Connect.
|    |
|    |- connectors
|       |- memorias-postgres.json      Configuración del conector Debezium para la base.
|    |
|    |- graphdb-from-docker    Archivos para cargar en GraphDB desde el Docker (= semana 1 y 2)
| 
|- semana-4/                   CONSUMIDOR: TRADUCE EVENTOS A RDF Y SINCRONIZA GRAPHDB
|    |- consumer.py            Script para consumir los cambios de Kafka y actualizar GraphDB
|    |- mapping.py             Lógica de mapeo relacional → RDF (= semana 2)
|    |- README-semana-4.md     Descripción del consumidor
|
|- semana-5/                   CONSULTAS SPARQLPARA VALIDAR
|    |- Consultas.md           Consultas SPARQL para validar el grafo
|
|- requirements.txt            Dependencias de Python necesarias
|- README.md                   Descripción del repositorio

```

---

## Puesta en funcionamiento

Comandos para levantar el proyecto y demostrar que funciona de punta a punta (bash, parado en la raíz del repo).

Prerrequisitos (una sola vez): PostgreSQL 18 con la base `new_memorias` restaurada desde `dump/`, Docker Desktop instalado, y `wal_level = logical` en `postgresql.conf` (lo necesita el CDC -> reiniciar el servicio tras el cambio).

**1. Entorno de Python**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Carga inicial (genera el grafo `memorias.ttl`)**
```bash
cd semana-2
export PGPASSWORD=postgres
python carga_inicial.py
```
Debería imprimir los conteos por entidad y ~19.000 tripletas.

**3. Levantar la infraestructura (Kafka + Debezium + GraphDB)**
```bash
cd ../semana-3
docker compose up -d
```
Esperar ~30 s. Quedan disponibles: Kafka Connect (puerto 8083), Kafka UI (puerto 8080) y GraphDB (puerto 7200).

**4. Cargar el grafo en GraphDB**

Todo por consola, parado en `semana-3`. Primero crear el repositorio a partir del archivo de configuración (ya trae el id `memorias-repo` y el ruleset de inferencia, así no hay que elegir nada en la interfaz):
```bash
cd ../semana-3
curl -X POST http://localhost:7200/rest/repositories -H "Content-Type: multipart/form-data" -F "config=@graphdb-from-docker/memorias-repository.ttl"
```

También se puede hacer desde la interfaz gráfica: Setup -> Repositories -> Create, con un ruleset RDFS/OWL para la inferencia (o directamente con el archivo `memorias-repository.ttl`).

Después importar la ontología (ontologia_memorias_lifia.ttl) y los datos (memorias.ttl) desde la propia interfaz gráfica de GraphDB o mediante los siguientes comandos:
```bash
curl -i -X POST -H "Content-Type: text/turtle" --data-binary @graphdb-from-docker/ontologia_memorias_lifia.ttl http://localhost:7200/repositories/memorias-repo/statements
curl -i -X POST -H "Content-Type: text/turtle" --data-binary @graphdb-from-docker/memorias.ttl http://localhost:7200/repositories/memorias-repo/statements
```
(Alternativa por interfaz gráfica: Setup -> Repositories -> Create para el repo, y la pestaña Import para subir los dos .ttl.)

**OJO**: si se hace desde comando no se ve en la interfaz gráfica que se importaron, verificar con `curl -s http://localhost:7200/rest/repositories/memorias-repo/size`.


**5. Registrar el conector Debezium**
```bash
./register-connector.sh
```
El estado del conector debería quedar en `RUNNING`.

**6. Correr el consumidor (sincronización en vivo)**
```bash
cd ../semana-4
python consumer.py
```
Queda escuchando los cambios. Dejar esta terminal abierta.

**7. Demostrar la sincronización**
En OTRA terminal, hacer un cambio en la base, por ejemplo:
```bash
psql -U postgres -h localhost -d new_memorias -c "UPDATE public.\"Member\" SET \"positionAtLab\"='Investigador Senior' WHERE \"firstName\"='Gustavo';"
```

---

Yo desde bash (en Windows) tuve que usar:
```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -h localhost -d new_memorias -c "UPDATE public.\"Member\" SET \"positionAtLab\"='Investigador Senior' WHERE \"firstName\"='Gustavo';"
```

---

En la terminal del consumer aparece `u  Member  ok`. Falta verificar en GraphDB que el cambio llegó.

1. Por consola:
```bash
curl -s -G http://localhost:7200/repositories/memorias-repo -H "Accept: text/csv" --data-urlencode "query=PREFIX lifia:<http://lifia.info.unlp.edu.ar/ontology#> SELECT ?p ?cargo WHERE { ?p lifia:positionAtLab ?cargo . FILTER(CONTAINS(?cargo,'Senior')) }"
```

2. Por interfaz gráfica (en SPARQL):
```SPARQL
PREFIX lifia: <http://lifia.info.unlp.edu.ar/ontology#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
SELECT ?p ?nombre ?cargo WHERE {
  ?p foaf:givenName ?nombre .
  OPTIONAL { ?p lifia:positionAtLab ?cargo }
  FILTER(?nombre = "Gustavo")
}
```

También se puede buscar directamente a la persona por su nombre (los Member se representan como `foaf:Person` y el nombre va en `foaf:givenName`):
```bash
curl -s -G http://localhost:7200/repositories/memorias-repo -H "Accept: text/csv" --data-urlencode "query=PREFIX lifia:<http://lifia.info.unlp.edu.ar/ontology#> PREFIX foaf:<http://xmlns.com/foaf/0.1/> SELECT ?p ?nombre ?cargo WHERE { ?p foaf:givenName ?nombre . OPTIONAL { ?p lifia:positionAtLab ?cargo } FILTER(?nombre='Gustavo') }"
```

**Para "apagar" todo**
```bash
# Ctrl+C en la terminal del consumer, y después:
cd ../semana-3
docker compose down
```

---

## Cronograma

1. Mapeo de las entidades (VIVO/DBLP/CSO + términos propios).
2. Carga inicial: datos a RDF y subida a GraphDB.
3. Pipeline CDC: Debezium + Kafka.
4. Consumidor: traducir los cambios a RDF y probar la sincronización.
5. Consultas SPARQL, comparación con SQL e inferencia.
6. Cierre: documentación y entrega.

---

## Resultado esperado

Un grafo de conocimiento de las Memorias del Centro LIFIA, con las entidades representadas en RDF e interoperables con Linked Open Data, que se actualiza automáticamente ante cada cambio del portal.
