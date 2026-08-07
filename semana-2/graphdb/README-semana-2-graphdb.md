
# Carga del grafo en GraphDB

Pasos para cargar el grafo de conocimiento en GraphDB, una vez generado el `memorias.ttl` con el script de carga inicial.

---
---

## Requisitos

- GraphDB corriendo en `http://localhost:7200`. Puede ser el GraphDB Free de escritorio o el que levanta el `docker-compose` de la semana 3; en ambos casos responde en esa misma URL, así que estos pasos sirven igual.
- Archivos: `ontologia_memorias_lifia.ttl` (vocabulario) y `memorias.ttl` (datos), generado este último por `carga_inicial.py`.

---
---

## Pasos

1. **Crear el repositorio.** En `http://localhost:7200` → *Setup → Repositories → Create → GraphDB Repository*. ID: `memorias`. Para habilitar la inferencia (necesaria en la etapa de consultas), elegir un ruleset con OWL/RDFS, por ejemplo *RDFS-Plus (Optimized)*.

2. **Importar la ontología primero.** *Import → RDF → Upload RDF files* → subir `ontologia_memorias_lifia.ttl` → *Import*. Es el esquema/vocabulario, va antes que los datos.

3. **Importar los datos.** Igual que el paso anterior, subir `memorias.ttl` → *Import*.

El orden ontología → datos es el lógico -> de todos modos GraphDB los carga en cualquier orden.


---
---


## Verificación

En la pestaña *SPARQL*:

```sparql
SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }
```

- Con **"Include inferred" activado** el total es mayor (~28.000): incluye las tripletas que deduce el razonador (tipos por subclase, propiedades inversas, `dcterms:relation`, etc).

- Con **"Include inferred" desactivado** se ven solo las cargadas explícitamente (~19.800 = datos + ontología).

Que el número suba con la inferencia activada es lo esperado y confirma que el razonamiento está funcionando.


