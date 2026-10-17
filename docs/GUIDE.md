# durtleshells — Implementation Guide

A terminal WaniKani client that feels like Smouldering Durtles. Typing
`durtleshells` opens a full-screen, Vim-style terminal UI. Kana can be typed
as romaji or entered on an emulated phone flick keyboard using real mouse drag.

This guide is the build plan. Each step lists what to build, the decisions
already made, and the acceptance criteria that must pass before moving on.

---

## 0. Agreed decisions

| Topic | Decision |
|---|---|
| Entry point | One command, `durtleshells`, which opens a full-screen terminal UI. No subcommands. |
| Stack | Python ≥ 3.11, Textual (UI), httpx (HTTP), SQLite (cache and offline queue). |
| Interaction model | Vim-like and modal: NORMAL / INSERT modes, single-key actions, a `:` command line and a status line. |
| Kana input | Romaji→kana conversion **and** the flick keyboard are active at the same time. `:set flick` only shows or hides the grid. |
| Flick mechanic | Real mouse drag: press on a key, drag in a direction, release to commit. |
| Features | Lessons, reviews (meaning and reading back to back), ignore answer, wrap-up, close-match tolerance, offline mode, ordering options. |
| Out of scope | Self-study, leech training, audio, context sentences. |
| Token | Prompted on first launch and stored in `~/.config/durtleshells/config.toml`. `WANIKANI_API_TOKEN` overrides it. |
| Data | `~/.local/share/durtleshells/durtleshells.db` (SQLite). |
| Offline | Full local cache of subjects and assignments. All submissions go through a local queue, sent with the original `created_at`. Stale entries are dropped and the user is notified. |
| Platform | Linux only. Primary test terminal: **Konsole** (Garuda Linux). |

---

## 1. Architecture

```
durtleshells/
├── pyproject.toml
├── docs/GUIDE.md
├── src/durtleshells/
│   ├── __main__.py          # main(): config bootstrap → App.run()
│   ├── config.py            # TOML config, token resolution, settings schema
│   ├── paths.py             # XDG paths via platformdirs
│   ├── api/
│   │   ├── client.py        # async WaniKani v2 client (httpx)
│   │   └── models.py        # dataclasses: Subject, Assignment, StudyMaterial, User
│   ├── store/
│   │   ├── db.py            # SQLite schema + migrations
│   │   ├── repo.py          # typed queries (available reviews, lessons, forecast…)
│   │   └── sync.py          # incremental sync + outbound queue flushing
│   ├── domain/
│   │   ├── kana.py          # romaji→kana converter (IME-style, incremental)
│   │   ├── checker.py       # answer checking: meanings (fuzzy) + readings
│   │   ├── session.py       # session engine: queue, back-to-back, ignore, wrap-up
│   │   ├── ordering.py      # ordering strategies
│   │   └── flick.py         # flick layout + gesture → kana resolution (pure)
│   └── ui/
│       ├── app.py           # DurtleApp: modes, keymap, command line, status line
│       ├── commands.py      # ":" command parser + registry
│       ├── screens/
│       │   ├── onboarding.py
│       │   ├── dashboard.py
│       │   ├── quiz.py      # shared by reviews and lesson quizzes
│       │   ├── lesson.py    # lesson presentation pages
│       │   └── help.py
│       └── widgets/
│           ├── prompt.py    # big character + prompt bar (colored by type)
│           ├── answer.py    # answer input with live romaji→kana
│           ├── flick.py     # FlickKeyboard widget (mouse drag)
│           ├── iteminfo.py  # meanings/readings/mnemonics panel
│           └── statusline.py
└── tests/
```

**Rules for the layers**

- `domain/` is pure Python. It does no I/O and imports nothing from Textual, so everything in it can be unit-tested.
- `ui/` never calls the API directly. It reads through `store.repo` and writes through `store.sync` (the queue).
- **Offline-first everywhere:** every review and lesson start is written to the queue first. A background worker flushes the queue. Online and offline therefore follow the same code path.

