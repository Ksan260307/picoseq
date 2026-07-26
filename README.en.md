# PicoSeq — Retro Chiptune Sequencer

A desktop app for making and playing 8-bit style chiptune music.
Place notes on a grid to build a song — or start from a photo or your own humming.

**日本語版: [README.md](README.md)**

## Features

- Draw phrases on a grid, then arrange them into a full song
- Four parts (melody / bass / rhythm / sub)
- **🧅 Layers per part** — stack up to 8 layers per part via "＋ Add". Give each layer its own
  tone and notes for harmonies and thickness; ✨ Auto fills every layer too (up to 32 voices)
- **🔇 Mute (per part or per layer)** — toggle mute for a whole part or an individual layer;
  applies to playback and WAV export (never changes the saved state)
- **🔍 Zoom the board** — zoom the piano roll in/out (the － / ＋ in its header, or Ctrl+wheel);
  cell width and height scale together, with horizontal scrolling when zoomed in
- **🪟 Resizable, detachable layout** — each panel (Controls, Piano roll, Song) resizes by dragging
  the divider, and "⧉ Detach" pops it out into its own window
- **🌐 Japanese / English** — switch the display language with 🌐 at the top-right; the choice is remembered
- **🎹 Sound sets** — "Chiptune 8-bit", "Mellow 16-bit", and "Crystal 32-bit".
  Switching also re-skins the whole interface to match
- **🎼 65 moods** — major / minor / all church modes / modes of the melodic & harmonic minor /
  Japanese scales (in-sen, ryukyu, …) / blues, jazz, whole-tone, diminished / world scales
  (Persian, Arabic, Hungarian, …) and more (plus photo-derived scales)
- **✨ Auto-compose** — one-click composition. Keep the "seed value" to recreate the exact same tune anytime.
  Chord progressions (500–4,000 per mood, **~120,000 total**) × 9 bass × 7 backing × 9 drum × 6 melody-rhythm ×
  4 development styles (**13,000+ playing-style combos alone**) combine, so every seed sounds different.
  Progressions are generated from functional harmony (tonic / subdominant / dominant) with substitute chords;
  the one used (e.g. Am→F→C→G) is shown after generating
- **🎲 Surprise me** — randomizes mood, sound set, **tempo** and seed, **plus each part's tone (pulse width,
  etc.) and length**, for a one-click reveal — so even the texture is an unexpected combination from all 65 moods
- **🎼 Auto-song** — generates a whole Intro → A → B → Outro song structure in one click
  (each pattern gets a default name: Intro / A / B / Outro)
- **🎧 DJ mode** — two big turntables for real-time jamming. Press ▶ and it **auto-generates a new
  phrase every 8 bars and flows on seamlessly** (pre-rendered and swapped in on the downbeat), and you
  can **drag a disc to scratch**. Crossfade between decks, build energy with **noise / filter / KILL**,
  and tick **🔁 Hold** to loop the current phrase
- **🗂 Pattern editor tab** — a dedicated tab between Phrase and Song to manage saved patterns
  (up to 8): load onto the board (edit), rename, duplicate, delete, preview
- **🎤 From humming** — sing into the microphone and PicoSeq turns your pitch into a melody
  (YIN-style pitch detection that resists octave errors even on harmonic-rich voices)
- **🎸 Auto-accompany** — draw only a melody and matching bass, drums, and backing are generated
- **📷 From a photo** — up to 8 rectangles found in a photo become a set of "allowed notes",
  added to the mood selector as a *Photo Scale* — compose using only those notes for inspiration
- **Editing tools** — octave transpose (🔼🔽 / Ctrl+↑↓), reverse the phrase in time (🔄),
  and clear a single part (right-click its part button)
- **Live updates** — add, remove, and stretch notes (or change the tempo) while the song keeps playing
- **🎧 WAV / 🎹 MIDI export** — save an audio file, or a standard MIDI file you can open in a DAW or
  notation software (parts split across MIDI channels)
