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
|    |- requirements.txt        Dependencias de Python necesarias
|    |- carga_inicial.py        Script ETL
|    |- mapping.py              Mapeo de entidades a RDF
|    |- memorias.ttl            Grafo RDF
|    |- graphdb
|        |- README.md                       Instrucciones para cargar en GraphDB
|        |- Tripletas con inferencia.png    Cantidad de tripletas con inferencia
|        |- Tripletas sin inferencia.png    Cantidad de tripletas sin inferencia
|    
|- IR AGREGANDO SEMANAS
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
