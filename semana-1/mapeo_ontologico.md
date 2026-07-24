# Mapeo ontológico

La idea de este mapeo es, para cada tabla y cada columna del dump, decidir con qué término de las ontologías la represento.

- Tomé **VIVO** como base porque modela bien todo lo académico (personas, proyectos, becas) -> es una ontología pensada para describir investigadores y su producción y las entidades del LIFIA caen casi 1:1 en sus clases (Member → vivo:Person, Project → vivo:Project, Scholarship → vivo:Grant)
- Para las publicaciones me apoyé en **DBLP** (Computer Science Bibliography) y **BIBO** (bibliographic ontology).
- Para los temas, en **CSO** (Computer Science Ontology) con **SKOS**
- Y cuando algo no encajaba, usé **FOAF** (para datos de personas), **Dublin Core** (para título, creador, fecha, tema) y **OWL** (para sameAs e inferencia).
- Lo que es puramente del LIFIA y no tiene equivalente estándar (por ejemplo, los cargos institucionales), lo definí con términos propios en `lifia:`.
- Con las clases hice lo mismo: reuso las de VIVO, BIBO y FOAF directamente, y solo invento algo `lifia:` cuando no hay nada estándar que sirva.

La base son 5 tablas de entidades (`Member`, `Project`, `Publication`, `Scholarship`, `Thesis`) y 9 tablas de joins N:M (`_ProjectMembers`, `_PublicationMembers`, `_ThesisMembers`, `_ScholarshipMembers`, `_ProjectPublications`, `_ProjectScholarships`, `_ProjectTheses`, `_ThesisPublications`, `_ThesisScholarships`). A estas últimas las traduzco como relaciones entre recursos, no como clases.

<br>

---
---

## Estrategia de IRIs (identificadores del grafo)

Cada cosa que entra al grafo necesita un nombre propio y estable (su **IRI**). Acá defino cómo las armo para los datos de `new_memorias`, buscando que no cambien de una corrida a otra del ETL y que sean cómodas de leer en las consultas.

### 1. Forma de la IRI

Todas las instancias siguen el mismo molde: `{base}{tipo}/{identificador}`

- **`{base}`**: es siempre `http://lifia.info.unlp.edu.ar/resource/`.
- **`{tipo}`**: es una palabra fija en minúscula que dice qué representa el recurso: `persona`, `publicacion`, `proyecto`, `beca`, `tesis`, `tema` o `venue`. Actúa como espacio de nombres interno, así 2 recursos de distinto tipo nunca chocan aunque compartan identificador.
- **`{identificador}`**: es la parte que distingue a un recurso de otro de su mismo tipo (*ver punto 3*).

En Turtle/SPARQL se abrevia con un prefijo propio para las instancias (`res:`), distinto del `lifia:` que usa el vocabulario: ` @prefix res: <http://lifia.info.unlp.edu.ar/resource/> . `

Conviene aclarar que el alcance de esta base es que se aplica **únicamente a los datos** (Matías Urbieta, tal publicación, tal proyecto). Los términos de las ontologías (`vivo:Person`, `cso:Topic`, `bibo:doi`) conservan sus propios namespaces de VIVO, BIBO, FOAF, DBLP, Dublin Core, SKOS y CSO -> no se copian ni se reescriben bajo `lifia:`.

### 2. Tipos y su tabla

| Entidad | Tipo en la IRI | Identificador | Ejemplo |
|---------|----------------|---------------|---------|
| `Member` | `persona` | slug | `.../resource/persona/matias-urbieta` |
| `Publication` | `publicacion` | slug | `.../resource/publicacion/{slug}` |
| `Project` | `proyecto` | slug | `.../resource/proyecto/{slug}` |
| `Scholarship` | `beca` | slug | `.../resource/beca/{slug}` |
| `Thesis` | `tesis` | slug | `.../resource/tesis/{slug}` |
| Tema (de `tags`/`keywords`) | `tema` | texto normalizado | `.../resource/tema/web-engineering` |
| Venue (de `bibtexData`) | `venue` | texto normalizado | `.../resource/venue/icwe-2019` |

