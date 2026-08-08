/* ブラウザ版の画面側。
 *
 * 役割分担:
 *   Python (core + bridge.py)  作曲・合成・状態の保持   ← デスクトップ版と同一
 *   JavaScript (このファイル)   描画・入力・音を鳴らす   ← tkinter の代わり
 *
 * 状態は Python 側に 1 つだけ置き、JS は毎回 snapshot() を読んで描く。
 * こうすると「画面が状態を持たない」のでデスクトップ版と同じ性質になる。
 */

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
const PART_COLORS = ["#8fd177", "#68b9c9", "#e08a8a", "#d9b45a"];
const KEY_W = 46;          // 鍵盤の幅 (canvas 座標)
const BLACK_KEYS = new Set([1, 3, 6, 8, 10]);

let py = null;             // Pyodide 本体
let bridge = null;         // bridge モジュール
let info = null;           // catalog() の内容
let view = null;           // snapshot() の内容
let audio = null;          // AudioContext
let source = null;         // 再生中の AudioBufferSourceNode
let playing = false;
let drag = null;           // { pitch, step } 伸ばし中の音符

const $ = (id) => document.getElementById(id);
const canvas = $("roll");
const ctx = canvas.getContext("2d");

// ---- 起動 ------------------------------------------------------------------

async function boot() {
  const step = (text, percent) => {
    $("boot-text").textContent = text;
    $("boot-bar").style.width = `${percent}%`;
  };
  try {
    step("Python 本体を読み込んでいます…", 10);
    const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
    py = await loadPyodide({ indexURL: PYODIDE });
    step("作曲エンジンを展開しています…", 60);
    const zip = await fetch("picoseq-core.zip");
    if (!zip.ok) throw new Error(`エンジンを取得できません (${zip.status})`);
    await py.unpackArchive(await zip.arrayBuffer(), "zip");
    py.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
    bridge = py.pyimport("bridge");
    step("画面を準備しています…", 85);
    info = JSON.parse(bridge.catalog());
    buildControls();
    bridge.generate(42);
    refresh();
    step("準備完了", 100);
    $("boot").hidden = true;
    $("app").hidden = false;
  } catch (error) {
    $("boot-text").textContent = `起動に失敗しました: ${error.message}`;
    $("boot-bar").style.background = "var(--danger)";
  }
}

// ---- 画面の部品 ------------------------------------------------------------

function buildControls() {
  const scale = $("scale");
  for (const item of info.scales) {
    scale.append(new Option(item.label, item.id));
  }
  const key = $("key");
  info.keys.forEach((name, index) => key.append(new Option(name, index)));
  const beats = $("beats");
  for (const n of info.beats) beats.append(new Option(`${n}/4`, n));

  $("bpm").min = info.bpm[0];
  $("bpm").max = info.bpm[1];
  $("seed").min = info.seed[0];
  $("seed").max = info.seed[1];

  const parts = $("parts");
  info.parts.forEach((name, index) => {
    const btn = document.createElement("button");
    btn.textContent = `${index + 1} ${name}`;
    btn.style.color = PART_COLORS[index];
    btn.onclick = () => { bridge.select_part(index); refresh(); };
    parts.append(btn);
  });

  scale.onchange = () => { bridge.set_scale(scale.value); reflow(); };
  key.onchange = () => { bridge.set_key(Number(key.value)); reflow(); };
  beats.onchange = () => { bridge.set_beats(Number(beats.value)); reflow(); };
  $("bpm").oninput = () => {
    bridge.set_bpm(Number($("bpm").value));
    $("bpm-out").textContent = $("bpm").value;
    reflow();
  };
  $("seed").onchange = () => { bridge.generate(Number($("seed").value)); reflow(); };

  $("auto").onclick = () => { bridge.generate(randomSeed()); reflow(); };
  $("surprise").onclick = () => {
    const pick = (list) => list[Math.floor(Math.random() * list.length)];
    // 4/4 を厚めに (毎回変拍子だと聴き疲れる — デスクトップ版と同じ重み)
    const meters = [2, 3, 3, 4, 4, 4, 4, 5, 6, 7];
    bridge.surprise(pick(info.scales).id, Math.floor(Math.random() * 12),
                    pick(meters), 80 + Math.floor(Math.random() * 101),
                    randomSeed());
    reflow();
  };
  $("arrange").onclick = () => { bridge.arrange(); reflow(); };
  $("up").onclick = () => { bridge.transpose(12); reflow(); };
  $("down").onclick = () => { bridge.transpose(-12); reflow(); };
  $("reverse").onclick = () => { bridge.reverse(); reflow(); };
  $("clear-part").onclick = () => { bridge.clear_part(); reflow(); };
  $("clear").onclick = () => { bridge.clear_all(); reflow(); };
  $("tone").oninput = () => { bridge.set_part_tone(Number($("tone").value)); reflow(); };
  $("gate").oninput = () => { bridge.set_part_gate(Number($("gate").value)); reflow(); };
  $("play").onclick = () => (playing ? stop() : play());
  $("wav").onclick = downloadWav;
  $("save").onclick = downloadProject;
  $("load").onchange = loadProject;

  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", () => { drag = null; });
}