**Dependencies**: `textual`, `httpx`, `platformdirs`, `tomli-w`, `rapidfuzz`.
Dev: `pytest`, `pytest-asyncio`, `respx`, `ruff`.

---

## 2. Step-by-step features

Each step ends in a working, testable state. Do them in order.

### Step 1 — Project scaffolding

- Set up `pyproject.toml` (hatchling) with the `src/` layout, the `[project.scripts] durtleshells = "durtleshells.__main__:main"` entry point and Python ≥ 3.11.
- Add a minimal Textual `App` that shows "durtleshells" and quits on `:q` (a placeholder until Step 5).
- Configure ruff and pytest and add a `.gitignore`.
- Make it installable with `uv tool install -e .` or `pipx install -e .`.

**Done when:** running `durtleshells` in Konsole opens the full-screen app, `:q` exits cleanly and leaves the terminal unchanged, and `pytest` runs.

### Step 2 — Config and token onboarding

- `paths.py`: config dir `~/.config/durtleshells/`, data dir `~/.local/share/durtleshells/` (via platformdirs).
- `config.py`: load and save TOML. Token resolution order: `WANIKANI_API_TOKEN` env var, then the `api_token` key in the config, then onboarding. Write the file with mode `0600`.
- Settings schema: typed keys with defaults and validation, reused later by `:set`.

  | key | type | default | meaning |
  |---|---|---|---|
  | `flick` | bool | `true` | show the flick grid during reading questions |
  | `order` | enum | `random` | review order (see Step 10) |
  | `lesson_order` | enum | `level` | lesson order |
  | `first` | enum | `meaning` | which half comes first in back-to-back: `meaning`/`reading`/`random` |
  | `lesson_batch` | int | user pref | lessons per batch (defaults to WaniKani's `lessons_batch_size`) |
  | `wrapup_mode` | enum | `started` | `started` = finish half-done items only; `count` = also N more |
  | `wrapup_count` | int | `10` | used when `wrapup_mode=count` |
  | `typo_tolerance` | bool | `true` | close-match acceptance for meanings |
  | `ignore_mode` | enum | `immediate` | after ignore: re-ask `immediate` or `later` |

- `onboarding.py`: on first launch, a screen asks for the token (masked input) and checks it with `GET /user`. If it's valid, save it. If not, show the error and ask again.

**Done when:** a first run asks for the token, an invalid token is rejected with a clear message, a valid one is saved with `0600` permissions, the env var overrides the file, and the settings schema has unit tests.

### Step 3 — WaniKani API client

`api/client.py`, async, built on `httpx.AsyncClient`.

- Base URL `https://api.wanikani.com/v2/`. Headers: `Authorization: Bearer <token>`, `Wanikani-Revision: 20170710`.
- **Pagination:** follow `pages.next_url` until null and yield items as they arrive.
- **Rate limiting:** the limit is 60 requests per minute. Track it with a token bucket. On `429`, sleep until the `RateLimit-Reset` header time, then retry.
- **Errors:** map them to `AuthError` (401), `RateLimited` (429), `UnprocessableError` (422, which the offline queue uses to detect stale entries), `NetworkError` (connection or timeout) and `ApiError` (other).
- Endpoints needed:
  - `GET /user` (level, `preferences.lessons_batch_size`, subscription max level)
  - `GET /subjects?updated_after=` (radical, kanji, vocabulary, kana_vocabulary)
  - `GET /assignments?updated_after=`
  - `GET /study_materials?updated_after=` (user meaning synonyms)
  - `POST /reviews` — body `{"review": {"assignment_id", "incorrect_meaning_answers", "incorrect_reading_answers", "created_at"}}`
  - `PUT /assignments/{id}/start` — body `{"started_at": ...}`
- `api/models.py`: dataclasses parsed from the JSON. Keep the raw `data` JSON as well, so the DB can store it unchanged.
  Watch for edge cases: radicals with `characters: null` (image-only), `kana_vocabulary` with no readings (meaning only), `auxiliary_meanings` with `type: whitelist|blacklist`, kanji reading `type: onyomi|kunyomi|nanori` and `accepted_answer`, and `hidden_at`.

**Done when:** tests mocked with `respx` cover pagination, a 429 followed by a retry, 401→`AuthError`, 422→`UnprocessableError`, and parsing of each subject type (including an image-only radical and kana_vocabulary).

### Step 4 — Local store and sync engine

`store/db.py` schema (version it with `PRAGMA user_version` for migrations):

```sql
subjects(id PK, object, level, characters, data JSON, hidden_at, updated_at)
assignments(id PK, subject_id, subject_type, srs_stage, unlocked_at, started_at,
            available_at, burned_at, hidden, data JSON, updated_at)
study_materials(id PK, subject_id, meaning_synonyms JSON, updated_at)
user(id PK, data JSON)
meta(key PK, value)              -- last_sync_<collection> timestamps
outbox(id PK AUTOINCREMENT, kind TEXT CHECK(kind IN ('review','lesson_start')),
       assignment_id, payload JSON, created_at, attempts, last_error)
```

`store/sync.py`:

- **Initial sync:** download all subjects (about 10 pages), assignments, study materials and the user. Show progress on the dashboard ("Syncing subjects 3/10…").
- **Incremental sync:** fetch each collection with `updated_after=<last_sync>` and upsert. Run it at startup, on `:sync`, after a session ends, and every 5 minutes while the app is open.
- **Outbox flush:** send entries in `created_at` order. Each entry has one of three results:
  - success: delete it, upsert the returned assignment and re-fetch that assignment
  - `UnprocessableError` (stale, e.g. already reviewed on the website): delete it and emit a `StaleSubmission` notification naming the subject
  - `NetworkError`: keep it, increment `attempts` and stop flushing (we're offline)
- Expose `online: bool` and `pending: int` as reactive state for the status line.

`store/repo.py` queries, all computed locally so they work offline:
`available_reviews(now)` (started, not burned, not hidden, `available_at ≤ now`, not already in the outbox), `available_lessons()` (unlocked, not started, not hidden), `forecast(hours=24)`, `srs_distribution()`, `subject(id)`, `synonyms(subject_id)`.

**Done when:** a fresh DB fills completely from mocked responses, a second sync only asks for `updated_after` data, outbox entries survive a restart, a 422 drops the entry and emits a notification, and a network error keeps it queued.

### Step 5 — App shell: modes, command line, status line, dashboard

`ui/app.py`, `ui/commands.py`, `widgets/statusline.py`, `screens/dashboard.py`.

- **Modes:** `NORMAL` and `INSERT`, shown on the status line. `Esc` switches to NORMAL. `i`/`a` switch to INSERT when an input is focused. Starting a quiz puts you straight into INSERT.
- **Command line:** `:` opens a one-line input at the bottom, like Vim. Commands are a registry of name → handler with tab completion.
  `:q` / `:quit`, `:sync`, `:reviews`, `:lessons`, `:wrap`, `:set key=value`, `:set key?`, `:set` (list all), `:help`.
  Changes made with `:set` are saved to the config straight away.
- **Status line** (always visible): `-- MODE --` · screen name · session progress (`12/48 ✓92%`) · `WRAP-UP` flag · sync state (`● online` / `○ offline` / `⇅ 3 pending`) · user level.
- **Dashboard** (start screen): lessons available, reviews available, a 24h forecast (hourly buckets in a small bar list), the SRS distribution (Apprentice/Guru/Master/Enlightened/Burned) and the time of the last sync.
  Keys: `r` reviews, `l` lessons, `s` sync, `?` help, `q` quit (with confirmation if the outbox is not empty and we're offline).
- Notifications (stale submissions, sync errors) use Textual's `notify`.

**Done when:** the app opens on the dashboard with real numbers from the cache, works with networking disabled (showing the offline marker), `:set order=level` persists across restarts, unknown commands or keys give a Vim-style error on the command line, and Textual `Pilot` tests cover mode switching and command parsing.

### Step 6 — Romaji→kana converter

`domain/kana.py`, pure Python with heavy tests.

- IME-style incremental conversion: convert what you can and keep the unresolved tail as romaji (e.g. typing `ky` shows `ky` until the next letter arrives, then `kyo` becomes `きょ`).
- Coverage: all gojūon, dakuten and handakuten, yōon (`kya`, `sha`, `cha`, `ja`…), sokuon from doubled consonants (`kka`→`っか`, `tchi`→`っち`), `n` rules (`nn`→`ん`, `n'`, `n` before a consonant → `ん`, a trailing `n` → `ん` **on submit**), explicit small kana (`xa`/`la`, `xtu`/`ltu`, `xya`…), `-`→`ー`, and common alternatives (`si`/`shi`, `ti`/`chi`, `tu`/`tsu`, `hu`/`fu`, `zi`/`ji`, `di`, `du`, `wo`, `fa`/`fi`/`fe`/`fo`, `vu`, `ti`→ち and `thi`→てぃ).
- Hiragana output by default. Katakana via shift (uppercase input → katakana), which you need for some kana_vocabulary readings.
- API: `convert(buffer: str, final: bool) -> str`.

**Done when:** table-driven tests pass for every romaji in the table plus the edge cases (`kanji`, `konnichiha`, `onna`, `kippu`, `shinbun`, a trailing `n`, `n'a`).

### Step 7 — Answer checker (close-match tolerance)

`domain/checker.py`. It returns a `Verdict` with `result ∈ {CORRECT, CORRECT_TYPO, INCORRECT, SHAKE}` and a `message`.

**Meaning questions**
1. Normalize: lowercase, trim, collapse whitespace, remove `-`, `.`, `'` and other punctuation.
2. Accepted set = meanings with `accepted_answer`, plus `auxiliary_meanings[type=whitelist]`, plus the user's `meaning_synonyms`.
3. A match against `auxiliary_meanings[type=blacklist]` → `INCORRECT`, checked first.
4. An exact match → `CORRECT`.
5. If `typo_tolerance` is on, use the Levenshtein distance from rapidfuzz with WaniKani's tolerance by length: ≤3 chars: 0, 4–5: 1, 6–7: 2, otherwise `2 + floor(len/7)`. Within tolerance → `CORRECT_TYPO`, with a message showing the right spelling.
6. If the answer contains kana or kanji → `SHAKE` ("We want the meaning, not the reading"). This doesn't count as a wrong answer.

**Reading questions**
1. Run the final conversion (`final=True`), so a trailing `n` becomes `ん`. Normalize katakana to hiragana before comparing.
2. If the answer still contains Latin letters after conversion → `SHAKE` ("Answer in kana").
3. A match against a reading with `accepted_answer` → `CORRECT`.
4. Kanji only: a match against a non-accepted reading → `SHAKE` with Durtles' nudge ("We want the on'yomi reading" or "…kun'yomi").
5. Vocabulary: a match against the reading of a component kanji instead of the vocab reading is still `INCORRECT` (WaniKani behaves the same way).
6. Otherwise → `INCORRECT`.

**Done when:** unit tests cover each branch, using real subject JSON fixtures (e.g. 大, 人, 一人, a kana_vocabulary, a blacklisted meaning, a user synonym).

### Step 8 — Session engine (back-to-back, ordering)

`domain/session.py` + `domain/ordering.py`, pure and fully unit-tested. Both reviews and lesson quizzes use it.

- `SessionItem`: assignment, subject, the halves still to ask (`{MEANING, READING}`, meaning only for radicals and kana_vocabulary), counters `incorrect_meaning`/`incorrect_reading`, and the half-done state.
- **Back to back:** when an item is drawn, both of its remaining halves are asked one after the other, in the order set by `first`.
- **Wrong answer:** that half's incorrect counter goes up, and the half stays pending. The item goes back into the pool and is asked again later, its remaining halves again back to back.
- **Completion:** when every half of an item has been answered correctly, the session emits `ItemCompleted(assignment_id, incorrect_meaning, incorrect_reading, completed_at)`. For reviews, the caller writes this to the outbox at once (Step 9). For lessons, it's collected (Step 12).
- **Answer state machine:** `ASKING → ANSWERED(verdict) → (next | ignore)`. A `SHAKE` stays in `ASKING`.
- **Ordering** (`ordering.py`) for the pool of not-yet-started items:
  `random` · `level` (ascending, then random) · `level_desc` · `srs` (lowest stage first) · `type` (radical → kanji → vocab) · `oldest` (earliest `available_at` first).
  Lessons: `level` (level, then `lesson_position`, as WaniKani does) · `type` · `random`.
  Items that were answered wrong and are waiting to be asked again go back in at a random position within the next 3–10 draws, so they don't come back immediately.
- Session stats: completed, remaining, correct percentage (by question).

**Done when:** tests show that the two halves of the same item come one after the other, a wrong half comes back later, completion reports the correct incorrect counts, each ordering strategy sorts as specified, and radicals/kana_vocabulary only ask the meaning.

### Step 9 — Review screen

`screens/quiz.py`, `widgets/prompt.py`, `widgets/answer.py`, `widgets/iteminfo.py`.

- **Layout** (top to bottom): the prompt area, whose background follows WaniKani colors (radical `#00AAFF`, kanji `#FF00AA`, vocab `#AA00FF`) with the subject characters centered; a prompt bar (`Vocabulary · Reading`, styled dark for reading and light for meaning, as Durtles does); the answer input; the feedback line; the flick keyboard (Step 13, reading questions only, when `flick=true`); the status line.
  An image-only radical shows its primary meaning in `[brackets]` with a note, because a terminal can't render the SVG.
- **Answer input:** for reading questions it converts live through `kana.convert`. For meaning questions it's plain text. `Enter` submits.
- **After submitting:** the input locks. Green means correct, yellow means correct with a typo (plus a message), red means incorrect. While locked the keys are commands, as in Vim's NORMAL mode:
  `Enter` next question · `u` ignore answer (Step 11) · `f` toggle the item info panel (meanings, readings, and mnemonics with WaniKani's `<kanji>`/`<radical>`/`<vocabulary>`/`<reading>`/`<ja>` tags rendered as colored Rich markup) · `w` wrap-up · `:` command line.
  On an incorrect answer the item info opens automatically.
- **SHAKE:** a short shake animation (offset jitter) plus the message, and the input stays editable.
- `ItemCompleted` → an outbox entry `kind=review` with `created_at = completed_at`, followed by an immediate background flush attempt.
- `Esc` then `q` leaves the session with confirmation. Completed items are already queued. Half-done items are dropped, as on WaniKani.
- Session summary screen: correct percentage, completed count, items answered wrong, then back to the dashboard.

**Done when:** a full review session with real data works end to end, SRS stages change on the website after the flush, and Pilot tests drive a session through correct, incorrect, typo and shake answers.

### Step 10 — Ordering options in the UI

- `:set order=<strategy>` and `:set lesson_order=<strategy>`, with completion of the valid values.
- Changing the order mid-session reorders only the items not yet drawn.
- The dashboard footer shows the active ordering.

**Done when:** each strategy can be selected, persists, and visibly changes the order of the next items.

### Step 11 — Ignore answer

- In the `ANSWERED` state, `u` undoes the last answer: it reverses that half's counter change (if it was incorrect) and sets that half back to pending.
- Where it goes next depends on `ignore_mode`: `immediate` asks the same question again at once with an empty input; `later` puts the item back in the pool.
- It works for correct answers too, so you can retype a mis-hit, as in Durtles.
- Only the latest answer can be ignored, and only until the next question has been answered.
- An item whose completion was triggered by the ignored answer is **not** written to the outbox until the next answer. The outbox write is therefore delayed until the user moves on (`Enter`), so an ignore never has to take back a queued review.
- The status line briefly shows `answer ignored`.

**Done when:** unit tests confirm that ignore restores the exact pre-answer state for both halves and both verdicts, and that nothing reaches the outbox for an ignored completing answer.

### Step 12 — Lessons

`screens/lesson.py` + reuse of `quiz.py`.

- `l` on the dashboard takes a batch of `lesson_batch` items from `available_lessons()` sorted by `lesson_order`.
- **Presentation:** one item at a time, with pages navigated by `h`/`l` (and arrows):
  radicals: *Name* (meaning + mnemonic) · kanji: *Radicals* (components) → *Meaning* → *Reading* (on'yomi/kun'yomi marked) · vocab: *Kanji* (components) → *Meaning* → *Reading*.
  `j`/`k` (or `n`/`p`) move to the next or previous item. After the last item, `Enter` starts the quiz.
- **Lesson quiz:** the same session engine with the same back-to-back rules. Lesson items are only answered locally and are never sent as reviews.
- When an item is completed in the quiz → an outbox entry `kind=lesson_start` with `started_at = completed_at`. The flush sends `PUT /assignments/{id}/start`.
- After the batch: offer `Enter` for another batch, `q` to go back to the dashboard.
- Wrap-up and ignore work in the lesson quiz too.

**Done when:** a lesson batch completes, the items show up as started on WaniKani after the flush (with their first review about 4h later), and this works offline, sending the start requests on the next connection.

### Step 13 — Flick keyboard (mouse drag)

The headline feature. It's split into pure logic (`domain/flick.py`) and the widget (`ui/widgets/flick.py`).

**13a — Layout and gesture logic (pure)**

A 4×3 grid matching the iOS/Android Japanese 12-key layout. The direction order per key is *center, left, up, right, down*:

| Key | ・ | ← | ↑ | → | ↓ |
|---|---|---|---|---|---|
| あ | あ | い | う | え | お |
| か | か | き | く | け | こ |
| さ | さ | し | す | せ | そ |
| た | た | ち | つ | て | と |
| な | な | に | ぬ | ね | の |
| は | は | ひ | ふ | へ | ほ |
| ま | ま | み | む | め | も |
| や | や | （ | ゆ | ） | よ |
| ら | ら | り | る | れ | ろ |
| ゛゜小 | *modifier* | | | | |
| わ | わ | を | ん | ー | |
| 、。?! | 、 | 。 | ？ | ！ | |

Grid rows: `[あ か さ] [た な は] [ま や ら] [゛゜小 わ 、。?!]`, plus a side column `[⌫] [␣] [⏎]` for backspace, space (no-op for answers) and submit.

- **Modifier key** (tap): cycles the last character through its variants: `か→が→か`, `は→ば→ぱ→は`, `つ→っ→づ→つ`, `や→ゃ→や`, `あ→ぁ→あ`, and so on. Implement it as a lookup table, `cycle(char) -> char`.
- **Gesture resolution:** `resolve(dx_cells, dy_cells) -> Direction`. Terminal cells are about 2:1 (taller than wide), so scale `dx` by 0.5 before comparing. If `max(|dx'|, |dy|) < 1` → CENTER, otherwise the dominant axis wins.
- A direction with no kana assigned (e.g. わ↓) → no output.

**13b — Widget rendering**

- Each key is a box about 7 cells wide and 3 rows high. The key's kana is centered and the four flick candidates sit faintly at its edges (as on Android), so the layout can be learned at a glance.
- The keyboard is shown only for reading questions when `flick=true`, and hidden otherwise to save space.
- It never takes keyboard focus. Romaji typing in the answer input keeps working while the grid is visible (decision 2b).

**13c — Mouse drag**

- `on_mouse_down` on a key: `capture_mouse()`, remember the origin key and the start position, and show the **flick popup** (a cross showing the 5 candidates over the key, as on the phone).
- `on_mouse_move` while captured: compute `(dx, dy)` relative to the start, resolve the direction and highlight the candidate it points at in the popup.
- `on_mouse_up`: release capture, resolve the final direction and send a `FlickInput(kana)` message. The answer widget inserts it at the cursor. Insertion appends to the already-converted kana and bypasses romaji conversion, so a pending romaji tail is flushed first.
- Releasing outside the widget still resolves correctly, because the mouse is captured.
- A plain click (no movement) = CENTER, so the keyboard also works as a tap keyboard.
- Konsole note: Textual turns on SGR any-motion mouse tracking, which Konsole supports. **Shift+drag** in Konsole bypasses the app and selects text instead. Mention this in `:help`.

**Done when:** unit tests check `resolve()` against direction thresholds (including the aspect correction) and cover the full layout and modifier cycles. Manually in Konsole: every kana can be produced by dragging, the popup tracks the pointer smoothly, a tap gives the center kana, and romaji typing and flicking can be mixed within one answer (e.g. type `ta`, flick `べ`, modifier-tap → `たべ`…).

### Step 14 — Wrap-up mode

- `w` (or `:wrap`) during a session toggles wrap-up.
- `wrapup_mode=started`: no new items are drawn. The session continues only with items that have a half answered (correct or wrong but pending), then ends.
- `wrapup_mode=count`: also draw up to `wrapup_count` new items, then stop.
- The status line shows `WRAP-UP · n left`. Toggling it off again goes back to the normal flow.

**Done when:** unit tests show that no new item is drawn after wrap-up (in `started` mode), that half-done items are completed, and that the session ends when they're done.

### Step 15 — Offline mode, end to end

Most of the pieces exist after Step 4. This step makes the whole flow solid.

- On startup with no network: open from the cache and show `○ offline`. Reviews and lessons work fully.
- The sync worker retries the outbox with backoff (30s → 5min) and also triggers on `:sync`.
- On reconnect: flush the outbox first, then run the incremental sync, so local state isn't overwritten with assignment data the server hasn't updated yet.
- Stale entries (422): delete them and send a notification ("1 review was discarded: 食べる — already reviewed elsewhere").
- Quitting with pending entries while offline shows a confirmation that the entries stay queued for the next launch.
- `available_reviews()` excludes assignments that already have an outbox entry, so an item is never reviewed twice before syncing.

**Done when:** a full session done with networking disabled is sent correctly after reconnecting (the timestamps on the server match the local completion times), a stale entry is handled gracefully, and nothing is lost across restarts.

### Step 16 — Help, polish and packaging

- `?` / `:help` opens a help screen listing every key and command, plus the Konsole Shift+drag note.
- Visual pass: consistent colors, a clear distinction between reading and meaning questions, and a layout that adapts to small terminals (hide the flick keyboard below about 30 rows with a hint).
- An error screen for an invalid or revoked token (401) that sends you back to onboarding.
- `README.md`: install (`uv tool install` / `pipx`), first launch, keys, settings.
- Optional AUR `PKGBUILD` for Garuda/Arch.

**Done when:** a fresh install on Garuda in Konsole goes from the token prompt to a completed review session without consulting the docs.

---

## 3. Later (not planned now)

- Big glyph rendering of the prompt character (Pillow plus a CJK font, rendered to half-block characters or the Kitty/Sixel graphics protocols) so kanji appear larger than the terminal font.
- Images for image-only radicals via the same graphics protocol.
- Themes.

## 4. References

- WaniKani API v2: https://docs.api.wanikani.com/
- Textual: https://textual.textualize.io/ (mouse events, `capture_mouse`, Pilot testing)
- Smouldering Durtles (behavioral reference): https://github.com/jerryhcooke/smouldering_durtles
- HebiKani (Python reference client): https://github.com/ajite/hebikani
