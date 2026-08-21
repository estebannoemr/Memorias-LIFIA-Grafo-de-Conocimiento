"""
mapping.py - Lógica de mapeo relacional → RDF, modelo NUEVO.

Alineado a mapeo_ontologico.md / ontologia_memorias_lifia.ttl:
  - IRIs por slug bajo  http://lifia.info.unlp.edu.ar/resource/{tipo}/{slug}
  - clases estándar directas (foaf:Person, vivo:Project, vivo:Grant, bibo:Thesis, ...)
  - id (UUID) conservado como dcterms:identifier
  - ETL: resolución de nombres (director/estudiante/asesor) a foaf:Person,
         parseo de bibtexData (venue/doi/páginas) y temas como nodos (cso:Topic).

Lo usan carga_inicial.py y consumer.py (CDC).
"""
import re
import unicodedata
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD, OWL, DCTERMS, FOAF

LIFIA = Namespace("http://lifia.info.unlp.edu.ar/ontology#") # Namespace de nuestro vocabulario propio (clases/propiedades lifia:)
RES   = "http://lifia.info.unlp.edu.ar/resource/" # string base para armar las IRIs de las instancias (recursos)
VIVO  = Namespace("http://vivoweb.org/ontology/core#")
BIBO  = Namespace("http://purl.org/ontology/bibo/")
DBLP  = Namespace("https://dblp.org/rdf/schema#")
CSO   = Namespace("http://cso.kmi.open.ac.uk/schema/cso#")
SKOS  = Namespace("http://www.w3.org/2004/02/skos/core#")



def bind_all(g):
    """Registra los prefijos de las ontologías utilizadas en el grafo."""
    for p, ns in [("lifia", LIFIA), ("vivo", VIVO), ("bibo", BIBO), ("dblp", DBLP),
                  ("cso", CSO), ("skos", SKOS), ("foaf", FOAF), ("dcterms", DCTERMS)]:
        g.bind(p, ns)



# ------ utilidades
def slugify(text):
    # Si el valor de entrada es None, no se puede generar un slug.
    if text is None:
        return None

    # Normaliza el texto Unicode y lo convierte a ASCII,
    # eliminando tildes y otras marcas de las letras.
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")

    # Convertir a minúsculas.
    t = t.lower()

    # Reemplaza 1 o + caracteres no alfanuméricos por 1 único guion
    # y elimina los guiones al principio y al final.
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or None


def uri(tipo, slug):
    """Genera una URI de la forma {base}{tipo}/{slug}."""
    return URIRef("%s%s/%s" % (RES, tipo, slug))



# tipo de IRI por entidad
TIPO = {"Member": "persona", "Project": "proyecto", "Publication": "publicacion",
        "Scholarship": "beca", "Thesis": "tesis"}



# ------ personas (resolución)
_TITULOS = re.compile(r"^(dr|dra|lic|ing|mg|mag|esp|prof|phd|dr\.|dra\.)\.?\s+", re.I)


def _clean_name(n):
    """Elimina los títulos de una persona (Dr., Dra., Lic., ...)."""
    n = (n or "").strip()  # limpia espacios

    while True:
        n2 = _TITULOS.sub("", n)  # elimina los títulos
        if n2 == n: 
            break           # si no cambia, se ha terminado
        n = n2.strip()      # limpiar espacios
    return n


def split_persons(text):
    """Separa un campo que puede tener varias personas."""
    if not text or not text.strip(): 
        return []  # no hay nada que separar

    # Separa los nombres utilizando "y", "and", ";" o "/".
    parts = re.split(r"\s+y\s+|\s+and\s+|\s*;\s*|\s*/\s*", text.strip())

    # Limpiar cada parte y devolver los nombres limpios
    return [_clean_name(p) for p in parts if p and p.strip()]


def build_person_index(members):
    """members: iterable de dicts con id, slug, firstName, lastName.
       Devuelve dict {clave_normalizada: URI} para resolver nombres."""
    idx = {}  # indice de nombres normalizados a URI de persona.

    for m in members:
        u = uri("persona", m["slug"])  # URI de la persona
        keys = {m["slug"],  # clave original
                slugify("%s %s" % (m.get("firstName") or "", m.get("lastName") or "")),  # slug de nombre
                slugify("%s %s" % (m.get("lastName") or "", m.get("firstName") or ""))}  # slug de apellido
        for k in keys:
            if k: 
                idx.setdefault(k, u) # conserva la primera URI asociada a cada clave.
    return idx


