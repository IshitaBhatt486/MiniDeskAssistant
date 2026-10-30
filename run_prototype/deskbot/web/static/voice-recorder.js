/* Push-to-talk recorder: microphone -> 16 kHz mono 16-bit WAV Blob (what /api/assistant/audio takes).
   Works in every current browser. Needs a secure context (https:// or localhost) - the server also
   listens on https://<robot>:8443 for exactly this reason.

   Why WAV in the browser instead of MediaRecorder: MediaRecorder gives webm/opus (Chrome) or mp4 (Safari);
   WAV is one format every speech-to-text backend (and faster-whisper on the Pi) reads without ffmpeg.
   16 kHz mono is what Whisper uses internally; 15 s = 480 kB. */
window.VoiceRecorder = (() => {
  "use strict";
  const TARGET_RATE = 16000;
  const MAX_SECONDS = 25;

  function downsample(chunks, inRate) {
    let len = 0;
    for (const c of chunks) len += c.length;
    const input = new Float32Array(len);
    let o = 0;
    for (const c of chunks) { input.set(c, o); o += c.length; }
    if (inRate === TARGET_RATE) return input;
    const ratio = inRate / TARGET_RATE;
    const out = new Float32Array(Math.floor(input.length / ratio));
    for (let i = 0; i < out.length; i++) {
      // average the input samples this output sample covers: a cheap low-pass against aliasing
      const start = Math.floor(i * ratio), end = Math.min(input.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end; j++) sum += input[j];
      out[i] = sum / Math.max(1, end - start);
    }
    return out;
  }

  function encodeWav(samples) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const str = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, TARGET_RATE, true); v.setUint32(28, TARGET_RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  function supported() {
    return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function whyUnsupported() {
    if (!window.isSecureContext) return "insecure";
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return "nomic";
    return null;
  }

  class Recorder {
    constructor(onLevel) { this.onLevel = onLevel; this.recording = false; }

    async start() {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new Ctx();
      this.src = this.ctx.createMediaStreamSource(this.stream);
      this.proc = this.ctx.createScriptProcessor(4096, 1, 1);
      this.chunks = [];
      this.started = performance.now();
      this.proc.onaudioprocess = (e) => {
        const d = e.inputBuffer.getChannelData(0);
        this.chunks.push(new Float32Array(d));
        if (this.onLevel) {
          let peak = 0;
          for (let i = 0; i < d.length; i += 8) peak = Math.max(peak, Math.abs(d[i]));
          this.onLevel(peak);
        }
        if ((performance.now() - this.started) / 1000 > MAX_SECONDS) this.stop();
      };
      this.src.connect(this.proc);
      this.proc.connect(this.ctx.destination);   // ScriptProcessor only runs while connected
      this.recording = true;
    }

    async stop() {
      if (!this.recording) return null;
      this.recording = false;
      try { this.proc.disconnect(); this.src.disconnect(); } catch { /* already disconnected */ }
      this.stream.getTracks().forEach((t) => t.stop());
      const rate = this.ctx.sampleRate;
      await this.ctx.close();
      return { blob: encodeWav(downsample(this.chunks, rate)), seconds: (performance.now() - this.started) / 1000 };
    }
  }

  return { Recorder, supported, whyUnsupported };
})();
