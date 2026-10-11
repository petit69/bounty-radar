#!/usr/bin/env python3
"""
RADAR DE RECOMPENSAS — busca trabajo pagado en GitHub y lo filtra antes de que el dueño lo mire.

Fuentes (las reales, medidas el 11-oct-2026):
  1. Opire  -> https://api.opire.dev/rewards   (lista pública, sin credenciales)
  2. GitHub -> búsquedas de issues abiertos con marcadores de recompensa (/bounty, opire, algora)

Descarta sin piedad:
  - issue cerrado (la plataforma no los limpia: medido, 2 de 5 en Opire ya estaban muertos)
  - repo archivado o sin actividad reciente
  - granjas de bots (repos recién creados, sin estrellas, títulos tipo "Bounty Alert")
  - repos con política ANTI-IA (si el repo prohíbe IA, no se toca: no se manda un PR que no se pueda defender)

Salida: informe markdown + JSON con la fecha, ordenado por "vale la pena / no vale la pena".

Uso:  python3 radar_recompensas.py [--top N] [--dias-max D]
No modifica NADA en GitHub ni en ninguna cuenta: sólo lee.
"""
import json, os, re, subprocess, sys, urllib.request, urllib.error, urllib.parse, datetime, argparse

SALIDA = os.path.dirname(os.path.abspath(__file__))
HOY = datetime.date.today().isoformat()

# Cuentas/repos detectados como granjas de bots el 11-oct-2026 (heurística: se revisan igual, pero se marcan)
PATRONES_BOT = re.compile(r"bountyscout|bounty-?(alert|watch|scout|bot)|scraping-bounties|bounties-?(list|feed)",
                          re.IGNORECASE)
PATRONES_IA_PROHIBIDA = re.compile(
    r"(no\s+llm|llm[s]?\s+(are|is)\s+not\s+allowed|do\s+not\s+use\s+(ai|llm)|"
    r"ai[- ]generated\s+(code|contributions?)\s+(is|are)\s+not|"
    r"prohibit(ed|s)\s+(the\s+use\s+of\s+)?(ai|llm|machine\s+learning)|"
    r"sin\s+(ia|inteligencia\s+artificial)|no\s+se\s+aceptan\s+(pr|contribuciones)\s+de\s+ia)",
    re.IGNORECASE)