def resolve_person(name_text, index):
    """Devuelve la URI del miembro si el nombre matchea; si no, None."""
    return index.get(slugify(_clean_name(name_text)))



# ------ temas (CSO / local)

def topic_uris(tags, g):
    """tags: lista de strings. Crea nodos de tema locales y devuelve sus URIs.
       (El match real contra CSO se haría acá; sin el dataset se usa fallback local.)"""
    out = []

    # Si no hay tags, no se generan temas
    if not tags:
        return out
    
    items = tags if isinstance(tags, (list, tuple)) else \
        [t.strip() for t in re.split(r"[;,]", str(tags))] if tags else []  # separar tags


    for t in items:
        t = (t or "").strip()  # limpiar espacios
        s = slugify(t)  # slug de tag

        if not s:  # si no hay slug, no se genera un tema
            continue

        u = uri("tema", s)  # URI de tema
        g.add((u, RDF.type, CSO.Topic)); g.add((u, RDF.type, SKOS.Concept))  # clases de tema
        g.add((u, SKOS.prefLabel, Literal(t)))  # etiqueta
        g.add((u, RDFS.label, Literal(t)))  # etiqueta
        out.append(u)  # guardar URI
    
    return out


# ------ bibtex (venue/doi/páginas)
def bibtex_extract(bib):
    """bib: dict del jsonb bibtexData. Devuelve (doi, pageStart, pageEnd, venue_name, venue_type)."""

    if not isinstance(bib, dict): 
        return None, None, None, None, None  # no es un dict

    tags = bib.get("entryTags", {}) or {}           # etiquetas
    # etype = (bib.get("entryType") or "").lower()    # tipo de publicación
    doi = (tags.get("doi") or "").strip() or None   # DOI
    pages = (tags.get("pages") or "").strip()       # páginas
    ps = pe = None                                  # páginas iniciales y finales

    if pages:
        m = re.split(r"\s*-{1,2}\s*", pages)  # separar páginas
        ps = m[0].strip() or None             # páginas iniciales
        pe = m[1].strip() if len(m) > 1 else None  # páginas finales

    journal = (tags.get("journal") or "").strip()  # nombre de la revista

    booktitle = (tags.get("booktitle") or "").strip()  # nombre de la conferencia

    if journal:
        venue, vtype = journal, "journal"  # tipo de venue
    elif booktitle:
        venue, vtype = booktitle, "conference"  # tipo de venue
    else:
        venue, vtype = None, None  # no hay venue

    if venue:                                       # si hay venue
        venue = re.sub(r"\s+", " ", venue).strip()  # limpiar espacios
    
    return doi, ps, pe, venue, vtype


def venue_node(name, vtype, g):
    """Crea (o referencia) el nodo de venue y devuelve su URI."""
    s = slugify(name)  # slug de nombre (identificador normalizado del venue)

    if not s:
        return None # si no hay slug, no se genera un nodo
    
    s = s[:70]  # limita la longitud del slug para evitar IRIs excesivamente largas. IMPORTANTE
    u = uri("venue", s) # URI de venue

    g.add((u, RDF.type, BIBO.Conference if vtype == "conference" else BIBO.Journal))  # clase de venue
    g.add((u, RDF.type, DBLP.Venue))  # clase de venue
    g.add((u, RDFS.label, Literal(name)))  # etiqueta

    return u  # URI de venue