- Audio is synthesized with integer math only, so the same project produces a bit-identical WAV on any machine
- Runs on the Python standard library alone — nothing to install
- Window size/position, panel split sizes, zoom level, and language are restored on the next launch

Optional extras: `numpy` (faster rendering) and `Pillow` (JPEG photos).
Everything works without them (PNG / BMP / PPM decoders are built in).

## Getting started

Python 3.9+ (built for Windows).

```console
py main.py            # launch the app
py main.py --demo     # launch with a demo song loaded
py main.py --selftest # run a headless self-check (exit code 0 = OK)
py -m unittest        # run the full test suite
py -m picoseq.vision photo.jpg   # inspect photo analysis from the command line
```

Sound playback uses the built-in Windows audio API. On other systems, editing and
WAV export still work, but live playback is silent.

### Building an exe

To build a single distributable executable (installs PyInstaller on first run):

```console
build_exe.bat
```

This produces `dist\PicoSeq.exe`, which runs on PCs without Python installed.

### Building for phones (Android)

The desktop UI (tkinter) cannot run on phones, so a **lightweight mobile shell**
(`mobile/`) reuses the same composition engine. The `Android APK` GitHub Actions
workflow (manual dispatch, or pushing a `v*` tag) packages `mobile/main.py` plus the
`picoseq` package into an APK with Buildozer; download it from the workflow Artifacts.
See `.github/workflows/android.yml` and `mobile/buildozer.spec`.

Mobile features: auto-compose, auto-song, sound set / mood / seed controls, loop playback.
Note: the APK build is verified in CI only — test on your own device.

`ci.yml` runs the full test suite and the UI self-check on every push / PR,
and also uploads a Windows exe on tags.

## How to use

**Phrase tab**

- Left-click a cell to place a note; **drag right to stretch it**
- Click a note (or right-click) to erase it
- Click the piano keys on the left to preview a pitch
- Switch parts with the part buttons or keys `1`–`4`
- **Layers** — use "＋ Add" below the parts to stack layers (up to 8 per part); select a layer by
  number, delete layers 2+ with "✕ N". Each layer has its own tone and notes
- **Mute** — 🔊/🔇 in the "Mute" row toggles a whole part; 🔊/🔇 in the layer bar toggles one layer.
  A part with only some layers muted shows 🔉. Applies to playback and WAV
- **Zoom** — the － / 100% / ＋ in the Piano roll header, or Ctrl+wheel over the board
- **Panels** — drag the divider between "Controls" and "Piano roll" to resize; "⧉ Detach" pops a
  panel into its own window, "⧈ Dock" returns it
- Shape each part (layer)'s sound with the *tone*, *length* and *volume* sliders — use
  *volume* to balance the mix (e.g. bring up the bass, pull down the rhythm)
- **✨ Auto-compose** — each press picks a fresh seed value; type a number and press Enter to recreate that exact tune
- **🎤 From humming** — record 6 seconds (or open a WAV file) to extract a melody
- **🎸 Auto-accompany** — generates the other three parts to fit your melody
- **★ Save** — store up to 8 favorite phrases as patterns

**📷 From a photo (Photo Scale)**

1. Click 📷 and pick a photo with clearly visible rectangular objects (books, cards, windows…)
2. Up to 8 detected rectangles are shown, each labeled with its note
3. Choose *compose with this scale* or *just import the scale*

Conversion rules (the same photo always gives the same result):

| Photo feature | Musical meaning |
| --- | --- |
| Horizontal position of each rectangle | Its note (left = low, right = high) |
| The largest rectangle | The key (home note) |
| All rectangle notes together | The *Photo Scale* — the set of allowed notes |
| Total rectangle area | Tempo (bigger = faster) |
| Fine corner positions | Seed value (same photo → same song) |

The imported scale stays available in the mood selector as *📷 Photo Scale*.

**Pattern editor tab**

- A dedicated screen (between Phrase and Song) to manage saved patterns (up to 8)
- Each pattern: **✏ Edit** (load onto the board), **🏷 Rename**, **⧉ Duplicate**, **🗑 Delete**, **▶ Play**
- Use "＋ Save here" on an empty slot to store the current phrase
- Names you set also appear on the Song grid cells

