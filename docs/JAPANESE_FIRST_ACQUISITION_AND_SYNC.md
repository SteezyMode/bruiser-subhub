# SubHub v2 — Japanese-first acquisition and intro-offset safety

## November 5 — CONFIRMED first full scratch acquisition + timing preview on real host

**Owner-run success.** Running Sublarr **1.18.0** on OptiPlex, source `American.Dad.S22E02.720p.x264-FENiX.mkv` (Wanted **#418**, Japanese/full profile), native **OpenSubtitles**, candidate uploader `ichi131`, source release `American.Dad!.S22E02`, match score **240**, non-forced, provider `machine_translated=false` and `mt_confidence=0` (these flags do **not** prove human linguistic quality).

**Observed real download:** **31,365 bytes**, **SRT** (the provider's pre-download format was `unknown`, and a previous dry-run proposed an `.ass` output; detect actual downloaded bytes rather than trusting prediction), **478 parsed subtitle cues**, **477 containing Japanese script**. Actual video `ffprobe` duration **1,299.36 seconds** (21m 39.36s). This is structurally plausible coverage, not an independent translation rating.

**Observed non-destructive synchronization:** Sublarr's installed `ffsubsync` preview returned **`status=ok, shift_ms=50`** (50 milliseconds = 0.05 seconds). On this particular subtitle, **there is no evidence of a meaningful several-second timing mismatch**, so no correction should be applied merely for 50 ms. Need to independently test an already-known seconds-off candidate before claiming automatic timing repair is robust. Sync compare's success, like a source score, does NOT prove the spoken words and Japanese cues refer to the same dialogue.

**Storage/output:** the scratch tool wrote `/tmp/bruiser-ja-418-review.tar.gz` inside the Sublarr container (contains raw downloaded subtitle plus private `report.json`), and the owner's SSH command successfully copied this to the host then the Mac mini's `~/Downloads/bruiser-ja-418-review.tar.gz`. No subtitles or videos were published/overwritten; no settings, automatic scans, translation queues or model configurations changed. The scratch downloader and separate credential-read fix worked, without exposing secrets.

**Current gate:** owner must provide the private archive for actual Japanese cue review and source quality determination; uploader's non-AI flag is only a reported metadata signal. Until such review, do **not** call this a high-quality Japanese source or promote it to the media library. For timing, the next useful pilot is a **known seconds-off subtitle** from their library (not another micro-adjustment of this 50ms example). Existing curated Japanese sidecars remain protected.

**Decision update:** provider credential setup is complete for native OpenSubtitles; do not re-diagnose it as missing. This successfully proves one independent third-party JP subtitle acquisition and one non-destructive sync preview on the actual OptiPlex, but **does not** yet establish library-wide availability, semantic fidelity or the ability to repair complicated timing drift.

## November 5 — Scratch-download failure diagnosed and corrected (owner-run)

The owner's first exact-item scratch inspection found **5 candidates**, **1 Japanese native OpenSubtitles** result. Reported `filename=American.Dad.S22E02.ja`, `release_info=American.Dad!.S22E02`, `score=240`, `forced=false`, `machine_translated=false`, `mt_confidence=0`, uploader `ichi131`. No subtitles were downloaded or synced.

The helper crashed with `/app/providers/opensubtitles.py:455: ProviderError("OpenSubtitles not initialized")`. The subsequent `docker cp` and `scp` failures simply reflected the missing scratch archive. **This was a helper defect, not an unhealthy live provider.**

**Root cause verified against the EXACT upstream [Sublarr v1.18.0 source](https://github.com/Abrechen2/sublarr/tree/v1.18.0):** `config_singleton.get_settings()` in a NEW `docker exec python3` process only creates boot/default UI settings. The **real** Flask `app.create_app()` loads saved UI overrides from DB `config_entries` through `reload_settings()` on startup (app.py ~589), including OpenSubtitles credentials. The initial helper incorrectly constructed a new `OpenSubtitlesProvider(api_key=get_settings().opensubtitles_api_key)` before applying the existing DB override. The key was absent there, so `initialize()` silently returned without a session. Do **not** change the live API key or install a second Sublarr.

**Fix:** [tools/sublarr_ja_418_scratch_inspect.py](../tools/sublarr_ja_418_scratch_inspect.py) now reads the existing `config_entries` rows in **SQLite mode=ro, PRAGMA query_only=ON**, and decrypts any `enc:v1` stored credential using **only an already-existing** `/config/.encryption_key` (never generating a new key). It supplies API key + optional login credentials to a privately initialized provider, and refuses to proceed if a credential is unavailable. It never prints, uploads, or stores credentials in the private subtitle archive. No Flask `create_app()` invocation, DB migrations, provider setting writes or media changes. This path currently requires the configured Sublarr DB to be SQLite; a Postgres configuration holds rather than making an unsafe assumption.

Offline tests include plaintext DB settings, read-only persistence, missing credentials, and wrong DB backend. Encrypted test cases run where the Sublarr `cryptography` dependency is available; GitHub's lightweight CI skips those optional cases. Main GitHub CI passed at **`11dc353794c9416dd5b7106c687d1aa735425dcd`**. A successful host download/ffsubsync result remains UNVERIFIED until the owner reruns.

**Corrected host inspection:** use the same command under this record's prior section with this updated code URL:
`https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/11dc353794c9416dd5b7106c687d1aa735425dcd/tools/sublarr_ja_418_scratch_inspect.py`
The downloader consumes one provider download and a candidate search; only the private `/tmp/bruiser-ja-418-review.tar.gz` is written. Preserve all existing video and JA sidecars.

## November 5 — Actual OpenSubtitles candidate found (owner-run result)

The corrected real-host one-item dry-run selected **Wanted #418**, `American.Dad.S22E02.720p.x264-FENiX.mkv`, and returned **`status=found`**, native **`opensubtitles`**, **score 240**, reported **Japanese ASS**, and proposed `American.Dad.S22E02.720p.x264-FENiX.ja.ass`. This is a **real search match**, not a downloaded or independently quality-verified subtitle. Actual Japanese dialogue, provenance and timing are still unexamined. No file was saved and the Wanted status was restored.

Next experiment: [tools/sublarr_ja_418_scratch_inspect.py](../tools/sublarr_ja_418_scratch_inspect.py) rechecks the exact Wanted identity and provider gate, searches that item for exact Japanese OpenSubtitles full-dialogue candidates, and downloads **one** into private `/tmp` inside the Sublarr container through the native provider's `download()`—**NOT** through the `download-specific` publishing route. Uses the actual downloaded file format, reports parsed cue counts, visible Japanese script, time span and provider machine-translation provenance; when plausible, calls Sublarr's existing `services.sync_preview.sync_compare()` to propose an `ffsubsync` offset against the actual local video, **without applying it**. It stores the raw candidate and summarized report in a private archive for human/contextual quality review. This consumes provider search and download quota, and the interactive search endpoint updates the item's search metadata. It does not mutate media files, original JA or model settings, run translations, enable scanners, or apply sync.

Host command on Mac mini:

```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
curl -fsSL --retry 3 \
'https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/11dc353794c9416dd5b7106c687d1aa735425dcd/tools/sublarr_ja_418_scratch_inspect.py' |
 docker exec -i -e PYTHONPATH=/app sublarr-pilot python3 -
mkdir -p "$HOME/bruiser-pilot/japanese-source-review"
docker cp sublarr-pilot:/tmp/bruiser-ja-418-review.tar.gz \
 "$HOME/bruiser-pilot/japanese-source-review/bruiser-ja-418-review.tar.gz"
REMOTE
scp optiplex@100.121.156.34:~/bruiser-pilot/japanese-source-review/bruiser-ja-418-review.tar.gz \
 ~/Downloads/
```

**Only after the private candidate archive is reviewed** should the owner decide whether to publish a separately named JA sidecar; do not treat score 240, Japanese script ratio or successful sync estimate as proof of 8/10 localization. A shift measured within the 45-second sanity ceiling can still be wrong. If OpenSubtitles refuses a download (key/JWT/quota), report the actual error and do not bypass credentials or increase quotas.

## November 5 — Probe fix: actual Wanted API schema

First real owner run returned `WANTED_EXAMINED 0` because the initial helper incorrectly read `response["items"]` while Sublarr 1.18 returns the list in **`response["data"]`** (verified in upstream `backend/db/repositories/wanted.py` and `backend/routes/wanted/list.py`). The prior, independent read-only diagnostic had seen **407 total Wanted records** and an OpenSubtitles `gate=ok`. No provider was queried by that failed probe.

**Fixed:** [tools/sublarr_japanese_dryrun_pilot.py](../tools/sublarr_japanese_dryrun_pilot.py) now reads `data`, prints the filtered Wanted count, fails loudly on an unexpected response format, and preserves the original 1-item provider search limits. Regression tests reproduce the original mismatch; GitHub CI passed at commit `16a41cd153f432df574a0070166cd5621bca7661`. The corrected one-command pin is directly below. No production containers/DB/configuration/models changed by the GitHub fix.

## November 5 — One-title real Japanese provider search preview (tested, no subtitle download)

After the owner ran the read-only readiness check, native OpenSubtitles was **enabled, initialized, healthy, and `gate=ok`**; `ffsubsync` and `ffmpeg` were installed, `alass` was absent, two American Dad standalone roots were enabled, and four Movies/TV roots were still disabled. **407 Wanted entries** were visible. Auto-translation, auto-sync-after-download, and upgrades remained off. Do not repeat the previous missing-native-credential diagnosis or change providers blindly.

Use [tools/sublarr_japanese_dryrun_pilot.py](../tools/sublarr_japanese_dryrun_pilot.py) inside the live container to select **exactly one** existing `wanted` Japanese full-dialogue video under `/media/`, skipping matching external Japanese sidecars and unsafe/missing paths, and then call official `POST /api/v1/wanted/dry-run` with its single ID. It **queries real providers and consumes search quota**, but does **not download a subtitle or write a sidecar**. Sublarr may briefly change the Wanted row status to `searching` while processing, then restores the original status; don't describe it as strictly DB-read-only. Do NOT use `Process` or `Batch Search` until one result has been inspected.

One command on Mac mini:

```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
curl -fsSL --retry 3 \
 'https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/16a41cd153f432df574a0070166cd5621bca7661/tools/sublarr_japanese_dryrun_pilot.py' |
  docker exec -i -e PYTHONPATH=/app sublarr-pilot python3 -
REMOTE
```

Expected report: `NATIVE_OPENSUBTITLES gate=ok`, one `SELECTED` item, then `PROVIDER_DRY_RUN` status. `found` means an **eligible result exists**, not that its Japanese language/provenance, human quality, or sync is verified. `not_found` means the search returned nothing that cleared the scoring bar **for that one title**; `skipped` may mean a stale Wanted item or gating. Treat a failed provider attempt as diagnostic, not a reason to bulk reset limits or enable all roots. Prefer reviewing candidate provenance and a scratch download for a successful first title, then non-destructive **Sync Compare** on a verified existing JA file whose offset is known wrong.

Code is offline safety-tested with fixed request count, JA/full filtering, sidecar exclusions and no-auto-translation preconditions; no real provider result is claimed until the owner runs the command.

## November 5 — First actual troubleshooting step (NO WRITE)

The next host action is **not a new translator or another install**. Run the existing targeted read-only preflight [tools/japanese_first_readiness.py](../tools/japanese_first_readiness.py) inside the **running** \`sublarr-pilot\` container. It checks provider search gates (including \`no_pool_key\`), native OpenSubtitles/SubDL/Jimaku presence, language profiles, enabled standalone mounts, local ffsubsync/ffmpeg binaries, \`GET /api/v1/sync/engines\`, and selected automation flags. It never starts a scan, provider request, download, sync operation or translation.

From a computer with SSH to the OptiPlex:

\`\`\`bash
ssh YOUR_OPTIPLEX_HOST 'bash -s' <<'REMOTE'
set -euo pipefail
echo "=== SUBLARR INSTANCE ==="
docker inspect -f 'State={{.State.Status}} Image={{.Config.Image}}' sublarr-pilot
docker port sublarr-pilot 5765/tcp || true
curl -fsSL --retry 3 \
  'https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/a16a5939465436900a390dcdbf3476311bb1f161/tools/japanese_first_readiness.py' |
  docker exec -i -e PYTHONPATH=/app sublarr-pilot python3 -
REMOTE
\`\`\`

**Interpret before any writes:** an enabled provider with no key/no pool is NOT working; a real test/download is needed. If a folder is disabled, leave it disabled until verifying container path exists and the target Japanese profile is correct. Never enable global automatic translation or automatic subtitle upgrades as an incidental setup step.

**Next tested workflow when readiness passes:** configure **native** OpenSubtitles in Sublarr Settings → Providers using the legitimate REST API key from the user's OpenSubtitles account; optionally add SubDL via its own key. Search **one real missing-JA episode** from Wanted, not Search All. For a known out-of-sync Japanese sidecar, use the **Sync Compare** menu for that subtitle to preview the measured offset without changing the file. Review early, middle and late cues; only Apply after verifying the result and backup/sidecar protection. Keep originals and user-curated JA unmodified in the pilot.

Official UI references: https://sublarr.de/docs/user-guide/settings/providers/ and https://sublarr.de/docs/user-guide/sync-compare/ . 
See [November 5 broader source/sync-quality research](JAPANESE_FIRST_SOURCE_SYNC_QUALITY_RESEARCH_2026-11-05.md).

## Observations (November 4, 2026)

- Japanese profile already exists; the four main movie/TV folders are registered but scanning-disabled.
- Two Subliminal OpenSubtitles adapters are initialized/healthy. Native OpenSubtitles, SubDL, and Jimaku are not initialized.
- Provider-test catalog searches returned abundant weak or unrelated records, and a promising but unverified `Its.Always.Sunny.in.Philadelphia.S01E01.WEB-DL.DSNP.ja.srt` label.
- The production `POST /api/v1/providers/search` returned one `subf2m` Smile 2 result (title match only, score 60), and no Sunny S01E01 results. That route creates a sparse `VideoQuery` that does not fill year, release metadata or file hash. It is not a reliable exact-file matching benchmark.

## Policy: source, quality and timing are separate gates

1. Verify correct film/year or series/season/episode and prefer strongly matched releases. A score or matching title is not proof of a human-quality Japanese translation.
2. Evaluate provenance and completeness. Forced/signs-only tracks do not replace full dialogue. Keep existing Japanese and English subtitle files intact.
3. For this household library, a few TV rips have a leading station intro, but **no known in-episode commercial breaks**. Focus on **constant-offset** synchronization first; do not construct a complex ad-break or multi-cut correction engine.
4. Use an actual-local-video audio/speech alignment tool (e.g. `ffsubsync`) to propose a constant offset. Check the resulting alignment at early, middle and late points. Only apply a highly confident correction; never guess a 15-second or 30-second standard intro length.
5. If a candidate is still mistimed or uncertain, hold rather than publish. Keep a verified English source timed to the actual file as authority for Hy-MT2 fallback; that translation must preserve cue IDs/timestamps.
6. Do **create-only** publication. No upgrading/replacing existing Japanese subtitles and no unattended library-wide searches until a narrow pilot works.

## Diagnostic

`tools/japanese_first_candidate_probe.py` runs inside sublarr-pilot and directly checks the two OpenSubtitles adapters, using a richer Smile 2 release query and separate Sunny S01E01 metadata-only query. It performs no downloads, file writes or configuration changes. It may spend provider-search quota. Hash usage is reported if supported; the probe does not claim a hash match unless the adapter provides that evidence.

The intended next stage is an isolated scratch-download comparison of one or two credible candidates, with constant-offset synchronization proposals and manual content spot checks before any automated acceptance logic is enabled.

## Proven provider gate root cause and preferred setup (2026-11-04)

The actual running Sublarr \`/api/v1/providers/health\` reports both
\`opensubtitlescom_subliminal\` and \`opensubtitles_subliminal\` as
initialized/healthy **but blocked with \`no_pool_key\`**. The native
\`opensubtitles\`, \`subdl\`, and \`jimaku\` providers are not initialized.
\`subf2m\` has gate \`ok\` but scored only a Smile 2 title-only match.

A read-only check of \`config_entries\` and the alternate adapter's pool
reported no stored OpenSubtitles key, username, password, or pool rows. No
credentials were created and no settings were modified.

### Native provider is the recommended route

- Use Sublarr's **native** \`opensubtitles\` provider, not the two
  Subliminal wrappers, for the first real production acquisition pilot.
- Its implementation (Sublarr 1.18.0,
  \`backend/providers/opensubtitles.py\`) requires **only**
  \`opensubtitles_api_key\` to initialize. Username/password are optional.
- The production budget gate explicitly allows a provider with no pool rows
  when its required credential is present in the active Settings object
  (\`_provider_credentials_configured\`). Thus, saving a genuine API key
  through Sublarr Settings -> Providers / API Keys should be enough for
  normal searches; **no fake pool row is needed**.
- A personal OpenSubtitles developer API key generally requires an
  OpenSubtitles.com account to issue it. This is one optional third-party
  account, not a demand for separate accounts for the underlying libraries.
- The existing \`subhub_v2_pool_repair.py\` is only a cautious helper for the
  **alternate** \`opensubtitlescom_subliminal\` adapter, which requires
  API key, username, and password. Do not use it as the normal onboarding
  route or interpret its three missing fields as requirements for native.
- Keep \`provider_budget_enabled=True\`, scan scheduling off,
  \`wanted_auto_translate=False\`, and publication create-only.
  Consider disabling subtitle upgrades before any automatic operation.

### Accountless evaluation only

OpenSubtitles currently documents limited anonymous REST downloads (a
client application still needs a valid application API key). A third-party
CLI, \`opensubs-cli\`, embeds its own app key and offers approximately
five unauthenticated downloads, but this would add another runtime tool and
is **not** approved as a production SubHub dependency. Use only as an
isolated scratch pilot if needed; never install it over the working host
stack or let it write next to source media. Do not circumvent provider quotas.

Next verification once the native API key is saved: health gate must be
\`ok\`; search the exact Smile 2 video and a real Sunny video through
Sublarr's own enriched Wanted query builder, then fetch at most one
reasonable JA candidate into isolated scratch storage for provenance,
coverage and constant-offset sync review. Nothing should auto-publish.