# ------ valores literales
def add_literal(g, s, pred, val, kind="str", lang=None): # g = graph, s = subject, pred = predicate, val = value
    """Agrega un valor al grafo RDF como literal, aplicando el tipo indicado."""
    if val is None:
        return  # no se agrega nada si el valor es None
    
    if isinstance(val, str) and val.strip() == "":
        return  # no se agrega nada si el valor es una cadena vacía
    
    if kind == "date":  # fecha
        g.add((s, pred, Literal(val.isoformat() if hasattr(val, "isoformat") else str(val), datatype=XSD.date)))

    elif kind == "dt":  # fecha y hora
        g.add((s, pred, Literal(val.isoformat() if hasattr(val, "isoformat") else str(val), datatype=XSD.dateTime)))

    elif kind == "int":  # entero
        try: g.add((s, pred, Literal(int(val), datatype=XSD.integer)))
        except (ValueError, TypeError): pass  # si no puede convertirse a entero, se ignora el valor.

    elif kind == "gyear":  # año
        try: g.add((s, pred, Literal(int(val), datatype=XSD.gYear)))
        except (ValueError, TypeError): pass  # si no puede convertirse a año, se ignora el valor.
 
    elif kind == "bool":  # booleano
        g.add((s, pred, Literal(bool(val), datatype=XSD.boolean)))

    elif kind == "uri":  # URI
        sv = str(val).strip()

        # Si el valor parece una URI HTTP válida, se crea un URIRef;
        # de lo contrario, se conserva como literal.
        g.add((s, pred, URIRef(sv) if (sv.startswith("http") and " " not in sv) else Literal(sv)))

    elif kind == "lang":  # literal con idioma
        g.add((s, pred, Literal(str(val), lang=lang)))

    else:  # literal
        g.add((s, pred, Literal(str(val))))



# ------ clase BIBO por type de publicación
BIBO_BY_TYPE = {"article": BIBO.AcademicArticle, "inproceedings": BIBO.Article,
                "conference": BIBO.Article, "inbook": BIBO.Chapter,
                "incollection": BIBO.Chapter, "book": BIBO.Book, "phdthesis": BIBO.Thesis}



# ------ tablas de join → object properties
# (tabla, tipo de A, tipo de B, función(uriA, uriB) -> [(s,p,o), ...])
JOINS = {
    "_ProjectMembers":      ("persona", "proyecto",     lambda a, b: [(a, LIFIA.worksOnProject, b), (b, LIFIA.hasProjectMember, a)]),
    "_PublicationMembers":  ("persona", "publicacion",  lambda a, b: [(a, LIFIA.authorOf, b), (b, DCTERMS.creator, a)]),
    "_ThesisMembers":       ("persona", "tesis",        lambda a, b: [(a, LIFIA.involvedInThesis, b), (b, LIFIA.involvedMember, a)]),
    "_ScholarshipMembers":  ("persona", "beca",         lambda a, b: [(a, LIFIA.involvedInScholarship, b), (b, LIFIA.involvedMember, a)]),
    "_ProjectPublications": ("proyecto", "publicacion", lambda a, b: [(a, LIFIA.producedPublication, b), (b, LIFIA.partOfProject, a)]),
    "_ProjectScholarships": ("proyecto", "beca",        lambda a, b: [(a, LIFIA.relatedScholarship, b), (b, LIFIA.relatedProject, a)]),
    "_ProjectTheses":       ("proyecto", "tesis",       lambda a, b: [(a, LIFIA.relatedThesis, b), (b, LIFIA.relatedProject, a)]),
    "_ThesisPublications":  ("publicacion", "tesis",    lambda a, b: [(b, LIFIA.relatedPublication, a), (a, LIFIA.relatedThesis, b)]),
    "_ThesisScholarships":  ("beca", "tesis",           lambda a, b: [(b, LIFIA.relatedScholarship, a), (a, LIFIA.relatedThesis, b)]),
}



# ------ clases por entidad
CLASSES = {
    "Member":      [FOAF.Person, VIVO.Person],
    "Project":     [VIVO.Project],
    "Publication": [DBLP.Publication, BIBO.Document],
    "Scholarship": [VIVO.Grant],
    "Thesis":      [BIBO.Thesis],
}