ARCHIVOS_POLITICA = ["AI_POLICY.md", "AI_POLICY", "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "AGENTS.md"]

# Plataformas/repos que YA NO PAGAN (medido el 11-oct-2026). Si aparecen, se descartan: no perder tiempo.
REPOS_MUERTOS = {
    "bountysource/core": "Bountysource dejó de pagar en jun-2023 y quebró (nov-2023)",
    "gitcoinco/web": "Gitcoin descontinuó el producto de bounties",
    "replit/clui": "Replit cerró sus bounties el 06-sep-2025",
}


def gh_api(path, timeout=60):
    """Lee la API de GitHub con las credenciales ya autorizadas del dueño (gh)."""
    try:
        p = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            return None
        return json.loads(p.stdout)
    except Exception:
        return None


def http_json(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "radar-recompensas"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def http_text(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "radar-recompensas"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return ""


def parsear_issue(url):
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)", url or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else (None, None, None)


def extraer_monto(texto):
    """Saca el monto de un comentario tipo '/bounty $150' o 'reward 50 USD'."""
    if not texto:
        return None
    montos = [float(x.replace(",", "")) for x in re.findall(r"\$\s?([0-9][0-9,]{0,9}(?:\.[0-9]{1,2})?)", texto)]
    return max(montos) if montos else None


# ---------------------------------------------------------------- 1) OPIRE
def de_opire():
    datos = http_json("https://api.opire.dev/rewards") or []
    salida = []
    for it in datos:
        owner, repo, num = parsear_issue(it.get("url"))
        if not owner:
            continue
        pp = it.get("pendingPrice") or {}
        monto = (pp.get("value") or 0) / 100 if pp.get("unit") == "USD_CENT" else None
        salida.append({
            "fuente": "Opire",
            "url": it.get("url"),
            "titulo": (it.get("title") or "").strip(),
            "owner": owner, "repo": repo, "num": num,
            "monto_usd": monto,
            "rivales": len(it.get("claimerUsers") or []) + len(it.get("tryingUsers") or []),
            "creado": it.get("createdAt"),
        })
    return salida


# ---------------------------------------------------------------- 2) GITHUB
BUSQUEDAS = [
    '"/bounty " in:body state:open type:issue',
    '"opire" in:comments state:open type:issue',
    '"algora.io" in:body state:open type:issue',
]


def de_github(por_busqueda=30):
    salida, vistos = [], set()
    for q in BUSQUEDAS:
        d = gh_api("search/issues?per_page=%d&sort=updated&q=%s"
                   % (por_busqueda, urllib.parse.quote(q)))
        for it in (d or {}).get("items", []):
            url = it.get("html_url", "")
            if url in vistos:
                continue
            vistos.add(url)
            owner, repo, num = parsear_issue(url)
            if not owner:
                continue
            salida.append({
                "fuente": "GitHub:" + q.split()[0].strip('"'),
                "url": url,
                "titulo": (it.get("title") or "").strip(),
                "owner": owner, "repo": repo, "num": num,
                "monto_usd": extraer_monto((it.get("body") or "")[:4000]),
                "rivales": None,   # se mide después, contando los PR que reclaman ese issue
                "creado": None,
                "comentarios": it.get("comments"),
                "actualizado": (it.get("updated_at") or "")[:10],
            })
    return salida


# ---------------------------------------------------------------- 3) FILTRO
def revisar(c):
    """Completa cada candidato con el estado real y decide si sirve."""
    owner, repo, num = c["owner"], c["repo"], c["num"]
    r = {}
    r["issue"] = gh_api(f"repos/{owner}/{repo}/issues/{num}")
    r["repo"] = gh_api(f"repos/{owner}/{repo}")
    it, rep = r["issue"], r["repo"]
    motivos = []
    if not it:
        motivos.append("no se pudo leer el issue")
    elif it.get("state") != "open":
        motivos.append("CERRADO")
    if not rep:
        motivos.append("no se pudo leer el repo")
    else:
        if rep.get("archived"):
            motivos.append("repo archivado")
        creado = (rep.get("created_at") or "")[:10]
        estrellas = rep.get("stargazers_count") or 0
        if creado >= (datetime.date.today() - datetime.timedelta(days=90)).isoformat() and estrellas < 5:
            motivos.append("repo nuevo sin estrellas (posible granja)")
        if (rep.get("pushed_at") or "")[:10] < (datetime.date.today() - datetime.timedelta(days=365)).isoformat():
            # OJO (corregido el 11-oct tras revisar la salida): un repo sin código nuevo hace un año
            # puede tener el issue VIVO. No se descarta por eso solo: se avisa.
            upd = ((it or {}).get("updated_at") or "")[:10]
            if upd and upd < (datetime.date.today() - datetime.timedelta(days=365)).isoformat():
                motivos.append("repo e issue sin actividad hace +1 año")
            else:
                c["aviso_actividad"] = "el repo no recibe código nuevo hace +1 año (el issue sigue vivo)"
    if PATRONES_BOT.search(c["repo"]) or PATRONES_BOT.search(c["titulo"] or ""):
        motivos.append("pinta de granja de bots")
    if "Bounty Alert" in (c["titulo"] or "") or "🎯" in (c["titulo"] or ""):
        motivos.append("aviso automático de bots, no trabajo real")
    if f"{owner}/{repo}".lower() in REPOS_MUERTOS:
        motivos.append("plataforma que ya no paga: " + REPOS_MUERTOS[f"{owner}/{repo}".lower()])

    # política anti-IA del repo (sólo si el resto viene limpio: gasta llamadas)
    ia = "sin dato"
    if not motivos:
        for f in ARCHIVOS_POLITICA:
            txt = http_text(f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{f}")
            if txt and PATRONES_IA_PROHIBIDA.search(txt):
                ia = f"PROHÍBE IA ({f})"
                motivos.append(f"el repo prohíbe contribuciones con IA ({f})")
                break
            if txt:
                ia = f"revisado {f}: no prohíbe"
                break

    # rivales reales: PR que ya reclaman ese issue (medido en la línea de tiempo del issue)
    if not motivos and it:
        tl = gh_api(f"repos/{owner}/{repo}/issues/{num}/timeline?per_page=100")
        if isinstance(tl, list):
            prs = set()
            for ev in tl:
                src = (ev.get("source") or {}).get("issue") or {}
                if ev.get("event") == "cross-referenced" and src.get("pull_request"):
                    prs.add(src.get("number"))
            c["prs_abiertos"] = len(prs)
            c["rivales"] = len(prs)
    if c.get("rivales") is None:
        c["rivales"] = 0

    c["motivos"] = motivos
    c["anti_ia"] = ia
    c["estrellas"] = (rep or {}).get("stargazers_count")
    c["lenguaje"] = ((rep or {}).get("language") or "-")
    c["actualizado_repo"] = ((rep or {}).get("pushed_at") or "")[:10]
    c["comentarios"] = (it or {}).get("comments", c.get("comentarios"))
    c["puntaje"] = 0 if motivos else round((c["monto_usd"] or 0) / (1 + min(c["rivales"] or 0, 20)), 2)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    print("=" * 78)
    print(f"RADAR DE RECOMPENSAS — {datetime.datetime.now():%d-%b-%Y %H:%M} (-03)")
    print("=" * 78)

    print("\n[1/3] Leyendo las fuentes...")
    cand = de_opire()
    print(f"      Opire:  {len(cand)} recompensas listadas")
    g = de_github()
    print(f"      GitHub: {len(g)} issues candidatos de {len(BUSQUEDAS)} búsquedas")
    vistos, todos = set(), []
    for c in cand + g:
        if c["url"] in vistos:
            continue
        vistos.add(c["url"])
        todos.append(c)
    print(f"      candidatos únicos: {len(todos)}")

    # los que traen monto primero (más probable que valgan la pena), y como máximo --top
    todos.sort(key=lambda x: -(x.get("monto_usd") or 0))
    a_revisar = todos[: max(args.top, 10)]
    print(f"\n[2/3] Revisando estado real de los {len(a_revisar)} mejores (issue + repo + política de IA)...")
    for i, c in enumerate(a_revisar, 1):
        revisar(c)
        print(f"      {i}/{len(a_revisar)} {c['owner']}/{c['repo']}#{c['num']} "
              f"-> {'SIRVE' if not c['motivos'] else 'descartado: ' + c['motivos'][0]}")

    sirven = [c for c in a_revisar if not c["motivos"]]
    sirven.sort(key=lambda x: -x["puntaje"])
    descartados = [c for c in a_revisar if c["motivos"]]

    print(f"\n[3/3] RESULTADO: {len(sirven)} vale(n) la pena de {len(a_revisar)} revisados\n")
    if sirven:
        print(f"  {'monto':>8}  {'rivales':>7}  {'repo':<38} {'leng':<10} anti-IA")
        print("  " + "-" * 84)
        for c in sirven:
            print(f"  {('USD %.0f' % c['monto_usd']) if c['monto_usd'] else '    ?':>8}  "
                  f"{c['rivales'] or 0:>7}  {(c['owner']+'/'+c['repo'])[:37]:<38} "
                  f"{c['lenguaje'][:9]:<10} {c['anti_ia']}")
            print(f"           {c['titulo'][:88]}")
            print(f"           {c['url']}   (comentarios: {c['comentarios']}, repo actualizado: {c['actualizado_repo']})")
    else:
        print("  (ninguna recompensa pasó el filtro hoy: eso también es un dato)")

    informe = os.path.join(SALIDA, f"informe_bounties_{HOY}.md")
    with open(informe, "w") as f:
        f.write(f"# Radar de recompensas — {HOY}\n\n")
        f.write(f"Revisados {len(a_revisar)} · **sirven {len(sirven)}** · descartados {len(descartados)}\n\n")
        f.write("## Vale la pena\n\n")
        for c in sirven:
            f.write(f"- **USD {c['monto_usd'] or '?'}** — [{c['owner']}/{c['repo']}#{c['num']}]({c['url']}) · "
                    f"rivales: {c['rivales'] or 0} · {c['lenguaje']} · {c['anti_ia']}\n  {c['titulo'][:120]}\n")
        f.write("\n## Descartados (y por qué)\n\n")
        for c in sorted(descartados, key=lambda x: x["motivos"][0]):
            f.write(f"- {c['owner']}/{c['repo']}#{c['num']} — {', '.join(c['motivos'])} · {c['url']}\n")
    with open(os.path.join(SALIDA, f"radar_{HOY}.json"), "w") as f:
        json.dump(a_revisar, f, indent=1, ensure_ascii=False)
    print(f"\n  informe escrito en: {informe}")
    print("  (nada se modificó: esto es sólo lectura)")


if __name__ == "__main__":
    main()
