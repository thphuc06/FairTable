// The voice page (plan task P3-11): microphone -> WebSocket -> Nova 2 Sonic -> speaker, with transcript and steps.
(() => {
  const $ = (id) => document.getElementById(id);
  const statusEl = $('status'), talk = $('talk'), steps = $('steps'), usage = $('usage');
  const startBtn = $('start'), stopBtn = $('stop');
  let ws = null, ctx = null, stream = null, node = null, ready = false;
  let outRate = 24000, nextAt = 0, playing = [];
  let line = { user: null, assistant: null };
  const stepRows = {};

  const setStatus = (text, cls) => { statusEl.textContent = text; statusEl.className = 'status ' + (cls || ''); };

  function addLine(role, text) {
    if (!line[role]) {
      const div = document.createElement('div');
      div.className = role === 'user' ? 'you' : 'bot';
      div.dataset.role = role;
      const who = document.createElement('b');
      who.textContent = role === 'user' ? 'You: ' : 'Assistant: ';
      const body = document.createElement('span');
      div.append(who, body);
      talk.append(div);
      line[role] = body;
    }
    line[role].textContent += text;
    talk.scrollTop = talk.scrollHeight;
  }

  function addStep(m) {
    if (m.phase === 'call') {
      const li = document.createElement('li');
      li.innerHTML = '<b></b> <span class="muted"></span> <span class="badge"></span><div class="muted out"></div>';
      li.querySelector('b').textContent = m.tool;
      li.querySelector('.muted').textContent = '(' + m.args + ')';
      steps.append(li);
      stepRows[m.id] = li;
    } else if (stepRows[m.id]) {
      const li = stepRows[m.id];
      const badge = li.querySelector('.badge');
      badge.textContent = m.ok ? 'ok' : 'refused';
      badge.className = 'badge ' + (m.ok ? 'ok' : 'no');
      li.querySelector('.out').textContent = m.summary;
    }
  }

  function play(b64) {
    const bin = atob(b64);
    const n = bin.length >> 1;
    const buf = ctx.createBuffer(1, n, outRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < n; i++) {
      let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
      if (v >= 32768) v -= 65536;
      data[i] = v / 32768;
    }
    const src = ctx.createBufferSource();
    src.buffer = buf; src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, nextAt);
    src.start(at); nextAt = at + buf.duration;
    playing.push(src);
    src.onended = () => { playing = playing.filter((s) => s !== src); };
  }

  function dropPlayback() {
    playing.forEach((s) => { try { s.stop(); } catch (e) { /* already stopped */ } });
    playing = []; nextAt = 0;
  }

  function onMessage(m) {
    switch (m.type) {
      case 'ready': outRate = m.out_rate; ready = true; setStatus('Listening. Speak now.', 'live'); break;
      case 'audio': play(m.pcm); break;
      case 'transcript': addLine(m.role, m.text); break;
      case 'transcript_end': line[m.role] = null; break;
      case 'barge_in': dropPlayback(); break;
      case 'state': if (m.speaking) setStatus('The assistant is speaking.', 'live'); else if (ready) setStatus('Listening. Speak now.', 'live'); break;
      case 'step': addStep(m); break;
      case 'usage': usage.textContent = m.input + ' tokens in, ' + m.output + ' out'; break;
      case 'error': setStatus(m.message, 'bad'); break;
      case 'closed': teardown('The call has ended.'); break;
    }
  }

  async function start() {
    startBtn.disabled = true;
    setStatus('Connecting...', '');
    try {
      ctx = new AudioContext();
      await ctx.audioWorklet.addModule('/voice/worklet.js');
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      setStatus('The microphone is not available: ' + (e && e.message ? e.message : e), 'bad');
      startBtn.disabled = false;
      return;
    }
    const source = ctx.createMediaStreamSource(stream);
    node = new AudioWorkletNode(ctx, 'fairtable-mic');
    const mute = ctx.createGain(); mute.gain.value = 0;
    source.connect(node); node.connect(mute); mute.connect(ctx.destination);
    ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/voice/ws');
    ws.binaryType = 'arraybuffer';
    node.port.onmessage = (e) => { if (ready && ws.readyState === WebSocket.OPEN) ws.send(e.data); };
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    ws.onclose = () => teardown('The call has ended.');
    ws.onerror = () => setStatus('The voice connection failed.', 'bad');
    stopBtn.disabled = false;
  }

  function teardown(text) {
    ready = false;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (ctx && ctx.state !== 'closed') ctx.close();
    stream = null; ctx = null; node = null; ws = null;
    startBtn.disabled = false; stopBtn.disabled = true;
    if (statusEl.className.indexOf('bad') < 0) setStatus(text, '');
    document.body.dataset.ended = '1';
  }

  function stop() {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'stop' }));
    teardown('The call has ended.');
  }

  startBtn.addEventListener('click', start);
  stopBtn.addEventListener('click', stop);
  if (new URLSearchParams(location.search).get('autostart') === '1') start();
})();
