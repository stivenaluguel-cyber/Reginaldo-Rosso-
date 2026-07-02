/**
 * Cloudflare Worker — endpoint de inscrição de alertas de leilão
 * POST /api/inscrever-alerta  → insere em alertas_leilao
 * POST /api/cancelar-alerta   → desativa pelo unsubscribe_token
 *
 * Secrets do Worker (configure via wrangler secret put ou dashboard CF):
 *   DATABASE_URL  — connection string Postgres (Neon)
 *
 * Deploy:
 *   cd worker
 *   npm install
 *   npx wrangler deploy
 *
 * URL base após deploy: https://inscrever-alerta.<sua-conta>.workers.dev
 * Configure WORKER_URL no frontend e no README.
 */

// Rate limit simples em memória (funciona dentro de uma única instância CF)
// CF Workers são stateless entre requests em diferentes instâncias, mas
// serve como proteção básica na maioria dos casos.
const rateLimitMap = new Map(); // ip -> { count, resetAt }

function checkRateLimit(ip) {
  const now = Date.now();
  const window = 60_000; // 1 minuto
  const maxRequests = 3;
  const entry = rateLimitMap.get(ip);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + window });
    return true;
  }
  if (entry.count >= maxRequests) return false;
  entry.count++;
  return true;
}

function corsHeaders(origin) {
  const allowed = ['https://reginaldorosso.com.br', 'https://www.reginaldorosso.com.br'];
  const o = allowed.includes(origin) ? origin : 'https://reginaldorosso.com.br';
  return {
    'Access-Control-Allow-Origin': o,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function jsonRes(data, status = 200, origin = '') {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
  });
}

function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function generateToken() {
  // Gera UUID v4 simples usando crypto.randomUUID() (disponível no CF Workers)
  return crypto.randomUUID();
}

// Executa query no Postgres via Neon HTTP API (sem driver — usa fetch puro)
// A Neon expõe uma HTTP API em https://<host>/sql
// Para Postgres genérico sem HTTP API, usamos a lib @neondatabase/serverless
async function queryNeon(connectionString, sql, params = []) {
  // Extrai host da connection string: postgresql://user:pass@host/db
  const match = connectionString.match(/postgresql:\/\/([^:]+):([^@]+)@([^\/]+)\/(.+)/);
  if (!match) throw new Error('DATABASE_URL inválida');
  const [, user, password, host, database] = match;

  // Neon HTTP API endpoint
  const url = `https://${host}/sql`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Basic ' + btoa(`${user}:${password}`),
      'Neon-Connection-String': connectionString,
    },
    body: JSON.stringify({ query: sql, params }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Neon HTTP error ${res.status}: ${text}`);
  }
  return res.json();
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin') || '';

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (request.method !== 'POST') {
      return jsonRes({ error: 'Método não permitido' }, 405, origin);
    }

    // Rate limit por IP
    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    if (!checkRateLimit(ip)) {
      return jsonRes({ error: 'Muitas tentativas. Aguarde 1 minuto.' }, 429, origin);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return jsonRes({ error: 'JSON inválido' }, 400, origin);
    }

    const DATABASE_URL = env.DATABASE_URL;
    if (!DATABASE_URL) {
      return jsonRes({ error: 'Configuração interna ausente' }, 500, origin);
    }

    // ── POST /api/inscrever-alerta ──────────────────────────────
    if (url.pathname === '/api/inscrever-alerta') {
      const { imovel_id, nome, email } = body;

      // Validações
      if (!nome || !nome.trim()) return jsonRes({ error: 'Nome é obrigatório' }, 400, origin);
      if (!email || !validateEmail(email.trim())) return jsonRes({ error: 'E-mail inválido' }, 400, origin);
      if (!imovel_id) return jsonRes({ error: 'imovel_id é obrigatório' }, 400, origin);

      const token = generateToken();

      try {
        const result = await queryNeon(
          DATABASE_URL,
          `INSERT INTO alertas_leilao (imovel_id, nome, email, unsubscribe_token)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (imovel_id, email) DO NOTHING
           RETURNING id`,
          [String(imovel_id).trim(), nome.trim().slice(0, 100), email.trim().toLowerCase(), token]
        );

        const inserted = result.rows && result.rows.length > 0;
        if (!inserted) {
          // ON CONFLICT DO NOTHING → já existia
          return jsonRes({ ok: true, duplicate: true, message: 'Você já está inscrito neste imóvel.' }, 200, origin);
        }

        return jsonRes({ ok: true, message: 'Inscrição realizada com sucesso.' }, 201, origin);
      } catch (err) {
        console.error('Erro ao inserir alerta:', err.message);
        return jsonRes({ error: 'Erro interno ao salvar inscrição.' }, 500, origin);
      }
    }

    // ── POST /api/cancelar-alerta ───────────────────────────────
    if (url.pathname === '/api/cancelar-alerta') {
      const { token } = body;
      if (!token) return jsonRes({ error: 'Token ausente' }, 400, origin);

      try {
        await queryNeon(
          DATABASE_URL,
          'UPDATE alertas_leilao SET ativo = false WHERE unsubscribe_token = $1',
          [token]
        );
        return jsonRes({ ok: true, message: 'Descadastro realizado com sucesso.' }, 200, origin);
      } catch (err) {
        console.error('Erro ao cancelar alerta:', err.message);
        return jsonRes({ error: 'Erro interno ao cancelar alerta.' }, 500, origin);
      }
    }

    return jsonRes({ error: 'Rota não encontrada' }, 404, origin);
  },
};
