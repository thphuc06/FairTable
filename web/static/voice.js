// The voice page (plan task P3-11): microphone -> WebSocket -> Nova 2 Sonic -> speaker, with transcript and steps.
(() => {
  const $ = (id) => document.getElementById(id);
  const statusEl = $('status'), talk = $('talk'), usage = $('usage');
  const startBtn = $('start'), stopBtn = $('stop');
  const youPill = $('ind-you'), botPill = $('ind-bot'), levelBar = $('level');
  const VOICE_LEVEL = 0.02, HOLD_MS = 400; // microphone level (0..1) that counts as speaking; how long the light stays on
  let micLevel = 0, lastVoice = 0;
  let ws = null, ctx = null, stream = null, node = null, ready = false;
  const LEAD_S = 0.3; // head start for the assistant's voice, in seconds
  let outRate = 24000, nextAt = 0, playing = [];
  let line = { user: null, assistant: null };
  const stepRows = {};
  let pending = 0; // tool calls that have not come back yet
  const WORKING = {
    restaurant_search: 'Looking for the restaurant', availability_check: 'Checking free tables',
    reservation_hold: 'Holding the table', reservation_confirm: 'Booking the table',
    reservation_manage: 'Updating the booking', waitlist_watch: 'Adding you to the list',
    waitlist_status: 'Checking the list',
  };
  let turnBox = null; // the box of tool calls under the assistant's answer to the diner's latest request

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
      if (role === 'user') {
        turnBox = null; // a new request starts a new turn
        talk.append(div);
      } else if (turnBox) {
        talk.insertBefore(div, turnBox); // the answer goes above the tool calls that led to it
      } else {
        talk.append(div);
      }
      line[role] = body;
    }
    line[role].textContent += text;
    talk.scrollTop = talk.scrollHeight;
  }

  function stepsBox() {
    if (!turnBox) {
      turnBox = document.createElement('div');
      turnBox.className = 'stepsbox';
      turnBox.innerHTML = '<div class="muted">Tool calls</div><ol></ol>';
      talk.append(turnBox);
    }
    return turnBox.querySelector('ol');
  }

  function addStep(m) {
    if (m.phase === 'call') {
      const li = document.createElement('li');
      li.innerHTML = '<b></b> <span class="muted"></span> <span class="badge"></span><div class="muted out"></div>';
      li.querySelector('b').textContent = m.tool;
      li.querySelector('.muted').textContent = '(' + m.args + ')';
      stepsBox().append(li);
      stepRows[m.id] = li;
      pending += 1;
      setStatus((WORKING[m.tool] || 'Working on it') + '...', 'work'); // the model is silent while it waits for the server
    } else if (stepRows[m.id]) {
      const li = stepRows[m.id];
      const badge = li.querySelector('.badge');
      badge.textContent = m.ok ? 'ok' : 'refused';
      badge.className = 'badge ' + (m.ok ? 'ok' : 'no');
      li.querySelector('.out').textContent = m.summary;
      pending = Math.max(0, pending - 1);
      if (pending === 0 && ready) setStatus('Listening. Speak now.', 'live');
    }
    talk.scrollTop = talk.scrollHeight;
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
    // The model's voice arrives in 80 ms pieces at about the speed of speech, in small bursts (measured: gaps of up
    // to 0.4 s between pieces). Start each answer, and restart after the queue ran dry, with a short head start so
    // that the pieces play back to back instead of with a click or a hole between them.
    if (nextAt < ctx.currentTime) nextAt = ctx.currentTime + LEAD_S;
    const at = nextAt;
    src.start(at); nextAt = at + buf.duration;
    playing.push(src);
    src.onended = () => { playing = playing.filter((s) => s !== src); };
  }

  // Lights for who is talking: the microphone level for you, the playback queue for the assistant.
  function level(buffer) {
    const samples = new Int16Array(buffer);
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    return samples.length ? Math.sqrt(sum / samples.length) / 32768 : 0;
  }

  function indicators() {
    if (!ctx) return;
    const now = performance.now();
    if (micLevel > VOICE_LEVEL) lastVoice = now;
    youPill.classList.toggle('on', now - lastVoice < HOLD_MS);
    botPill.classList.toggle('on', ctx.currentTime < nextAt);
    levelBar.style.width = Math.min(100, Math.round(micLevel * 400)) + '%';
    micLevel *= 0.9;
    requestAnimationFrame(indicators);
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
      case 'state': if (m.speaking) setStatus('The assistant is speaking.', 'live'); else if (ready && pending === 0) setStatus('Listening. Speak now.', 'live'); break;
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
    node.port.onmessage = (e) => {
      micLevel = Math.max(micLevel, level(e.data));
      if (ready && ws.readyState === WebSocket.OPEN) ws.send(e.data);
    };
    requestAnimationFrame(indicators);
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
    youPill.classList.remove('on'); botPill.classList.remove('on'); levelBar.style.width = '0';
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
