// Comment Builder (v4): main screen.
// build.py inserts updates-feed.js and then this file into the v2 bundle in place of its original `function Pn(){…}`.
// Layout, top to bottom: deal header → monday Updates (updates-feed.js) → comment form with the comment
// history panel beside it (sticky, searchable, filterable — no scrolling down, no separate tab).
// Uses the bundle's own helpers: Z (jsx), H (useState), U (useEffect), Re (useCallback), Cn (monday SDK),
// Q (field), Mn (chips), Nn (dropdown), $ (pill), Y (label colour), jn (empty form), option lists Gt/qt/Jt/Yt/Kt,
// and from updates-feed.js: DclUpdatesFeed, dclSectionTitle, dclFmtShort, dclFmtFull, dclInitials.

/* ---------- ✨ Autofill ---------- */

// Sends the comment to the app server (/api/ai/autofill → OpenAI), which picks the classification using the team's
// category definitions and priority rules. Returns e.g.
//   { escalation: `Yes`, categories: `W-Quote`, mainCategory: `Quote`, subCategory: `TERMS`, nextStep: `Send Proposal`, dueDate: `2026-10-30` }
// Every value is checked against this form's own option lists; anything else is dropped.
// Returns null when there is no app server (zip version): the button then shows "coming soon".
function dclYmd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, `0`)}-${String(d.getDate()).padStart(2, `0`)}`;
}

async function dclAiAutofill(comment, deal, history) {
  let now = new Date();
  let options = { escalation: Gt, categories: qt, mainCategory: Jt, subCategory: Yt, nextStep: Kt };
  // Earlier comments on this deal that the team already tagged: examples of how they classify.
  let examples = (history || [])
    .filter(h => h.comment && (h.categories || h.mainCategory || h.subCategory || h.nextStep))
    .slice(0, 8)
    .map(h => ({ comment: h.comment.slice(0, 400), escalation: h.escalation, categories: h.categories, mainCategory: h.mainCategory, subCategory: h.subCategory, nextStep: h.nextStep }));
  let data = await dclServer(`/ai/autofill`, {
    comment,
    today: dclYmd(now),
    weekday: now.toLocaleDateString(`en-GB`, { weekday: `long` }),
    dealName: deal?.name || ``,
    dealStage: deal?.stage || ``,
    options,
    examples,
  });
  if (!data) return null;
  let f = data.fields || {}, out = {};
  let pick = (val, list) => list.find(o => o.toLowerCase() === String(val || ``).trim().toLowerCase()) || ``;
  for (let key of Object.keys(options)) {
    let v = pick(f[key], options[key]);
    if (v) out[key] = v;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(f.dueDate || ``)) out.dueDate = f.dueDate;
  if (/^https?:\/\//i.test(f.transcript || ``)) out.transcript = f.transcript;
  return out;
}

/* ---------- Comment history panel (beside the form) ---------- */

function dclHistDate(e) {
  return e.date ? dclFmtShort(`${e.date}T12:00:00`) : dclFmtShort(e.createdAt);
}

function DclHistoryPanel({ items, highlightId }) {
  let [query, setQuery] = H(``), [filter, setFilter] = H(`all`), [openId, setOpenId] = H(null);
  let [cat, setCat] = H(``); // Catagories filter, e.g. `W-Quote` (same chips as the form)
  let boards = [...new Set(items.map(e => e.boardLabel).filter(Boolean))];
  let escalations = items.filter(e => e.escalation === `Yes`).length;
  let q = query.trim().toLowerCase();
  let anyFilter = !!cat || filter !== `all` || !!q;
  let shown = items.filter(e => {
    if (filter === `esc` && e.escalation !== `Yes`) return false;
    if (filter.startsWith(`board:`) && e.boardLabel !== filter.slice(6)) return false;
    if (cat && e.categories !== cat) return false;
    if (!q) return true;
    return [e.comment, e.categories, e.mainCategory, e.subCategory, e.nextStep, e.boardLabel, e.author, e.authorEmail, e.originBoard].join(` `).toLowerCase().includes(q);
  });
  // One chip per category (qt = the form's Catagories options), coloured like the form.
  let catChips = qt.map(c => {
    let active = cat === c;
    let count = items.filter(e => e.categories === c).length;
    return Z(`button`, {
      type: `button`,
      className: `chip hp-cat${active ? ` chip-active` : ``}${count ? `` : ` is-empty`}`,
      style: active ? { background: Y(c), borderColor: Y(c) } : undefined,
      "aria-pressed": active,
      onClick: () => setCat(active ? `` : c),
      children: [!active && Z(`span`, { className: `chip-dot`, style: { background: Y(c) } }), c, Z(`span`, { className: `hp-cat-count`, children: count })],
    }, c);
  });
  // "All" clears the category too; the other chips keep it.
  let chip = (key, label, count) =>
    Z(`button`, {
      type: `button`,
      className: `hp-chip${filter === key && (key !== `all` || !cat) ? ` is-active` : ``}`,
      onClick: () => { setFilter(key); if (key === `all`) setCat(``); },
      children: [label, Z(`span`, { className: `hp-chip-count`, children: count })],
    }, key);

  return Z(`aside`, {
    className: `hp`,
    children: [
      Z(`div`, {
        className: `hp-head`,
        children: [
          Z(`div`, {
            className: `hp-title`,
            children: [Z(`span`, { className: `section-icon`, children: `🕘` }), `Comment history`, items.length > 0 && Z(`span`, { className: `count`, children: items.length })],
          }),
          items.length > 0 && Z(`input`, {
            className: `hp-search`,
            type: `search`,
            value: query,
            placeholder: `Search comments…`,
            onChange: ev => setQuery(ev.target.value),
          }),
          items.length > 0 && Z(`div`, {
            className: `hp-chips`,
            children: [
              chip(`all`, `All`, items.length),
              escalations > 0 && chip(`esc`, `Escalations`, escalations),
              ...(boards.length > 1 ? boards.map(b => chip(`board:${b}`, b, items.filter(e => e.boardLabel === b).length)) : []),
              ...catChips, // Catagories, right beside "All"
            ],
          }),
          anyFilter && Z(`div`, {
            className: `hp-result`,
            children: [
              `Showing ${shown.length} of ${items.length}`,
              Z(`button`, { type: `button`, className: `hp-clear`, onClick: () => { setCat(``), setFilter(`all`), setQuery(``); }, children: `Clear filters` }),
            ],
          }),
        ],
      }),
      Z(`div`, {
        className: `hp-list`,
        children: items.length === 0
          ? Z(`div`, { className: `hp-empty`, children: [Z(`div`, { className: `hp-empty-icon`, children: `💬` }), `No comments yet. Your first one will appear here.`] })
          : shown.length === 0
            ? Z(`div`, { className: `hp-empty`, children: `Nothing matches this search.` })
            : shown.map((e, idx) => {
                let open = openId === e.id;
                let tags = [e.escalation === `Yes` && Z($, { label: `Escalation` }), Z($, { label: e.categories }), Z($, { label: e.mainCategory }), Z($, { label: e.subCategory })].filter(Boolean);
                return Z(`article`, {
                  className: `hp-item${open ? ` is-open` : ``}${e.id === highlightId ? ` is-new` : ``}${e.escalation === `Yes` ? ` is-esc` : ``}`,
                  children: [
                    Z(`button`, {
                      type: `button`,
                      className: `hp-row`,
                      onClick: () => setOpenId(open ? null : e.id),
                      "aria-expanded": open,
                      children: [
                        Z(`span`, { className: `hp-rail`, children: [Z(`span`, { className: `hp-dot` }), idx < shown.length - 1 && Z(`span`, { className: `hp-line` })] }),
                        Z(`span`, {
                          className: `hp-main`,
                          children: [
                            Z(`span`, {
                              className: `hp-top`,
                              children: [
                                Z(`strong`, { title: dclFmtFull(e.createdAt), children: dclHistDate(e) }),
                                e.id === highlightId && Z(`span`, { className: `hp-new`, children: `New` }),
                                e.escalation === `Yes` && Z(`span`, { className: `hp-flag`, children: `⚑ Escalation` }),
                                e.author && Z(`span`, { className: `hp-by`, children: `by ${e.author}` }),
                                Z(`span`, { className: `hp-chevron`, children: open ? `▴` : `▾` }),
                              ],
                            }),
                            Z(`span`, { className: `hp-text`, children: e.comment || e.name }),
                          ],
                        }),
                      ],
                    }),
                    open && Z(`div`, {
                      className: `hp-details`,
                      children: [
                        tags.length > 0 && Z(`div`, { className: `hp-tags`, children: tags }),
                        e.nextStep && Z(`div`, { className: `hp-detail`, children: [Z(`span`, { children: `Next step` }), Z($, { label: e.nextStep })] }),
                        (e.author || e.authorEmail) && Z(`div`, {
                          className: `hp-detail`,
                          children: [
                            Z(`span`, { children: `Logged by` }),
                            Z(`span`, {
                              className: `hp-author`,
                              children: [
                                Z(`strong`, { children: e.author || e.authorEmail }),
                                e.author && e.authorEmail && Z(`a`, { className: `hp-email`, href: `mailto:${e.authorEmail}`, children: e.authorEmail }),
                              ],
                            }),
                          ],
                        }),
                        e.originBoard && Z(`div`, {
                          className: `hp-detail`,
                          children: [Z(`span`, { children: `From` }), Z(`strong`, { children: [e.originBoard, e.originItem && Z(`span`, { className: `hp-origin-item`, children: ` · ${e.originItem}` })] })],
                        }),
                        e.boardLabel && Z(`div`, { className: `hp-detail`, children: [Z(`span`, { children: `Saved on` }), Z(`strong`, { children: e.boardLabel })] }),
                        Z(`div`, { className: `hp-detail`, children: [Z(`span`, { children: `Logged` }), Z(`strong`, { children: dclFmtFull(e.createdAt) })] }),
                      ],
                    }),
                  ],
                }, e.id);
              }),
      }),
    ],
  });
}

/* ---------- Main screen ---------- */

function Pn() {
  let [e, t] = H(null), // monday context
    [n, r] = H(null), // deal
    [i, a] = H(jn), // form
    [o, s] = H([]), // comment history
    [u, d] = H(!0), // loading
    [f, p] = H(!1), // saving
    [m, h] = H(``), // error
    [g, _] = H(null), // toast
    [lastId, setLastId] = H(null), // just-logged comment (highlighted in the history panel)
    [aiBusy, setAiBusy] = H(!1),
    [aiNote, setAiNote] = H(``),
    [aiFilled, setAiFilled] = H({}), // values the last Autofill put in (see autofill)
    v = k => val => a(prev => ({ ...prev, [k]: val }));
  U(() => {
    Cn.listen(`context`, c => t(c.data));
    Cn.get(`context`).then(c => t(c.data)).catch(() => {});
  }, []);
  let y = e?.itemId || e?.itemIds?.[0],
    b = Re(async () => {
      if (y) {
        d(!0), h(``);
        try {
          let deal = await Tn(y);
          r(deal), s(await On(deal.id || y));
        } catch (err) {
          h(err.message || `Could not load this deal.`);
        } finally {
          d(!1);
        }
      }
    }, [y]);
  U(() => { b(); }, [b]);
  let x = i.comment.trim().length,
    S = x > 0 && !f && !!n,
    C = En(i.comment, n?.name, n);
  async function w(ev) {
    if ((ev.preventDefault(), S)) {
      p(!0), h(``);
      try {
        let created = await Dn({ form: i, deal: n });
        a(jn()), setAiNote(``), setLastId(created.id), _(`Comment logged to ${created.boardLabel} — "${created.name}"`), s(await On(n.id || y, [created.id])), setTimeout(() => _(null), 4e3);
      } catch (err) {
        h(err.message || `Could not save the comment.`);
      } finally {
        p(!1);
      }
    }
  }
  // ✨ Autofill: fills the fields below the comment from its text (see dclAiAutofill).
  async function autofill() {
    if (!x || aiBusy) return;
    setAiBusy(!0), setAiNote(``);
    try {
      let fields = await dclAiAutofill(i.comment, n, o);
      if (fields === null) setAiNote(`Autofill is coming soon. It will fill Classification, Next step and Due date from your comment.`);
      else if (!Object.keys(fields).length) setAiNote(`Autofill couldn't tell the classification from this comment. Add a bit more detail and try again.`);
      else {
        // A field the previous Autofill filled and nobody changed since is cleared when this Autofill doesn't fill it
        // again (otherwise e.g. the last comment's due date stays). Anything typed or picked by hand is kept.
        a(prev => {
          let next = { ...prev };
          for (let k of Object.keys(aiFilled)) if (!(k in fields) && prev[k] === aiFilled[k]) next[k] = ``;
          return { ...next, ...fields };
        });
        setAiFilled(fields);
        let labels = { escalation: `Escalation`, categories: `Catagories`, mainCategory: `Main`, subCategory: `Sub`, nextStep: `Next step`, dueDate: `Due date`, transcript: `Transcript` };
        let missing = [`mainCategory`, `subCategory`, `categories`, `escalation`].filter(k => !fields[k]).map(k => labels[k]);
        setAiNote(`Filled by Autofill: ${Object.keys(fields).map(k => labels[k] || k).join(`, `)}.${missing.length ? ` Not filled: ${missing.join(`, `)}.` : ``} Please check before saving.`);
      }
    } catch (err) {
      setAiNote(err.message || `Autofill failed.`);
    } finally {
      setAiBusy(!1);
    }
  }
  if (u) return Z(`div`, { className: `app app-center`, children: [Z(`div`, { className: `spinner` }), Z(`p`, { className: `muted`, children: `Loading deal…` })] });
  if (!y) {
    return Z(`div`, {
      className: `app app-center`,
      children: [Z(`h2`, { children: `No deal in context` }), Z(`p`, { className: `muted`, children: `Open this view from inside a Deals item so the comment can be linked back to the right deal.` })],
    });
  }
  return Z(`div`, {
    className: `app`,
    children: [
      Z(`header`, {
        className: `header`,
        children: [
          Z(`div`, { className: `deal-avatar`, "aria-hidden": `true`, children: dclInitials(n?.name || `Deal`) }),
          Z(`div`, {
            className: `header-main`,
            children: [
              Z(`div`, { className: `eyebrow`, children: `Logging a comment on` }),
              n?.openedFrom && Z(`div`, { className: `opened-from`, children: [`Opened from `, Z(`strong`, { children: n.openedFrom.boardName }), ` ("${n.openedFrom.itemName}"). Showing its ${n.kind === `lead` ? `lead` : n.kind === `source` ? `item` : `deal`}.`] }),
              Z(`h1`, { className: `deal-name`, children: n?.name || `Deal` }),
              Z(`div`, {
                className: `meta`,
                children: [
                  n?.stage && Z($, { label: n.stage }),
                  n?.kind === `source` && n.boardName && Z(`span`, { className: `meta-item`, children: n.boardName }),
                  n?.dealId && Z(`span`, { className: `meta-item`, children: [n.kind === `lead` ? `Lead ID ` : n.kind === `source` ? `ID ` : `Deal ID `, n.dealId] }),
                  n?.owner && Z(`span`, { className: `meta-item`, children: n.owner }),
                ],
              }),
            ],
          }),
          Z(`div`, {
            className: `linked-badge`,
            title: n?.noLink ? `Comments from this board are saved with the board name, without a link` : `This comment is linked automatically`,
            children: [Z(`span`, { className: `link-icon`, children: `🔗` }), Z(`span`, { children: n?.noLink ? `Not linked (saved with board name)` : n?.kind === `lead` ? `Auto-linked to this lead` : n?.kind === `source` ? `Auto-linked to this item` : `Auto-linked to this deal` })],
          }),
        ],
      }),
      m && Z(`div`, {
        className: `banner banner-error`,
        role: `alert`,
        children: [Z(`strong`, { children: `Something went wrong.` }), ` `, m, Z(`button`, { className: `banner-action`, onClick: b, children: `Retry` })],
      }),
      // 1. monday Updates of this deal
      n && Z(DclUpdatesFeed, { itemId: n.id || y, boardId: n.boardId, userId: e?.user?.id }),
      // 2. Deal comment form (unchanged behaviour)
      dclSectionTitle(`✏️`, `Log a new comment`, 0),
      Z(`div`, {
        className: `cb-split`,
        children: [
      Z(`form`, {
        className: `form`,
        onSubmit: w,
        children: [
          Z(`section`, {
            className: `card card-primary cb-comment-card`,
            children: [
              // Label row: "Comment * the only required field" on the left, Autofill button on the right (same line, no overlap).
              Z(`div`, {
                className: `field`,
                role: `group`,
                "aria-label": `Comment`,
                children: [
                  Z(`div`, {
                    className: `cb-comment-head`,
                    children: [
                      Z(`span`, {
                        className: `field-label`,
                        children: [`Comment`, Z(`span`, { className: `req`, "aria-hidden": `true`, children: `*` }), Z(`span`, { className: `hint`, children: `the only required field` })],
                      }),
                      Z(`button`, {
                        type: `button`,
                        className: `ai-btn${aiBusy ? ` is-busy` : ``}`,
                        disabled: !x || aiBusy,
                        title: x ? `Fill Classification, Next step and Due date from this comment` : `Write a comment first`,
                        onClick: autofill,
                        children: [Z(`span`, { className: `ai-spark`, children: `✨` }), aiBusy ? `Filling…` : `Autofill`],
                      }),
                    ],
                  }),
                  Z(`textarea`, {
                    className: `textarea`,
                    rows: 5,
                    value: i.comment,
                    placeholder: `What happened on this deal? Log it plainly — you can tag it below, or not at all.`,
                    onChange: ev => v(`comment`)(ev.target.value),
                  }),
                ],
              }),
              Z(`div`, {
                className: `under-textarea`,
                children: [
                  Z(`span`, { className: `muted small`, children: [`Saves as: `, Z(`strong`, { children: C })] }),
                  Z(`span`, { className: `muted small${x ? `` : ` dim`}`, children: [x, ` characters`] }),
                ],
              }),
              aiNote && Z(`div`, { className: `ai-note`, role: `status`, children: [Z(`span`, { children: `✨` }), aiNote] }),
            ],
          }),
          Z(`div`, {
            className: `grid-2`,
            children: [
              Z(`section`, {
                className: `card`,
                children: Z(Q, {
                  label: `Date of comment`,
                  children: Z(`input`, { type: `date`, className: `input`, value: i.dateOfComment, onChange: ev => v(`dateOfComment`)(ev.target.value) }),
                }),
              }),
              Z(`section`, {
                className: `card`,
                children: Z(Q, { label: `Escalation needed`, children: Z(Mn, { options: Gt, value: i.escalation, onChange: v(`escalation`) }) }),
              }),
            ],
          }),
          Z(`section`, {
            className: `card`,
            children: [
              Z(`div`, { className: `card-title`, children: [`Classification `, Z(`span`, { className: `muted small`, children: `— all optional` })] }),
              Z(Q, { label: `Catagories`, children: Z(Mn, { options: qt, value: i.categories, onChange: v(`categories`) }) }),
              Z(`div`, {
                className: `grid-2`,
                children: [
                  Z(Q, { label: `Main Catagory`, children: Z(Nn, { options: Jt, value: i.mainCategory, onChange: v(`mainCategory`), placeholder: `Select main category` }) }),
                  Z(Q, { label: `Sub catagory`, children: Z(Nn, { options: Yt, value: i.subCategory, onChange: v(`subCategory`), placeholder: `Select sub category` }) }),
                ],
              }),
              Z(Q, { label: `Next Step`, children: Z(Nn, { options: Kt, value: i.nextStep, onChange: v(`nextStep`), placeholder: `Select next step` }) }),
              Z(`div`, {
                className: `grid-2`,
                children: [
                  Z(Q, {
                    label: `Due Date`,
                    children: Z(`input`, { type: `date`, className: `input`, value: i.dueDate, onChange: ev => v(`dueDate`)(ev.target.value) }),
                  }),
                  Z(Q, {
                    label: `Discussed Topic — AI Transcript`,
                    children: Z(`input`, { type: `url`, className: `input`, value: i.transcript, placeholder: `https://…`, onChange: ev => v(`transcript`)(ev.target.value) }),
                  }),
                ],
              }),
            ],
          }),
          Z(`footer`, {
            className: `actions`,
            children: [
              Z(`button`, { type: `button`, className: `btn btn-ghost`, onClick: () => { a(jn()), setAiNote(``); }, disabled: f, children: `Clear` }),
              Z(`button`, { type: `submit`, className: `btn btn-primary`, disabled: !S, children: f ? `Saving…` : `Log comment` }),
            ],
          }),
        ],
      }),
      // 3. Comment history, beside the form (sticky; no scrolling down, no separate tab)
      n && Z(DclHistoryPanel, { items: o, highlightId: lastId }),
        ],
      }),
      g && Z(`div`, { className: `toast`, role: `status`, children: g }),
    ],
  });
}