const randomSeed = () =>
  info.seed[0] + Math.floor(Math.random() * (info.seed[1] - info.seed[0]));

/** 状態を読み直して描き、鳴っていれば音も差し替える。 */
function reflow() {
  refresh();
  if (playing) play();          // 編集を鳴っている音へ反映する
}

function refresh() {
  view = JSON.parse(bridge.snapshot());
  $("scale").value = view.scale;
  $("key").value = view.key;
  $("beats").value = view.beats;
  $("bpm").value = view.bpm;
  $("bpm-out").textContent = view.bpm;
  $("seed").value = view.seed;
  const params = JSON.parse(bridge.part_settings());
  $("tone").value = params.tone;
  $("gate").value = params.gate;
  [...$("parts").children].forEach((btn, index) =>
    btn.setAttribute("aria-pressed", String(index === view.part)));
  $("status").textContent =
    `${view.count} 音 ・ コード進行 ${view.progression} ・ シード値 ${view.seed}`;
  draw();
}

// ---- ピアノロール ----------------------------------------------------------

function layout() {
  const [low, high] = info.pitch;
  const rows = high - low + 1;
  return {
    low, high, rows,
    cellW: (canvas.width - KEY_W) / view.steps,
    cellH: canvas.height / rows,
  };
}

function draw() {
  const { low, high, rows, cellW, cellH } = layout();
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (let row = 0; row < rows; row++) {          // 行 (音階内は明るく)
    const pitch = high - row;
    const degree = (pitch - (48 + view.key)) % 12;
    ctx.fillStyle = degree === 0 ? color("--root") : color("--row");
    ctx.fillRect(KEY_W, row * cellH, canvas.width - KEY_W, cellH);
  }
  ctx.strokeStyle = color("--line");
  ctx.lineWidth = 1;
  for (let step = 0; step <= view.steps; step += 2) {   // 拍線・小節線
    const x = KEY_W + step * cellW;
    const bar = step % (view.beats * 4) === 0;
    ctx.strokeStyle = bar ? color("--edge") : color("--line");
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height);
    ctx.stroke();
  }

  for (const note of view.notes) {                // 音符 (選択パートを前面へ)
    if (note.wave !== view.part) drawNote(note, cellW, cellH, high, 0.4);
  }
  for (const note of view.notes) {
    if (note.wave === view.part) drawNote(note, cellW, cellH, high, 1);
  }
  drawKeys(rows, cellH, color);
}

function drawNote(note, cellW, cellH, high, alpha) {
  const gain = info.softGain[note.soft] / 100;
  ctx.globalAlpha = alpha * gain;
  ctx.fillStyle = PART_COLORS[note.wave];
  const x = KEY_W + note.step * cellW + 1;
  const y = (high - note.pitch) * cellH + 1;
  ctx.fillRect(x, y, Math.max(2, note.dur * cellW - 2), Math.max(2, cellH - 2));
  ctx.globalAlpha = 1;
}