**Song tab**

- **✨ Auto-song** — generates patterns 1–4 (Intro / A / B / Outro) and the full
  16-block arrangement in one click; press ▶ to hear a complete piece
- Pick a pattern from the palette — "Placing: name" shows which — then place it on the 4-track × 16-block grid
- **▶ Preview** plays the selected pattern once so you can check it
- Cells show the **pattern name** (or F-number) with **block numbers** along the top;
  cells matching the pattern you're placing are highlighted with a bright border, and
  long names are truncated with "…" to fit the cell
- Hover a cell to see the full name of the pattern there in the status bar
- Horizontal = sequence, vertical = play together
- *WAV export* renders the whole song to an audio file

**🎧 DJ mode**

- A screen with two big turntables (decks A / B) for real-time jamming
- **▶ Spin** to start, and it **auto-generates a new phrase every 8 bars and flows on with no gap**
  (the next loop is pre-rendered in the background and swapped in **sample-accurately without
  stopping playback**, so no silence is ever inserted)
- Scratching and previews are **mixed over** the music, so playback never cuts out
- **Drag a disc (with the mouse) to scratch** — it layers over the music.
  Click a disc without moving (a tap) to generate a fresh phrase on that deck
- The **crossfader** switches between decks A ⇄ B (cue up the other deck, then bring it in)
- **Mood / Key / Tempo / Noise / Filter / Hold / KILL are per-deck** channel strips, so you can set up
  one deck while the other is playing:
  - **Mood**: pick any of the 65 scales from the selector (🎲 Roll is the random shortcut).
    Both decks start on "Bright (major)"
  - **Key**: pick any of the 12 keys. Set the decks apart to modulate, or match them for a
    seamless blend (changing mood or key keeps the phrase's shape — only 🎲 Roll rewrites it)
  - **Sound**: the same 3 sound sets as the Phrase screen, per deck. In DJ mode the
    **palette stays put**, so the discs never jump and A and B can hold different sounds
  - **Noise** (0–4): hi-hat-style ticks and build-up rolls
  - **Tone / Length / Volume (per part)**: pick Melody / Bass / Rhythm / Sub under "Part", then dial in
    that part's **Tone** (for the melody, the pulse-wave duty cycle 12.5%–50%: **thin blip ⇄
    fat square**), **Length** (gate — shorter is punchier, longer sustains) and **Volume**
    (mix balance). The notes stay the same; only the sound design changes
  - **Filter**: sweep a low-pass (dark ⇄ open)
  - **Hold loop**: stop advancing and loop that deck's phrase
  - **KILL**: instantly mute a part (melody / bass / rhythm / sub)
  - **SYNC**: match **tempo and key** to the other deck. Mood and sound are left alone,
    so you can layer two different moods that share a beat and a key
- Control changes apply **immediately** (no waiting for the loop boundary); **Tap** sets the tempo
- **🕘 History**: every phrase you played, newest first. From a row you can
  **recall it onto either deck (→A / →B)**, **star it**, or **save it as a pattern (💾)**.
  **Control tweaks are logged too** (committed as one row once you settle), so you can always
  jump back to "how it sounded before I dialed it in". Use **Clear** when it fills up
- **⏺ Record**: the record button in the centre captures the live mix (switches, scratches,
  noise and all) **straight to a WAV**. Press again to stop and choose where to save —
  it comes out exactly as you heard it
- **★ Favorites**: star the ones you like — they are **kept in the settings file, so they
  survive a restart**. The centre **★ Save / 💾 Keep** buttons do the same for whatever is
  playing right now
- What is stored is not audio but the **seed of the phrase** (mood, key, tempo, sound,
  noise, seed). It regenerates deterministically, so the log stays tiny however long you play

**Playback & sound sets**

- `Space` to play / stop (loops)
- **Edits are reflected live while playing** — no need to stop
- Tempo changes apply during playback too
- The *sound* selector in the header changes the overall character —
  **the color scheme changes with it** (green → purple → indigo), and the choice is saved
