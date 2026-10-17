# durtleshells

A terminal WaniKani client that feels like
[Smouldering Durtles](https://github.com/jerryhcooke/smouldering_durtles).
Type `durtleshells` and you get a full-screen, Vim-style UI. Answer reading
questions in romaji, or flick kana on an emulated Japanese phone keyboard with
real mouse drags.

- **Lessons and reviews.** Meaning and reading are asked back to back.
- **Ignore answer** (`u`), **wrap-up** (`w`) and **typo tolerance** for meanings.
- **Ordering options** for reviews and lessons.
- **Offline mode.** Everything is cached locally. Answers go into a queue and
  are sent, with their original timestamps, the next time you're online.
- **Flick keyboard.** Press a key, drag left/up/right/down and release. A tap
  types the key's centre kana, and `゛゜小` adds dakuten, handakuten or small kana.

Linux only. It's developed and tested in Konsole.

## Install

```sh
uv tool install .          # or: pipx install .
durtleshells
```

To work on it:

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

On Arch or Garuda you can also run `cd packaging/arch && makepkg -si`.

## First launch

On first launch durtleshells asks for a WaniKani **API token (v2)**. Create
one at <https://www.wanikani.com/settings/personal_access_tokens> and give it
these permissions:

- **reviews:create**, to submit reviews
- **assignments:start**, to finish lessons

The token is checked against WaniKani and then stored in
`~/.config/durtleshells/config.toml` with mode `0600`. The environment
variable `WANIKANI_API_TOKEN` overrides the stored token.

The cache and the answer queue live in `~/.local/share/durtleshells/durtleshells.db`.

## Keys

| Where | Key | Action |
|---|---|---|
| Dashboard | `r` / `l` / `s` / `q` | reviews / lessons / sync / quit |
| Anywhere | `:` | command line (Tab completes) |
| Anywhere | `?` | help |
| Quiz, typing | `Enter` | submit |
| Quiz, typing | `Esc` | NORMAL mode |
| Quiz, NORMAL mode | `i` | back to typing |
| Quiz, NORMAL mode | `q` | leave the session |
| After an answer | `Enter` | next question |
| After an answer | `u` | ignore the answer |
| After an answer | `f` | item info |
| After an answer | `w` | wrap-up |
| Lessons | `h` / `l` | previous / next page |
| Lessons | `j` / `k` | next / previous item |
| Lessons | `Enter` | continue, then start the quiz |

Romaji tips: `nn` or `n'` types ん, and a final `n` becomes ん when you submit.
Doubled consonants type っ. UPPERCASE types katakana.

**Konsole:** Shift+drag selects text instead of flicking, so drag without Shift.

## Commands and settings

| Command | What it does |
|---|---|
| `:q`, `:q!` | leave the session, or quit (`!` skips the confirmation) |
| `:sync` | send queued answers, then sync with WaniKani |
| `:reviews`, `:lessons` | start a review or lesson session |
| `:wrap` | toggle wrap-up |
| `:help` | show help |
| `:set key=value` | change a setting (saved immediately) |
| `:set key?` | show a setting |
| `:set` | list all settings |
| `:set noflick`, `:set flick!` | turn a boolean off, or toggle it |

| Setting | Values | Default |
|---|---|---|
| `flick` | `true` / `false` | `true` |
| `order` | `random` `level` `level_desc` `srs` `type` `oldest` | `random` |
| `lesson_order` | `level` `type` `random` | `level` |
| `first` | `meaning` `reading` `random` | `meaning` |
| `lesson_batch` | number | your WaniKani setting |
| `wrapup_mode` | `started` (finish half-done items) / `count` | `started` |
| `wrapup_count` | number | `10` |
| `typo_tolerance` | `true` / `false` | `true` |
| `ignore_mode` | `immediate` / `later` | `immediate` |

See [docs/GUIDE.md](docs/GUIDE.md) for the design and build plan.
