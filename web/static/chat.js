// The chat page: scroll to the newest message, and show a "typing" indicator while the assistant answers.
// The page works without this script (every button is a plain form); this only makes the wait visible.
(function () {
  'use strict';
  var talk = document.getElementById('talk');
  if (talk) {
    talk.scrollTop = talk.scrollHeight;
  }
  var forms = document.querySelectorAll('form[data-busy]');
  for (var i = 0; i < forms.length; i++) {
    forms[i].addEventListener('submit', function () {
      if (talk && !talk.querySelector('.typing')) {
        var dots = document.createElement('div');
        dots.className = 'typing';
        dots.setAttribute('aria-label', 'The assistant is answering');
        dots.innerHTML = '<i></i><i></i><i></i>';
        talk.appendChild(dots);
        talk.scrollTop = talk.scrollHeight;
      }
      var buttons = document.querySelectorAll('form[data-busy] button');
      window.setTimeout(function () {
        for (var j = 0; j < buttons.length; j++) {
          buttons[j].disabled = true;
        }
      }, 0);
    });
  }
})();