- Use 🌐 at the top-right to switch between Japanese and English; the choice is remembered

**Keyboard**

| Key | Action |
| --- | --- |
| `Space` / `Esc` | Play & stop / stop |
| `1`–`4` | Switch part |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Ctrl+Tab` | Cycle Phrase → Patterns → Song → DJ |
| `F1` | Help |

## Under the hood (for developers)

Logic (`picoseq/core/`, pure functions only) is separated from the UI (`picoseq/ui/`).
All randomness derives from the seed value and all audio synthesis uses integer math,
so **the same project renders a bit-identical WAV in any environment**.

```
picoseq/
├── main.py                launcher (--selftest / --demo)
├── build_exe.bat          exe build script
├── picoseq/
│   ├── core/              logic (pure functions; no I/O, drawing, or wall-clock)
│   │   ├── constants.py   limits and part definitions
│   │   ├── prng.py        deterministic random generator (seeded)
│   │   ├── music.py       keys / scales / chords / pitch table (incl. photo scales)
│   │   ├── note.py        one note packed into a 32-bit integer
│   │   ├── phrase.py      phrase (note collection) operations
│   │   ├── song.py        song-grid operations
│   │   ├── project.py     the whole app state (immutable object)
│   │   ├── actions.py     every edit operation (pure functions)
│   │   ├── composer.py    auto-composition and accompaniment
│   │   ├── dj.py          DJ-mode noise injection (pure functions)
│   │   ├── arranger.py    chord inference from a melody
│   │   ├── humming.py     pitch detection (autocorrelation, integer math)
│   │   ├── schedule.py    timing and event expansion
│   │   ├── synth.py       fixed-point synth (pulse/triangle/noise/saw)
│   │   ├── renderer.py    mixer (voice cache, optional numpy fast path)
│   │   ├── wavio.py       WAV encoding
│   │   ├── midiio.py      standard MIDI file export (split per layer)
│   │   ├── serialize.py   versioned JSON save files + legacy migration
│   │   └── history.py     undo / redo
│   ├── vision/            photo scale (image analysis)
│   │   ├── image.py       image loading (built-in PNG/BMP/PPM decoders)
│   │   ├── quad.py        rectangle detection (multi-threshold, up to 8, dedup)
│   │   ├── harmony.py     rectangles → musical scale
│   │   └── __main__.py    CLI inspector
│   └── ui/                screen (state changes only via actions)
│       ├── app.py         wiring, live re-rendering
│       ├── panel.py       detachable dock panels (wm manage/forget)
│       ├── roll_view.py   piano roll (zoom + horizontal scroll)
│       ├── song_view.py   song grid
│       ├── dj_view.py     DJ mode (turntables + mixer)
│       ├── photo.py       photo-scale dialog
│       ├── hum.py         humming dialog
│       ├── mic.py         microphone recording (native Windows API)
│       ├── help.py        help screen (JP/EN)
│       ├── i18n.py        display language (Japanese / English)
│       ├── playback.py    playback, position clock, mid-loop restart
│       ├── stream.py      streaming output (waveOut): gapless swaps + one-shot mixing
│       ├── storage.py     file locations + app settings (language, zoom, window)
│       └── theme.py       colors and fonts
└── tests/                 test suite (py -m unittest)
```

### Design principles

| Principle | Meaning |
| --- | --- |
| Reproducibility | Randomness comes only from the seed value; same settings → same song, same WAV |
| Order independence | Mixing is integer addition; processing order never changes the result |
| Environment independence | Integer-only synthesis; the numpy path is verified bit-identical to pure Python |
| Display separation | Only the playhead display uses real time; it never affects song data |
| Versioned saves | JSON with app ID + format version; newer/foreign data is rejected safely |
| Backward compatibility | Reads v1/v2 saves and even the old browser version's retro_project.json |

### Tests

Run everything with `py -m unittest`. Waveforms and PCM output are pinned by
checksums, so any change that alters the sound is caught by the tests.
The UI is exercised end-to-end by `py main.py --selftest`.
