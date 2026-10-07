"""Banc d'essai des modèles Ollama sur bench/commands.json (stdlib uniquement).

Usage : python -m bench.run_bench qwen3:8b [ministral-3:8b ...] [--think]
Ne télécharge jamais de modèle : s'arrête si Ollama ou le modèle est absent.
"""
import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434"
COMMANDS = Path(__file__).with_name("commands.json")
OPTIONS = {"temperature": 0, "num_ctx": 4096}


def load(path=COMMANDS):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    names = {t["name"] for t in data["tools"]}
    for cmd in data["commands"]:
        for alt in cmd["expect"]:
            for call in alt:
                if call["tool"] not in names:
                    raise ValueError(f"commande {cmd['id']} : outil inconnu {call['tool']}")
    return data


def ollama_tools(tools):
    """Format compact de commands.json -> format tool calling d'Ollama."""
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": {"type": "object", "properties": t["params"], "required": t.get("required", [])},
    }} for t in tools]


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return text.lower()


def arg_ok(expected, actual):
    """Texte : sous-chaîne sans casse ni accents. Autres types : égalité stricte (True n'est pas 1)."""
    if isinstance(expected, str):
        return isinstance(actual, str) and _norm(expected) in _norm(actual)
    return type(expected) is type(actual) and expected == actual


def call_ok(expected, actual):
    return expected["tool"] == actual["tool"] and all(
        k in actual["args"] and arg_ok(v, actual["args"][k]) for k, v in expected["args"].items())


def score(expect, calls):
    """(bon outil, bons paramètres) : une alternative attendue doit couvrir exactement les outils appelés."""
    names = {c["tool"] for c in calls}
    tool = args = False
    for alt in expect:
        if {c["tool"] for c in alt} == names:
            tool = True
            args = args or all(any(call_ok(e, c) for c in calls) for e in alt)
    return tool, args


def parse_stream(lines, start):
    """Lit le flux NDJSON d'/api/chat -> (texte, appels, ttft_s, stats finales)."""
    text, calls, ttft, last = "", [], None, {}
    for line in lines:
        if not line.strip():
            continue
        chunk = json.loads(line)
        if "error" in chunk:
            raise RuntimeError(chunk["error"])
        msg = chunk.get("message", {})
        if ttft is None and (msg.get("content") or msg.get("tool_calls")):
            ttft = time.perf_counter() - start
        text += msg.get("content", "")
        for tc in msg.get("tool_calls", []):
            fn = tc["function"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_invalide": args}
            calls.append({"tool": fn["name"], "args": args if isinstance(args, dict) else {}})
        last = chunk
    return text, calls, ttft, last


def summarize(results):
    n = len(results) or 1
    lat = sorted(r["total_s"] for r in results)
    ttft = sorted(r["ttft_s"] for r in results if r["ttft_s"] is not None)
    return {
        "outil_pct": round(100 * sum(r["tool"] for r in results) / n),
        "params_pct": round(100 * sum(r["args"] for r in results) / n),
        "ttft_median_s": round(ttft[len(ttft) // 2], 2) if ttft else None,
        "total_median_s": round(lat[len(lat) // 2], 2) if lat else None,
        "total_max_s": round(lat[-1], 2) if lat else None,
    }


def _get(path):
    with urllib.request.urlopen(OLLAMA + path, timeout=5) as r:
        return json.load(r)


def _chat(model, data, text, think):
    body = {
        "model": model, "stream": True, "think": think, "options": OPTIONS, "keep_alive": "10m",
        "tools": ollama_tools(data["tools"]),
        "messages": [{"role": "system", "content": data["system"]}, {"role": "user", "content": text}],
    }
    req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        out = parse_stream((line.decode("utf-8") for line in r), start)
    return (*out, time.perf_counter() - start)


def bench(model, data, think):
    print(f"\n== {model} (réflexion {'activée' if think else 'désactivée'})")
    *_, last, load_s = _chat(model, data, "Bonjour", think)  # chargement, hors mesures
    print(f"chargement : {load_s:.1f} s")
    vram = next((m.get("size_vram") for m in _get("/api/ps").get("models", []) if m["name"] == model), None)
    results = []
    for cmd in data["commands"]:
        text, calls, ttft, _, total = _chat(model, data, cmd["text"], think)
        tool, args = score(cmd["expect"], calls)
        results.append({"id": cmd["id"], "tool": tool, "args": args, "ttft_s": ttft, "total_s": total})
        mark = "OK " if tool and args else ("~  " if tool else "KO ")
        got = ", ".join(f"{c['tool']}{c['args']}" for c in calls) or f"(texte) {text[:60]!r}"
        print(f"{mark}{cmd['id']:>2} [{cmd['cat']}] {total:5.2f} s  {cmd['text'][:45]!r} -> {got}")
    s = summarize(results)
    s["vram_go"] = round(vram / 1e9, 1) if vram else None
    print(f"| {model} | {s['outil_pct']} % | {s['params_pct']} % | {s['ttft_median_s']} s | "
          f"{s['total_median_s']} s | {s['total_max_s']} s | {s['vram_go']} Go |")
    return s


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console Windows cp1252 : emojis des réponses
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("models", nargs="+")
    p.add_argument("--think", action="store_true", help="active le mode réflexion")
    a = p.parse_args(argv)
    data = load()
    try:
        installed = {m["name"] for m in _get("/api/tags").get("models", [])}
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"Ollama injoignable sur {OLLAMA} ({e}). Lancez Ollama puis réessayez.")
    models = [m if ":" in m else m + ":latest" for m in a.models]
    missing = [m for m in models if m not in installed]
    if missing:
        sys.exit(f"Modèle(s) absent(s) : {', '.join(missing)}. Téléchargement manuel requis "
                 f"(ollama pull), jamais automatique. Installés : {', '.join(sorted(installed)) or 'aucun'}.")
    try:
        for m in models:
            bench(m, data, a.think)
    except (urllib.error.URLError, RuntimeError) as e:
        sys.exit(f"Erreur Ollama : {e}")


if __name__ == "__main__":
    main()
