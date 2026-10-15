#!/usr/bin/env python3
"""
consumer.py - Consume los cambios publicados por Debezium en Kafka y mantiene
actualizado el grafo RDF en GraphDB.

El flujo es:

    PostgreSQL -> Debezium/Kafka -> consumer.py -> GraphDB

Cada evento indica que una fila fue creada, modificada o eliminada.
Para las entidades principales, el consumer vuelve a consultar la fila en 
PostgreSQL y utiliza el mismo mapeo de la carga inicial (mapping.emit_entity)
para generar las tripletas RDF. De esta forma, PostgreSQL sigue siendo la
fuente de datos y se mantiene el mismo formato de representación que en
la carga inicial.

Las relaciones que corresponden a tablas intermedias se actualizan a partir
de sus propios eventos de Kafka, mientras que al actualizar una entidad se
conservan esas relaciones, ya que son mantenidas por las tablas de relación.

Requisitos:

    Instalar dependencias (mismas que semana-3): pip install -r requirements.txt

    Kafka, Debezium y GraphDB deben estar levantados y el repositorio
    'memorias' debe estar creado.
"""


import os
import json
import time
import requests
import psycopg2
import psycopg2.extras
from rdflib import Graph

import mapping as M

# datos de conexión (se pueden pisar con variables de entorno)
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
GRAPHDB_URL     = os.environ.get("GRAPHDB_URL", "http://localhost:7200")
GRAPHDB_REPO    = os.environ.get("GRAPHDB_REPO", "memorias-repo")

# endpoint de GraphDB al que se le mandan los INSERT/DELETE
STATEMENTS      = "%s/repositories/%s/statements" % (GRAPHDB_URL, GRAPHDB_REPO)

# un tópico de kafka por tabla: memorias.public.Member, memorias.public.Project, ...
TOPIC_PATTERN   = r"^memorias\.public\..+"
IDENTIFIER      = str(M.DCTERMS.identifier)

# segundos de espera antes de reintentar un evento cuando graphdb no responde
ESPERA_REINTENTO = 5

# para las tablas de join necesito el nombre de la tabla a partir del tipo de iri
TABLE_BY_TIPO = {v: k for k, v in M.TIPO.items()}

# estas relaciones vienen de las tablas de join, no de la fila de la entidad.
# se preservan cuando actualizo una entidad (las maneja el evento de su tabla _XY).
REL_PREDS = {M.LIFIA.worksOnProject, M.LIFIA.hasProjectMember, M.DBLP.authorOf,
             M.LIFIA.involvedInThesis, M.LIFIA.involvedInScholarship, M.LIFIA.involvedMember,
             M.LIFIA.producedPublication, M.LIFIA.partOfProject, M.LIFIA.relatedProject,
             M.LIFIA.relatedPublication, M.LIFIA.relatedScholarship, M.LIFIA.relatedThesis,
             M.DBLP.authoredBy}



# ------ GraphDB (se le habla por SPARQL Update via HTTP)
def sparql_update(update):
    r = requests.post(STATEMENTS, data=update.encode("utf-8"),
                      headers={"Content-Type": "application/sparql-update"}, timeout=30)
    r.raise_for_status()


def insert_graph(g):
    # serializo el grafo a n-triples y lo meto con un INSERT DATA
    if len(g):
        sparql_update("INSERT DATA {\n%s}" % g.serialize(format="nt"))


def delete_entity_attributes(subject):
    # en un update borro solo los atributos del recurso, no las relaciones de join
    values = ", ".join("<%s>" % p for p in REL_PREDS)
    sparql_update("DELETE { <%s> ?p ?o } WHERE { <%s> ?p ?o . FILTER(?p NOT IN (%s)) }"
                  % (subject, subject, values))


def delete_by_identifier(id_value):
    # borro el recurso que tenga ese dcterms:identifier (el id/uuid siempre viene
    # en el evento, aunque no venga el slug). primero lo saliente, después lo entrante.
    sparql_update('DELETE { ?s ?p ?o } WHERE { ?s <%s> "%s" ; ?p ?o }' % (IDENTIFIER, id_value))

    # también elimino las relaciones entrantes para evitar referencias
    # colgantes hacia un recurso que ya no existe.
    sparql_update('DELETE { ?x ?q ?s } WHERE { ?s <%s> "%s" . ?x ?q ?s }' % (IDENTIFIER, id_value))



# ------ PostgreSQL (releo las filas de acá, no del evento)
def pg():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"), port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", "postgres"),
        dbname=os.environ.get("PGDATABASE", "new_memorias"))

def load_person_index(conn):
    # índice {nombre normalizado: uri} para resolver director/estudiante/asesor a la persona
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute('SELECT id, slug, "firstName", "lastName" FROM public."Member"')
    idx = M.build_person_index([dict(r) for r in cur.fetchall()])

    cur.close()
    return idx


