// Comment Builder (v4): the deal's monday Updates, shown inside the app like monday's Updates tab.
// build.py inserts this file (followed by ui.js) into the v2 bundle in place of its original `function Pn(){…}`.
// Uses the bundle's own helpers: Z (jsx), H (useState), U (useEffect), Re (useCallback), Cn (monday SDK).
// Optional extras (likes, viewers, item e-mail, people for @mentions) are loaded best-effort: if monday refuses
// one of them, that detail is simply hidden and everything else keeps working.

var DCL_ACCOUNT_URL = `https://zvg-group.monday.com`;
// Default "custom" update address monday gives every item: pulse-<item id>@<account>.<region>.monday.com
var DCL_CUSTOM_EMAIL_DOMAIN = `zvg-group.eu.monday.com`;
var DCL_FEEDBACK_URL = `https://forms.monday.com/forms/98e54dc3488d8019915d8c3114c55f47?r=use1`;
var DCL_EMOJIS = `👍 👏 🙌 🎉 ✅ ❌ 🔥 💡 🚀 ⭐ ❤️ 😊 😂 😉 🤔 😮 😢 🙏 👀 💪 📌 📎 📅 ⏰ 📞 ✉️ 💬 ⚠️ ❗ ❓ 👉 💯`.split(` `);

/* ---------- API ---------- */

// monday's API is replacing the flat user photo fields (photo_thumb_small…) with `photo_url { thumb_small … }`.
// Queries ask for `photo_thumb_small`; it is sent as the new `photo_url { thumb_small }` first, then as the old flat
// fields, and finally without a photo, always under the key `photo_thumb_small` (a URL string), so the rest of the
// page doesn't change. The first shape monday accepts is remembered for the rest of the session.
var DCL_PHOTO_FIELDS = [`photo_url`, `photo_thumb_small`, `photo_thumb`, `photo_tiny`, `photo_small`, ``];
var dclPhotoAt = 0;

function dclPhotoQuery(query, field) {
  if (field === `photo_thumb_small`) return query;
  let as = field === `photo_url` ? `photo_thumb_small: photo_url { thumb_small }` : field ? `photo_thumb_small: ${field}` : ``;
  return query.replace(/photo_thumb_small/g, as);
}

// `photo_thumb_small: { thumb_small: url }` (new nested shape) → `photo_thumb_small: url`, anywhere in the response.
function dclFlattenPhotos(x) {
  if (Array.isArray(x)) x.forEach(dclFlattenPhotos);
  else if (x && typeof x === `object`) {
    for (let k of Object.keys(x)) {
      if (k === `photo_thumb_small` && x[k] && typeof x[k] === `object`) x[k] = x[k].thumb_small || null;
      else dclFlattenPhotos(x[k]);
    }
  }
  return x;
}

async function dclApi(query, variables) {
  if (!query.includes(`photo_thumb_small`)) return dclApiOnce(query, variables);
  for (;;) {
    let field = DCL_PHOTO_FIELDS[dclPhotoAt];
    try {
      return dclFlattenPhotos(await dclApiOnce(dclPhotoQuery(query, field), variables));
    } catch (err) {
      let bad = /Cannot query field \\?"(\w+)\\?" on type/.exec(err?.message || ``);
      let at = !bad ? -1 : field === `photo_url` && bad[1] === `thumb_small` ? 0 : DCL_PHOTO_FIELDS.indexOf(bad[1]);
      if (at < 0) throw err;
      dclPhotoAt = Math.max(dclPhotoAt, at + 1); // another request may already have moved on
    }
  }
}

// Like wn(), but the error message includes monday's details (error code, missing scope, bad field…).
// The SDK rejects with Error(errorMessage) and hides monday's response in `err.data`, so that is surfaced too.
async function dclApiOnce(query, variables) {
  let detail = x => (x ? ` ${JSON.stringify(x).slice(0, 600)}` : ``);
  let r;
  try {
    r = await Cn.api(query, { variables });
  } catch (err) {
    console.error(`[Comment Builder] monday API error`, err, err?.data);
    throw Error(`${err?.message || `monday API error`}${detail(err?.data)}`);
  }
  if (r?.errors?.length) {
    console.error(`[Comment Builder] monday API errors`, r);
    throw Error(r.errors.map(e => `${e.message}${detail(e.extensions)}`).join(`; `));
  }
  if (r?.error_message) {
    console.error(`[Comment Builder] monday API error`, r);
    throw Error(`${r.error_message}${detail(r.error_data || r.error_code)}`);
  }
  return r.data;
}

async function dclTry(fn) {
  try {
    return await fn();
  } catch (err) {
    console.warn(`[Comment Builder] optional detail unavailable:`, err?.message);
    return null;
  }
}

function dclItemVars(itemId) {
  return { itemId: [String(itemId)] };
}

// Tried in order: if monday rejects a field in one shape, the next, simpler shape is used.
var DCL_UPDATE_QUERIES = [
  `query ($itemId: [ID!]) {
    items (ids: $itemId) {
      updates (limit: 50) {
        id
        body
        created_at
        creator { id name photo_thumb_small }
        replies { id body created_at creator { id name photo_thumb_small } }
      }
    }
  }`,
  `query ($itemId: [ID!]) {
    items (ids: $itemId) {
      updates (limit: 50) { id body created_at creator { id name photo_thumb_small } }
    }
  }`,
  `query ($itemId: [ID!]) {
    items (ids: $itemId) {
      updates (limit: 50) { id body created_at creator_id }
    }
  }`,
];

async function dclLoadUpdates(itemId) {
  let errors = [];
  for (let q of DCL_UPDATE_QUERIES) {
    try {
      let updates = (await dclApi(q, dclItemVars(itemId)))?.items?.[0]?.updates || [];
      if (updates.some(u => !(`creator` in u) && u.creator_id)) await dclAttachCreators(updates);
      return updates.map(u => ({ ...u, replies: u.replies || [] }));
    } catch (err) {
      errors.push(err.message);
    }
  }
  throw Error(errors[0] || `Could not load updates.`);
}

// For the minimal query: fill in author name/photo from creator_id (best effort).
async function dclAttachCreators(updates) {
  let ids = [...new Set(updates.map(u => u.creator_id).filter(Boolean).map(String))];
  let byId = {};
  let users = (await dclTry(() => dclApi(`query ($ids: [ID!]) { users (ids: $ids) { id name photo_thumb_small } }`, { ids })))?.users || [];
  users.forEach(u => (byId[String(u.id)] = u));
  updates.forEach(u => (u.creator = u.creator_id ? byId[String(u.creator_id)] || { name: `User ${u.creator_id}` } : null));
}

// Viewer counts and likes per update id: { [id]: { viewers?: n, likes?: [userId…] } }.
async function dclLoadReactions(itemId) {
  let out = {};
  let put = (id, k, v) => (out[id] = { ...(out[id] || {}), [k]: v });
  let [views, likes, pins] = await Promise.all([
    dclTry(() => dclApi(`query ($itemId: [ID!]) { items (ids: $itemId) { updates (limit: 50) { id viewers { user_id } } } }`, dclItemVars(itemId))),
    dclTry(() => dclApi(`query ($itemId: [ID!]) { items (ids: $itemId) { updates (limit: 50) { id likes { id creator_id } } } }`, dclItemVars(itemId))),
    dclTry(() => dclApi(`query ($itemId: [ID!]) { items (ids: $itemId) { updates (limit: 50) { id pinned_to_top { item_id } } } }`, dclItemVars(itemId))),
  ]);
  (views?.items?.[0]?.updates || []).forEach(u => put(u.id, `viewers`, (u.viewers || []).length));
  (likes?.items?.[0]?.updates || []).forEach(u => put(u.id, `likes`, (u.likes || []).map(l => String(l.creator_id))));
  (pins?.items?.[0]?.updates || []).forEach(u => {
    let pt = u.pinned_to_top;
    put(u.id, `pinned`, Array.isArray(pt) ? pt.length > 0 : !!pt);
  });
  return out;
}

// Pin an update to the top of the deal's Updates (or unpin it).
function dclPinUpdate(id, itemId, pinned) {
  let vars = { id: String(id), itemId: String(itemId) };
  return pinned
    ? dclApi(`mutation ($id: ID!, $itemId: ID) { unpin_from_top (id: $id, item_id: $itemId) { id } }`, vars)
    : dclApi(`mutation ($id: ID!, $itemId: ID) { pin_to_top (id: $id, item_id: $itemId) { id } }`, vars);
}

// Calls the app's own server (monday code: same address as this page). Every request carries monday's signed
// session token so the server can check it comes from this app and a logged-in user.
// Returns null when there is no server (e.g. the page was uploaded as a zip): the UI then says "coming soon".
async function dclServer(path, body) {
  let token = ``;
  try {
    token = (await Cn.get(`sessionToken`))?.data || ``;
  } catch {}
  let res;
  try {
    res = await fetch(`/api${path}`, {
      method: `POST`,
      headers: { "Content-Type": `application/json`, Authorization: token },
      body: JSON.stringify(body),
    });
  } catch {
    return null;
  }
  let isJson = (res.headers.get(`content-type`) || ``).includes(`application/json`);
  if (!isJson) return null; // no app server behind this page
  let data = await res.json().catch(() => ({}));
  if (!res.ok) throw Error(data.error || `The AI request failed (${res.status}).`);
  return data;
}

// Summarize: a few short bullet points about an update (server → OpenAI gpt-4o-mini).
async function dclAiSummarize(text, context) {
  return (await dclServer(`/ai/summarize`, { text }))?.text || null;
}

// Reminders still need a scheduled job on the server (next step); null shows "coming soon".
// dclSetReminder: notify the user about an update at `when`.
async function dclSetReminder(update, when, context) {
  return null;
}

var DCL_REMINDERS = [
  [`In 1 hour`, () => new Date(Date.now() + 3600e3)],
  [`In 3 hours`, () => new Date(Date.now() + 3 * 3600e3)],
  [`Tomorrow, 9:00`, () => { let d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return d; }],
  [`Next week, Monday 9:00`, () => { let d = new Date(); d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7)); d.setHours(9, 0, 0, 0); return d; }],
];

async function dclLoadItemEmail(itemId) {
  return (await dclTry(() => dclApi(`query ($itemId: [ID!]) { items (ids: $itemId) { email } }`, dclItemVars(itemId))))?.items?.[0]?.email || ``;
}

