/* Quiz "Perfil do Investidor Caixa" — reginaldorosso.com.br
   Uso: <div id="quizInvestidor"></div><script src="/quiz-investidor.js" defer></script>
   Envia o lead (com respostas e prioridade) pelo mesmo Web3Forms do formulário de contato. */
(function () {
  var root = document.getElementById('quizInvestidor');
  if (!root) return;

  var ACCESS_KEY = 'efe281ee-c450-4faa-bfe0-dbb185f349ab';
  var WA = '5551991104976';

  var P = [
    { k: 'objetivo', q: 'Qual é o seu objetivo principal com imóveis da Caixa?',
      o: ['Revender com lucro (flip)', 'Alugar e ter renda mensal', 'Morar', 'Ainda estou avaliando'] },
    { k: 'valor', q: 'Quanto você pretende investir no próximo arremate?',
      o: ['Até R$ 150 mil', 'R$ 150 a 300 mil', 'R$ 300 a 600 mil', 'Acima de R$ 600 mil'] },
    { k: 'pagamento', q: 'Como pretende pagar?',
      o: ['À vista', 'Financiamento Caixa', 'FGTS + financiamento', 'Ainda não sei'] },
    { k: 'experiencia', q: 'Você já arrematou imóvel em leilão ou venda direta?',
      o: ['Nunca, seria o primeiro', '1 ou 2 vezes', 'Mais de 3 vezes, invisto com frequência'] },
    { k: 'regiao', q: 'Em que região você quer investir?',
      o: ['Porto Alegre e região metropolitana', 'Interior do RS', 'Grande Florianópolis / litoral de SC', 'Sul de SC (Criciúma e região)', 'Sem preferência, quero onde der mais lucro'] },
    { k: 'prazo', q: 'Quando pretende fazer o próximo lance?',
      o: ['Nos próximos 30 dias', 'Em até 3 meses', 'Em até 6 meses', 'Só estou pesquisando'] }
  ];

  var css = '' +
    '.qz{max-width:1200px;margin:0 auto;padding:70px 22px}' +
    '.qz-box{display:grid;grid-template-columns:1fr 1.25fr;gap:44px;align-items:center;background:linear-gradient(160deg,var(--navy2,#1a2d4a),var(--navy-d,#081120));border:1px solid rgba(201,161,90,.3);border-radius:22px;padding:46px;color:var(--cream,#f3ead4);box-shadow:0 24px 60px rgba(8,17,32,.25)}' +
    '.qz-k{color:var(--gold,#c9a15a);font-size:.74rem;font-weight:700;letter-spacing:.2em;text-transform:uppercase;margin-bottom:12px}' +
    '.qz h2{font-family:var(--serif,Georgia,serif);color:#fff;font-size:clamp(1.7rem,3vw,2.3rem);font-weight:600;line-height:1.12;margin-bottom:14px}' +
    '.qz h2 em{color:var(--gold-soft,#e3cd9c);font-style:italic}' +
    '.qz-intro p{color:rgba(243,234,212,.82);margin-bottom:10px}' +
    '.qz-intro ul{list-style:none;margin-top:16px}.qz-intro li{padding:5px 0 5px 26px;position:relative;font-size:.95rem}' +
    '.qz-intro li:before{content:"✓";position:absolute;left:0;color:var(--gold,#c9a15a);font-weight:700}' +
    '.qz-card{background:var(--card,#fff);border-radius:16px;padding:30px;color:var(--ink2,#3c4b64);min-height:400px;display:flex;flex-direction:column}' +
    '.qz-bar{height:5px;background:var(--line,#e7e1d2);border-radius:5px;overflow:hidden;margin-bottom:8px}' +
    '.qz-bar i{display:block;height:100%;background:var(--gold,#c9a15a);transition:width .35s}' +
    '.qz-step{font-size:.75rem;color:var(--muted,#6d7889);font-weight:600;letter-spacing:.08em;text-transform:uppercase;margin-bottom:16px}' +
    '.qz-q{font-family:var(--serif,Georgia,serif);color:var(--ink,#14213a);font-size:1.3rem;font-weight:600;line-height:1.25;margin-bottom:18px}' +
    '.qz-opts{display:grid;gap:10px}' +
    '.qz-opt{text-align:left;background:var(--bg,#f7f4ee);border:1.5px solid var(--line,#e7e1d2);border-radius:11px;padding:13px 16px;font:600 .95rem var(--sans,system-ui);color:var(--ink,#14213a);cursor:pointer;transition:.15s}' +
    '.qz-opt:hover,.qz-opt:focus-visible{border-color:var(--gold,#c9a15a);background:#fff;outline:none}' +
    '.qz-opt.sel{border-color:var(--gold,#c9a15a);background:rgba(201,161,90,.12)}' +
    '.qz-back{margin-top:auto;padding-top:16px;background:none;border:0;color:var(--muted,#6d7889);font:600 .85rem var(--sans,system-ui);cursor:pointer;align-self:flex-start}' +
    '.qz-perfil{background:rgba(201,161,90,.12);border-left:3px solid var(--gold,#c9a15a);border-radius:8px;padding:12px 14px;margin-bottom:16px;font-size:.92rem}' +
    '.qz-perfil b{display:block;font-family:var(--serif,Georgia,serif);color:var(--ink,#14213a);font-size:1.15rem}' +
    '.qz-form input[type=text],.qz-form input[type=tel],.qz-form input[type=email]{width:100%;padding:12px 14px;border:1.5px solid var(--line,#e7e1d2);border-radius:10px;font:400 .95rem var(--sans,system-ui);margin-bottom:10px;background:#fff;color:var(--ink,#14213a)}' +
    '.qz-form input:focus{outline:none;border-color:var(--gold,#c9a15a)}' +
    '.qz-lgpd{display:flex;gap:9px;align-items:flex-start;font-size:.8rem;color:var(--muted,#6d7889);margin:4px 0 14px}' +
    '.qz-lgpd input{margin-top:3px;accent-color:var(--gold,#c9a15a)}.qz-lgpd a{text-decoration:underline}' +
    '.qz-send{width:100%;background:var(--gold,#c9a15a);color:var(--navy,#0f1e33);border:0;border-radius:10px;padding:14px;font:700 .95rem var(--sans,system-ui);letter-spacing:.04em;cursor:pointer}' +
    '.qz-send:disabled{opacity:.6;cursor:wait}' +
    '.qz-msg{font-size:.88rem;margin-top:10px}.qz-msg.err{color:#b3261e}' +
    '.qz-ok{text-align:center;margin:auto 0}.qz-ok .ic{font-size:2.4rem;color:var(--gold,#c9a15a)}' +
    '.qz-ok h3{font-family:var(--serif,Georgia,serif);color:var(--ink,#14213a);font-size:1.4rem;margin:8px 0}' +
    '.qz-ok a{display:inline-block;margin-top:14px;background:var(--navy,#0f1e33);color:#fff;padding:11px 20px;border-radius:10px;font-weight:600}' +
    '@media(max-width:860px){.qz{padding:50px 16px}.qz-box{grid-template-columns:1fr;padding:26px 18px;gap:24px}.qz-card{padding:22px;min-height:0}}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  root.innerHTML =
    '<section class="qz" id="perfil-investidor" aria-labelledby="qzTitulo"><div class="qz-box">' +
      '<div class="qz-intro">' +
        '<div class="qz-k">Perfil do investidor · 1 minuto</div>' +
        '<h2 id="qzTitulo">Descubra o seu <em>perfil de arrematante</em></h2>' +
        '<p>Responda 6 perguntas rápidas e receba só as oportunidades da Caixa que combinam com o seu objetivo, orçamento e região.</p>' +
        '<ul><li>Imóveis filtrados para o seu perfil</li><li>Aviso antes dos leilões que valem a pena</li><li>Relatório Confidencial grátis quando escolher o imóvel</li></ul>' +
      '</div>' +
      '<div class="qz-card" id="qzCard" aria-live="polite"></div>' +
    '</div></section>';

  var card = document.getElementById('qzCard');
  var resp = {}, i = 0, enviado = false;
  function ev(n, p) { try { if (window.gtag) gtag('event', n, p || {}); } catch (e) {} }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function perfil() {
    var o = resp.objetivo || '', v = P[1].o.indexOf(resp.valor), pz = P[5].o.indexOf(resp.prazo),
        pg = resp.pagamento, ex = P[3].o.indexOf(resp.experiencia);
    var nome = /flip/.test(o) ? 'Investidor de Revenda' : /Alugar/.test(o) ? 'Investidor de Renda' :
               /Morar/.test(o) ? 'Comprador para Moradia' : 'Investidor em Formação';
    if (resp.regiao === P[4].o[4]) nome += ' · foco em rentabilidade';
    var pts = (pz === 0 ? 3 : pz === 1 ? 2 : pz === 2 ? 1 : 0) + (v >= 2 ? 2 : v === 1 ? 1 : 0) +
              (pg === 'À vista' ? 2 : pg === 'Ainda não sei' ? 0 : 1) + (ex === 2 ? 1 : 0);
    var prio = pts >= 6 ? 'QUENTE' : pts >= 3 ? 'MORNO' : 'FRIO';
    var dica = pz === 0 ? 'Você está pronto para agir: vou te mandar as melhores oportunidades abertas agora.' :
               pz === 3 ? 'Sem pressa: vou te mandar oportunidades selecionadas para você acompanhar o mercado.' :
               'Vou montar uma seleção para o seu prazo e te avisar antes dos leilões certos.';
    return { nome: nome, prio: prio, pts: pts, dica: dica };
  }

  function render() {
    if (i < P.length) {
      var p = P[i], h = '<div class="qz-bar"><i style="width:' + Math.round(i / P.length * 100) + '%"></i></div>' +
        '<div class="qz-step">Pergunta ' + (i + 1) + ' de ' + P.length + '</div>' +
        '<div class="qz-q">' + esc(p.q) + '</div><div class="qz-opts">';
      p.o.forEach(function (o, j) {
        h += '<button type="button" class="qz-opt' + (resp[p.k] === o ? ' sel' : '') + '" data-j="' + j + '">' + esc(o) + '</button>';
      });
      h += '</div>' + (i > 0 ? '<button type="button" class="qz-back">← Voltar</button>' : '');
      card.innerHTML = h;
      card.querySelectorAll('.qz-opt').forEach(function (b) {
        b.addEventListener('click', function () {
          if (i === 0 && !resp.objetivo) ev('quiz_inicio', { quiz: 'perfil_investidor' });
          resp[p.k] = p.o[+b.dataset.j]; b.classList.add('sel');
          setTimeout(function () { i++; render(); }, 180);
        });
      });
      var bk = card.querySelector('.qz-back');
      if (bk) bk.addEventListener('click', function () { i--; render(); });
      return;
    }
    var pf = perfil();
    card.innerHTML =
      '<div class="qz-bar"><i style="width:100%"></i></div><div class="qz-step">Seu resultado</div>' +
      '<div class="qz-perfil"><b>' + esc(pf.nome) + '</b>' + esc(pf.dica) + '</div>' +
      '<form class="qz-form" id="qzForm" novalidate>' +
        '<label class="sr-only" for="qzNome">Seu nome</label><input type="text" id="qzNome" name="nome" placeholder="Seu nome" autocomplete="name" required>' +
        '<label class="sr-only" for="qzTel">WhatsApp</label><input type="tel" id="qzTel" name="telefone" placeholder="WhatsApp com DDD" autocomplete="tel" required>' +
        '<label class="sr-only" for="qzEmail">E-mail</label><input type="email" id="qzEmail" name="email" placeholder="Seu e-mail" autocomplete="email" required>' +
        '<label class="qz-lgpd"><input type="checkbox" id="qzOk" required> <span>Aceito receber oportunidades de imóveis por WhatsApp e e-mail. <a href="/privacidade.html" target="_blank">Política de Privacidade</a></span></label>' +
        '<input type="checkbox" name="botcheck" style="display:none" tabindex="-1" autocomplete="off">' +
        '<button type="submit" class="qz-send">Receber oportunidades do meu perfil</button>' +
        '<p class="qz-msg" id="qzMsg"></p>' +
      '</form><button type="button" class="qz-back">← Revisar respostas</button>';
    card.querySelector('.qz-back').addEventListener('click', function () { i = P.length - 1; render(); });
    var f = document.getElementById('qzForm'), msg = document.getElementById('qzMsg');
    f.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (enviado) return;
      var nome = f.nome.value.trim(), tel = f.telefone.value.replace(/\D/g, ''), em = f.email.value.trim();
      if (nome.length < 2) return erro('Informe seu nome.');
      if (tel.length < 10) return erro('Informe o WhatsApp com DDD.');
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)) return erro('Informe um e-mail válido.');
      if (!document.getElementById('qzOk').checked) return erro('Marque o consentimento para receber as oportunidades.');
      var btn = f.querySelector('.qz-send'); btn.disabled = true; btn.textContent = 'Enviando...';
      var d = new FormData();
      d.append('access_key', ACCESS_KEY);
      d.append('subject', '[' + pf.prio + '] Lead investidor (quiz) — ' + pf.nome);
      d.append('from_name', 'Site Reginaldo Rosso · Quiz');
      d.append('nome', nome); d.append('telefone', f.telefone.value.trim()); d.append('email', em);
      d.append('perfil', pf.nome); d.append('prioridade', pf.prio + ' (' + pf.pts + '/8)');
      P.forEach(function (p) { d.append(p.q, resp[p.k] || ''); });
      d.append('pagina', location.pathname); d.append('consentimento_lgpd', 'sim — ' + new Date().toISOString());
      if (f.botcheck.checked) d.append('botcheck', 'on');
      try {
        var r = await fetch('https://api.web3forms.com/submit', { method: 'POST', body: d, headers: { Accept: 'application/json' } });
        var j = await r.json(); if (!j.success) throw 0;
        enviado = true;
        ev('generate_lead', { method: 'quiz_investidor', perfil: pf.nome, prioridade: pf.prio });
        try { if (window.fbq) fbq('track', 'Lead', { content_name: 'quiz_investidor' }); } catch (x) {}
        var wa = 'Olá! Fiz o quiz do site. Meu perfil: ' + pf.nome + '. Objetivo: ' + resp.objetivo + '; investimento: ' + resp.valor + '; região: ' + resp.regiao + '.';
        card.innerHTML = '<div class="qz-ok"><div class="ic">✓</div><h3>Recebido, ' + esc(nome.split(' ')[0]) + '!</h3>' +
          '<p>Seu perfil foi registrado. Em breve você recebe as primeiras oportunidades selecionadas.</p>' +
          '<a href="https://wa.me/' + WA + '?text=' + encodeURIComponent(wa) + '" target="_blank" rel="noopener">Quero adiantar pelo WhatsApp</a>' +
          '<p style="margin-top:12px"><a href="/imoveis.html" style="background:none;color:var(--ink,#14213a);padding:0;text-decoration:underline">Ver imóveis disponíveis agora</a></p></div>';
      } catch (x) {
        btn.disabled = false; btn.textContent = 'Receber oportunidades do meu perfil';
        erro('Não consegui enviar agora. Tente de novo ou me chame no WhatsApp.');
      }
    });
    function erro(t) { msg.className = 'qz-msg err'; msg.textContent = t; }
  }
  render();
})();
