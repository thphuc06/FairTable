// Recomputes a Fair Drop in the visitor's browser (Web Crypto). It mirrors server/domain/fairdrop.py: verify_audit.
//   commitment = SHA-256(seed)            order = entries sorted by (HMAC-SHA256(seed, entry id), entry id)
// Nothing is sent anywhere. The same file is loaded by Node in the tests (module.exports below).
(function () {
  'use strict';

  var encoder = new TextEncoder();

  function toHex(buffer) {
    var out = '';
    var bytes = new Uint8Array(buffer);
    for (var i = 0; i < bytes.length; i++) {
      out += bytes[i].toString(16).padStart(2, '0');
    }
    return out;
  }

  function fromHex(text) {
    if (typeof text !== 'string' || text.length === 0 || text.length % 2 !== 0 || !/^[0-9a-fA-F]+$/.test(text)) {
      throw new Error('the seed is not a hexadecimal string');
    }
    var out = new Uint8Array(text.length / 2);
    for (var i = 0; i < out.length; i++) {
      out[i] = parseInt(text.substr(i * 2, 2), 16);
    }
    return out;
  }

  async function sha256Hex(bytes) {
    return toHex(await crypto.subtle.digest('SHA-256', bytes));
  }

  async function drawKey(seed, entryId) {
    var key = await crypto.subtle.importKey('raw', seed, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    return toHex(await crypto.subtle.sign('HMAC', key, encoder.encode(entryId)));
  }

  function check(ok, passText, failText) {
    return { ok: ok, text: ok ? passText : failText };
  }

  // Returns a list of { ok, text }. All ok means the draw checks out.
  async function verifyAudit(audit) {
    var results = [];
    try {
      var seed = fromHex(audit.seed);
      results.push(check(
        (await sha256Hex(seed)) === audit.commitment,
        'The revealed seed matches the commitment published before the draw.',
        'The revealed seed does NOT match the commitment published before the draw.'));

      var entries = audit.entries.slice();
      results.push(check(
        new Set(entries).size === entries.length,
        'Every entry appears once.', 'An entry appears more than once.'));

      var keys = {};
      var wrongKeys = [];
      for (var i = 0; i < audit.order.length; i++) {
        var row = audit.order[i];
        keys[row.entry_id] = await drawKey(seed, row.entry_id);
        if (keys[row.entry_id] !== row.draw_key) {
          wrongKeys.push(row.entry_id);
        }
      }
      results.push(check(
        wrongKeys.length === 0,
        'Every draw key equals HMAC-SHA256(seed, entry id).',
        'Wrong draw key for ' + wrongKeys.length + ' entr' + (wrongKeys.length === 1 ? 'y.' : 'ies.')));

      var expected = [];
      for (var e = 0; e < entries.length; e++) {
        expected.push({ id: entries[e], key: await drawKey(seed, entries[e]) });
      }
      expected.sort(function (a, b) {
        if (a.key !== b.key) { return a.key < b.key ? -1 : 1; }
        return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
      });
      var listed = audit.order.map(function (r) { return r.entry_id; });
      var inOrder = listed.length === expected.length && expected.every(function (x, n) { return x.id === listed[n]; });
      results.push(check(
        inOrder,
        'The published order is the entries sorted by draw key, lowest first.',
        'The published order is NOT the entries sorted by draw key.'));

      var winners = audit.order.filter(function (r) { return r.outcome === 'won'; }).map(function (r) { return r.entry_id; });
      var winnersOk = JSON.stringify(winners) === JSON.stringify(audit.winners) && winners.length <= audit.capacity;
      results.push(check(
        winnersOk,
        'The winners are exactly the entries marked won, and there are no more than the places (' + audit.capacity + ').',
        'The winners do not match the results, or there are more winners than places.'));

      var won = 0;
      var fair = true;
      audit.order.forEach(function (r) {
        if (r.outcome === 'won') {
          won += 1;
        } else if (r.outcome === 'lost' && won < audit.capacity) {
          fair = false;
        } else if (r.outcome === 'skipped' && !r.reason) {
          fair = false;
        }
      });
      results.push(check(
        fair,
        'Nobody was passed over: an entry only lost after the places were full, and every skip has a reason.',
        'Someone was passed over without a reason.'));
    } catch (error) {
      results.push({ ok: false, text: 'The record could not be read: ' + error.message });
    }
    return results;
  }

  // Where a ticket is in the record. The code may be the whole ticket or only its 64-character fingerprint.
  function findTicket(audit, code) {
    var wanted = String(code || '').trim().toLowerCase();
    if (!wanted) { return null; }
    for (var i = 0; i < audit.order.length; i++) {
      var id = String(audit.order[i].entry_id).toLowerCase();
      var digest = id.slice(id.lastIndexOf('~') + 1);
      if (id === wanted || digest === wanted) {
        return { position: i + 1, of: audit.order.length, outcome: audit.order[i].outcome, entry_id: audit.order[i].entry_id };
      }
    }
    return null;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { verifyAudit: verifyAudit, findTicket: findTicket };
    return;
  }

  // ---- the page
  function show(results) {
    var list = document.getElementById('checks');
    list.textContent = '';
    results.forEach(function (r) {
      var li = document.createElement('li');
      li.className = r.ok ? 'pass' : 'fail';
      li.textContent = (r.ok ? '✓ ' : '✗ ') + r.text;
      list.appendChild(li);
    });
  }

  function run(audit) {
    if (!window.crypto || !window.crypto.subtle) {
      show([{ ok: false, text: 'Your browser allows this check only on HTTPS or on localhost.' }]);
      return;
    }
    verifyAudit(audit).then(show);
  }

  var data = document.getElementById('audit-data');
  if (!data) { return; }
  var audit = JSON.parse(data.textContent);

  document.getElementById('verify-btn').addEventListener('click', function () { run(audit); });

  document.getElementById('tamper-btn').addEventListener('click', function () {
    var copy = JSON.parse(JSON.stringify(audit));
    if (copy.order.length > 1) {
      var first = copy.order[0];
      copy.order[0] = copy.order[1];
      copy.order[1] = first;
    } else if (copy.order.length === 1) {
      copy.order[0].outcome = copy.order[0].outcome === 'won' ? 'lost' : 'won';
    }
    run(copy);
  });

  document.getElementById('ticket-btn').addEventListener('click', function () {
    var found = findTicket(audit, document.getElementById('ticket-input').value);
    var out = document.getElementById('ticket-result');
    document.querySelectorAll('tr.mine').forEach(function (r) { r.classList.remove('mine'); });
    if (!found) {
      out.textContent = 'This ticket is not in this draw.';
      return;
    }
    var row = document.querySelector("tr[data-entry='" + found.entry_id.replace(/'/g, '') + "']");
    if (row) { row.classList.add('mine'); row.scrollIntoView({ block: 'center' }); }
    out.textContent = 'Your ticket is number ' + found.position + ' of ' + found.of + ' in the draw order: ' +
      (found.outcome === 'won' ? 'you won this seat.' : found.outcome === 'lost' ? 'you were not picked.' : 'you were drawn but could not be given the seat (' + found.outcome + ').');
  });

  document.getElementById('paste-btn').addEventListener('click', function () {
    try {
      run(JSON.parse(document.getElementById('paste').value));
    } catch (error) {
      show([{ ok: false, text: 'That is not valid JSON: ' + error.message }]);
    }
  });
})();