// People that can be @mentioned.
// If the list can't be loaded, the reason is kept here so the @ picker can show it.
var DCL_USERS_ERROR = ``;

async function dclLoadUsers() {
  let errors = [];
  for (let q of [
    `query { users (limit: 500, kind: non_guests) { id name title email photo_thumb_small } }`,
    `query { users (limit: 500, kind: non_guests) { id name photo_thumb_small } }`,
    `query { users (limit: 500) { id name photo_thumb_small } }`,
  ]) {
    try {
      let users = (await dclApi(q))?.users || [];
      DCL_USERS_ERROR = users.length ? `` : `monday returned no people.`;
      return users.sort((a, b) => a.name.localeCompare(b.name));
    } catch (err) {
      errors.push(err.message);
    }
  }
  DCL_USERS_ERROR = errors[0] || `Could not load people.`;
  console.warn(`[Comment Builder] people list for @mentions unavailable:`, DCL_USERS_ERROR);
  return [];
}

// Board members (listed first under "People") and the account's teams (teams need the teams:read permission;
// if it is missing, the Teams section shows only "Everyone on this board").
async function dclLoadMentionExtras(boardId) {
  let [subs, teams] = await Promise.all([
    boardId ? dclTry(() => dclApi(`query ($b: [ID!]) { boards (ids: $b) { subscribers { id } } }`, { b: [String(boardId)] })) : null,
    dclTry(() => dclApi(`query { teams { id name picture_url } }`)),
  ]);
  return {
    memberIds: (subs?.boards?.[0]?.subscribers || []).map(u => String(u.id)),
    teams: (teams?.teams || []).sort((a, b) => a.name.localeCompare(b.name)),
  };
}

// Post a new update, or a reply when parentId is given. Mentions are sent as mentions_list when monday accepts it.
async function dclPostUpdate(itemId, html, parentId, mentionIds) {
  let vars = { itemId: String(itemId), body: html };
  if (parentId) vars.parentId = String(parentId);
  let sig = `$itemId: ID!, $body: String!${parentId ? `, $parentId: ID!` : ``}`;
  let args = `item_id: $itemId, body: $body${parentId ? `, parent_id: $parentId` : ``}`;
  if (mentionIds?.length) {
    try {
      let created = (await dclApi(
        `mutation (${sig}, $mentions: [UpdateMention]) { create_update (${args}, mentions_list: $mentions) { id } }`,
        { ...vars, mentions: mentionIds.map(m => ({ id: String(m.id ?? m), type: m.type || `User` })) },
      )).create_update;
      // mentions_list notifies the people but monday also appends its own copy of each mention to the text, so the
      // mention would show twice. Put back the text exactly as written (best effort: the update is already posted).
      if (created?.id) await dclTry(() => dclEditUpdate(created.id, html));
      return created;
    } catch (err) {
      // Only retry without mentions_list when monday rejected the query shape (nothing was created).
      if (!/validation|argument|unknown|type|field/i.test(err.message)) throw err;
    }
  }
  return (await dclApi(`mutation (${sig}) { create_update (${args}) { id } }`, vars)).create_update;
}

function dclEditUpdate(id, html) {
  return dclApi(`mutation ($id: ID!, $body: String!) { edit_update (id: $id, body: $body) { id } }`, { id: String(id), body: html });
}

function dclDeleteUpdate(id) {
  return dclApi(`mutation ($id: ID!) { delete_update (id: $id) { id } }`, { id: String(id) });
}

function dclLikeUpdate(id, liked) {
  return liked
    ? dclApi(`mutation ($id: ID!) { unlike_update (update_id: $id) { id } }`, { id: String(id) })
    : dclApi(`mutation ($id: ID!) { like_update (update_id: $id) { id } }`, { id: String(id) });
}

function dclOpenMondayUpdates(itemId) {
  try {
    Cn.execute(`openItemCard`, { itemId: Number(itemId), kind: `updates` });
  } catch {}
}

async function dclCopy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      let t = document.createElement(`textarea`);
      t.value = text;
      document.body.appendChild(t);
      t.select();
      let ok = document.execCommand(`copy`);
      t.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

/* ---------- HTML handling ---------- */