def fetch_row(conn, table, _id):
    # traigo la fila completa por id, con los tipos limpios que da psycopg2
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute('SELECT * FROM public."%s" WHERE id=%%s' % table, (_id,))
    row = cur.fetchone(); cur.close()

    return dict(row) if row else None


def slug_of(conn, table, _id):
    # para las join: necesito el slug de la entidad referenciada para armar su uri
    cur = conn.cursor()

    cur.execute('SELECT slug FROM public."%s" WHERE id=%%s' % table, (_id,))
    row = cur.fetchone(); cur.close()
    
    return row[0] if row else None



# ------ qué hacer con cada evento
def handle(conn, person_index, table, op, before, after):
    if table in M.TIPO:                                  # es una entidad principal
        if op in ("c", "r", "u"):                        # c: create / r: read/snapshot / u: update
            # releo la fila de postgres (no confío en el 'after' del evento)
            row = fetch_row(conn, table, after["id"])

            if row is None:
                return

            g = Graph(); M.bind_all(g)
            subj = M.emit_entity(g, table, row, person_index)

            # si es update, primero limpio los atributos viejos y después reinserto
            if op == "u":
                delete_entity_attributes(subj)
            insert_graph(g)

        elif op == "d":                                  # d: delete
            # borro por id, que siempre está en el 'before'
            delete_by_identifier(before["id"])

    elif table in M.JOINS:                                # es una tabla de join (una relación)
        akind, bkind, fn = M.JOINS[table]
        row = after if op in ("c", "r") else before

        # las columnas A/B son ids: busco el slug de cada entidad para armar sus uris
        sa = slug_of(conn, TABLE_BY_TIPO[akind], row["A"])
        sb = slug_of(conn, TABLE_BY_TIPO[bkind], row["B"])
        if not sa or not sb:
            return
        g = Graph()
        for t in fn(M.uri(akind, sa), M.uri(bkind, sb)):
            g.add(t)
        if op in ("c", "r"):
            insert_graph(g)
        elif op == "d":
            sparql_update("DELETE DATA {\n%s}" % g.serialize(format="nt"))


def es_falla_de_graphdb(e):
    # graphdb caído o sin responder: en ese caso conviene reintentar, no saltear el evento
    if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    return (isinstance(e, requests.exceptions.HTTPError) and e.response is not None
            and e.response.status_code >= 500)


def main():
    from confluent_kafka import Consumer
    conn = pg()
    person_index = load_person_index(conn)

    # me conecto a kafka y me suscribo a todos los tópicos memorias.public.*.
    # el commit automático está apagado: cada mensaje se confirma a mano, recién
    # cuando el cambio quedó aplicado en graphdb (así no se pierde si graphdb está caído)
    consumer = Consumer({"bootstrap.servers": KAFKA_BOOTSTRAP,
                         "group.id": "memorias-rdf-consumer", "auto.offset.reset": "earliest",
                         "enable.auto.commit": False})
    consumer.subscribe([TOPIC_PATTERN])

    print("Escuchando %s ... (Ctrl+C para cortar)" % TOPIC_PATTERN)
    try:
        while True:
            msg = consumer.poll(1.0)                      # espero el próximo mensaje
            if msg is None or msg.value() is None:
                continue
            if msg.error():
                print("  error kafka:", msg.error()); continue
            env = json.loads(msg.value())
            env = env.get("payload", env)                 # tolera esquema on/off
            op = env.get("op")

            # de qué tabla vino el cambio
            table = (env.get("source") or {}).get("table") or msg.topic().split(".")[-1]
            while True:
                try:
                    handle(conn, person_index, table, op, env.get("before"), env.get("after"))
                    print("  %s %-20s ok" % (op, table))

                    # si cambió un Member, refresco el índice de resolución para que quede actualizado
                    if table == "Member":
                        person_index.clear(); person_index.update(load_person_index(conn))
                    break
                except Exception as e:
                    if es_falla_de_graphdb(e):
                        # graphdb no responde: espero y vuelvo a intentar el mismo evento
                        print("  GraphDB no responde (%s), reintento en %d s..." % (type(e).__name__, ESPERA_REINTENTO))
                        time.sleep(ESPERA_REINTENTO)
                        continue
                    # otro error (dato raro, bug): lo muestro y sigo, para no trabar la cola
                    print("  ERROR %s/%s: %s" % (table, op, e))
                    break

            # recién ahora confirmo el mensaje en kafka: si el programa se corta antes,
            # al volver a arrancar el evento se procesa de nuevo
            consumer.commit(message=msg, asynchronous=False)

    except KeyboardInterrupt:
        pass
    finally:
        consumer.close(); conn.close()


if __name__ == "__main__":
    main()
