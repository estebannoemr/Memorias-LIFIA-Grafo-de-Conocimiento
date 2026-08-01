#!/usr/bin/env python3
"""
carga_inicial.py - Carga inicial del grafo (modelo nuevo, con ETL).

Lee la base new_memorias y genera memorias.ttl aplicando mapping:
IRIs por slug, clases estándar, y ETL (resolución de nombres a personas,
parseo de bibtexData para venue/doi/páginas, temas como nodos).

Uso:
    pip install psycopg2-binary rdflib
    python carga_inicial.py
Conexión por variables de entorno PG* (por defecto localhost / postgres / new_memorias).
"""
import os
import psycopg2
import psycopg2.extras
from rdflib import Graph

import mapping as M

ENTITIES = ["Member", "Project", "Publication", "Scholarship", "Thesis"]

def connect():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"), port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", "postgres"),
        dbname=os.environ.get("PGDATABASE", "new_memorias"))

def main():
    conn = connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    g = Graph(); M.bind_all(g)

    # 1) leer miembros: índice para resolución + mapa id->uri
    cur.execute('SELECT * FROM public."Member"')
    members = [dict(r) for r in cur.fetchall()]
    person_index = M.build_person_index(members)

    # 2) mapa id -> uri por tipo (para las tablas de join, que guardan ids)
    id_to_uri = {t: {} for t in M.TIPO.values()}
    rows_by_table = {}
    for table in ENTITIES:
        cur.execute('SELECT * FROM public."%s"' % table)
        rows = [dict(r) for r in cur.fetchall()]
        rows_by_table[table] = rows
        tipo = M.TIPO[table]
        for r in rows:
            id_to_uri[tipo][r["id"]] = M.uri(tipo, r["slug"])

    # 3) emitir entidades (datos + objetos de columna + resolución + tags + bibtex)
    stats = {"resolved": 0, "unresolved": 0}
    for table in ENTITIES:
        for r in rows_by_table[table]:
            M.emit_entity(g, table, r, person_index, stats)
        print("  %-14s -> %d instancias" % (table, len(rows_by_table[table])))

    # 4) emitir relaciones de las tablas de join
    total_rel = 0
    for jtable, (akind, bkind, fn) in M.JOINS.items():
        cur.execute('SELECT "A","B" FROM public."%s"' % jtable)
        n = 0
        for row in cur.fetchall():
            ua = id_to_uri[akind].get(row["A"]); ub = id_to_uri[bkind].get(row["B"])
            if ua is None or ub is None:
                continue
            for (s, p, o) in fn(ua, ub):
                g.add((s, p, o))
            n += 1
        total_rel += n

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memorias.ttl")
    g.serialize(destination=out, format="turtle")
    print("\nGrafo generado: %s" % out)
    print("Tripletas: %d | relaciones de join: %d" % (len(g), total_rel))
    print("Resolución de nombres -> resueltos: %d | sin resolver: %d"
          % (stats["resolved"], stats["unresolved"]))
    cur.close(); conn.close()

if __name__ == "__main__":
    main()
