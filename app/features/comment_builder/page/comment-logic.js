// Comment Builder: data layer (v4).
// build.py swaps this file into the v2 bundle in place of its original Tn/En/Dn/On functions.
// Relies on the bundle's `wn(query, variables)` helper (monday.api wrapper that throws on GraphQL errors).

// One entry per workspace, keyed by its Deals board ID. The app picks the entry for the board it is opened on.
var DCL_ENVS = {
  // Netgains Sandbox (original)
  "5094120922": {
    name: `Netgains Sandbox`,
    leadBoard: `5094120770`, // Qualified Warm Lead Board
    leadsBoard: { id: `5097679090`, label: `Sandbox Leads Comments` },
    commentsBoard: { id: `5097679207`, label: `Sandbox Comments` },
  },
  // Netgains Dev Sandbox (copy of the above; column IDs assumed identical)
  "5099245981": {
    name: `Netgains Dev Sandbox`,
    leadBoard: `5099246029`, // Lead Qualification Board (Dev)
    // Other boards with the tab (SQL, Opportunity, the 4 Lead data boards): comments go to Leads Comments,
    // linked through its "Comment source" connect column.
    sourceBoards: [`5100294110`, `5099246016`, `5099245930`, `5099245948`, `5099245938`, `5099245967`, `5106281544`], // + 🟢Warm Lead Mining Board🟢 (Copy)
    // Boards whose comments are NOT linked to the item; only the Source Board / Source Status text says where they came from.
    // unlinkedBoards → Leads Comments; customerBoards (the active customer workflow) → Sandbox Comments.
    unlinkedBoards: [
      `5099246051`, // Lead Generation Board (Dev)
      `5099245977`, // V2 Sandbox Shipping & Fulfilment (dev)
    ],
    customerBoards: [
      `5099246246`, // ✅ (Dev) Sandbox Kontakte (Contacts)
      `5099246109`, // ✅ (Dev) Sandbox Kunden (customers)
      `5099246214`, // ✅ V3 (Dev) Sandbox Email Address Master Board
      `5099246179`, // ✅ (Dev) Sandbox Address Master Board
    ],
    sourceLinkCol: `board_relation_mm8c72kx`,
    leadsBoard: { id: `5099245971`, label: `Sandbox Leads Comments (dev)` },
    commentsBoard: { id: `5099246381`, label: `Sandbox Comments (dev)` },
    // Column IDs that differ from the original boards (checked 22 Oct 2026), plus the "Source Board" / "Source Status" text columns.
    boardCols: {
      "5099245971": { sourceBoard: `text_mm8crwmz`, sourceStatus: `text_mm8ccqwj` },
      "5099246381": { sourceBoard: `text_mm89jz79`, sourceStatus: `text_mm8c5dc1`, transcript: `text_mm5j655k`, escalation: `color_mm5jagza` },
    },
  },
};

var DCL_WON_STAGE = /customer won/i; // Deal Stage label "Customer Won/ PO Received"

// Columns on the Deals item (same IDs in both workspaces).
var DCL_DEAL_COLS = {
  leadLink: `board_relation_mm1z3d4k`, // Sandbox Lead Qualification Board
};

// Column IDs differ between the two kinds of comment board.
var DCL_LEADS_COLS = {
  comment: `long_text_mkw2gd7g`,
  dateOfComment: `date4`,
  escalation: `color_mm3yrx1m`,
  transcript: `link_mm3yzbbw`,
  transcriptIsLink: true,
  nextStep: `color_mm3xvsq4`,
  categories: `color_mm33dxbw`,
  mainCategory: `color_mm33mzct`,
  subCategory: `color_mm338v9v`,
  dueDate: `date_mm3xgp56`,
  linkToDeal: `board_relation_mm3x67yf`,
  linkToLead: `board_relation_mm3xkrqc`, // "Sandbox Lead Qualification Board"
};
var DCL_COMMENTS_COLS = {
  comment: `long_text_mkw2gd7g`,
  dateOfComment: `date4`,
  escalation: `color_mm5jzt3a`,
  transcript: `text_mm5jx42z`,
  transcriptIsLink: false,
  nextStep: `color_mm3xvsq4`,
  categories: `color_mm33dxbw`,
  mainCategory: `color_mm33mzct`,
  subCategory: `color_mm338v9v`,
  dueDate: `date_mm3ye7y5`,
  linkToDeal: `board_relation_mm3x4wbq`,
};