Los temas y venues son un caso aparte, ya que sólo se genera una IRI propia (`res:tema/...`) cuando el término no existe en CSO (para los temas) o cuando no se puede enlazar a un recurso externo. Si el tema ya está en CSO, se apunta directamente a la IRI de CSO en lugar de crear una nueva.

### 3. Por qué el slug y no el id

En las 5 tablas principales **hay 2 columnas que podrían servir de identificador**:

- **`id`**: la clave primaria, un UUID como `9d0a5af7-b064-4962-ac33-d332d22549cf`. *Ventaja*: no cambia nunca. *Desventaja*: es ilegible y vuelve las consultas SPARQL incómodas de leer y escribir.

- **`slug`**: un campo único y legible como `matias-urbieta`, que además ya es el que aparece en las URLs del sitio del LIFIA.

Mi elección es el **slug**, priorizando la legibilidad y la coherencia con el sitio existente. La contra es que el slug se puede editar desde el gestor de contenidos -> si eso pasa, la IRI del recurso quedaría distinta en la próxima corrida. Para cubrir ese escenario, cada recurso lleva además su `id` (UUID) como valor de `dcterms:identifier`. De ese modo, aunque el slug cambie, el UUID sigue siendo un ancla estable para volver a emparejar el recurso. *Descarté poner el UUID en la propia IRI*, ya que **resuelve un problema infrecuente a costa de sacrificar la legibilidad en todas las consultas**.

### 4. Cómo se arma el identificador de temas y venues

Los `tags`, `keywords` y nombres de `venue` obtenidos desde *bibtexData* se reciben como Strings (cadenas de texto libre).

Por lo tanto, antes de utilizarlos como identificadores dentro del grafo, es necesario aplicar la función `slugify`, definida en `mapping.py`.

El *objetivo* de esta función es obtener un identificador uniforme a partir del texto original. **Para ello, el contenido se procesa de la siguiente manera**:

1. *Normalización*: normaliza el texto y elimina tildes y otras marcas de las letras, convirtiendo el resultado a una representación ASCII (por ejemplo, "á" → "a", "ñ" → "n").
2. *Normalización de mayúsculas*: todo el texto se convierte a minúsculas.
3. *Reemplazo de espacios y caracteres no alfanuméricos*: se convierten espacios y caracteres no alfanuméricos en guiones simples, sin dejar guiones consecutivos ni en los extremos.
4. Si el resultado queda vacío, se devuelve None.


El resultado es un identificador basado únicamente en una representación normalizada del texto original. Por ejemplo:
- tema `"Human-Computer Interaction"` → `human-computer-interaction`
- venue `"Software & Systems Modeling"` → `software-systems-modeling`

Esta transformación DEBE ser **determinística**, es decir, ante una misma entrada siempre debe producirse exactamente el mismo identificador. De esta manera, si un mismo tema o venue aparece asociado a distintas publicaciones, todas las referencias apuntan al mismo nodo del grafo en lugar de generar duplicados.

<br>

---
---

## Mapeo por entidad

Cada entidad separa las **propiedades de datos** (columna → valor literal) de las **propiedades de objeto** (apuntan a otro recurso: otra entidad, un tema o una URI externa como ORCID/DBLP). Las relaciones que salen de las tablas de join (`_XY`) también son propiedades de objeto y van con el nombre de la tabla como referencia.


### Miembro (`Member`)

- **Clase:** `foaf:Person`, `vivo:Person`

- **Propiedades de datos:**
  - **id**: `dcterms:identifier`
  - **firstName**: `foaf:firstName`
  - **lastName**: `foaf:lastName`
  - **slug**: `lifia:slug`
  - **startDate**: `lifia:startDate`
  - **endDate**: `lifia:endDate`
  - **highestDegree**: `lifia:highestDegree`
  - **coursesAtUNLP**: `lifia:coursesAtUNLP`
  - **positionAtLab**: `lifia:positionAtLab`
  - **positionAtUnlp**: `lifia:positionAtUnlp`
  - **category**: `lifia:category`
  - **sicadiCategory**: `lifia:sicadiCategory`
  - **positionAtCIC**: `lifia:positionAtCIC`
  - **positionAtCONICET**: `lifia:positionAtCONICET`
  - **personalEmail**: `foaf:mbox`
  - **institutionalEmail**: `lifia:institutionalEmail`
  - **phone**: `foaf:phone`
  - **webPage**: `foaf:homepage`
  - **shortCvInSpanish**: `vivo:overview` / `dcterms:description` (`@es`)
  - **shortCvInEnglish**: `vivo:overview` / `dcterms:description` (`@en`)
  - **interestsInEnglish**: `vivo:freetextKeyword` (`@en`)
  - **interestsInSpanish**: `vivo:freetextKeyword` (`@es`)
  - **affiliations**: `lifia:affiliations`
  - **avatarUrl**: `foaf:depiction`
  - **createdAt**: `dcterms:created`
  - **updatedAt**: `dcterms:modified`

