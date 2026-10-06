// The owner console: a slider for the agent share, with a live note on what it means in covers.
// The form works without this script (the number box is the real field); the slider only follows it.
(function () {
  'use strict';
  var form = document.querySelector('form[data-share]');
  if (!form) { return; }
  var number = form.querySelector('input[name=pct]');
  var seats = parseInt(form.getAttribute('data-seats'), 10);
  var current = parseInt(form.getAttribute('data-current'), 10);
  if (!number || !(seats >= 0)) { return; }

  var range = document.createElement('input');
  range.type = 'range';
  range.min = '0';
  range.max = '100';
  range.step = '1';
  range.setAttribute('aria-label', 'Share of seats that assistants may book, in percent');
  var note = document.createElement('p');
  note.className = 'muted';
  note.setAttribute('aria-live', 'polite');

  function show(value) {
    var covers = Math.floor(seats * value / 100);
    note.textContent = 'Assistants could book ' + covers + ' of ' + seats + ' covers a day (' + value + '%). ' +
      'The other ' + (seats - covers) + ' stay for phone and walk-in guests.' +
      (value === current ? ' This is the current setting.' : ' Press Save to apply it.');
  }

  function fromNumber() {
    var value = parseInt(number.value, 10);
    if (isNaN(value) || value < 0 || value > 100) { return; }
    range.value = String(value);
    show(value);
  }

  range.addEventListener('input', function () {
    number.value = range.value;
    show(parseInt(range.value, 10));
  });
  number.addEventListener('input', fromNumber);

  number.value = String(current);
  range.value = String(current);
  var label = number.closest('label');
  form.insertBefore(range, label);
  form.insertBefore(note, label);
  show(current);
})();