// Every comment board, by board ID: { label, cols }.
var DCL_BOARDS = {};
Object.values(DCL_ENVS).forEach(env => {
  let extra = id => (env.boardCols || {})[id] || {};
  DCL_BOARDS[env.leadsBoard.id] = { label: env.leadsBoard.label, cols: { ...DCL_LEADS_COLS, ...extra(env.leadsBoard.id) } };
  DCL_BOARDS[env.commentsBoard.id] = { label: env.commentsBoard.label, cols: { ...DCL_COMMENTS_COLS, ...extra(env.commentsBoard.id) } };
});

// Lead boards, by board ID → the environment (workspace) they belong to.
var DCL_LEAD_BOARDS = {};
Object.values(DCL_ENVS).forEach(env => env.leadBoard && (DCL_LEAD_BOARDS[env.leadBoard] = env));

// Source boards (see sourceBoards) → their environment; comment boards → their environment.
// Unlinked boards → the comment board their comments go to (see unlinkedBoards / customerBoards).
var DCL_SOURCE_BOARDS = {}, DCL_UNLINKED_BOARDS = {}, DCL_COMMENT_ENVS = {};
Object.values(DCL_ENVS).forEach(env => {
  (env.sourceBoards || []).forEach(id => (DCL_SOURCE_BOARDS[id] = env));
  (env.unlinkedBoards || []).forEach(id => ((DCL_SOURCE_BOARDS[id] = env), (DCL_UNLINKED_BOARDS[id] = env.leadsBoard.id)));
  (env.customerBoards || []).forEach(id => ((DCL_SOURCE_BOARDS[id] = env), (DCL_UNLINKED_BOARDS[id] = env.commentsBoard.id)));
  DCL_COMMENT_ENVS[env.leadsBoard.id] = env;
  DCL_COMMENT_ENVS[env.commentsBoard.id] = env;
});

// Environment for a Deals board, a lead board or a source board.
function dclEnvFor(board) {
  let id = String(board?.id);
  let env = DCL_ENVS[id] || DCL_LEAD_BOARDS[id] || DCL_SOURCE_BOARDS[id];
  if (!env) throw Error(`Comment Builder is not set up for the board "${board?.name || board?.id}". No comment will be saved.`);
  return env;
}

// Routing rule for deals: Deal Stage "Customer Won/ PO Received" → Sandbox Comments, every other stage → Sandbox Leads Comments.
function dclPickBoard(env, stage) {
  return DCL_WON_STAGE.test(stage || ``) ? env.commentsBoard.id : env.leadsBoard.id;
}

// Load the deal for this item view. On a Deals item that's the item itself. On a comment-board item (Sandbox Comments,
// Sandbox Leads Comments…) it's the deal the comment is linked to, so the tab shows the same full interface there.
async function Tn(e) {
  let first = (await wn(`
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        id
        name
        board { id name }
        column_values (types: [board_relation]) { id ... on BoardRelationValue { linked_item_ids } }
      }
    }
  `, { itemId: [String(e)] }))?.items?.[0];
  if (!first) throw Error(`Item ${e} could not be loaded.`);
  if (DCL_LEAD_BOARDS[String(first.board?.id)]) return dclLoadLead(e);
  if (DCL_SOURCE_BOARDS[String(first.board?.id)]) return dclLoadSource(e);
  let commentBoard = DCL_BOARDS[String(first.board?.id)];
  if (!commentBoard) return dclLoadDeal(e);
  let linked = col => (col ? first.column_values.find(c => c.id === col)?.linked_item_ids?.[0] : null);
  let cEnv = DCL_COMMENT_ENVS[String(first.board?.id)];
  let srcCol = String(first.board?.id) === cEnv?.leadsBoard.id ? cEnv?.sourceLinkCol : null;
  let dealId = linked(commentBoard.cols.linkToDeal), leadId = linked(commentBoard.cols.linkToLead), sourceId = linked(srcCol);
  if (!dealId && !leadId && !sourceId) throw Error(`This comment on "${first.board?.name}" isn't linked to a deal, lead or source item yet. Link it to see that item here.`);
  let target = dealId ? await dclLoadDeal(dealId) : leadId ? await dclLoadLead(leadId) : await dclLoadSource(sourceId);
  target.openedFrom = { boardName: first.board?.name || commentBoard.label, itemName: first.name, itemId: first.id };
  return target;
}