- **Propiedades de objeto:**
  - **orcid**: `owl:sameAs` → URI de ORCID (`https://orcid.org/{orcid}`)
  - **dblpProfile**: `rdfs:seeAlso`
  - **googleResearchProfile**: `rdfs:seeAlso`
  - **researchGateProfile**: `rdfs:seeAlso`
  - **tags**: `dcterms:subject` → `cso:Topic`
  - `_PublicationMembers`: `lifia:authorOf` → Publicación
  - `_ProjectMembers`: `lifia:worksOnProject` → Proyecto
  - `_ScholarshipMembers`: `lifia:involvedInScholarship` → Beca
  - `_ThesisMembers`: `lifia:involvedInThesis` → Tesis

- **Ontologías:** VIVO / FOAF

---

### Publicación (`Publication`)

- **Clase:** `dblp:Publication`, `bibo:Document` (subclase específica depende del `type`)

- **Propiedades de datos:**
  - **id**: `dcterms:identifier`
  - **slug**: `lifia:slug`
  - **type**: `lifia:publicationType` (además define la subclase BIBO: article → `bibo:AcademicArticle`, conferencia → `bibo:Article`, capítulo → `bibo:Chapter`, libro → `bibo:Book`, ...)
  - **title**: `dcterms:title` + `dblp:title`
  - **authors**: `dblp:bibtexAuthor` (string completo, incluye coautores externos)
  - **year**: `dblp:yearOfPublication`
  - **ranking**: `lifia:ranking` (p.ej. categoría CORE/Scimago)
  - **selfArchivingUrl**: `lifia:selfArchivingUrl`
  - **bibtexData**: se parsea (JSON) → `bibo:doi`, `bibo:pageStart`/`pageEnd`
  - **createdAt**: `dcterms:created`
  - **updatedAt**: `dcterms:modified`

- **Propiedades de objeto:**
  - **tags**: `dcterms:subject` → `cso:Topic`
  - `_PublicationMembers`: `dcterms:creator` → Miembro (solo autores internos)
  - `_ProjectPublications`: `lifia:partOfProject` → Proyecto
  - `_ThesisPublications`: relación → Tesis
  - **venue** (de `bibtexData`): `bibo:presentedAt` / `dcterms:isPartOf` → Venue

- **Ontologías:** DBLP / BIBO / DC

---

### Proyecto (`Project`)

- **Clase:** `vivo:Project`

- **Propiedades de datos:**
  - **id**: `dcterms:identifier`
  - **title**: `dcterms:title`
  - **code**: `lifia:code`
  - **slug**: `lifia:slug`
  - **startDate**: `lifia:startDate`
  - **endDate**: `lifia:endDate`
  - **responsibleGroup**: `lifia:responsibleGroup`
  - **fundingAgency**: `lifia:fundingAgency`
  - **amount**: `lifia:amount`
  - **summary**: `dcterms:abstract`
  - **website**: `foaf:homepage`
  - **featured**: `lifia:featured`
  - **createdAt**: `dcterms:created`
  - **updatedAt**: `dcterms:modified`

- **Propiedades de objeto:**
  - **director**: `lifia:directorName` (texto libre → resolución a Miembro)
  - **coDirector**: `lifia:coDirectorName` (texto libre → resolución a Miembro)
  - **tags**: `dcterms:subject` → `cso:Topic`
  - `_ProjectMembers`: `lifia:hasProjectMember` → Miembro
  - `_ProjectPublications`: `lifia:producedPublication` → Publicación
  - `_ProjectScholarships`: `lifia:relatedScholarship` → Beca
  - `_ProjectTheses`: `lifia:relatedThesis` → Tesis