# columnas → propiedad de datos (columna, predicado, kind, lang)
DATA = {
    "Member": [
        ("id", DCTERMS.identifier, "str", None), ("firstName", FOAF.givenName, "str", None),
        ("lastName", FOAF.familyName, "str", None), ("slug", LIFIA.slug, "str", None),
        ("startDate", LIFIA.startDate, "date", None), ("endDate", LIFIA.endDate, "date", None),
        ("highestDegree", LIFIA.highestDegree, "str", None), ("coursesAtUNLP", LIFIA.coursesAtUNLP, "str", None),
        ("positionAtLab", LIFIA.positionAtLab, "str", None), ("positionAtUnlp", LIFIA.positionAtUnlp, "str", None),
        ("category", LIFIA.category, "str", None), ("sicadiCategory", LIFIA.sicadiCategory, "str", None),
        ("positionAtCIC", LIFIA.positionAtCIC, "str", None), ("positionAtCONICET", LIFIA.positionAtCONICET, "str", None),
        ("personalEmail", FOAF.mbox, "str", None), ("institutionalEmail", LIFIA.institutionalEmail, "str", None),
        ("phone", FOAF.phone, "str", None), ("webPage", FOAF.homepage, "uri", None),
        ("shortCvInSpanish", VIVO.overview, "lang", "es"), ("shortCvInEnglish", VIVO.overview, "lang", "en"),
        ("interestsInEnglish", VIVO.freetextKeyword, "lang", "en"), ("interestsInSpanish", VIVO.freetextKeyword, "lang", "es"),
        ("affiliations", LIFIA.affiliations, "str", None), ("avatarUrl", FOAF.depiction, "uri", None),
        ("createdAt", DCTERMS.created, "dt", None), ("updatedAt", DCTERMS.modified, "dt", None),
    ],
    "Project": [
        ("id", DCTERMS.identifier, "str", None), ("title", DCTERMS.title, "str", None),
        ("code", LIFIA.code, "str", None), ("slug", LIFIA.slug, "str", None),
        ("startDate", LIFIA.startDate, "date", None), ("endDate", LIFIA.endDate, "date", None),
        ("responsibleGroup", LIFIA.responsibleGroup, "str", None), ("fundingAgency", LIFIA.fundingAgency, "str", None),
        ("amount", LIFIA.amount, "str", None), ("summary", DCTERMS.abstract, "str", None),
        ("website", FOAF.homepage, "uri", None), ("featured", LIFIA.featured, "bool", None),
        ("createdAt", DCTERMS.created, "dt", None), ("updatedAt", DCTERMS.modified, "dt", None),
    ],
    "Publication": [
        ("id", DCTERMS.identifier, "str", None), ("slug", LIFIA.slug, "str", None),
        ("publicationType", LIFIA.publicationType, "str", None),  # se completa desde 'type'
        ("title", DCTERMS.title, "str", None), ("authors", DBLP.bibtexAuthor, "str", None),
        ("year", DBLP.yearOfPublication, "gyear", None), ("ranking", LIFIA.ranking, "str", None),
        ("selfArchivingUrl", LIFIA.selfArchivingUrl, "uri", None),
        ("createdAt", DCTERMS.created, "dt", None), ("updatedAt", DCTERMS.modified, "dt", None),
    ],
    "Scholarship": [
        ("id", DCTERMS.identifier, "str", None), ("title", DCTERMS.title, "str", None),
        ("slug", LIFIA.slug, "str", None), ("scholarshipType", LIFIA.scholarshipType, "str", None),  # desde 'type'
        ("fundingAgency", LIFIA.fundingAgency, "str", None), ("startDate", LIFIA.startDate, "date", None),
        ("endDate", LIFIA.endDate, "date", None), ("summary", DCTERMS.abstract, "str", None),
        ("createdAt", DCTERMS.created, "dt", None), ("updatedAt", DCTERMS.modified, "dt", None),
    ],
    "Thesis": [
        ("id", DCTERMS.identifier, "str", None), ("title", DCTERMS.title, "str", None),
        ("slug", LIFIA.slug, "str", None), ("career", LIFIA.career, "str", None),
        ("level", LIFIA.level, "str", None), ("startDate", LIFIA.startDate, "date", None),
        ("endDate", LIFIA.endDate, "date", None), ("summary", DCTERMS.abstract, "str", None),
        ("reportUrl", LIFIA.reportUrl, "uri", None), ("progress", LIFIA.progress, "int", None),
        ("website", FOAF.homepage, "uri", None), ("featured", LIFIA.featured, "bool", None),
        ("createdAt", DCTERMS.created, "dt", None), ("updatedAt", DCTERMS.modified, "dt", None),
    ],
}



# nombres en texto libre → (columna, propiedad literal, propiedad de objeto tras resolución)
NAMES = {
    "Project":     [("director", LIFIA.directorName, LIFIA.hasDirector),
                    ("coDirector", LIFIA.coDirectorName, LIFIA.hasCoDirector)],
    "Scholarship": [("student", LIFIA.studentName, LIFIA.hasStudent),
                    ("director", LIFIA.directorName, LIFIA.hasDirector),
                    ("coDirector", LIFIA.coDirectorName, LIFIA.hasCoDirector)],
    "Thesis":      [("student", LIFIA.studentName, LIFIA.hasStudent),
                    ("director", LIFIA.directorName, LIFIA.hasDirector),
                    ("coDirector", LIFIA.coDirectorName, LIFIA.hasCoDirector),
                    ("otherAdvisors", LIFIA.otherAdvisors, LIFIA.hasAdvisor)],
}