// Load an item from a source board (SQL, Opportunity, Lead data boards). Comments go to Leads Comments, linked through
// the environment's "Comment source" column.
async function dclLoadSource(e) {
  let t = (await wn(`
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        id
        name
        board { id name }
        column_values (types: [status, people, text]) { id type text column { title } }
      }
    }
  `, { itemId: [String(e)] }))?.items?.[0];
  if (!t) throw Error(`Item ${e} could not be loaded.`);
  let env = dclEnvFor(t.board);
  let unlinkedTarget = DCL_UNLINKED_BOARDS[String(t.board?.id)];
  let target = unlinkedTarget || env.leadsBoard.id;
  if (!unlinkedTarget && !env.sourceLinkCol) throw Error(`Comment Builder can't link comments to "${t.board?.name}" yet. No comment will be saved.`);
  let cv = t.column_values || [];
  let byTitle = re => cv.find(c => re.test(c.column?.title || ``))?.text || ``;
  let stage = cv.find(c => c.id === `status`)?.text || byTitle(/stage|status/i) || cv.find(c => c.type === `status` && c.text)?.text || ``;
  return {
    id: t.id,
    name: t.name,
    kind: `source`,
    boardId: t.board?.id,
    boardName: t.board?.name || ``,
    envName: env.name,
    stage,
    owner: byTitle(/owner/i) || cv.find(c => c.type === `people` && c.text)?.text || ``,
    dealId: byTitle(/^(lead|opportunity|deal|customer|kunden)\s*(id|nr|nummer|no\.?)$/i),
    value: ``,
    leadNo: ``,
    leadIds: [],
    leads: [],
    noLink: !!unlinkedTarget,
    linkCol: unlinkedTarget ? null : env.sourceLinkCol,
    targetBoardId: target,
    targetLabel: DCL_BOARDS[target].label,
  };
}

// Load a lead (Lead Qualification board item). Comments on leads always go to Sandbox Leads Comments, linked to the lead.
async function dclLoadLead(e) {
  let t = (await wn(`
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        id
        name
        board { id name }
        column_values (types: [status, people, text]) { id text column { title } }
      }
    }
  `, { itemId: [String(e)] }))?.items?.[0];
  if (!t) throw Error(`Lead item ${e} could not be loaded.`);
  let env = dclEnvFor(t.board);
  let cv = t.column_values || [];
  let byTitle = re => cv.find(c => re.test(c.column?.title || ``))?.text || ``;
  let stage = cv.find(c => c.id === `status`)?.text || byTitle(/lead stage|lifecycle/i);
  return {
    id: t.id,
    name: t.name,
    kind: `lead`,
    boardId: t.board?.id,
    boardName: t.board?.name || ``,
    envName: env.name,
    stage,
    owner: byTitle(/owner/i),
    dealId: byTitle(/^lead id$/i),
    value: ``,
    leadNo: ``,
    leadIds: [String(t.id)],
    leads: [{ id: t.id, name: t.name, status: stage }],
    targetBoardId: env.leadsBoard.id,
    targetLabel: DCL_BOARDS[env.leadsBoard.id].label,
  };
}