- **Ontologías:** VIVO

---

### Beca (`Scholarship`)

- **Clase:** `vivo:Grant`

- **Propiedades de datos:**
  - **id**: `dcterms:identifier`
  - **title**: `dcterms:title`
  - **slug**: `lifia:slug`
  - **type**: `lifia:scholarshipType` (p.ej. doctoral/inicio)
  - **fundingAgency**: `lifia:fundingAgency`
  - **startDate**: `lifia:startDate`
  - **endDate**: `lifia:endDate`
  - **summary**: `dcterms:abstract`
  - **createdAt**: `dcterms:created`
  - **updatedAt**: `dcterms:modified`

- **Propiedades de objeto:**
  - **student**: `lifia:studentName` (texto libre → resolución a Miembro)
  - **director**: `lifia:directorName` (texto libre → resolución a Miembro)
  - **coDirector**: `lifia:coDirectorName` (texto libre → resolución a Miembro)
  - **tags**: `dcterms:subject` → `cso:Topic`
  - `_ScholarshipMembers`: `lifia:involvedMember` → Miembro
  - `_ProjectScholarships`: relación → Proyecto
  - `_ThesisScholarships`: relación → Tesis

- **Ontologías:** VIVO

---

### Tesis (`Thesis`)
- **Clase:** `bibo:Thesis`
- **Propiedades de datos:**
  - **id**: `dcterms:identifier`
  - **title**: `dcterms:title`
  - **slug**: `lifia:slug`
  - **career**: `lifia:career`
  - **level**: `lifia:level` (Licenciatura/Magíster/Doctorado)
  - **startDate**: `lifia:startDate`
  - **endDate**: `lifia:endDate`
  - **summary**: `dcterms:abstract`
  - **reportUrl**: `lifia:reportUrl`
  - **progress**: `lifia:progress`
  - **website**: `foaf:homepage`
  - **featured**: `lifia:featured`
  - **createdAt**: `dcterms:created`
  - **updatedAt**: `dcterms:modified`

- **Propiedades de objeto:**
  - **student**: `lifia:studentName` (texto libre → resolución a Miembro)
  - **director**: `lifia:directorName` (texto libre → resolución a Miembro)
  - **coDirector**: `lifia:coDirectorName` (texto libre → resolución a Miembro)
  - **otherAdvisors**: `lifia:otherAdvisors` (texto libre → resolución a Miembro)
  - **keywords**: `dcterms:subject` → `cso:Topic`
  - **tags**: `dcterms:subject` → `cso:Topic`
  - `_ThesisMembers`: `lifia:involvedMember` → Miembro
  - `_ThesisPublications`: relación → Publicación
  - `_ProjectTheses`: relación → Proyecto
  - `_ThesisScholarships`: relación → Beca

- **Ontologías:** BIBO / VIVO

<br>

---
---

## Entidades derivadas (sin tabla)

### Tema
- **Clase:** `cso:Topic`, `skos:Concept`

- **Origen:** no es una tabla; sale de los valores de `tags` (`text[]`) y de `Thesis.keywords`

- **Propiedades de datos:**
  - **valor del tag**: `skos:prefLabel` / `rdfs:label`

- **Propiedades de objeto:**
  - `cso:superTopicOf` → subtópico en CSO
  - `cso:relatedEquivalent` → tópico equivalente en CSO Web

- **Ontologías:** CSO / SKOS

---

### Venue
- **Clase:** `bibo:Conference`, `bibo:Journal`, `dblp:Venue`

- **Origen:** no es una tabla; sale de parsear el JSON `Publication.bibtexData`

- **Propiedades de datos:**
  - **nombre (journal/booktitle)**: `rdfs:label`
  - **ISSN/ISBN**: `bibo:issn` / `bibo:isbn` (si el BibTeX los trae)

- **Propiedades de objeto:**
  - `dcterms:hasPart` → edición/proceedings del año

- **Ontologías:** BIBO / VIVO / DBLP

<br>

---
---

## Alineación de propiedades

Para mantener la consistencia interna y no perder interoperabilidad, la ontología declara estas relaciones entre propiedades:

