// Assemblage name-suggestion endpoint (Cloudflare Worker + Workers AI).
//
// POST {"text": "plain description"}  ->  {"terms": [{"term", "gloss"}], "model"}
//
// No API key exists anywhere: the model runs in the same Cloudflare account
// through the AI binding. On the Workers Free plan, going past the daily free
// allocation makes calls fail (the add-on then searches the user's own words);
// it can never produce a bill.

const DEFAULT_MODEL = "@cf/google/gemma-4-26b-a4b-it";
// Models the eval script may ask for with ?model=. Kept to cheap ones so a
// stranger can't point the endpoint at an expensive model.
const ALLOWED_MODELS = new Set([
  DEFAULT_MODEL,
  "@cf/meta/llama-3.1-8b-instruct-fp8-fast",
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
]);

const MAX_INPUT_CHARS = 300;
const MAX_TERMS = 5;

const SYSTEM_PROMPT = `You help 3D artists find reference images. The user describes an object in plain words, often because they do not know its proper name.

Return the names that the people who make, sell, specify or install it actually use: the words on product pages, catalogs and spec sheets. An image search will be run with the name the user picks.

Rules:
- Give 3 to 5 different candidates, most likely first.
- If the description could mean different things (for example residential vs commercial, or different parts), cover the different readings.
- Each "term": 1 to 5 words, the trade or industry name, no brand names. Keep any colour, material or style the user gave (e.g. "black").
- Each "gloss": at most 12 plain words that let a non-expert tell which one this is.
- If the user's words are already the standard name, make them the first term unchanged.

Reply with JSON only, no other text:
{"terms":[{"term":"...","gloss":"..."}]}`;

// One worked example, deliberately NOT one of the test cases.
const EXAMPLE_USER = "the metal arm thing that holds a tv on the wall";
const EXAMPLE_REPLY = JSON.stringify({
  terms: [
    { term: "full-motion TV wall mount", gloss: "Folding arm that swings the TV out from the wall" },
    { term: "tilting TV wall mount", gloss: "Flat bracket, TV tilts up and down only" },
    { term: "fixed TV wall mount", gloss: "Low flat bracket, TV sits flush to the wall" },
  ],
});

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// Models sometimes wrap JSON in prose or code fences: take the outermost {...}.
function parseTerms(raw) {
  if (raw && typeof raw === "object") return raw.terms;
  const text = String(raw ?? "");
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    return JSON.parse(text.slice(start, end + 1)).terms;
  } catch {
    return null;
  }
}

function clean(terms) {
  if (!Array.isArray(terms)) return [];
  const seen = new Set();
  const out = [];
  for (const t of terms) {
    const term = String(t?.term ?? "").trim().slice(0, 60);
    const key = term.toLowerCase();
    if (!term || seen.has(key)) continue;
    seen.add(key);
    out.push({ term, gloss: String(t?.gloss ?? "").trim().slice(0, 100) });
    if (out.length === MAX_TERMS) break;
  }
  return out;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return json({ error: "POST only" }, 405);

    // Optional per-IP rate limit (configure [[ratelimits]] in wrangler.toml).
    if (env.LIMITER) {
      const ip = request.headers.get("cf-connecting-ip") || "unknown";
      const { success } = await env.LIMITER.limit({ key: ip });
      if (!success) return json({ error: "rate_limited" }, 429);
    }

    let text;
    try {
      text = String((await request.json()).text ?? "").trim();
    } catch {
      return json({ error: "bad_request" }, 400);
    }
    if (!text) return json({ error: "empty" }, 400);
    text = text.slice(0, MAX_INPUT_CHARS);

    const asked = new URL(request.url).searchParams.get("model");
    const model = asked && ALLOWED_MODELS.has(asked) ? asked : DEFAULT_MODEL;

    let result;
    try {
      result = await env.AI.run(model, {
        messages: [
          { role: "system", content: SYSTEM_PROMPT },
          { role: "user", content: EXAMPLE_USER },
          { role: "assistant", content: EXAMPLE_REPLY },
          { role: "user", content: text },
        ],
        max_tokens: 220,
        temperature: 0.2,
      });
    } catch (err) {
      // Daily free allocation used up, model unavailable, etc.
      return json({ error: "model_unavailable", detail: String(err).slice(0, 200) }, 503);
    }

    const terms = clean(parseTerms(result?.response));
    if (!terms.length) return json({ error: "unparseable", model }, 502);
    return json({ terms, model });
  },
};