// Load a deal (and its linked leads); its Deal Stage decides the target board (see dclPickBoard).
async function dclLoadDeal(e) {
  let t = (await wn(`
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        id
        name
        board { id name }
        column_values (ids: ["status", "person", "text_mm25rpgg", "text_mm1g2vs2", "text_mm3q51dx", "${DCL_DEAL_COLS.leadLink}"]) {
          id
          text
          ... on BoardRelationValue { linked_item_ids }
        }
      }
    }
  `, { itemId: [String(e)] }))?.items?.[0];
  if (!t) throw Error(`Deal item ${e} could not be loaded.`);
  let env = dclEnvFor(t.board);
  let n = Object.fromEntries(t.column_values.map(c => [c.id, c.text]));
  let leadCol = t.column_values.find(c => c.id === DCL_DEAL_COLS.leadLink);
  if (!leadCol) throw Error(`The lead link column was not found on "${t.board?.name}". No comment will be saved.`);
  let leadIds = (leadCol.linked_item_ids || []).map(String);
  let leads = [];
  if (leadIds.length) {
    leads = ((await wn(`
      query ($ids: [ID!]) {
        items (ids: $ids, limit: 100) {
          id
          name
          column_values (ids: ["status"]) { text }
        }
      }
    `, { ids: leadIds }))?.items || []).map(l => ({ id: l.id, name: l.name, status: l.column_values?.[0]?.text || `` }));
  }
  let target = dclPickBoard(env, n.status);
  return {
    id: t.id,
    name: t.name,
    boardId: t.board?.id,
    boardName: t.board?.name || ``,
    envName: env.name,
    stage: n.status || ``,
    owner: n.person || ``,
    dealId: n.text_mm25rpgg || ``,
    value: n.text_mm1g2vs2 || ``,
    leadNo: n.text_mm3q51dx || ``,
    leadIds,
    leads,
    targetBoardId: target,
    targetLabel: DCL_BOARDS[target].label,
  };
}

// "Saves as" preview: the item is named after the deal (customer), not the comment.
function En(e, t, d) {
  return `${t || `Deal`}${d?.targetLabel ? ` → ${d.targetLabel}` : ``}`;
}

// Create the comment item on the board chosen for this deal.
async function Dn({ form: e, deal: t }) {
  let b = DCL_BOARDS[t.targetBoardId];
  let c = b.cols;
  let n = {
    [c.comment]: e.comment,
    [c.dateOfComment]: { date: e.dateOfComment },
  };
  if (t.linkCol) {
    n[t.linkCol] = { item_ids: [String(t.id)] };
  } else if (t.noLink) {
    // Unlinked board: the Source Board / Source Status text below says where the comment came from.
  } else if (t.kind === `lead`) {
    if (!c.linkToLead) throw Error(`${b.label} has no column to link a comment to a lead.`);
    n[c.linkToLead] = { item_ids: [String(t.id)] };
  } else {
    n[c.linkToDeal] = { item_ids: [String(t.id)] };
  }
  if (e.escalation) n[c.escalation] = { label: e.escalation };
  if (e.nextStep) n[c.nextStep] = { label: e.nextStep };
  if (e.categories) n[c.categories] = { label: e.categories };
  if (e.mainCategory) n[c.mainCategory] = { label: e.mainCategory };
  if (e.subCategory) n[c.subCategory] = { label: e.subCategory };
  if (e.dueDate) n[c.dueDate] = { date: e.dueDate };
  // Where the comment came from, as plain text (a connect column can only show the item's name).
  if (c.sourceBoard && t.boardName) n[c.sourceBoard] = t.boardName;
  if (c.sourceStatus && t.stage) n[c.sourceStatus] = t.stage;
  if (e.transcript?.trim()) {
    n[c.transcript] = c.transcriptIsLink ? { url: e.transcript.trim(), text: `AI Transcript` } : e.transcript.trim();
  }
  let created = (await wn(`
    mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON!) {
      create_item (
        board_id: $boardId,
        group_id: $groupId,
        item_name: $itemName,
        column_values: $columnValues,
        create_labels_if_missing: false
      ) { id name }
    }
  `, { boardId: t.targetBoardId, groupId: `topics`, itemName: t.name || `Deal`, columnValues: JSON.stringify(n) })).create_item;
  return { ...created, boardLabel: b.label };
}