- **`lifia:authorOf` es la inversa de `dcterms:creator`** (`lifia:authorOf owl:inverseOf dcterms:creator`). Las 2 describen el mismo vínculo de `_PublicationMembers`, visto desde cada lado: desde el miembro, "es autor de"; desde la publicación, "tiene por autor". Al declararlas inversas, el grafo las trata como una única relación y una consulta la puede recorrer en cualquier dirección (por eso en Member figura `lifia:authorOf` y en Publication `dcterms:creator`, pero no son 2 relaciones distintas).

- **Las propiedades de relación propias son sub-propiedades de `dcterms:relation`** (`rdfs:subPropertyOf dcterms:relation`): `lifia:worksOnProject`, `lifia:involvedInScholarship`, `lifia:involvedInThesis`, `lifia:hasProjectMember`, `lifia:producedPublication`, `lifia:relatedScholarship`, `lifia:relatedThesis` y las demás. Así se conserva la claridad de los nombres específicos y, a la vez, un sistema externo reconoce que hay una relación.

Se eligió `dcterms:relation` en lugar de `vivo:relatedBy` porque, según la definición de VIVO, `vivo:relatedBy` está asociada a su modelo de relaciones y no resulta adecuada para representar directamente estos vínculos entre las entidades del grafo.


<br>

---
---

## Consideraciones para la carga de datos (ETL)

No todo lo que figura en el listado se resuelve leyendo una fila y copiando valores. Varios casos exigen procesamiento previo -> se dejan anotados para tenerlos presentes al momento de programar los scripts.

**Las tablas de enlace ya vienen resueltas.** Las 9 tablas `_XY` tienen claves foráneas (definidas con `ON UPDATE CASCADE` /`ON DELETE CASCADE`), así que cada fila se traduce sin ambigüedad en una relación entre 2 recursos. Son la parte fácil: alcanzan para poblar casi todas las propiedades de objeto y no requieren una clase propia.


**Hay 3 cosas que no son tablas y hay que "fabricar".** -> ni los temas, ni los venues, ni el vínculo real con las personas nombradas están modelados como entidades en el dump y por eso necesitan un paso extra:

1. *Temas*: `tags` es un arreglo de texto (`tags text[]`) presente en `Member`, `Project`, `Publication` y `Thesis`, y en tesis se suma `keywords`. Para llegar a `cso:Topic` hay que contrastar cada valor con el vocabulario de CSO: si coincide, se enlaza a la IRI de CSO; si no, se crea un tema local `lifia:tema/{slug}`.

2. *Venues*: el congreso o revista, junto con DOI, páginas e ISSN/ISBN, viven dentro del JSON `bibtexData` de `Publication`; hay que parsearlo. Como un mismo evento puede aparecer escrito en varias publicaciones, conviene normalizar el nombre (igual que los temas) para no terminar con venues repetidos.

3. *Personas mencionadas por su nombre*: los campos `director`, `coDirector`, `student` y `otherAdvisors` de `Project`, `Scholarship` y `Thesis` guardan el nombre como texto y NO el `id` de `Member`. Para trazar la relación hacia la persona correcta hace falta una etapa de resolución de entidades que empareje esos nombres con la tabla `Member` y si no hay coincidencia que se conserve el nombre como literal.


**Los perfiles externos van como enlaces**: antes que guardar `orcid` o `dblpProfile` como simples cadenas, se los expresa con `owl:sameAs`/`rdfs:seeAlso` hacia la URI externa correspondiente (ORCID, DBLP). Eso es lo que efectivamente conecta el grafo con **Linked Open Data**.


**Cuidado con los autores**: la columna `Publication.authors` trae la lista completa de firmantes como texto e incluye coautores ajenos al LIFIA, mientras que `_PublicationMembers` solo enlaza a los que están dados de alta como `Member`. Por eso conviven 2 caminos:
1. `dblp:bibtexAuthor`, que preserva la autoría íntegra desde el string,
2. `dcterms:creator` (vía la tabla de enlace) que apunta únicamente a los autores internos, que sí son nodos del grafo.


**Qué queda deliberadamente afuera**: el enum `Role` (`USER`, `EDITOR`, `ADMIN`, `POWER_EDITOR`), ya que describe permisos del gestor de contenidos, no información académica, así que no forma parte de este mapeo.