def emit_entity(g, table, row, person_index, stats=None):
    """Agrega al grafo g todas las tripletas de una fila de entidad principal.
       row: dict {columna: valor}.  person_index: para resolver nombres."""
    
    s = uri(TIPO[table], row["slug"])  # URI de entidad

    for c in CLASSES[table]:  # clases de entidad
        g.add((s, RDF.type, c))
    
    # Agregar la subclase BIBO correspondiente al tipo de publicación.
    if table == "Publication":
        extra = BIBO_BY_TYPE.get(str(row.get("type") or "").lower())  # clase BIBO según el type de la publicación
        if extra:
            g.add((s, RDF.type, extra))  # agrega la subclase BIBO
        row = dict(row); row["publicationType"] = row.get("type")  # guarda el tipo de publicación

    if table == "Scholarship":
        row = dict(row); row["scholarshipType"] = row.get("type")  # guarda el tipo de beca


    # propiedades de datos
    for col, pred, kind, lang in DATA[table]:
        add_literal(g, s, pred, row.get(col), kind, lang)  # agrega la propiedad de datos

    # perfiles / identificadores externos (Member)
    if table == "Member":
        orc = re.sub(r"\s+", "", (row.get("orcid") or ""))  # elimina espacios

        if orc:
            u = orc if orc.startswith("http") else "https://orcid.org/" + orc  # arma la url del orcid
            if " " not in u:
                # el orcid va como literal (dblp:orcid), no como owl:sameAs, así no crea
                # una segunda identidad de la persona que duplica los conteos al razonar
                g.add((s, DBLP.orcid, Literal(u, datatype=XSD.anyURI)))

        for col in ("dblpProfile", "googleResearchProfile", "researchGateProfile"):
            v = (row.get(col) or "").strip() # limpia espacios
            if v.startswith("http") and " " not in v:  # si es un URI
                g.add((s, RDFS.seeAlso, URIRef(v)))  # agrega la propiedad de perfil


    # Genera los nodos de tema a partir de tags y, en el caso de Thesis, keywords.
    tag_cols = ["tags"] + (["keywords"] if table == "Thesis" else [])  # columnas de temas
    for tc in tag_cols:
        for tu in topic_uris(row.get(tc), g):  # agrega los temas
            g.add((s, DCTERMS.subject, tu))  # agrega la propiedad de tema


    # bibtex (Publication)
    if table == "Publication":
        doi, ps, pe, venue, vtype = bibtex_extract(row.get("bibtexData"))  # extrae los datos de bibtex

        if doi: g.add((s, BIBO.doi, Literal(doi)))  # agrega la propiedad de DOI
        if ps:  g.add((s, BIBO.pageStart, Literal(ps)))  # agrega la propiedad de páginas
        if pe:  g.add((s, BIBO.pageEnd, Literal(pe)))  # agrega la propiedad de páginas

        if venue:
            vu = venue_node(venue, vtype, g)  # crea el nodo de venue
            if vu:
                g.add((s, BIBO.presentedAt if vtype == "conference" else DCTERMS.isPartOf, vu))  # agrega la propiedad de venue


    # nombres en texto libre + resolución de entidades
    for col, litpred, objpred in NAMES.get(table, []):
        val = row.get(col)  # valor de la columna

        if not val:
            continue  # si no hay valor, no se agrega nada

        add_literal(g, s, litpred, val, "str")          # se conserva el literal

        for name in split_persons(val):
            pu = resolve_person(name, person_index)      # se intenta resolver a un Member

            if pu is not None:  # si se encontró un miembro
                g.add((s, objpred, pu))  # agrega la propiedad de objeto

                if stats is not None:
                    stats["resolved"] = stats.get("resolved", 0) + 1  # aumenta el número de miembros resueltos

            elif stats is not None:  # si no se encontró un miembro
                stats["unresolved"] = stats.get("unresolved", 0) + 1  # aumenta el número de miembros no resueltos
    return s
