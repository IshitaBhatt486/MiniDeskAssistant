"""
"Read this for me": text from a picture, read aloud, saved to a file, optionally summarised or turned into flashcards.

Where the picture comes from:
    camera     "read this for me": the robot's newest frame. The camera runs at 320x240 for speed, which is only
               enough for big print held close (about 20-30 cm); for a whole page use one of the two below
    upload     the dashboard's Reader card (a phone's camera works: the file picker offers it)
    Telegram   send the bot a photo (telegram.py)

Reading (settings "ocr", default "auto" = the first that works, in this order, local first):
    ollama     a local vision model (qwen2.5vl:3b) through local_llm.py: free, private, handles photos and some
               handwriting; ~10-60 s on a laptop, too slow for a Pi 4 (run Ollama on the laptop)
    tesseract  Tesseract OCR (`sudo apt install tesseract-ocr`): free, private, fast; printed text only, wants a flat,
               well-lit page
    claude     Claude's vision (paid, sends the image to Anthropic; skipped in local-only mode)

Summaries / flashcards ("summarise this", "make flashcards from this"): ollama text model, else Claude, else none.

Files: data/reads/<date>_<time>.txt (+ .summary.txt / .flashcards.txt), listed on the dashboard and downloadable.
The robot reads the first ~2,500 characters aloud in sentence chunks (the speaker keeps at most 6 queued), then
says the rest is saved.
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

MAX_IMAGE = 8_000_000
SPEAK_CHARS = 2500


def jpeg_from_frame(image):
    import cv2
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("couldn't encode the camera frame")
    return buf.tobytes()


def tesseract_read(jpeg):
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("Tesseract isn't installed (sudo apt install tesseract-ocr)")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "page.jpg"
        p.write_bytes(jpeg)
        r = subprocess.run([exe, str(p), "stdout", "--psm", "3"], capture_output=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError("Tesseract failed: " + r.stderr.decode(errors="replace")[:120])
        return r.stdout.decode("utf-8", errors="replace").strip()


def chunks(text, size=450):
    """Sentence-sized pieces for the speaker."""
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+|\n{2,}", " ".join(text.split("\n"))):
        if len(cur) + len(sent) > size and cur:
            parts.append(cur.strip())
            cur = ""
        cur += " " + sent
    if cur.strip():
        parts.append(cur.strip())
    return parts


class Reader:
    def __init__(self, folder: Path, settings, ollama=None, claude=None, model=lambda: "claude-haiku-5-5",
                 allow_cloud=lambda: True, on_usage=None, clock=datetime.now):
        self.folder = Path(folder)
        self.settings = settings          # fn() -> {"ocr", "summary"}
        self.ollama, self.claude, self.model = ollama, claude, model
        self.allow_cloud = allow_cloud
        self.on_usage = on_usage
        self.clock = clock
        self.busy = False
        self.last = None

    # -- backends --

    def _claude_vision(self, jpeg, prompt):
        if self.claude is None or not self.allow_cloud() or not self.claude.available():
            raise RuntimeError("Claude isn't available")
        resp = self.claude.client().beta.messages.create(
            model=self.model(), max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()}},
                {"type": "text", "text": prompt}]}])
        if self.on_usage and getattr(resp, "usage", None) is not None:
            u = resp.usage
            self.on_usage({"input": u.input_tokens or 0, "output": u.output_tokens or 0, "model": self.model()})
        return next((b.text for b in resp.content if b.type == "text"), "").strip()

    def ocr_order(self):
        pref = self.settings().get("ocr", "auto")
        order = ["ollama", "tesseract", "claude"]
        if pref in order:
            order.remove(pref)
            order.insert(0, pref)
        if not self.allow_cloud():
            order.remove("claude")
        return order

    def read_text(self, jpeg):
        """(text, backend). Raises RuntimeError listing why every backend failed."""
        errors = []
        for name in self.ocr_order():
            try:
                if name == "ollama":
                    if self.ollama is None:
                        raise RuntimeError("no Ollama")
                    text = self.ollama.read_image(jpeg)
                elif name == "tesseract":
                    text = tesseract_read(jpeg)
                else:
                    text = self._claude_vision(jpeg, "Transcribe all the text in this image exactly, keeping line breaks. "
                                                     "Output only the text, or NO TEXT if there is none.")
                if text and text.strip().upper() != "NO TEXT":
                    return text.strip(), name
                errors.append(f"{name}: no text found")
            except Exception as exc:
                errors.append(f"{name}: {exc}"[:120])
        raise RuntimeError("; ".join(errors) or "no reader available")

    def make(self, text, kind):
        """A summary or flashcards: (result, backend) or (None, None)."""
        if self.ollama is not None:
            try:
                return self.ollama.summarise(text, kind), "ollama"
            except Exception:
                pass
        if self.claude is not None and self.allow_cloud() and self.claude.available():
            ask = {"summary": "Summarise this in 2-4 short spoken sentences.",
                   "flashcards": "Make up to 6 flashcards from this, one per line as 'Q: ... | A: ...'."}[kind]
            resp = self.claude.client().beta.messages.create(model=self.model(), max_tokens=600,
                                                             messages=[{"role": "user", "content": f"{ask}\n\n{text[:8000]}"}])
            if self.on_usage and getattr(resp, "usage", None) is not None:
                self.on_usage({"input": resp.usage.input_tokens or 0, "output": resp.usage.output_tokens or 0, "model": self.model()})
            return next((b.text for b in resp.content if b.type == "text"), "").strip(), "claude"
        return None, None

    # -- one reading --

    def read(self, jpeg, source="camera", extra=None, speak=None):
        """Read, save and (if speak is given) say it. extra: None | "summary" | "flashcards". Returns the record."""
        if len(jpeg) > MAX_IMAGE:
            raise ValueError("That picture is too big (8 MB at most)")
        self.busy = True
        try:
            t0 = time.perf_counter()
            text, backend = self.read_text(jpeg)
            stamp = self.clock().strftime("%Y-%m-%d_%H-%M-%S")
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / f"{stamp}.txt"
            path.write_text(text + "\n", encoding="utf-8")
            rec = {"file": path.name, "chars": len(text), "backend": backend, "source": source, "t": time.time(),
                   "preview": text[:200], "extra": None}
            if extra:
                result, by = self.make(text, extra)
                if result:
                    (self.folder / f"{stamp}.{extra}.txt").write_text(result + "\n", encoding="utf-8")
                    rec.update(extra={"kind": extra, "file": f"{stamp}.{extra}.txt", "by": by, "text": result})
            rec["ms"] = round((time.perf_counter() - t0) * 1000)
            self.last = rec
            if speak:
                if extra and rec["extra"]:
                    speak(rec["extra"]["text"] if extra == "summary" else f"I made {rec['extra']['text'].count('Q:')} flashcards. They're saved.")
                else:
                    said = 0
                    for part in chunks(text):
                        if said + len(part) > SPEAK_CHARS:
                            speak("That's the first part. The whole text is saved on the dashboard.")
                            break
                        speak(part)
                        said += len(part)
            return rec
        finally:
            self.busy = False

    def read_async(self, jpeg_fn, source, extra, speak, on_error):
        """Run read() on a thread (OCR can take a minute); jpeg_fn() supplies the picture."""
        def go():
            try:
                self.read(jpeg_fn(), source, extra, speak)
            except Exception as exc:
                on_error(str(exc))
        threading.Thread(target=go, name="reader", daemon=True).start()

    def files(self, limit=30):
        if not self.folder.exists():
            return []
        out = []
        for p in sorted(self.folder.glob("*.txt"), reverse=True)[:limit]:
            out.append({"name": p.name, "kb": round(p.stat().st_size / 1024, 1),
                        "preview": p.read_text(encoding="utf-8", errors="replace")[:140]})
        return out

    def file(self, name):
        """A saved text by name (only plain names inside the folder)."""
        if not re.fullmatch(r"[\w\-.]+\.txt", name or ""):
            return None
        p = (self.folder / name).resolve()
        return p if p.parent == self.folder.resolve() and p.exists() else None

    def status(self):
        return {"busy": self.busy, "last": self.last, "files": self.files(),
                "ocr_order": self.ocr_order(), "tesseract": bool(shutil.which("tesseract")),
                "ollama_vision": bool(self.ollama and self.ollama.has(self.ollama.settings().get("vision_model", "qwen2.5vl:3b")))}
