# Consultas SPARQL - Memorias del LIFIA

Consultas de ejemplo sobre el grafo, una por una. Se ejecutan en el Workbench de GraphDB (http://localhost:7200 -> SPARQL) sobre el repositorio `memorias-repo`. Cada una va con su equivalente en SQL y el resultado esperado sobre los datos actuales (19.853 tripletas sin razonar).

Los prefijos van al principio de cada consulta:

```sparql
PREFIX lifia:   <http://lifia.info.unlp.edu.ar/ontology#>
PREFIX foaf:    <http://xmlns.com/foaf/0.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX vivo:    <http://vivoweb.org/ontology/core#>
PREFIX bibo:    <http://purl.org/ontology/bibo/>
PREFIX dblp:    <https://dblp.org/rdf/schema#>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
```

Detalle a recordar: los miembros NO tienen una clase `lifia:Member`, se representan con clases estándar (`foaf:Person`). Los proyectos son `vivo:Project`, las publicaciones `dblp:Publication`, las tesis `bibo:Thesis` y las becas `vivo:Grant`.

Sobre el razonador y el ORCID: el ORCID de cada investigador se guarda como un literal, con la propiedad `dblp:orcid` (no como `owl:sameAs`). Así la persona es un solo nodo y las consultas de conteo (C1 a C5) dan lo mismo con el razonador prendido o apagado, e igual que en SQL. El razonador aporta en C6, donde deduce relaciones genéricas que no estaban cargadas.

---

## C1 - Cuántas instancias hay de cada tipo

Sirve como control de que la carga entró completa.

```sparql
SELECT ?clase (COUNT(DISTINCT ?s) AS ?n) WHERE {
  VALUES ?clase { foaf:Person vivo:Project dblp:Publication bibo:Thesis vivo:Grant }
  ?s a ?clase .
} GROUP BY ?clase ORDER BY DESC(?n)
```

**SQL equivalente** (cada clase se corresponde con una tabla):
```sql
SELECT 'Publication' t, COUNT(*) n FROM "Publication"
UNION ALL SELECT 'Thesis',      COUNT(*) FROM "Thesis"
UNION ALL SELECT 'Scholarship', COUNT(*) FROM "Scholarship"
UNION ALL SELECT 'Project',     COUNT(*) FROM "Project"
UNION ALL SELECT 'Member',      COUNT(*) FROM "Member"
ORDER BY n DESC;
```

**Resultado esperado:** Publication 518, Thesis 154, Grant (becas) 65, Project 56, Person 51.

---

## C2 - Top 6 de investigadores con más publicaciones

Recorre el grafo de la persona a sus publicaciones sin ningún JOIN.

```sparql
SELECT ?nombre (COUNT(?p) AS ?publicaciones) WHERE {
  ?m a foaf:Person ; foaf:givenName ?g ; foaf:familyName ?f ; lifia:authorOf ?p .
  BIND(CONCAT(?g, " ", ?f) AS ?nombre)
} GROUP BY ?nombre ORDER BY DESC(?publicaciones) LIMIT 6
```

**SQL equivalente:**
```sql
SELECT m."firstName"||' '||m."lastName", COUNT(*) c
FROM "Member" m JOIN "_PublicationMembers" pm ON pm."A"=m.id
GROUP BY 1 ORDER BY c DESC LIMIT 6;
```

**Resultado esperado (= SQL):** Alejandro Fernandez 109, Gustavo Rossi 97, Leandro Antonelli 94, Diego Torres 85, Claudia Pons 57, Alejandra Garrido 56.

---

## C3 - Top 6 de co-autorías: quiénes publican más juntos

Junta dos autores sobre la misma publicación. El `FILTER` con `<` impone un orden entre los 2 autores, por lo que cada par aparece una sola vez y una persona no puede emparejarse consigo misma.

```sparql
SELECT ?autor1 ?autor2 (COUNT(?p) AS ?juntos) WHERE {
  ?m1 lifia:authorOf ?p ; foaf:familyName ?autor1 .
  ?m2 lifia:authorOf ?p ; foaf:familyName ?autor2 .
  FILTER( STR(?m1) < STR(?m2) )
} GROUP BY ?autor1 ?autor2 ORDER BY DESC(?juntos) LIMIT 6
```

**SQL equivalente:**
```sql
SELECT m1."lastName", m2."lastName", COUNT(*) c
FROM "_PublicationMembers" a JOIN "_PublicationMembers" b
     ON a."B"=b."B" AND a."A"<b."A"
JOIN "Member" m1 ON m1.id=a."A" JOIN "Member" m2 ON m2.id=b."A"
GROUP BY 1,2 ORDER BY c DESC LIMIT 6;
```

**Resultado esperado (= SQL):** Fernandez-Torres 42, Rossi-Firmenich 37, Garrido-Grigera 30, Torres-Antonelli 27, Fernandez-Antonelli 23, Rossi-Grigera 20.

(El agrupamiento es por apellido, así que si hubiera 2 personas distintas con el mismo apellido y un paper en común podría aparecer un par "Apellido-Apellido" -> no es un error)

---

## C4 - Top 6 de temas compartidos por más investigadores

Los temas son nodos propios (`res:tema/...`) tipados `cso:Topic` y `skos:Concept`. Se toma su etiqueta con `skos:prefLabel`.

```sparql
SELECT ?tema (COUNT(DISTINCT ?m) AS ?investigadores) WHERE {
  ?m a foaf:Person ; dcterms:subject ?t .
  ?t skos:prefLabel ?tema .
} GROUP BY ?tema ORDER BY DESC(?investigadores) LIMIT 6
```

**Sobre el SQL equivalente:** acá no hay uno directo. En la base, los temas viven como texto libre en la columna `tags` de cada miembro; es el ETL de la carga el que parte ese texto en temas normalizados y los convierte en nodos compartidos y enlazables. En SQL habría que partir strings a mano y aun así no se obtienen entidades comunes entre investigadores. Que los temas pasen de texto suelto a nodos compartidos es, justamente, parte de lo que aporta el grafo.

**Resultado esperado:** human-computer interaction 27, software engineering 26, artificial intelligence 20, web engineering 9, citizen science 8, technology and society 7.

---

## C5 - Publicaciones de los proyectos en los que participa un investigador

Es una consulta de varios saltos: de la persona a sus proyectos y de ahí a las publicaciones de esos proyectos, todo en un solo patrón.

```sparql
SELECT (COUNT(DISTINCT ?pub) AS ?publicacionesDeSusProyectos) WHERE {
  ?m a foaf:Person ; foaf:familyName "Rossi" ; lifia:worksOnProject ?proj .
  ?proj lifia:producedPublication ?pub .
}
```

**SQL equivalente (3 JOINs sobre dos tablas de unión):**
```sql
SELECT COUNT(DISTINCT pp."B")
FROM "Member" m
JOIN "_ProjectMembers" pm ON pm."A"=m.id
JOIN "_ProjectPublications" pp ON pp."A"=pm."B"
WHERE m."lastName"='Rossi';
```

**Resultado esperado:** 158 publicaciones. Lo interesante es el contraste: en SQL son tres JOINs, en SPARQL es un camino directo por el grafo.

---

## C6 - Inferencia

Requiere que el repositorio tenga el razonador activado (el `memorias-repo` se crea con el ruleset `rdfs`, que alcanza para lo que se muestra).

Para comprobar el efecto del razonamiento, se ejecuta la misma consulta con la opción Include inferred del editor SPARQL desactivada y activada:

```sparql
SELECT (COUNT(*) AS ?tripletas) WHERE { ?s ?p ?o }
```

Con "Include inferred" desactivad, el resultado corresponde a las tripletas explícitamente almacenadas en el repositorio: 19.853 entre datos y ontología.

Al activar "Include inferred", el resultado incluye además las tripletas que el razonador puede deducir a partir de las relaciones y axiomas definidos en la ontología, por lo que el total aumenta. La cantidad exacta depende del ruleset configurado en el repositorio y se puede consultar directamente en GraphDB. El total con inferidas también se puede ver por consola con `curl -s http://localhost:7200/repositories/memorias-repo/size`.

La inferencia más clara para mostrar en este caso es `dcterms:relation` -> ya que las relaciones específicas del vocabulario `lifia:` están declaradas como subpropiedad de `dcterms:relation`. Por lo tanto, a partir de una tripleta como:

`persona lifia:authorOf publicacion`

el razonador puede inferir:

`persona dcterms:relation publicacion`

La siguiente consulta permite observar directamente esta diferencia:

```sparql
SELECT (COUNT(*) AS ?relacionesGenericasInferidas) WHERE { ?x dcterms:relation ?y }
```

**Resultado esperado:** 0 sin razonar, 3063 con razonamiento.


Esto muestra una diferencia importante respecto de la base relacional: las 3063 relaciones genéricas no fueron cargadas explícitamente por el ETL ni existen como una columna o tabla en PostgreSQL. Se obtienen a partir de la semántica definida en la ontología. El razonador toma las relaciones específicas (`lifia:authorOf`, participación en proyectos, dirección de tesis, etc) y las relaciona con el concepto más general `dcterms:relation`.


---


Aclaración sobre las otras inferencias posibles:

- Las relaciones inversas (`dcterms:creator` / `lifia:authorOf`, `lifia:hasProjectMember` / `lifia:worksOnProject`) están declaradas en la ontología con `owl:inverseOf`. Sin embargo, el ETL ya carga las 2 direcciones de cada relación, por lo que el razonador no agrega tripletas nuevas en estos casos. Las declaraciones se mantienen como parte de la semántica del modelo y permiten que la relación pueda inferirse si en algún momento se cargara solamente 1 de las 2 direcciones.

- Las equivalencias de clase con vocabularios externos (DBLP, FOAF, schema.org) tampoco generan nuevas instancias en este repositorio, ya que las ontologías externas correspondientes no están importadas.

Por eso, el ejemplo utilizado para mostrar la inferencia es `dcterms:relation`: al ejecutar la consulta con el razonamiento desactivado se obtienen 0 relaciones explícitas, mientras que con el razonamiento activado se obtienen 3063, producto de las relaciones específicas declaradas como subpropiedades de `dcterms:relation`.

---

## Conclusiones

De estas consultas se pueden sacar 3 cosas.

La 1° es que la migración a RDF quedó fiel, ya que en C1, C2, C3 y C5, la consulta SPARQL da exactamente los mismos números que su equivalente en SQL sobre la base original. O sea, al pasar los datos al grafo no se perdió ni se inventó nada. Y como el ORCID se modeló con un literal (`dblp:orcid`) y no con `owl:sameAs`, los conteos dan igual con el razonador prendido o apagado, sin duplicar personas (cosa que me había pasado y tuve que arreglarlo).

La 2° es sobre la forma de consultar. Preguntas que en SQL necesitan varios JOINs en SPARQL se escriben como un recorrido por el grafo. El caso más claro es C5 -> 3 JOINs sobre 2 tablas de unión contra 1 único patrón "Persona -> Proyecto -> Publicación". Esto hace que la consulta refleje de forma más directa las relaciones que existen en el modelo.

La 3° es la **inferencia**, que es donde aparece el aporte semántico del modelo. Con el razonador activado, el grafo puede responder relaciones que no fueron almacenadas explícitamente, sino que se deducen a partir de la ontología. El ejemplo mostrado en C6 es `dcterms:relation`, que pasa de 0 relaciones explícitas a 3063 inferidas. Ahí ya no hay un SQL equivalente posible (o si lo hay, es muy complicado de plantear), porque esa información no existe en la base relacional -> es lo que agrega representar el dominio con semántica.

**Sumado al pipeline CDC, que mantiene el grafo actualizado ante los cambios del portal, el RESULTADO es un Grafo de Conocimiento que conserva la información de la base original, permite recorrer sus relaciones mediante SPARQL y agrega relaciones inferidas a partir de la semántica definida en la ontología**.