function drawKeys(rows, cellH, color) {
  ctx.font = `${Math.min(11, cellH)}px system-ui`;
  ctx.textBaseline = "middle";
  for (let row = 0; row < rows; row++) {
    const pitch = info.pitch[1] - row;
    const black = BLACK_KEYS.has(pitch % 12);
    ctx.fillStyle = black ? color("--key-black") : color("--key-white");
    ctx.fillRect(0, row * cellH, KEY_W, cellH);
    ctx.strokeStyle = color("--line");
    ctx.strokeRect(0, row * cellH, KEY_W, cellH);
    if (pitch % 12 === 0 && cellH >= 9) {
      ctx.fillStyle = color("--key-text");
      ctx.fillText(bridge.pitch_label(pitch), 4, row * cellH + cellH / 2);
    }
  }
}

/** マウス位置を (音高, ステップ) に直す。canvas は CSS で伸縮するので比率で戻す。 */
function locate(event) {
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * (canvas.width / rect.width);
  const y = (event.clientY - rect.top) * (canvas.height / rect.height);
  const { high, cellW, cellH } = layout();
  const pitch = high - Math.floor(y / cellH);
  if (x < KEY_W) return { zone: "key", pitch, step: 0 };
  const step = Math.floor((x - KEY_W) / cellW);
  if (step < 0 || step >= view.steps) return { zone: null, pitch, step };
  return { zone: "grid", pitch, step };
}

function onPointerDown(event) {
  const { zone, pitch, step } = locate(event);
  if (zone !== "grid") return;
  if (event.shiftKey) {                      // 強さを 1 段回す
    bridge.cycle_soft(pitch, step);
    reflow();
    return;
  }
  const placed = bridge.toggle_note(pitch, step);
  drag = placed ? { pitch, step } : null;    // 置いた直後だけ伸ばせる
  reflow();
}

function onPointerMove(event) {
  if (!drag) return;
  const { zone, step } = locate(event);
  if (zone !== "grid" || step < drag.step) return;
  bridge.resize_note(drag.pitch, drag.step, step - drag.step + 1);
  refresh();                                  // 伸ばし中は音を差し替えない
}

// ---- 音 --------------------------------------------------------------------

/** Python が返した 16bit PCM を AudioBuffer にする。 */
function toBuffer(bytes) {
  const pcm = new Int16Array(bytes.buffer, bytes.byteOffset,
                             bytes.byteLength / 2);
  const buffer = audio.createBuffer(1, pcm.length, info.rate);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
  return buffer;
}

function play() {
  if (!audio) audio = new AudioContext();
  const bytes = bridge.loop_pcm().toJs();
  if (!bytes.length) {
    $("status").textContent = "音符がありません。自動作成か、マス目をクリックしてください。";
    return;
  }
  const offset = source ? audio.currentTime - source._startedAt : 0;
  stopSource();
  source = audio.createBufferSource();
  source.buffer = toBuffer(bytes);
  source.loop = true;
  source.connect(audio.destination);
  // 編集で作り直したときは、鳴っていた位置から続ける (継ぎ目を感じにくい)
  source.start(0, offset % source.buffer.duration);
  source._startedAt = audio.currentTime - (offset % source.buffer.duration);
  playing = true;
  $("play").textContent = "■ 停止";
}

function stopSource() {
  if (source) {
    try { source.stop(); } catch { /* 既に止まっている */ }
    source.disconnect();
    source = null;
  }
}

function stop() {
  stopSource();
  playing = false;
  $("play").textContent = "▶ 再生";
}

// ---- 書き出し・読み込み ----------------------------------------------------

function saveBlob(data, name, type) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadWav() {
  saveBlob(bridge.wav_download().toJs(), `picoseq-${view.seed}.wav`,
           "audio/wav");
}

function downloadProject() {
  saveBlob(bridge.export_json(), `picoseq-${view.seed}.json`,
           "application/json");
}

async function loadProject(event) {
  const file = event.target.files[0];
  if (!file) return;
  const ok = bridge.import_json(await file.text());
  $("status").textContent = ok ? "読み込みました。" : "このファイルは読めません。";
  if (ok) reflow();
  event.target.value = "";
}

boot();