function dclEscHtml(s) {
  return String(s).replace(/&/g, `&amp;`).replace(/</g, `&lt;`).replace(/>/g, `&gt;`).replace(/"/g, `&quot;`);
}

// Plain text from the composer → update HTML (one paragraph per line).
function dclTextToHtml(text) {
  return text.trim().split(`\n`).map(line => `<p>${line ? dclEscHtml(line) : `<br>`}</p>`).join(``);
}

// Update bodies are HTML written by people, automations and incoming emails, so only a safe subset is kept:
// whitelisted tags, a few safe styles (colour, size, alignment, direction), http(s)/mailto links, https images and
// monday @mention links. Everything else is dropped or turned into text. Used both for showing and for sending.
var DCL_ALLOWED_TAGS = { p: 1, br: 1, b: 1, strong: 1, i: 1, em: 1, u: 1, s: 1, strike: 1, del: 1, a: 1, ul: 1, ol: 1, li: 1, blockquote: 1, h1: 1, h2: 1, h3: 1, h4: 1, h5: 1, h6: 1, span: 1, div: 1, img: 1, pre: 1, code: 1, hr: 1, table: 1, thead: 1, tbody: 1, tr: 1, td: 1, th: 1, sub: 1, sup: 1, font: 1 };
var DCL_VOID_TAGS = { br: 1, img: 1, hr: 1 };
var DCL_FONT_SIZES = { 1: `10px`, 2: `12px`, 3: `14px`, 4: `16px`, 5: `20px`, 6: `24px`, 7: `32px` };

function dclDecodeEntities(s) {
  return s
    .replace(/&#x([0-9a-f]+);?/gi, (m, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/&#(\d+);?/g, (m, d) => String.fromCharCode(+d))
    .replace(/&colon;/gi, `:`).replace(/&quot;/g, `"`).replace(/&#39;|&apos;/g, `'`).replace(/&nbsp;/g, ` `)
    .replace(/&lt;/g, `<`).replace(/&gt;/g, `>`).replace(/&amp;/g, `&`);
}

function dclAttr(attrs, name) {
  let m = attrs.match(new RegExp(`(?:^|\\s)${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s"'>]+))`, `i`));
  return m ? dclDecodeEntities(m[1] ?? m[2] ?? m[3] ?? ``).trim() : ``;
}

function dclSafeUrl(url, httpsOnly) {
  let squeezed = url.replace(/[\u0000- \u007f]/g, ``);
  return (httpsOnly ? /^https:\/\//i : /^(https?:\/\/|mailto:)/i).test(squeezed) ? url : ``;
}

// Only these CSS properties, and only plain values (no url(), expressions, etc.).
var DCL_STYLE_RULES = {
  color: /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|[a-z]{3,20})$/i,
  "background-color": /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|[a-z]{3,20})$/i,
  "font-size": /^\d{1,2}(\.\d+)?(px|em|rem|%)$/i,
  "text-align": /^(left|right|center|justify|start|end)$/i,
  direction: /^(ltr|rtl)$/i,
};

function dclSafeStyle(attrs, tag) {
  let out = [];
  dclAttr(attrs, `style`).split(`;`).forEach(rule => {
    let i = rule.indexOf(`:`);
    if (i < 0) return;
    let prop = rule.slice(0, i).trim().toLowerCase(), val = rule.slice(i + 1).trim();
    if (DCL_STYLE_RULES[prop] && DCL_STYLE_RULES[prop].test(val)) out.push(`${prop}:${val}`);
  });
  if (tag === `font`) {
    let c = dclAttr(attrs, `color`), sz = dclAttr(attrs, `size`);
    if (c && DCL_STYLE_RULES.color.test(c)) out.push(`color:${c}`);
    if (DCL_FONT_SIZES[sz]) out.push(`font-size:${DCL_FONT_SIZES[sz]}`);
  }
  let align = dclAttr(attrs, `align`);
  if (align && DCL_STYLE_RULES[`text-align`].test(align)) out.push(`text-align:${align}`);
  return out.length ? ` style="${dclEscHtml(out.join(`;`))}"` : ``;
}

function dclSanitizeHtml(html) {
  let s = String(html || ``), prev;
  do {
    prev = s;
    s = s.replace(/<(script|style|iframe|object|embed|noscript|template|svg|math|title|head|textarea|select)\b[\s\S]*?<\/\1\s*>/gi, ``);
  } while (s !== prev);
  s = s.replace(/<!--[\s\S]*?-->/g, ``);
  let out = ``, last = 0, m;
  let re = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*)>/g;
  let text = t => t.replace(/</g, `&lt;`).replace(/>/g, `&gt;`);
  while ((m = re.exec(s))) {
    out += text(s.slice(last, m.index));
    last = re.lastIndex;
    let closing = m[1] === `/`, tag = m[2].toLowerCase(), attrs = m[3];
    if (!DCL_ALLOWED_TAGS[tag]) continue;
    let outTag = tag === `font` ? `span` : tag;
    if (closing) {
      if (!DCL_VOID_TAGS[tag]) out += `</${outTag}>`;
      continue;
    }
    if (tag === `a`) {
      let href = dclSafeUrl(dclAttr(attrs, `href`));
      let mentionId = dclAttr(attrs, `data-mention-id`);
      let mentionType = dclAttr(attrs, `data-mention-type`) || `User`;
      if (/^\d+$/.test(mentionId) && DCL_MENTION_PATHS[mentionType] && /user_mention_editor/.test(dclAttr(attrs, `class`))) {
        out += dclMentionLinkOpen(mentionType, mentionId);
      } else {
        out += href ? `<a href="${dclEscHtml(href)}" target="_blank" rel="noopener noreferrer">` : `<a>`;
      }
    } else if (tag === `img`) {
      let src = dclSafeUrl(dclAttr(attrs, `src`), true);
      if (src) out += `<img src="${dclEscHtml(src)}" alt="">`;
    } else if (DCL_VOID_TAGS[tag]) {
      out += `<${outTag}>`;
    } else {
      let dir = dclAttr(attrs, `dir`).toLowerCase();
      out += `<${outTag}${dclSafeStyle(attrs, tag)}${dir === `rtl` || dir === `ltr` ? ` dir="${dir}"` : ``}>`;
    }
  }
  return out + text(s.slice(last));
}

// Editor HTML → update body: safe subset, no trailing empty lines.
function dclEditorToHtml(html) {
  return dclTidyHtml(dclSanitizeHtml(html).replace(/(<br>\s*)+$/, ``));
}

// @mentions can point at a person, a team or "everyone on this board".
var DCL_MENTION_PATHS = { User: `users`, Team: `teams`, Board: `boards` };

function dclMentionLinkOpen(type, id) {
  return `<a class="user_mention_editor router" href="${dclEscHtml(`${DCL_ACCOUNT_URL}/${DCL_MENTION_PATHS[type]}/${id}`)}" data-mention-type="${type}" data-mention-id="${id}" target="_blank" rel="noopener noreferrer">`;
}

// @mentions contained in an update body, as [{ type, id }] (for mentions_list).
function dclMentionIds(html) {
  let seen = {}, out = [];
  for (let m of String(html).matchAll(/data-mention-type="(User|Team|Board)" data-mention-id="(\d+)"/g)) {
    if (!seen[m[1] + m[2]]) (seen[m[1] + m[2]] = 1), out.push({ type: m[1], id: m[2] });
  }
  return out;
}

// Drop the runs of empty paragraphs / line breaks that email updates are full of.
function dclTidyHtml(html) {
  let empty = `<(p|div)>(?:\\s|&nbsp;|<br>)*</\\1>`;
  return html
    .replace(new RegExp(`(?:${empty}\\s*){2,}`, `g`), `<p><br></p>`)
    .replace(new RegExp(`^(?:\\s*${empty})+`), ``)
    .replace(new RegExp(`(?:${empty}\\s*)+$`), ``)
    .replace(/(?:<br>\s*){3,}/g, `<br><br>`);
}

/* ---------- Shared bits (also used by ui.js) ---------- */

function dclFmtShort(iso) {
  let d = new Date(iso);
  if (isNaN(d)) return iso || ``;
  let opts = { day: `numeric`, month: `short` };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = `numeric`;
  return d.toLocaleDateString(`en-GB`, opts);
}

function dclFmtFull(iso) {
  let d = new Date(iso);
  return isNaN(d) ? iso || `` : d.toLocaleString(`en-GB`, { day: `numeric`, month: `short`, year: `numeric`, hour: `2-digit`, minute: `2-digit` });
}

// "Just now", "5m", "2h", "Yesterday", then the short date (exact time is in the tooltip).
function dclFmtRelative(iso) {
  let d = new Date(iso);
  if (isNaN(d)) return iso || ``;
  let mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return `Just now`;
  if (mins < 60) return `${mins}m`;
  if (mins < 24 * 60) return `${Math.floor(mins / 60)}h`;
  let y = new Date();
  y.setDate(y.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Yesterday`;
  return dclFmtShort(iso);
}

function dclIsRecent(iso) {
  let t = new Date(iso).getTime();
  return !isNaN(t) && Date.now() - t < 24 * 3600 * 1000;
}

function dclInitials(name) {
  return (name || `?`).split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join(``);
}

function dclSectionTitle(icon, label, count) {
  return Z(`div`, {
    className: `section-title`,
    children: [Z(`span`, { className: `section-icon`, children: icon }), label, count > 0 && Z(`span`, { className: `count`, children: count })],
  });
}

var DCL_AVATAR_COLORS = [`#579bfc`, `#00c875`, `#fdab3d`, `#a25ddc`, `#ff642e`, `#037f4c`, `#e2445c`, `#0086c0`];

function DclAvatar({ person, small }) {
  let cls = `upd-avatar${small ? ` upd-avatar-sm` : ``}`;
  // Automations (no person): three coloured bars, like monday's automation avatar.
  if (!person) {
    return Z(`span`, { className: `${cls} upd-avatar-auto`, title: `Automations`, children: [Z(`i`, {}), Z(`i`, {}), Z(`i`, {})] });
  }
  let name = person.name || ``;
  let color = DCL_AVATAR_COLORS[[...name].reduce((h, ch) => h + ch.charCodeAt(0), 0) % DCL_AVATAR_COLORS.length];
  return Z(`span`, {
    className: `${cls}${person.photo_thumb_small ? ` has-photo` : ``}`,
    title: name,
    style: person.photo_thumb_small ? undefined : { background: color },
    children: person.photo_thumb_small ? Z(`img`, { src: person.photo_thumb_small, alt: `` }) : dclInitials(name),
  });
}

// Small line icons (feather style).
var DCL_ICONS = {
  mail: [[`path`, { d: `M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z` }], [`polyline`, { points: `22,6 12,13 2,6` }]],
  feedback: [[`path`, { d: `M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z` }]],
  at: [[`circle`, { cx: `12`, cy: `12`, r: `4` }], [`path`, { d: `M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94` }]],
  clip: [[`path`, { d: `M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48` }]],
  smile: [[`circle`, { cx: `12`, cy: `12`, r: `10` }], [`path`, { d: `M8 14s1.5 2 4 2 4-2 4-2` }], [`line`, { x1: `9`, y1: `9`, x2: `9.01`, y2: `9` }], [`line`, { x1: `15`, y1: `9`, x2: `15.01`, y2: `9` }]],
  like: [[`path`, { d: `M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3` }]],
  reply: [[`polyline`, { points: `9 14 4 9 9 4` }], [`path`, { d: `M20 20v-7a4 4 0 0 0-4-4H4` }]],
  eye: [[`path`, { d: `M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z` }], [`circle`, { cx: `12`, cy: `12`, r: `3` }]],
  more: [[`circle`, { cx: `12`, cy: `12`, r: `1` }], [`circle`, { cx: `19`, cy: `12`, r: `1` }], [`circle`, { cx: `5`, cy: `12`, r: `1` }]],
  link: [[`path`, { d: `M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71` }], [`path`, { d: `M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71` }]],
  edit: [[`path`, { d: `M12 20h9` }], [`path`, { d: `M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z` }]],
  trash: [[`polyline`, { points: `3 6 5 6 21 6` }], [`path`, { d: `M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2` }]],
  list: [[`line`, { x1: `8`, y1: `6`, x2: `21`, y2: `6` }], [`line`, { x1: `8`, y1: `12`, x2: `21`, y2: `12` }], [`line`, { x1: `8`, y1: `18`, x2: `21`, y2: `18` }], [`line`, { x1: `3`, y1: `6`, x2: `3.01`, y2: `6` }], [`line`, { x1: `3`, y1: `12`, x2: `3.01`, y2: `12` }], [`line`, { x1: `3`, y1: `18`, x2: `3.01`, y2: `18` }]],
  table: [[`rect`, { x: `3`, y: `3`, width: `18`, height: `18`, rx: `2` }], [`line`, { x1: `3`, y1: `9`, x2: `21`, y2: `9` }], [`line`, { x1: `3`, y1: `15`, x2: `21`, y2: `15` }], [`line`, { x1: `12`, y1: `3`, x2: `12`, y2: `21` }]],
  align: [[`line`, { x1: `17`, y1: `10`, x2: `3`, y2: `10` }], [`line`, { x1: `21`, y1: `6`, x2: `3`, y2: `6` }], [`line`, { x1: `21`, y1: `14`, x2: `3`, y2: `14` }], [`line`, { x1: `17`, y1: `18`, x2: `3`, y2: `18` }]],
  minus: [[`line`, { x1: `5`, y1: `12`, x2: `19`, y2: `12` }]],
  direction: [[`polyline`, { points: `17 1 21 5 17 9` }], [`path`, { d: `M3 11V9a4 4 0 0 1 4-4h14` }], [`polyline`, { points: `7 23 3 19 7 15` }], [`path`, { d: `M21 13v2a4 4 0 0 1-4 4H3` }]],
  check: [[`path`, { d: `M22 11.08V12a10 10 0 1 1-5.93-9.14` }], [`polyline`, { points: `22 4 12 14.01 9 11.01` }]],
  aipen: [[`path`, { d: `M12 20h9` }], [`path`, { d: `M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z` }], [`path`, { d: `M5 3v4M3 5h4` }]],
  summarize: [[`path`, { d: `M4 5h12M4 10h12M4 15h7` }], [`path`, { d: `M18 14v6M15 17h6` }]],
  reminder: [[`path`, { d: `M15 8A5 5 0 0 0 5 8c0 6-2.5 8-2.5 8h15S15 14 15 8` }], [`path`, { d: `M11.5 20a1.7 1.7 0 0 1-3 0` }], [`circle`, { cx: `18`, cy: `6`, r: `3.5` }], [`path`, { d: `M18 4.5V6l1 1` }]],
  pin: [[`path`, { d: `M12 17v5` }], [`path`, { d: `M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6z` }]],
  bookmark: [[`path`, { d: `M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z` }]],
  open: [[`path`, { d: `M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6` }], [`polyline`, { points: `15 3 21 3 21 9` }], [`line`, { x1: `10`, y1: `14`, x2: `21`, y2: `3` }]],
};

function DclIcon({ name, size }) {
  return Z(`svg`, {
    className: `ic`,
    viewBox: `0 0 24 24`,
    width: size || 16,
    height: size || 16,
    fill: `none`,
    stroke: `currentColor`,
    "stroke-width": `2`,
    "stroke-linecap": `round`,
    "stroke-linejoin": `round`,
    "aria-hidden": `true`,
    children: (DCL_ICONS[name] || []).map(([tag, attrs]) => Z(tag, attrs)),
  });
}

/* ---------- Body ---------- */

// Update / reply body, collapsed behind "See more" when long.
function DclUpdateBody({ html }) {
  let [open, setOpen] = H(false);
  let safe = dclTidyHtml(dclSanitizeHtml(html));
  let plain = safe.replace(/<[^>]+>/g, ``);
  let blocks = (safe.match(/<(p|br|div|li|tr|h\d)\b/g) || []).length;
  let long = plain.length > 420 || blocks > 10;
  return Z(`div`, {
    className: `upd-body-wrap`,
    children: [
      Z(`div`, { className: `upd-body${long && !open ? ` upd-clamped` : ``}`, dangerouslySetInnerHTML: { __html: safe } }),
      long && Z(`button`, { type: `button`, className: `upd-link`, onClick: () => setOpen(!open), children: open ? `… See less` : `… See more` }),
    ],
  });
}

/* ---------- Composer (new update, reply, edit): rich editor like monday's ---------- */

// - dclUploadFile: upload a file from the computer to an update, through the app's server (monday's file API).
// - dclAiWrite: turn a short description into an update text, through the app's server (see dclServer).

// Files picked with "From Computer". monday attaches a file only to an update that exists, so the composer puts a
// placeholder link in the text; when the update is posted, each file is uploaded to it and the placeholder becomes
// monday's own link to the file (…/protected_static/…, which downloads it), as monday's Updates editor does.
var DCL_MAX_FILE_BYTES = 25 * 1024 * 1024; // the server's limit too (router.py MAX_FILE)
var dclPendingUrl = key => `https://pending-file.invalid/${key}`;

async function dclUploadFile(file, updateId, itemId) {
  let token = ``;
  try {
    token = (await Cn.get(`sessionToken`))?.data || ``;
  } catch {}
  let query = new URLSearchParams({ updateId: String(updateId), itemId: String(itemId), name: file.name });
  let res = await fetch(`/api/files/upload?${query}`, {
    method: `POST`,
    headers: { "Content-Type": file.type || `application/octet-stream`, Authorization: token },
    body: file,
  });
  let data = await res.json().catch(() => ({}));
  if (!res.ok || !data.url) throw Error(data.error || `The upload failed (${res.status}).`);
  return data;
}

// post(html) creates or edits the update and returns its id. Returns the names of the files that could not be
// attached: their link is turned into plain text, so the update never keeps a placeholder.
async function dclPostWithFiles(html, files, itemId, post) {
  let keys = Object.keys(files || {}).filter(k => html.includes(`"${dclPendingUrl(k)}"`)); // still in the text
  let id = await post(html);
  if (!keys.length || !id) return [];
  let failed = [];
  for (let k of keys) {
    let link = new RegExp(`<a href="${dclPendingUrl(k).replace(/[.*+?^${}()|[\]\\/]/g, `\\$&`)}"[^>]*>([\\s\\S]*?)</a>`, `g`);
    try {
      let res = await dclUploadFile(files[k], id, itemId);
      html = html.replace(link, `<a href="${dclEscHtml(res.url)}" target="_blank" rel="noopener noreferrer">$1</a>`);
    } catch (err) {
      console.error(`[Comment Builder] file upload failed`, err);
      failed.push(`${files[k].name} (${err.message})`);
      html = html.replace(link, `$1`);
    }
  }
  await dclEditUpdate(id, html);
  return failed;
}
// Write with AI: turn a short description into update text (server → OpenAI gpt-4o-mini).
async function dclAiWrite(prompt, context) {
  return (await dclServer(`/ai/write`, { prompt }))?.text || null;
}

var DCL_TEXT_COLORS = [`#323338`, `#e2445c`, `#fdab3d`, `#ffcb00`, `#00c875`, `#0086c0`, `#579bfc`, `#a25ddc`, `#ff158a`, `#7f5347`, `#676879`, `#c4c4c4`];
var DCL_SIZES = [[`Small`, `2`], [`Normal`, `3`], [`Large`, `5`], [`Huge`, `6`]];
var DCL_BLOCKS = [[`Normal text`, `p`], [`Heading 1`, `h1`], [`Heading 2`, `h2`], [`Heading 3`, `h3`]];
var DCL_ALIGNS = [[`Align left`, `justifyLeft`], [`Center`, `justifyCenter`], [`Align right`, `justifyRight`]];
var DCL_CLOUDS = [
  [`drive`, `From Google Drive`, `Google Drive`],
  [`dropbox`, `From DropBox`, `DropBox`],
  [`box`, `From Box`, `Box`],
  [`onedrive`, `From OneDrive & SharePoint`, `OneDrive`],
];

// Which formats are on at the cursor (drives the highlighted toolbar buttons, like monday's).
function dclReadFormats(el) {
  let sel = window.getSelection();
  if (!el || !sel || !sel.rangeCount || !el.contains(sel.anchorNode)) return {};
  let st = cmd => { try { return document.queryCommandState(cmd); } catch { return false; } };
  let block = ``;
  try { block = String(document.queryCommandValue(`formatBlock`) || ``).toLowerCase(); } catch {}
  let node = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement;
  return {
    bold: st(`bold`), italic: st(`italic`), underline: st(`underline`), strike: st(`strikeThrough`),
    ol: st(`insertOrderedList`), ul: st(`insertUnorderedList`),
    align: st(`justifyCenter`) || st(`justifyRight`),
    heading: /^h[1-3]$/.test(block),
    link: !!node?.closest(`a`),
    rtl: node?.closest(`[dir="rtl"]`) ? true : false,
  };
}

function dclIsEmptyEditor(el) {
  return !el || (!el.textContent.replace(/ /g, ` `).trim() && !el.querySelector(`img,hr,table,a`));
}

// "@partial" just before the caret, or null.
function dclMentionAtCaret(el) {
  let sel = window.getSelection();
  if (!sel || !sel.rangeCount || !el || !el.contains(sel.anchorNode)) return null;
  let r = sel.getRangeAt(0), node = r.startContainer;
  if (node.nodeType !== 3) return null;
  let before = node.textContent.slice(0, r.startOffset);
  let m = before.match(/(?:^|[\s ])@([^@\n]{0,40})$/);
  if (!m) return null;
  return { query: m[1].replace(/ /g, ` `), node, start: r.startOffset - m[1].length - 1, end: r.startOffset, rect: dclCaretRect(r, el) };
}

// Screen position for the @ list: just under the caret (or above it when there is no room below), like monday's.
function dclCaretRect(range, el) {
  let rect = range.getBoundingClientRect();
  if (!rect || (!rect.height && !rect.width)) {
    let tmp = document.createElement(`span`);
    tmp.textContent = `​`;
    let r2 = range.cloneRange();
    r2.insertNode(tmp);
    rect = tmp.getBoundingClientRect();
    tmp.remove();
  }
  if (!rect || (!rect.height && !rect.width)) rect = el.getBoundingClientRect();
  return { left: rect.left, top: rect.top, bottom: rect.bottom };
}

// Fixed position for a menu opened from a button: just below it (like monday's), above only if there's no room.
function dclPopStyle(rect, w, h) {
  if (!rect) return undefined;
  let vw = window.innerWidth || 1024, vh = window.innerHeight || 768;
  let left = Math.max(8, Math.min(rect.left, vw - w - 8));
  let below = vh - rect.bottom - 10;
  return below >= h || below >= rect.top
    ? { position: `fixed`, left: `${left}px`, top: `${rect.bottom + 6}px`, bottom: `auto`, maxHeight: `${Math.max(140, below)}px`, overflowY: `auto` }
    : { position: `fixed`, left: `${left}px`, bottom: `${vh - rect.top + 6}px`, top: `auto`, maxHeight: `${Math.max(140, rect.top - 10)}px`, overflowY: `auto` };
}

function dclPickerStyle(rect) {
  if (!rect) return undefined;
  let w = 340, vw = window.innerWidth || 1024, vh = window.innerHeight || 768;
  let left = Math.max(8, Math.min(rect.left - 12, vw - w - 8));
  let below = vh - rect.bottom - 12, above = rect.top - 12;
  return below >= 220 || below >= above
    ? { position: `fixed`, left: `${left}px`, top: `${rect.bottom + 6}px`, bottom: `auto`, maxHeight: `${Math.max(160, Math.min(340, below))}px` }
    : { position: `fixed`, left: `${left}px`, bottom: `${vh - rect.top + 6}px`, top: `auto`, maxHeight: `${Math.max(160, Math.min(340, above))}px` };
}

function DclToolBtn({ title, onClick, active, on, children, label }) {
  return Z(`button`, {
    type: `button`,
    className: `rt-btn${active ? ` is-active` : ``}${on ? ` is-on` : ``}${label ? ` rt-btn-text` : ``}`,
    title,
    "aria-label": title,
    "aria-pressed": on ? `true` : undefined,
    onMouseDown: e => e.preventDefault(), // keep the text selection in the editor
    onClick,
    children,
  });
}

function DclComposer({ placeholder, buttonLabel, onSubmit, onCancel, autoFocus, initialHtml, users, people, itemId, me, compact, inputRef, allowAi }) {
  users = people?.users || users || [];
  let [box] = H(() => ({ el: null, range: null })); // editor element + last selection (kept across renders)
  let [empty, setEmpty] = H(!initialHtml), [busy, setBusy] = H(false), [err, setErr] = H(``), [note, setNote] = H(``);
  let [focused, setFocused] = H(!!autoFocus), [menu, setMenu] = H(null), [picker, setPicker] = H(null);
  let [linkUrl, setLinkUrl] = H(``), [ai, setAi] = H(null); // ai: { prompt, busy, note }
  let [fmt, setFmt] = H({}), [menuRect, setMenuRect] = H(null);
  let syncFmt = () => {
    let next = dclReadFormats(box.el);
    setFmt(prev => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  };
  U(() => {
    if (!focused) return;
    document.addEventListener(`selectionchange`, syncFmt);
    return () => document.removeEventListener(`selectionchange`, syncFmt);
  }, [focused]);
  let open = focused || !empty || busy || !!err || !!note || !!menu || !!picker || !!onCancel;
  if (!box.attachRoot) box.attachRoot = el => { if (el) box.root = el; };
  // Close any open menu / @ list when clicking outside this composer or pressing Esc.
  U(() => {
    if (!menu && !picker) return;
    let onDown = e => {
      if (box.root && !box.root.contains(e.target)) setMenu(null), setPicker(null);
    };
    let onKey = e => {
      if (e.key === `Escape`) setMenu(null), setPicker(null);
    };
    // Keep the floating @ list next to the caret while the page scrolls.
    let onScroll = e => {
      if (box.root && box.root.contains(e.target) && e.target !== document) return; // scrolling inside a menu
      let m = picker && dclMentionAtCaret(box.el);
      if (m) setPicker(prev => (prev ? { ...prev, rect: m.rect } : prev));
      if (menu === `attach` || menu === `emoji` || String(menu).startsWith(`cloud:`)) setMenu(null);
    };
    document.addEventListener(`mousedown`, onDown, true);
    document.addEventListener(`keydown`, onKey, true);
    window.addEventListener(`scroll`, onScroll, true);
    return () => {
      document.removeEventListener(`mousedown`, onDown, true);
      document.removeEventListener(`keydown`, onKey, true);
      window.removeEventListener(`scroll`, onScroll, true);
    };
  }, [menu, picker]);

  // Stable ref callback (created once), so the editor element is wired up only when it mounts.
  box.inputRef = inputRef;
  if (!box.attach) {
    box.attach = el => {
      if (!el || box.el === el) return;
      box.el = el;
      if (initialHtml) el.innerHTML = initialHtml;
      if (autoFocus) setTimeout(() => el.focus(), 0);
      box.inputRef?.(el);
    };
  }
  let saveRange = () => {
    let sel = window.getSelection();
    if (sel && sel.rangeCount && box.el && box.el.contains(sel.anchorNode)) box.range = sel.getRangeAt(0).cloneRange();
  };
  let restoreRange = () => {
    if (!box.el) return;
    box.el.focus();
    let sel = window.getSelection();
    if (box.range && sel) {
      sel.removeAllRanges();
      sel.addRange(box.range);
    }
  };
  let changed = () => {
    setEmpty(dclIsEmptyEditor(box.el));
    syncFmt();
    let m = dclMentionAtCaret(box.el);
    // A typed full name ("@Daniel K") keeps the list open while it still matches someone.
    if (m && /\s/.test(m.query)) {
      let ql = m.query.trim().toLowerCase();
      let any = users.some(u => u.name.toLowerCase().includes(ql)) || (people?.teams || []).some(t => t.name.toLowerCase().includes(ql)) || `everyone on this board`.includes(ql);
      if (!any || /\s\s$/.test(m.query)) m = null;
    }
    if (m) setPicker(prev => ({ query: m.query, rect: m.rect, index: prev && prev.query === m.query ? prev.index || 0 : 0 }));
    else if (picker) setPicker(null);
    saveRange();
  };
  // Only put the saved selection back when the cursor has left the editor. Re-applying it while the cursor is
  // still inside would wipe the browser's pending "bold on/off" state, so a second click couldn't switch it off.
  let ensureSelection = () => {
    let sel = window.getSelection();
    if (document.activeElement === box.el && sel && sel.rangeCount && box.el.contains(sel.anchorNode)) return;
    restoreRange();
  };
  let exec = (cmd, val) => {
    ensureSelection();
    document.execCommand(cmd, false, val);
    setMenu(null);
    changed();
  };
  let insertHtml = html => exec(`insertHTML`, html);

  function toggleDirection() {
    restoreRange();
    let sel = window.getSelection();
    let node = sel && sel.anchorNode;
    let block = node && (node.nodeType === 1 ? node : node.parentElement)?.closest(`p,div,li,h1,h2,h3,td`);
    if (!block || !box.el.contains(block) || block === box.el) {
      document.execCommand(`formatBlock`, false, `p`);
      node = window.getSelection().anchorNode;
      block = node && (node.nodeType === 1 ? node : node.parentElement)?.closest(`p,div,li,h1,h2,h3,td`);
    }
    if (block && box.el.contains(block) && block !== box.el) block.setAttribute(`dir`, block.getAttribute(`dir`) === `rtl` ? `ltr` : `rtl`);
    changed();
  }

  // target: { type: `User`|`Team`|`Board`, id, name }
  function pickMention(t) {
    restoreRange();
    let m = dclMentionAtCaret(box.el);
    if (m) {
      let r = document.createRange();
      r.setStart(m.node, m.start);
      r.setEnd(m.node, m.end);
      let sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
    }
    let link = `${dclMentionLinkOpen(t.type, t.id)}@${dclEscHtml(t.name)}</a>&nbsp;`;
    document.execCommand(`insertHTML`, false, link);
    setPicker(null);
    changed();
  }

  function startMention() {
    restoreRange();
    document.execCommand(`insertText`, false, `@`);
    setPicker({ query: `` });
    changed();
  }

  function addLink(kind) {
    let url = linkUrl.trim();
    if (!/^https?:\/\//i.test(url)) return setNote(`Please paste a full link starting with https://`);
    let cloud = DCL_CLOUDS.find(c => c[0] === kind);
    let label = cloud ? `📎 ${cloud[2]} file` : url;
    restoreRange();
    let sel = window.getSelection();
    if (!cloud && sel && sel.rangeCount && !sel.getRangeAt(0).collapsed) document.execCommand(`createLink`, false, url);
    else document.execCommand(`insertHTML`, false, `<a href="${dclEscHtml(url)}" target="_blank" rel="noopener noreferrer">${dclEscHtml(label)}</a>&nbsp;`);
    setLinkUrl(``), setMenu(null), setNote(``);
    changed();
  }

  // The file is uploaded when the update is posted (see dclPostWithFiles); until then it is a placeholder link.
  function onFile(ev) {
    let file = ev.target.files?.[0];
    ev.target.value = ``;
    setMenu(null);
    if (!file) return;
    if (!file.size) return setNote(`"${file.name}" is empty.`);
    if (file.size > DCL_MAX_FILE_BYTES) return setNote(`"${file.name}" is larger than 25 MB. Attach it in monday's Updates tab.`);
    box.files = box.files || {};
    let key = String((box.fileSeq = (box.fileSeq || 0) + 1));
    box.files[key] = file;
    insertHtml(`<a href="${dclPendingUrl(key)}" target="_blank" rel="noopener noreferrer">📎 ${dclEscHtml(file.name)}</a>&nbsp;`);
    setNote(`"${file.name}" is attached when you click ${buttonLabel || `Update`}.`);
  }

  async function generate() {
    if (!ai?.prompt?.trim() || ai.busy) return;
    setAi({ ...ai, busy: true, note: `` });
    try {
      let text = await dclAiWrite(ai.prompt, { itemId });
      if (text) {
        box.el.innerHTML += dclTextToHtml(text);
        setAi(null);
        setTimeout(() => { box.el?.focus(); changed(); }, 0);
      } else {
        setAi({ ...ai, busy: false, note: `Write with AI is coming soon. It needs the app's server part to connect an AI service.` });
      }
    } catch (e) {
      setAi({ ...ai, busy: false, note: e.message || `Could not generate the text.` });
    }
  }

  async function submit() {
    if (dclIsEmptyEditor(box.el) || busy) return;
    setBusy(true), setErr(``);
    try {
      let html = dclEditorToHtml(box.el.innerHTML);
      let failed = await onSubmit(html, dclMentionIds(html), box.files || {});
      box.el.innerHTML = ``;
      box.files = {};
      setEmpty(true), setPicker(null);
      setNote(failed?.length ? `Posted, but not attached: ${failed.join(`; `)}. Attach ${failed.length > 1 ? `them` : `it`} in monday's Updates tab.` : ``);
    } catch (e) {
      setErr(e.message || `Could not post.`);
    } finally {
      setBusy(false);
    }
  }

  let keep = e => e.preventDefault();
  let q = (picker?.query || ``).trim().toLowerCase();
  // @ list like monday's: People (board members first, then everyone; searchable by name, title or email), then Teams.
  let members = new Set(people?.memberIds || []);
  let personOpts = picker
    ? users
        .filter(u => !q || [u.name, u.title, u.email].some(v => (v || ``).toLowerCase().includes(q)))
        .sort((a, b) => members.has(String(b.id)) - members.has(String(a.id)) || a.name.localeCompare(b.name))
        .slice(0, 50)
        .map(u => ({ type: `User`, id: u.id, name: u.name, sub: u.title, person: u }))
    : [];
  let teamOpts = picker
    ? [
        people?.boardId && { type: `Board`, id: people.boardId, name: `Everyone on this board` },
        ...(people?.teams || []).map(t => ({ type: `Team`, id: t.id, name: t.name, photo: t.picture_url })),
      ].filter(t => t && (!q || t.name.toLowerCase().includes(q)))
    : [];
  let options = [...personOpts, ...teamOpts];
  let active = Math.min(picker?.index || 0, Math.max(options.length - 1, 0));
  let optionRow = (o, i) => Z(`button`, {
    type: `button`,
    className: `upd-picker-item${i === active ? ` is-active` : ``}`,
    onMouseDown: keep,
    onMouseEnter: () => setPicker({ ...picker, index: i }),
    onClick: () => pickMention(o),
    children: [
      o.type === `User` ? Z(DclAvatar, { person: o.person, small: true }) : Z(`span`, { className: `upd-team-ic`, children: o.photo ? Z(`img`, { src: o.photo, alt: `` }) : `👥` }),
      Z(`span`, { className: `upd-picker-name`, children: [o.name, o.sub && Z(`span`, { className: `upd-picker-sub`, children: ` (${o.sub})` })] }),
    ],
  }, `${o.type}:${o.id}`);
  let pop = (key, children, cls, style) => menu === key && Z(`div`, { className: `rt-pop${cls ? ` ${cls}` : ``}`, style, onMouseDown: e => { if (e.target.tagName !== `INPUT`) e.preventDefault(); }, children });
  let toggle = (key, ev) => {
    saveRange();
    if (ev?.currentTarget) setMenuRect(ev.currentTarget.getBoundingClientRect());
    setMenu(menu === key ? null : key);
    setLinkUrl(``);
  };

  // Formatting bar (shown while the editor is in use, like monday's).
  let toolbar = open && Z(`div`, {
    className: `rt-toolbar`,
    children: [
      Z(`div`, { className: `rt-group`, children: [
        Z(DclToolBtn, { title: `Text style`, label: true, on: fmt.heading, active: menu === `block`, onClick: () => toggle(`block`), children: `¶` }),
        pop(`block`, DCL_BLOCKS.map(([label, tag]) => Z(`button`, { type: `button`, className: `rt-pop-item rt-block-${tag}`, onClick: () => exec(`formatBlock`, `<${tag}>`), children: label }, tag))),
      ] }),
      Z(DclToolBtn, { title: `Bold (⌘B)`, label: true, on: fmt.bold, onClick: () => exec(`bold`), children: Z(`b`, { children: `B` }) }),
      Z(DclToolBtn, { title: `Italic (⌘I)`, label: true, on: fmt.italic, onClick: () => exec(`italic`), children: Z(`i`, { children: `I` }) }),
      Z(DclToolBtn, { title: `Underline (⌘U)`, label: true, on: fmt.underline, onClick: () => exec(`underline`), children: Z(`u`, { children: `U` }) }),
      Z(DclToolBtn, { title: `Strikethrough`, label: true, on: fmt.strike, onClick: () => exec(`strikeThrough`), children: Z(`s`, { children: `S` }) }),
      Z(`div`, { className: `rt-group`, children: [
        Z(DclToolBtn, { title: `Text color`, label: true, active: menu === `color`, onClick: () => toggle(`color`), children: Z(`span`, { className: `rt-color-a`, children: `A` }) }),
        pop(`color`, DCL_TEXT_COLORS.map(c => Z(`button`, { type: `button`, className: `rt-swatch`, title: c, style: { background: c }, onClick: () => exec(`foreColor`, c) }, c)), `rt-swatches`),
      ] }),
      Z(`div`, { className: `rt-group`, children: [
        Z(DclToolBtn, { title: `Font size`, label: true, active: menu === `size`, onClick: () => toggle(`size`), children: `A↕` }),
        pop(`size`, DCL_SIZES.map(([label, v]) => Z(`button`, { type: `button`, className: `rt-pop-item`, onClick: () => exec(`fontSize`, v), children: label }, v))),
      ] }),
      Z(`span`, { className: `rt-sep` }),
      Z(DclToolBtn, { title: `Numbered list`, label: true, on: fmt.ol, onClick: () => exec(`insertOrderedList`), children: `1.` }),
      Z(DclToolBtn, { title: `Bulleted list`, on: fmt.ul, onClick: () => exec(`insertUnorderedList`), children: Z(DclIcon, { name: `list` }) }),
      Z(DclToolBtn, {
        title: `Insert table`,
        onClick: () => insertHtml(`<table><tbody><tr><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr><tr><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr></tbody></table><p><br></p>`),
        children: Z(DclIcon, { name: `table` }),
      }),
      Z(`div`, { className: `rt-group`, children: [
        Z(DclToolBtn, { title: `Link`, on: fmt.link, active: menu === `link`, onClick: () => toggle(`link`), children: Z(DclIcon, { name: `link` }) }),
        pop(`link`, [
          Z(`input`, { className: `rt-input`, type: `url`, value: linkUrl, placeholder: `Paste a link…`, autoFocus: true, onChange: e => setLinkUrl(e.target.value), onKeyDown: e => { if (e.key === `Enter`) { e.preventDefault(); addLink(); } } }),
          Z(`button`, { type: `button`, className: `btn btn-primary upd-btn`, onClick: () => addLink(), children: `Add` }),
        ], `rt-linkpop`),
      ] }),
      Z(`div`, { className: `rt-group`, children: [
        Z(DclToolBtn, { title: `Align`, on: fmt.align, active: menu === `align`, onClick: () => toggle(`align`), children: Z(DclIcon, { name: `align` }) }),
        pop(`align`, DCL_ALIGNS.map(([label, cmd]) => Z(`button`, { type: `button`, className: `rt-pop-item`, onClick: () => exec(cmd), children: label }, cmd))),
      ] }),
      Z(DclToolBtn, { title: `Divider line`, onClick: () => exec(`insertHorizontalRule`), children: Z(DclIcon, { name: `minus` }) }),
      Z(DclToolBtn, { title: `Text direction (left-to-right / right-to-left)`, on: fmt.rtl, onClick: toggleDirection, children: Z(DclIcon, { name: `direction` }) }),
      Z(DclToolBtn, { title: `Checklist item`, onClick: () => insertHtml(`<p>☐&nbsp;</p>`), children: Z(DclIcon, { name: `check` }) }),
    ],
  });

  let aiPanel = ai && Z(`div`, {
    className: `ai-panel`,
    children: [
      Z(`div`, {
        className: `ai-panel-head`,
        children: [
          Z(`span`, { className: `ai-panel-title`, children: [Z(`span`, { children: `✨` }), `Write with AI`] }),
          Z(`span`, { className: `ai-beta`, children: `Beta` }),
          Z(`button`, { type: `button`, className: `upd-icon-btn`, title: `Close`, onClick: () => setAi(null), children: `✕` }),
        ],
      }),
      Z(`textarea`, {
        className: `ai-panel-input`,
        rows: 3,
        value: ai.prompt,
        autoFocus: true,
        placeholder: `Describe your update and what it should include…`,
        onChange: e => setAi({ ...ai, prompt: e.target.value, note: `` }),
        onKeyDown: e => { if ((e.metaKey || e.ctrlKey) && e.key === `Enter`) generate(); },
      }),
      ai.note && Z(`div`, { className: `ai-note`, children: [Z(`span`, { children: `✨` }), ai.note] }),
      Z(`div`, {
        className: `ai-panel-bar`,
        children: Z(`button`, { type: `button`, className: `btn ai-generate`, disabled: !ai.prompt.trim() || ai.busy, onClick: generate, children: [`✦ `, ai.busy ? `Generating…` : `Generate`] }),
      }),
    ],
  });

  return Z(`div`, {
    className: `upd-composer-row${compact ? ` is-compact` : ``}`,
    ref: box.attachRoot,
    children: [
      compact && Z(DclAvatar, { person: me, small: true }),
      aiPanel,
      Z(`div`, {
        className: `upd-composer rt-composer${open ? ` is-open` : ``}`,
        style: ai ? { display: `none` } : undefined,
        children: [
          toolbar,
          Z(`div`, {
            className: `rt-editor${empty ? ` is-empty` : ``}`,
            contentEditable: true,
            role: `textbox`,
            "aria-multiline": `true`,
            "data-placeholder": placeholder,
            ref: box.attach,
            onFocus: () => setFocused(true),
            onBlur: () => { saveRange(); setFocused(false); },
            onInput: changed,
            onKeyUp: saveRange,
            onMouseUp: saveRange,
            onMouseDown: () => menu && setMenu(null),
            onKeyDown: e => {
              if (picker && options.length && (e.key === `ArrowDown` || e.key === `ArrowUp`)) {
                e.preventDefault();
                setPicker({ ...picker, index: (active + (e.key === `ArrowDown` ? 1 : options.length - 1)) % options.length });
                return;
              }
              if (picker && options.length && (e.key === `Enter` || e.key === `Tab`) && !e.metaKey && !e.ctrlKey) {
                e.preventDefault();
                pickMention(options[active]);
                return;
              }
              if ((e.metaKey || e.ctrlKey) && e.key === `Enter`) { e.preventDefault(); submit(); }
              if (allowAi && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === `j`) { e.preventDefault(); setAi({ prompt: ``, busy: false, note: `` }); }
              if (e.key === `Escape`) setPicker(null), setMenu(null);
            },
          }),
          picker && Z(`div`, {
            className: `upd-picker upd-mention-picker`,
            style: dclPickerStyle(picker.rect),
            onMouseDown: keep,
            children: options.length
              ? [
                  personOpts.length > 0 && Z(`div`, { className: `upd-picker-head`, children: `People` }),
                  ...personOpts.map((o, i) => optionRow(o, i)),
                  teamOpts.length > 0 && Z(`div`, { className: `upd-picker-head`, children: `Teams` }),
                  ...teamOpts.map((o, i) => optionRow(o, personOpts.length + i)),
                ]
              : Z(`div`, {
                  className: `upd-picker-empty`,
                  children: users?.length
                    ? `No one matches "${picker.query}"`
                    : [
                        Z(`strong`, { children: `Can't load people to mention.` }),
                        Z(`div`, { children: `The app needs the "users:read" permission (Developer Center → OAuth & permissions).` }),
                        DCL_USERS_ERROR && Z(`div`, { className: `upd-picker-reason`, children: DCL_USERS_ERROR }),
                      ],
                }),
          }),
          menu === `emoji` && Z(`div`, {
            className: `upd-picker upd-emoji-grid`,
            style: dclPopStyle(menuRect, 316, 180),
            onMouseDown: keep,
            children: DCL_EMOJIS.map(em => Z(`button`, { type: `button`, className: `upd-emoji`, title: em, onMouseDown: keep, onClick: () => exec(`insertText`, em), children: em }, em)),
          }),
          note && Z(`div`, { className: `rt-note`, children: [note, Z(`button`, { type: `button`, className: `hp-clear`, onClick: () => setNote(``), children: `OK` })] }),
          Z(`div`, {
            className: `upd-composer-bar`,
            children: [
              Z(`div`, {
                className: `upd-tools`,
                children: [
                  Z(DclToolBtn, { title: `Mention someone`, onClick: startMention, children: Z(DclIcon, { name: `at` }) }),
                  Z(`div`, { className: `rt-group`, children: [
                    Z(DclToolBtn, { title: `Add file`, active: menu === `attach` || String(menu).startsWith(`cloud:`), onClick: ev => toggle(`attach`, ev), children: Z(DclIcon, { name: `clip` }) }),
                    pop(`attach`, [
                      Z(`label`, {
                        className: `rt-pop-item rt-attach-item`,
                        children: [Z(`span`, { className: `rt-attach-ic`, children: Z(DclIcon, { name: `clip` }) }), `From Computer`, Z(`input`, { type: `file`, className: `rt-file`, onChange: onFile })],
                      }),
                      ...DCL_CLOUDS.map(([kind, label]) => Z(`button`, {
                        type: `button`,
                        className: `rt-pop-item rt-attach-item`,
                        onClick: () => { setMenu(`cloud:${kind}`); setLinkUrl(``); },
                        children: [Z(`span`, { className: `rt-attach-ic rt-cloud-${kind}` }), label],
                      }, kind)),
                    ], `rt-attachpop`, dclPopStyle(menuRect, 260, 270)),
                    String(menu).startsWith(`cloud:`) && Z(`div`, {
                      className: `rt-pop rt-linkpop rt-attachpop`,
                      style: dclPopStyle(menuRect, 300, 120),
                      children: [
                        Z(`span`, { className: `rt-pop-hint`, children: `Paste the ${DCL_CLOUDS.find(c => `cloud:${c[0]}` === menu)?.[2]} share link` }),
                        Z(`input`, { className: `rt-input`, type: `url`, value: linkUrl, placeholder: `https://…`, autoFocus: true, onChange: e => setLinkUrl(e.target.value), onKeyDown: e => { if (e.key === `Enter`) { e.preventDefault(); addLink(menu.slice(6)); } } }),
                        Z(`button`, { type: `button`, className: `btn btn-primary upd-btn`, onClick: () => addLink(menu.slice(6)), children: `Add` }),
                      ],
                    }),
                  ] }),
                  Z(DclToolBtn, { title: `Emoji`, active: menu === `emoji`, onClick: ev => toggle(`emoji`, ev), children: Z(DclIcon, { name: `smile` }) }),
                  allowAi && Z(DclToolBtn, { title: `Write with AI (⌘J)`, onClick: () => setAi({ prompt: ``, busy: false, note: `` }), children: Z(DclIcon, { name: `aipen` }) }),
                ],
              }),
              open && Z(`div`, {
                className: `upd-submit`,
                children: [
                  err ? Z(`span`, { className: `upd-error`, children: err }) : Z(`span`, { className: `upd-hint`, children: `⌘ + Enter` }),
                  onCancel && Z(`button`, { type: `button`, className: `btn btn-ghost upd-btn`, onClick: onCancel, disabled: busy, children: `Cancel` }),
                  Z(`button`, { type: `button`, className: `btn btn-primary upd-btn`, disabled: empty || busy, onMouseDown: keep, onClick: submit, children: busy ? `Posting…` : buttonLabel }),
                ],
              }),
            ],
          }),
        ],
      }),
    ],
  });
}

/* ---------- Update card ---------- */

function DclUpdateCard({ u, itemId, boardId, userId, me, users, people, reaction, onChanged, onReactionsChanged }) {
  let [menu, setMenu] = H(false), [editing, setEditing] = H(false), [confirmDelete, setConfirmDelete] = H(false);
  let [note, setNote] = H(``), [replyEl, setReplyEl] = H(null), [likeBusy, setLikeBusy] = H(false);
  let [panel, setPanel] = H(null), [summary, setSummary] = H(null), [reminderNote, setReminderNote] = H(``), [pinBusy, setPinBusy] = H(false);
  let pinned = !!reaction?.pinned;
  let replies = [...(u.replies || [])].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  let mine = userId && String(u.creator?.id) === String(userId);
  let likes = reaction?.likes;
  let liked = !!(likes && userId && likes.includes(String(userId)));
  let flash = msg => { setNote(msg); setTimeout(() => setNote(``), 2500); };

  async function copyLink() {
    setMenu(false);
    let ok = await dclCopy(`${DCL_ACCOUNT_URL}/boards/${boardId}/pulses/${itemId}/posts/${u.id}`);
    flash(ok ? `Link copied` : `Could not copy the link`);
  }

  async function doDelete() {
    try {
      await dclDeleteUpdate(u.id);
      await onChanged();
    } catch (e) {
      setConfirmDelete(false);
      flash(e.message || `Could not delete`);
    }
  }

  async function toggleLike() {
    if (likeBusy) return;
    setLikeBusy(true);
    try {
      await dclLikeUpdate(u.id, liked);
      await onReactionsChanged();
    } catch (e) {
      flash(e.message || `Could not update the like`);
    } finally {
      setLikeBusy(false);
    }
  }

  async function togglePin() {
    setMenu(false);
    if (pinBusy) return;
    setPinBusy(true);
    try {
      await dclPinUpdate(u.id, itemId, pinned);
      await onReactionsChanged();
      flash(pinned ? `Unpinned` : `Pinned to top`);
    } catch (e) {
      flash(e.message || `Could not pin the update`);
    } finally {
      setPinBusy(false);
    }
  }

  async function openSummary() {
    if (panel === `summary`) return setPanel(null);
    setPanel(`summary`), setSummary({ loading: true });
    let plain = dclDecodeEntities(String(u.body || ``).replace(/<br\s*\/?>/gi, `\n`).replace(/<[^>]+>/g, ` `)).replace(/[ \t]+/g, ` `).trim();
    try {
      let text = await dclAiSummarize(plain, { itemId, updateId: u.id });
      setSummary(text ? { text } : { soon: true });
    } catch (e) {
      setSummary({ error: e.message || `Could not summarize.` });
    }
  }

  async function remind([label, when]) {
    try {
      let ok = await dclSetReminder(u, when(), { itemId, userId });
      setReminderNote(ok ? `Reminder set: ${label}` : `Reminders are coming soon. They need the app's server part to notify you at the right time.`);
    } catch (e) {
      setReminderNote(e.message || `Could not set the reminder.`);
    }
  }

  // ⋯ menu item. opts: { danger, disabled, hint }
  let menuItem = (icon, label, onClick, opts = {}) =>
    Z(`button`, {
      type: `button`,
      className: `upd-menu-item${opts.danger ? ` is-danger` : ``}${opts.disabled ? ` is-disabled` : ``}`,
      disabled: !!opts.disabled,
      title: opts.hint || undefined,
      onClick,
      children: [Z(DclIcon, { name: icon }), label],
    });
  let menuSep = () => Z(`div`, { className: `upd-menu-sep` });

  return Z(`article`, {
    className: `upd-card`,
    children: [
      Z(`div`, {
        className: `upd-head`,
        children: [
          Z(DclAvatar, { person: u.creator }),
          Z(`strong`, { className: `upd-name`, children: u.creator?.name || `Automations` }),
          Z(`span`, { className: `upd-time`, title: dclFmtFull(u.created_at), children: dclFmtRelative(u.created_at) }),
          dclIsRecent(u.created_at) && Z(`span`, { className: `upd-new`, children: `New` }),
          pinned && Z(`span`, { className: `upd-pinned`, title: `Pinned to top`, children: [Z(DclIcon, { name: `pin`, size: 13 }), `Pinned`] }),
          Z(`div`, {
            className: `upd-head-actions`,
            children: [
              note && Z(`span`, { className: `upd-note`, children: note }),
              Z(`button`, {
                type: `button`,
                className: `upd-icon-btn${panel === `summary` ? ` is-active` : ``}`,
                title: `Summarize`,
                onClick: openSummary,
                children: Z(DclIcon, { name: `summarize`, size: 18 }),
              }),
              Z(`div`, {
                className: `rt-group`,
                children: [
                  Z(`button`, {
                    type: `button`,
                    className: `upd-icon-btn${panel === `reminder` ? ` is-active` : ``}`,
                    title: `Set reminder`,
                    onClick: () => { setReminderNote(``); setPanel(panel === `reminder` ? null : `reminder`); },
                    children: Z(DclIcon, { name: `reminder`, size: 18 }),
                  }),
                  panel === `reminder` && Z(`div`, { className: `select-backdrop`, onClick: () => setPanel(null) }),
                  panel === `reminder` && Z(`div`, {
                    className: `upd-menu upd-reminder-menu`,
                    children: [
                      Z(`div`, { className: `upd-menu-head`, children: `Remind me about this update` }),
                      ...DCL_REMINDERS.map(r => Z(`button`, { type: `button`, className: `upd-menu-item`, onClick: () => remind(r), children: [Z(DclIcon, { name: `reminder` }), r[0]] }, r[0])),
                      reminderNote && Z(`div`, { className: `upd-menu-note`, children: reminderNote }),
                    ],
                  }),
                ],
              }),
              Z(`button`, { type: `button`, className: `upd-icon-btn${menu ? ` is-active` : ``}`, title: `More actions`, onClick: () => setMenu(!menu), children: Z(DclIcon, { name: `more`, size: 18 }) }),
              menu && Z(`div`, { className: `select-backdrop`, onClick: () => setMenu(false) }),
              menu && Z(`div`, {
                className: `upd-menu`,
                children: [
                  menuItem(`edit`, `Edit update`, () => { setMenu(false), setEditing(true); }, { disabled: !mine, hint: mine ? `` : `Only the author can edit this update` }),
                  menuSep(),
                  menuItem(`pin`, pinned ? `Unpin from top` : `Pin to top`, togglePin, { disabled: pinBusy }),
                  menuItem(`bookmark`, `Bookmark to update feed`, () => {}, { disabled: true, hint: `Bookmarks are only available in monday's own Updates tab` }),
                  menuSep(),
                  menuItem(`link`, `Copy link to update`, copyLink),
                  menuSep(),
                  menuItem(`trash`, `Delete update`, () => { setMenu(false), setConfirmDelete(true); }, { danger: true }),
                ],
              }),
            ],
          }),
        ],
      }),
      panel === `summary` && Z(`div`, {
        className: `upd-summary`,
        children: [
          Z(`div`, {
            className: `upd-summary-head`,
            children: [Z(`span`, { children: [`✨ `, `Summary`] }), Z(`button`, { type: `button`, className: `upd-icon-btn`, title: `Close`, onClick: () => setPanel(null), children: `✕` })],
          }),
          Z(`div`, {
            className: `upd-summary-body`,
            children: summary?.loading
              ? `Summarizing…`
              : summary?.text
                ? summary.text
                : summary?.error || `Summarize is coming soon. It needs the AI service that will be connected in step 2.`,
          }),
        ],
      }),
      editing
        ? Z(`div`, {
            className: `upd-edit`,
            children: Z(DclComposer, {
              placeholder: `Edit update…`,
              buttonLabel: `Save`,
              initialHtml: dclSanitizeHtml(u.body),
              autoFocus: true,
              users,
              people,
              itemId,
              onCancel: () => setEditing(false),
              onSubmit: async (html, mentionIds, files) => {
                let failed = await dclPostWithFiles(html, files, itemId, async h => (await dclEditUpdate(u.id, h), u.id));
                setEditing(false);
                await onChanged();
                return failed;
              },
            }),
          })
        : Z(DclUpdateBody, { html: u.body }),
      confirmDelete && Z(`div`, {
        className: `upd-confirm`,
        children: [
          Z(`span`, { children: `Delete this update? This can't be undone.` }),
          Z(`button`, { type: `button`, className: `btn btn-ghost upd-btn`, onClick: () => setConfirmDelete(false), children: `Cancel` }),
          Z(`button`, { type: `button`, className: `btn upd-btn upd-btn-danger`, onClick: doDelete, children: `Delete` }),
        ],
      }),
      typeof reaction?.viewers === `number` && Z(`div`, {
        className: `upd-viewers`,
        title: `Seen by ${reaction.viewers}`,
        children: [Z(DclIcon, { name: `eye` }), reaction.viewers],
      }),
      Z(`div`, {
        className: `upd-actions`,
        children: [
          Z(`button`, {
            type: `button`,
            className: `upd-action${liked ? ` is-liked` : ``}`,
            disabled: likeBusy,
            onClick: toggleLike,
            children: [Z(DclIcon, { name: `like` }), liked ? `Liked` : `Like`, likes?.length > 0 && Z(`span`, { className: `upd-like-count`, children: likes.length })],
          }),
          Z(`button`, { type: `button`, className: `upd-action`, onClick: () => replyEl?.focus(), children: [Z(DclIcon, { name: `reply` }), `Reply`] }),
        ],
      }),
      Z(`div`, {
        className: `upd-replies`,
        children: [
          ...replies.map(r => Z(`div`, {
            className: `upd-reply`,
            children: [
              Z(DclAvatar, { person: r.creator, small: true }),
              Z(`div`, {
                className: `upd-reply-main`,
                children: [
                  Z(`div`, {
                    className: `upd-reply-head`,
                    children: [
                      Z(`strong`, { children: r.creator?.name || `Automations` }),
                      Z(`span`, { className: `upd-time`, title: dclFmtFull(r.created_at), children: dclFmtRelative(r.created_at) }),
                    ],
                  }),
                  Z(DclUpdateBody, { html: r.body }),
                ],
              }),
            ],
          }, r.id)),
          Z(DclComposer, {
            placeholder: `Write a reply and mention others with @`,
            buttonLabel: `Reply`,
            compact: true,
            me,
            users,
            people,
            itemId,
            inputRef: setReplyEl,
            onSubmit: async (html, mentionIds, files) => {
              let failed = await dclPostWithFiles(html, files, itemId, async h => (await dclPostUpdate(itemId, h, u.id, mentionIds))?.id);
              await onChanged();
              return failed;
            },
          }),
        ],
      }),
    ],
  });
}

/* ---------- "Create updates via email" window (like monday's) ---------- */

// Show the start and the domain of a long address: zvg-group_puls…@euc1.mx.monday.com
function dclShortEmail(email) {
  let [local, domain] = String(email).split(`@`);
  return local && local.length > 16 ? `${local.slice(0, 14)}…@${domain}` : email;
}

function DclEmailModal({ email, itemId, onClose }) {
  let [copied, setCopied] = H(``), [customOpen, setCustomOpen] = H(false), [customCopied, setCustomCopied] = H(``);
  let customEmail = `pulse-${itemId}@${DCL_CUSTOM_EMAIL_DOMAIN}`;
  U(() => {
    let onKey = e => { if (e.key === `Escape`) onClose(); };
    document.addEventListener(`keydown`, onKey);
    return () => document.removeEventListener(`keydown`, onKey);
  }, []);
  return Z(`div`, {
    className: `em-overlay`,
    onMouseDown: e => { if (e.target === e.currentTarget) onClose(); },
    children: Z(`div`, {
      className: `em-card`,
      role: `dialog`,
      "aria-modal": `true`,
      "aria-label": `Create updates via email`,
      children: [
        Z(`button`, { type: `button`, className: `em-close`, title: `Close`, onClick: onClose, children: `✕` }),
        Z(`h2`, { className: `em-title`, children: `Create updates via email` }),
        Z(`p`, { className: `em-sub`, children: `Create updates on this item by sending an email to this address.` }),
        Z(`div`, {
          className: `em-section`,
          children: [
            Z(`div`, { className: `em-section-title`, children: [Z(`span`, { className: `em-ic`, children: `🛡` }), `Secure address`] }),
            Z(`div`, { className: `em-section-sub`, children: `Can be used by people outside the company` }),
            email === null
              ? Z(`div`, { className: `em-address`, children: Z(`span`, { className: `muted`, children: `Loading…` }) })
              : email
                ? Z(`div`, {
                    className: `em-address`,
                    children: [
                      Z(`span`, { className: `em-address-text`, title: email, children: dclShortEmail(email) }),
                      Z(`button`, {
                        type: `button`,
                        className: `em-copy`,
                        onClick: async () => { setCopied((await dclCopy(email)) ? `Copied` : `Copy failed`); setTimeout(() => setCopied(``), 2000); },
                        children: [`⧉ `, copied || `Copy`],
                      }),
                    ],
                  })
                : Z(`div`, { className: `em-address`, children: Z(`span`, { className: `muted`, children: `The address isn't available here. Open monday's Updates tab to get it.` }) }),
          ],
        }),
        Z(`div`, {
          className: `em-section em-section-custom`,
          children: [
            Z(`button`, {
              type: `button`,
              className: `em-expand`,
              onClick: () => setCustomOpen(!customOpen),
              "aria-expanded": customOpen,
              children: [
                Z(`span`, {
                  children: [
                    Z(`span`, { className: `em-section-title`, children: [Z(`span`, { className: `em-ic`, children: `⚙` }), `Custom address`] }),
                    Z(`span`, { className: `em-section-sub`, children: `Can be used only by account members` }),
                  ],
                }),
                Z(`span`, { className: `em-chevron`, children: customOpen ? `▴` : `▾` }),
              ],
            }),
            customOpen && Z(`div`, {
              className: `em-address em-address-custom`,
              children: [
                Z(`span`, { className: `em-address-text`, title: customEmail, children: dclShortEmail(customEmail) }),
                Z(`button`, {
                  type: `button`,
                  className: `em-copy em-copy-dark`,
                  onClick: async () => { setCustomCopied((await dclCopy(customEmail)) ? `Copied` : `Copy failed`); setTimeout(() => setCustomCopied(``), 2000); },
                  children: [`⧉ `, customCopied || `Copy`],
                }),
              ],
            }),
            customOpen && Z(`div`, {
              className: `em-custom-note`,
              children: [
                `This is the item's default address. If someone renamed it in monday's own Updates tab (✎), use that one instead. `,
                Z(`button`, { type: `button`, className: `hp-clear`, onClick: () => { onClose(); dclOpenMondayUpdates(itemId); }, children: `Open monday Updates` }),
              ],
            }),
          ],
        }),
      ],
    }),
  });
}

/* ---------- Feed ---------- */

// The deal's monday Updates: links + write box on top, then the feed (newest first).
function DclUpdatesFeed({ itemId, boardId, userId }) {
  let [list, setList] = H([]), [loading, setLoading] = H(true), [err, setErr] = H(``), [all, setAll] = H(false);
  let [reactions, setReactions] = H({}), [users, setUsers] = H([]), [me, setMe] = H(null);
  let [emailOpen, setEmailOpen] = H(false), [email, setEmail] = H(null);
  let [extras, setExtras] = H({ memberIds: [], teams: [] });
  let people = { users, memberIds: extras.memberIds, teams: extras.teams, boardId };

  let loadReactions = Re(async () => setReactions(await dclLoadReactions(itemId)), [itemId]);
  let load = Re(async () => {
    setErr(``);
    try {
      setList(await dclLoadUpdates(itemId));
      loadReactions();
    } catch (e) {
      setErr(e.message || `Could not load updates.`);
    } finally {
      setLoading(false);
    }
  }, [itemId, loadReactions]);
  U(() => { load(); }, [load]);
  U(() => {
    dclLoadUsers().then(list => {
      setUsers(list);
      let self = userId && list.find(u => String(u.id) === String(userId));
      if (self) setMe(self);
      else if (userId) dclTry(() => dclApi(`query ($ids: [ID!]) { users (ids: $ids) { id name photo_thumb_small } }`, { ids: [String(userId)] })).then(d => d?.users?.[0] && setMe(d.users[0]));
    });
  }, [userId]);
  U(() => { dclLoadMentionExtras(boardId).then(setExtras); }, [boardId]);

  async function openEmail() {
    setEmailOpen(true);
    if (email === null) setEmail(await dclLoadItemEmail(itemId));
  }

  let ordered = [...list].sort((a, b) => (reactions[b.id]?.pinned ? 1 : 0) - (reactions[a.id]?.pinned ? 1 : 0)); // pinned first, else newest first
  let shown = all ? ordered : ordered.slice(0, 5);
  return Z(`section`, {
    className: `upd-section upd-panel`,
    children: [
      // Panel header: title + count on the left, monday's two links on the right.
      Z(`div`, {
        className: `upd-panel-head`,
        children: [
          dclSectionTitle(`💬`, `Updates`, list.length),
          Z(`div`, {
            className: `upd-toplinks`,
            children: [
              Z(`button`, { type: `button`, className: `upd-toplink`, onClick: openEmail, children: [Z(DclIcon, { name: `mail` }), `Update via email`] }),
              Z(`span`, { className: `upd-sep` }),
              Z(`a`, { className: `upd-toplink`, href: DCL_FEEDBACK_URL, target: `_blank`, rel: `noopener noreferrer`, children: [Z(DclIcon, { name: `feedback` }), `Give feedback`] }),
            ],
          }),
        ],
      }),
      emailOpen && Z(DclEmailModal, { email, itemId, onClose: () => setEmailOpen(false) }),
      Z(DclComposer, {
        placeholder: `Write an update and mention others with @`,
        buttonLabel: `Update`,
        allowAi: true,
        users,
        people,
        itemId,
        onSubmit: async (html, mentionIds, files) => {
          let failed = await dclPostWithFiles(html, files, itemId, async h => (await dclPostUpdate(itemId, h, null, mentionIds))?.id);
          await load();
          return failed;
        },
      }),
      err && Z(`div`, { className: `banner banner-error`, role: `alert`, children: [Z(`strong`, { children: `Updates could not be loaded.` }), ` `, err] }),
      loading
        ? Z(`div`, {
            className: `upd-list`,
            "aria-label": `Loading updates`,
            children: [0, 1].map(k => Z(`div`, {
              className: `upd-skel`,
              children: [
                Z(`div`, { className: `upd-skel-head`, children: [Z(`span`, { className: `upd-skel-avatar` }), Z(`span`, { className: `upd-skel-line upd-skel-short` })] }),
                Z(`span`, { className: `upd-skel-line` }),
                Z(`span`, { className: `upd-skel-line upd-skel-mid` }),
              ],
            }, k)),
          })
        : !err && list.length === 0
          ? Z(`div`, { className: `upd-empty`, children: `No updates yet on this deal.` })
          : Z(`div`, {
              className: `upd-list`,
              children: shown.map(u => Z(DclUpdateCard, {
                u,
                itemId,
                boardId,
                userId,
                me,
                users,
                people,
                reaction: reactions[u.id],
                onChanged: load,
                onReactionsChanged: loadReactions,
              }, u.id)),
            }),
      list.length > shown.length && Z(`button`, {
        type: `button`,
        className: `btn btn-ghost upd-older`,
        onClick: () => setAll(true),
        children: `Show ${list.length - shown.length} older update${list.length - shown.length === 1 ? `` : `s`}`,
      }),
    ],
  });
}
