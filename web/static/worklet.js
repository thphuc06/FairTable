// Microphone to 16 kHz 16-bit mono PCM, in blocks of 100 ms, posted to the page (plan task P3-11).
class FairTableMic extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000; // input samples per output sample
    this.t = 0; this.sum = 0; this.count = 0;
    this.block = new Int16Array(1600); this.n = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i]; this.count += 1; this.t += 1;
      if (this.t >= this.ratio) {
        this.t -= this.ratio;
        const v = Math.max(-1, Math.min(1, this.sum / this.count));
        this.block[this.n++] = v < 0 ? v * 32768 : v * 32767;
        this.sum = 0; this.count = 0;
        if (this.n === this.block.length) {
          const out = this.block.buffer;
          this.port.postMessage(out, [out]);
          this.block = new Int16Array(1600); this.n = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('fairtable-mic', FairTableMic);