// Items on `boardId` whose connect column `columnId` links to `itemId`. Uses monday's filter when available,
// otherwise scans the newest 500 items of the board.
async function dclFindLinked(boardId, columnId, itemId) {
  try {
    let d = await wn(`
      query ($b: [ID!], $col: ID!, $v: CompareValue!) {
        boards (ids: $b) { items_page (limit: 200, query_params: { rules: [{ column_id: $col, compare_value: $v, operator: any_of }] }) { items { id } } }
      }
    `, { b: [String(boardId)], col: columnId, v: [Number(itemId)] });
    return (d?.boards?.[0]?.items_page?.items || []).map(i => String(i.id));
  } catch {}
  try {
    let d = await wn(`
      query ($b: [ID!]) {
        boards (ids: $b) { items_page (limit: 500) { items { id column_values (ids: ["${columnId}"]) { ... on BoardRelationValue { linked_item_ids } } } } }
      }
    `, { b: [String(boardId)] });
    return (d?.boards?.[0]?.items_page?.items || [])
      .filter(i => (i.column_values?.[0]?.linked_item_ids || []).map(String).includes(String(itemId)))
      .map(i => String(i.id));
  } catch {
    return [];
  }
}

// History: every item linked to the deal (two-way connect columns) that sits on this workspace's comment boards.
// Board-relation `value` is always null in the current API; linked_item_ids is the reliable field.
async function On(e, extra = []) {
  let d = (await wn(`
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        board { id name }
        column_values (types: [board_relation]) {
          ... on BoardRelationValue { linked_item_ids }
        }
      }
    }
  `, { itemId: [String(e)] }))?.items?.[0];
  if (!d) return [];
  let env = dclEnvFor(d.board);
  let envBoards = [env.leadsBoard.id, env.commentsBoard.id];
  let leadLinked = DCL_LEAD_BOARDS[String(d.board?.id)]
    ? await dclFindLinked(env.leadsBoard.id, DCL_LEADS_COLS.linkToLead, e)
    : DCL_SOURCE_BOARDS[String(d.board?.id)] && !DCL_UNLINKED_BOARDS[String(d.board?.id)] && env.sourceLinkCol
      ? await dclFindLinked(env.leadsBoard.id, env.sourceLinkCol, e)
      : [];
  let ids = [...new Set([...(d.column_values || []).flatMap(c => c.linked_item_ids || []), ...leadLinked, ...extra].map(String))];
  let items = [];
  for (let i = 0; i < ids.length; i += 100) {
    let page = (await wn(`
      query ($ids: [ID!]) {
        items (ids: $ids, limit: 100) {
          id
          name
          created_at
          creator { id name email }
          board { id }
          column_values {
            id
            text
            ... on BoardRelationValue { linked_items { id name board { id name } } }
          }
        }
      }
    `, { ids: ids.slice(i, i + 100) }))?.items || [];
    items.push(...page);
  }
  return items
    .filter(it => envBoards.includes(String(it.board?.id)))
    .map(it => {
      let b = DCL_BOARDS[it.board.id];
      let c = b.cols;
      let v = Object.fromEntries(it.column_values.map(x => [x.id, x.text || ``]));
      // Origin = the deal or lead this comment was logged on (a lead link wins, as lead comments only link to the lead).
      let linkedOf = col => (col ? it.column_values.find(x => x.id === col)?.linked_items?.[0] : null);
      let srcCol = String(it.board.id) === env.leadsBoard.id ? env.sourceLinkCol : null;
      let origin = linkedOf(srcCol) || linkedOf(c.linkToLead) || linkedOf(c.linkToDeal);
      return {
        id: it.id,
        name: it.name,
        createdAt: it.created_at,
        boardLabel: b.label,
        author: it.creator?.name || ``,
        authorEmail: it.creator?.email || ``,
        originBoard: origin?.board?.name || ``,
        originItem: origin?.name || ``,
        comment: v[c.comment] || ``,
        date: v[c.dateOfComment] || ``,
        escalation: v[c.escalation] || ``,
        nextStep: v[c.nextStep] || ``,
        categories: v[c.categories] || ``,
        mainCategory: v[c.mainCategory] || ``,
        subCategory: v[c.subCategory] || ``,
      };
    })
    .filter(x => x.comment.trim())
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
}
