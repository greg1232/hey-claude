"""Listen to what woke the speaker, and say whether it was right.

    ./label.sh

Fetches the clips off the Pi, opens a page in your browser, and plays them
one at a time. One key each: **y** if that really was somebody saying the
wake word, **n** if it wasn't. Your answers go back to the Pi and are what
the nightly retraining learns from.

Why this exists
---------------
The speaker labels its own firings, and it is good at the easy half: a
firing followed by silence was the television, one followed by a question
that got answered was real. The hard half it guesses at, and the guesses
matter — the first retrained model, measured on firings held back from the
fitting, caught 85% of the real ones and fired on 43% of the mistakes,
which is very much worse than the model it would have replaced.

A person listening to thirty clips fixes that in five minutes. Labels from
here are appended after the automatic ones, so they win.

There is nothing to install and nothing runs on the Pi. It copies the
clips down, serves them from this machine, and appends your answers when
you're finished.
"""

import argparse
import http.server
import json
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET_FILE = HERE / ".deploy-target"
REMOTE = "claude-speaker/state/wakes"
CACHE = HERE / "state" / "labelling"
# Where to serve the page. If something else already has this port — and
# on a developer's laptop something usually does — take whatever is free.
PORT = 8899
# As many as somebody will sit through in one go. --all for the lot.
MOST = 60

_answers: dict[int, int] = {}
_clips: list[dict] = []


def target() -> str:
    if not TARGET_FILE.is_file():
        raise SystemExit(
            "I don't know which Pi to ask. Deploy once first:\n\n"
            "    ./deploy.sh normal@192.168.4.95")
    return TARGET_FILE.read_text().strip()


def fetch(pi: str) -> None:
    """Copy the clips and the index down from the Pi."""
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"Fetching clips from {pi}...")
    done = subprocess.run(
        ["rsync", "-az", "--delete", f"{pi}:{REMOTE}/", f"{CACHE}/"],
        capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"Couldn't fetch:\n{done.stderr.strip()}")


def load(everything: bool) -> list[dict]:
    """The firings that still have their audio, newest first."""
    index = CACHE / "wakes.jsonl"
    if not index.exists():
        return []

    rows: dict[int, dict] = {}
    for line in index.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "n" in row:
            rows.setdefault(row["n"], {}).update(row)

    out = []
    for number, row in sorted(rows.items(), reverse=True):
        clip = CACHE / "audio" / f"{number:06d}.wav"
        if not clip.exists() or row.get("taught"):
            continue
        if not everything and row.get("by") == "person":
            continue
        out.append({
            "rank": _usefulness(row),
            "n": number,
            "score": row.get("score", 0),
            "at": (row.get("at") or "")[:16].replace("T", " "),
            "near": bool(row.get("near")),
            "repeated": bool(row.get("repeated")),
            "heard": row.get("heard") or "",
            "window": row.get("window") or "",
            "guess": row.get("label"),
            "why": row.get("why", ""),
        })

    # Most useful first, and only as many as a person will actually sit
    # through. Four hundred clips newest-first means half an hour of the
    # room being quiet before you reach anything that decides the model.
    out.sort(key=lambda c: c["rank"])
    return out if everything else out[:MOST]


# How much a person's answer is worth on each kind of clip, lowest first.
def _usefulness(row: dict) -> int:
    """What to put in front of somebody first.

    A firing nobody could label automatically is worth most: it is the
    case the machine could not decide and the one the model will be fitted
    on either way. A near miss that somebody repeated seconds later is
    next, because those are the recall failures and there is no other way
    to find them. Ordinary near misses are the room being a room.
    """
    if not row.get("near"):
        return 0 if row.get("label") is None else 1
    return 2 if row.get("repeated") else 3


def push(pi: str) -> int:
    """Send the answers back, as lines appended to the Pi's log."""
    if not _answers:
        return 0
    lines = "\n".join(json.dumps({
        "n": number, "label": label, "by": "person",
        "why": "listened to by a person",
    }) for number, label in sorted(_answers.items()))
    done = subprocess.run(
        ["ssh", pi, f"cat >> {REMOTE}/wakes.jsonl"],
        input=lines + "\n", text=True, capture_output=True)
    if done.returncode != 0:
        print(f"Couldn't save to the Pi:\n{done.stderr.strip()}")
        return 0
    return len(_answers)


class Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                    # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            return self._send(PAGE.encode(), "text/html; charset=utf-8")
        if path == "/clips":
            return self._send(json.dumps(_clips).encode(), "application/json")
        if path.startswith("/audio/"):
            clip = CACHE / "audio" / Path(path).name
            if clip.is_file():
                return self._send(clip.read_bytes(), "audio/wav")
        self.send_error(404)

    def do_POST(self):                                   # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            said = json.loads(self.rfile.read(length) or b"{}")
            _answers[int(said["n"])] = int(said["label"])
        except Exception:
            return self.send_error(400)
        self._send(b'{"ok":true}', "application/json")

    def _send(self, body: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


PAGE = r"""<!doctype html><meta charset=utf-8>
<title>What woke the speaker</title>
<style>
:root{color-scheme:light dark;--edge:#8884}
body{font:16px/1.5 system-ui,sans-serif;margin:0;display:grid;
     place-items:center;min-height:100vh}
main{width:min(46rem,92vw);padding:2rem 0}
h1{font-size:1.1rem;font-weight:600;margin:0 0 .25rem}
.sub{opacity:.65;font-size:.9rem;margin-bottom:1.5rem}
.card{border:1px solid var(--edge);border-radius:14px;padding:1.5rem}
.meta{display:flex;gap:1rem;flex-wrap:wrap;font-size:.85rem;opacity:.7;
      margin-bottom:1rem}
.tag{border:1px solid var(--edge);border-radius:999px;padding:.1rem .6rem}
.said{font-size:1.05rem;margin:.75rem 0;min-height:1.6rem}
.said b{font-weight:600}
audio{width:100%;margin:.5rem 0 1rem}
.row{display:flex;gap:.75rem}
button{flex:1;font:inherit;padding:.9rem;border-radius:10px;cursor:pointer;
       border:1px solid var(--edge);background:transparent}
button.yes{border-color:#3a3;color:#3a3}
button.no{border-color:#c44;color:#c44}
button:hover{background:#8881}
.skip{flex:0 0 auto;opacity:.6}
.bar{height:4px;background:#8883;border-radius:2px;margin-top:1.5rem}
.bar div{height:100%;background:#8888;border-radius:2px;width:0}
.done{text-align:center;padding:3rem 1rem}
kbd{border:1px solid var(--edge);border-radius:4px;padding:0 .35rem;
    font-size:.8em}
</style>
<main>
<h1>What woke the speaker</h1>
<div class=sub>Was that somebody saying <b>hey Claude</b>?
  <kbd>y</kbd> yes &middot; <kbd>n</kbd> no &middot;
  <kbd>space</kbd> play again &middot; <kbd>s</kbd> skip</div>
<div id=box></div>
<div class=bar><div id=bar></div></div>
</main>
<script>
let clips=[], at=0, done=0;
const box=document.getElementById('box'), bar=document.getElementById('bar');

fetch('/clips').then(r=>r.json()).then(c=>{clips=c;show()});

function show(){
  if(at>=clips.length){
    box.innerHTML='<div class="card done"><h1>That\'s all of them.</h1>'+
      '<div class=sub>'+done+' labelled. Close this and the answers go '+
      'back to the Pi.</div></div>';
    return;
  }
  const c=clips[at];
  const tags=[c.near?'nearly fired':'fired', 'score '+c.score.toFixed(3), c.at]
    .concat(c.repeated?['said again seconds later']:[])
    .concat(c.guess!=null?['it guessed '+(c.guess?'yes':'no')]:[]);
  box.innerHTML=
    '<div class=card><div class=meta>'+
      tags.map(t=>'<span class=tag>'+t+'</span>').join('')+
    '</div>'+
    '<audio id=a controls autoplay src="/audio/'+
      String(c.n).padStart(6,'0')+'.wav"></audio>'+
    '<div class=said>'+
      (c.window?'the two seconds sounded like <b>'+esc(c.window)+'</b><br>':'')+
      (c.heard?'what came next: <b>'+esc(c.heard)+'</b>':
        (c.near?'':'<i>nothing was said afterwards</i>'))+
    '</div>'+
    '<div class=row>'+
      '<button class=yes onclick="say(1)">Yes &mdash; hey Claude</button>'+
      '<button class=no onclick="say(0)">No &mdash; something else</button>'+
      '<button class=skip onclick="skip()">Skip</button>'+
    '</div></div>';
  bar.style.width=(100*at/clips.length)+'%';
}
function esc(s){return s.replace(/[<>&]/g,m=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[m]))}
function say(label){
  fetch('/',{method:'POST',body:JSON.stringify({n:clips[at].n,label})});
  done++; at++; show();
}
function skip(){at++; show()}
addEventListener('keydown',e=>{
  if(e.key==='y'||e.key==='1') say(1);
  else if(e.key==='n'||e.key==='0') say(0);
  else if(e.key==='s') skip();
  else if(e.key===' '){e.preventDefault();
    const a=document.getElementById('a'); if(a){a.currentTime=0;a.play()}}
});
</script>"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true",
                        help="include ones a person has already answered")
    parser.add_argument("--keep", action="store_true",
                        help="don't fetch again, use the clips already here")
    args = parser.parse_args()

    if not shutil.which("rsync"):
        raise SystemExit("This needs rsync, same as deploy does.")

    pi = target()
    if not args.keep:
        fetch(pi)

    global _clips
    _clips = load(args.all)
    if not _clips:
        raise SystemExit(
            "No clips to listen to. The speaker keeps the most recent "
            f"{'400' if True else ''} — give it a day with the wake word on.")

    try:
        server = http.server.HTTPServer(("127.0.0.1", PORT), Pages)
    except OSError:
        server = http.server.HTTPServer(("127.0.0.1", 0), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    where = f"http://127.0.0.1:{server.server_port}/"
    print(f"{len(_clips)} clips to listen to.\n  {where}\n"
          "  Ctrl-C when you've had enough — your answers are saved then.")
    webbrowser.open(where)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print()
    server.shutdown()

    sent = push(pi)
    print(f"Saved {sent} answer{'s' if sent != 1 else ''} to the Pi."
          if sent else "Nothing to save.")
    if sent:
        print("Now teach it:  ./relearn.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
