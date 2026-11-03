#!/usr/bin/env python3
"""Compare three translation models on the SAME existing English episode dialogue.

Hy-MT2: Tencent's documented Default Translation prompt + recommended settings.
CAT 7B: CyberAgent's documented English->Japanese prompt, no added settings.
Two 30-cue continuous passages, no timestamps and no subtitle formatting prompt.
Print and save untouched model replies. NO translation pipeline or publication.
"""
import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

SOURCE = Path("/tmp/subhub-hy-mt2-full-chair-test/original.en.srt")
FAILED = Path("/tmp/subhub-hy-mt2-full-chair-test/part-0005.raw.txt")
MODELS = {
    "hy7": "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
    "hy18": "hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M",
    "cat7": "hf.co/mmnga-o/CAT-Translate-7b-gguf:Q4_K_M",
}
HY_OPTIONS = {
    "temperature": 0.7,
    "top_p": 0.6,
    "top_k": 20,
    "repeat_penalty": 1.05,
    "num_predict": 4096,
}
URL = "http://172.17.0.1:11434"  # Confirmed from the working container's Sublarr configuration.


def get(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def post(url, payload, timeout=1800):
    request = urllib.request.Request(
        url, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"HTTP {error.code}: {error.read().decode(errors='replace')[:500]}"
        ) from error


def cues_from_srt():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"English subtitle source missing: {SOURCE}")
    text = SOURCE.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    blocks = re.split(r"\n[ \t]*\n", text.strip())
    cues = []
    for block in blocks:
        match = re.fullmatch(
            r"(\d+)\n(\d\d:\d\d:\d\d,\d{3} --> [^\n]+)\n(.+)",
            block.strip(),
            flags=re.DOTALL,
        )
        if not match:
            raise ValueError(f"Cannot parse subtitle: {block[:75]!r}")
        cues.append({"id": int(match.group(1)), "time": match.group(2),
                     "en": match.group(3)})
    return cues


def inspect_failed_part(cues):
    print("\n=== PREVIOUS 7B SRT FAILURE (PRESERVED) ===", flush=True)
    if not FAILED.is_file():
        print("No failed raw output available", flush=True)
        return
    raw = FAILED.read_text(encoding="utf-8", errors="replace")
    ids = [int(n) for n in re.findall(r"(?m)^(\d+)$", raw)]
    expected = [c["id"] for c in cues[120:150]]
    missing = sorted(set(expected) - set(ids))
    extra = sorted(set(ids) - set(expected))
    print(f"Expected IDs: {expected[0]}..{expected[-1]}; found {len(ids)}")
    print(f"Missing IDs: {missing}; unexpected IDs: {extra}", flush=True)
    if missing:
        for number in missing:
            nearby = next((i for i,c in enumerate(cues) if c["id"]==number), None)
            if nearby is not None:
                print(f"Missing #{number}: {cues[nearby]['en'][:160]}", flush=True)
    print("This is a formatting diagnostic, not a Japanese quality grade.\n", flush=True)


def passage(cues, offset):
    sample = cues[offset:offset + 30]
    if len(sample) != 30:
        raise ValueError("Need 30 consecutive cues")
    return "\n\n".join(c["en"] for c in sample)


def prompt(name, english):
    if name.startswith("hy"):
        return (
            "Translate the following text into Japanese. Note that you should "
            "only output the translated result without any additional explanation:\n"
            + english
        )
    return "Translate the following English text into Japanese.\n\n" + english


def ensure_model(tag):
    installed = {m.get("name") or m.get("model")
                 for m in get(URL + "/api/tags").get("models", [])}
    if tag in installed:
        print("Already installed:", tag, flush=True)
        return
    print("Downloading:", tag, flush=True)
    request = urllib.request.Request(
        URL + "/api/pull", method="POST",
        data=json.dumps({"model": tag, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    last_decile = -1
    with urllib.request.urlopen(request, timeout=3600) as response:
        for line in response:
            state = json.loads(line)
            if "error" in state:
                raise RuntimeError(state["error"])
            if state.get("total"):
                decile = int(10 * state.get("completed", 0) / state["total"])
                if decile > last_decile:
                    print(f"  Download {decile * 10}%", flush=True)
                    last_decile = decile
            elif state.get("status") == "success":
                print("  Model installed", flush=True)


def run(model_name, english):
    request = {
        "model": MODELS[model_name], "stream": False,
        "messages": [{"role": "user", "content": prompt(model_name, english)}],
    }
    if model_name.startswith("hy"):
        request["options"] = HY_OPTIONS
    start = time.monotonic()
    response = post(URL + "/api/chat", request)
    seconds = round(time.monotonic() - start, 1)
    answer = (response.get("message") or {}).get("content", "")
    if not answer:
        raise RuntimeError(f"Empty answer; finish: {response.get('done_reason')}")
    eval_seconds = (response.get("eval_duration") or 0) / 1e9
    return {
        "answer": answer, "seconds": seconds,
        "tokens_per_second": round(response.get("eval_count", 0) / eval_seconds, 2)
        if eval_seconds else None,
        "done_reason": response.get("done_reason"),
        "model": MODELS[model_name], "prompt": request["messages"][0]["content"],
        "options": request.get("options", "Embedded Ollama defaults"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=tuple(MODELS),
                        default=["hy18", "cat7", "hy7"])
    args = parser.parse_args()
    cues = cues_from_srt()
    inspect_failed_part(cues)
    samples = {
        "opening_cues_1_30": passage(cues, 0),
        "failed_region_cues_121_150": passage(cues, 120),
    }
    folder = Path("/tmp/subhub-clean-model-merit-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    folder.mkdir()
    results = {
        "english_source": str(SOURCE),
        "samples": samples, "responses": {}, "errors": {},
        "note": "Pure text translation, not SRT structure. Rate actual Japanese and omissions by a human.",
    }
    print("Comparing the SAME two 30-cue passages using each developer's own prompt.")
    print("Results:", folder, flush=True)
    try:
        for name in args.models:
            try:
                ensure_model(MODELS[name])
                for label, english in samples.items():
                    print(f"\n=== {name} / {label} ===", flush=True)
                    record = run(name, english)
                    results["responses"][f"{name}:{label}"] = record
                    print(record["answer"], flush=True)
                    print(f"\nFinished: {record['done_reason']}; elapsed {record['seconds']}s",
                          f"; generation {record['tokens_per_second']} tokens/s", flush=True)
            except Exception as exc:
                results["errors"][name] = str(exc)
                print(f"FAILED {name}: {exc}", flush=True)
            finally:
                (folder / "raw_results.json").write_text(
                    json.dumps(results, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
    finally:
        (folder / "raw_results.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("\nSaved all raw responses:", folder / "raw_results.json", flush=True)
        print("Nothing was translated into published SRT files.", flush=True)


if __name__ == "__main__":
    main()
