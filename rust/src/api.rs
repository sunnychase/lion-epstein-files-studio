// (c) 2026 Sunny Chase - Lion Studios. Source-available: see LICENSE.
//! api.rs — every endpoint of the studio, a port of server.py with the same SQL and the same JSON shapes, so static/ needs no change.
//! Every answer is grounded: entities come with their mentions (page + quote), links with the pages that are their evidence.
//! Redacted parties are objects of their own, shown with their context only; nothing here proposes who a redacted person is.
use crate::db::{gf, gi, gs, ids_csv, qmarks, Arg, Row};
use crate::{args, State};
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Map, Value};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BinaryHeap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::Instant;

pub type Q = HashMap<String, String>;
pub type R = Result<Value, String>;

pub const PRODUCT: &str = "The Epstein Files - Lion Studios";
pub const COPYRIGHT: &str = "(c) 2026 Sunny Chase - Lion Studios. Source-available licence: non-commercial use free, see LICENSE.";

pub const THEMES: &[(&str, &str)] = &[
    ("blackmail / extortion", "\"blackmail\" OR \"extort\" OR \"extortion\" OR \"leverage\" OR \"compromis*\""),
    ("cameras / recordings", "\"camera\" OR \"cameras\" OR \"videotape\" OR \"recording\" OR \"recorded\" OR \"surveillance\" OR \"hidden\""),
    ("trafficking / minors", "\"trafficking\" OR \"minor\" OR \"underage\" OR \"under age\" OR \"recruit*\""),
    ("massage", "\"massage\" OR \"masseuse\" OR \"massages\""),
    ("flights / aircraft", "\"flight log\" OR \"flight logs\" OR \"manifest\" OR \"jet\" OR \"N908JE\" OR \"pilot\""),
    ("money / payments", "\"wire transfer\" OR \"payment\" OR \"paid\" OR \"invoice\" OR \"settlement\" OR \"trust\""),
    ("island / properties", "\"Little St\" OR \"island\" OR \"Zorro\" OR \"ranch\" OR \"Palm Beach\" OR \"71st Street\" OR \"Paris apartment\""),
    ("intelligence / agencies", "\"intelligence\" OR \"Mossad\" OR \"CIA\" OR \"FBI\" OR \"informant\" OR \"cooperat*\""),
    ("non-prosecution / plea", "\"non-prosecution\" OR \"NPA\" OR \"plea\" OR \"immunity\" OR \"co-conspirator\""),
    ("phones / contacts", "\"black book\" OR \"contact\" OR \"phone number\" OR \"address book\""),
    ("named as participants", "\"co-conspirator\" OR \"co-conspirators\" OR \"accomplice\" OR \"accomplices\" OR \"recruiter\" OR \"recruiters\" OR \"scheduled\" OR \"assistant\" OR \"procured\""),
];

fn e<E: std::fmt::Display>(x: E) -> String { x.to_string() }
fn arr(rows: Vec<Row>) -> Value { Value::Array(rows.into_iter().map(Value::Object).collect()) }
fn obj(r: Option<Row>) -> Value { r.map(Value::Object).unwrap_or(Value::Null) }
fn pi(q: &Q, k: &str, d: i64) -> i64 { q.get(k).and_then(|v| v.trim().parse::<f64>().ok()).map(|v| v as i64).unwrap_or(d) }
fn pf(q: &Q, k: &str, d: f64) -> f64 { q.get(k).and_then(|v| v.trim().parse().ok()).unwrap_or(d) }
fn ps<'a>(q: &'a Q, k: &str) -> &'a str { q.get(k).map(|s| s.as_str()).unwrap_or("") }
fn json_ids(v: &Value, n: usize) -> Value {
    let s = v.as_str().unwrap_or("[]");
    let parsed: Value = serde_json::from_str(s).unwrap_or(Value::Array(vec![]));
    match parsed { Value::Array(a) => Value::Array(a.into_iter().take(n).collect()), _ => Value::Array(vec![]) }
}
fn theme_q(lead: &str) -> Option<&'static str> { THEMES.iter().find(|t| t.0 == lead).map(|t| t.1) }

pub fn fts_query(q: &str) -> String {
    static TOK: Lazy<Regex> = Lazy::new(|| Regex::new(r#""[^"]*"|NEAR\([^)]*\)|\S+"#).unwrap());
    let q = q.trim();
    if q.is_empty() { return String::new(); }
    let mut out = Vec::new();
    for m in TOK.find_iter(q) {
        let t = m.as_str();
        if t.starts_with('"') || t.starts_with("NEAR(") { out.push(t.to_string()); }
        else if ["AND", "OR", "NOT"].contains(&t.to_uppercase().as_str()) { out.push(t.to_uppercase()); }
        else { out.push(format!("\"{}\"{}", t.replace('"', ""), if t.ends_with('*') { "*" } else { "" })); }
    }
    out.join(" ")
}

fn hidden_ids(st: &State) -> HashSet<i64> {
    static CLEAN: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^a-z0-9 ]").unwrap());
    let names: Vec<String> = std::fs::read_to_string(st.root.join("suppressed.json")).ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v.as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect()))
        .unwrap_or_default();
    if names.is_empty() { return HashSet::new(); }
    let norms: Vec<Arg> = names.iter().map(|n| Arg::S(CLEAN.replace_all(&n.to_lowercase(), "").trim().to_string())).collect();
    st.db.rows(&format!("SELECT id FROM entities WHERE type='PERSON' AND substr(norm, 8) IN ({})", qmarks(norms.len())), &norms)
        .map(|r| r.iter().map(|x| gi(x, "id")).collect()).unwrap_or_default()
}

pub fn api_stats(st: &State) -> R {
    let db = &st.db;
    let mut ent = Map::new();
    for r in db.rows("SELECT type, COUNT(*) n FROM entities GROUP BY type", &[]).map_err(e)? { ent.insert(gs(&r, "type"), Value::from(gi(&r, "n"))); }
    Ok(json!({"copyright": COPYRIGHT, "product": PRODUCT, "items": arr(db.rows("SELECT id, title, url, pages, mode, ingested FROM items", &[]).map_err(e)?),
        "documents": db.count("SELECT COUNT(*) FROM documents", &[]).map_err(e)?, "pages": db.count("SELECT COUNT(*) FROM pages", &[]).map_err(e)?,
        "mentions": db.count("SELECT COUNT(*) FROM mentions", &[]).map_err(e)?, "entities": ent, "links": db.count("SELECT COUNT(*) FROM links", &[]).map_err(e)?,
        "notebook": db.count("SELECT COUNT(*) FROM notebook", &[]).map_err(e)?}))
}

pub fn api_search(st: &State, q: &Q) -> R {
    let fq = fts_query(ps(q, "q")); let limit = pi(q, "limit", 50).min(200);
    if fq.is_empty() { return Ok(json!({"q": "", "hits": []})); }
    let hits = st.db.rows("SELECT p.id page_id, p.pdf_page, p.doc_id, d.title doc_title, d.docket, snippet(pages_fts, 0, '[[', ']]', '…', 28) snip, bm25(pages_fts) score \
        FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid JOIN documents d ON d.id = p.doc_id WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts) LIMIT ?", &args![&fq, limit]);
    let mut hits = match hits { Ok(h) => h, Err(er) => return Ok(json!({"q": fq, "error": format!("query not understood: {er}"), "hits": []})) };
    for h in hits.iter_mut() {
        let ents = st.db.rows("SELECT e.id, e.type, e.name FROM mentions m JOIN entities e ON e.id = m.entity_id WHERE m.page_id = ? GROUP BY e.id ORDER BY e.type, e.name LIMIT 40", &args![gi(h, "page_id")]).map_err(e)?;
        h.insert("entities".into(), arr(ents));
    }
    let total = st.db.count("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH ?", &args![&fq]).map_err(e)?;
    Ok(json!({"q": fq, "hits": arr(hits), "total": total}))
}

pub fn api_entities(st: &State, q: &Q) -> R {
    let t = ps(q, "type"); let qq = ps(q, "q").trim().to_lowercase(); let sort = ps(q, "sort"); let limit = pi(q, "limit", 100).min(2000);
    let mut sql = "SELECT id, type, name, mentions, docs FROM entities WHERE 1=1".to_string(); let mut a: Vec<Arg> = vec![];
    let hid = hidden_ids(st);
    if !hid.is_empty() { sql += &format!(" AND id NOT IN ({})", ids_csv(hid.iter().copied())); }
    if !t.is_empty() { let ts: Vec<&str> = t.split(',').collect(); sql += &format!(" AND type IN ({})", qmarks(ts.len())); a.extend(ts.iter().map(|x| Arg::from(*x))); }
    if !qq.is_empty() { sql += " AND lower(name) LIKE ?"; a.push(Arg::S(format!("%{qq}%"))); }
    sql += " ORDER BY "; sql += match sort { "docs" => "docs DESC, mentions DESC", "name" => "name", _ => "mentions DESC, docs DESC" }; sql += " LIMIT ?"; a.push(Arg::I(limit));
    Ok(json!({"entities": arr(st.db.rows(&sql, &a).map_err(e)?)}))
}

pub fn api_entity(st: &State, eid: i64, q: &Q) -> R {
    let db = &st.db;
    let Some(mut en) = db.one("SELECT * FROM entities WHERE id=?", &args![eid]).map_err(e)? else { return Ok(json!({"error": "no such entity"})) };
    en.insert("aliases".into(), Value::Array(db.rows("SELECT alias_norm FROM aliases WHERE entity_id=?", &args![eid]).map_err(e)?.iter().map(|r| Value::from(gs(r, "alias_norm"))).collect()));
    en.insert("documents".into(), arr(db.rows("SELECT d.id, d.docket, d.title, d.filed, COUNT(*) n, MIN(p.pdf_page) first_page FROM mentions m JOIN documents d ON d.id=m.doc_id JOIN pages p ON p.id=m.page_id WHERE m.entity_id=? GROUP BY d.id ORDER BY n DESC", &args![eid]).map_err(e)?));
    en.insert("mentions".into(), arr(db.rows("SELECT m.id, m.page_id, p.pdf_page, m.doc_id, d.docket, m.quote, m.surface FROM mentions m JOIN pages p ON p.id=m.page_id JOIN documents d ON d.id=m.doc_id WHERE m.entity_id=? ORDER BY p.pdf_page LIMIT ?", &args![eid, pi(q, "limit", 300).min(2000)]).map_err(e)?));
    let mut conns = db.rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END other_id, x.type, x.name, l.kind, l.weight, l.pages FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END \
        WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type NOT IN ('CASE','DATE','MONEY','URL') ORDER BY l.weight DESC, x.mentions DESC LIMIT 200", &args![eid, eid, eid, eid]).map_err(e)?;
    for c in conns.iter_mut() { let p = json_ids(c.get("pages").unwrap_or(&Value::Null), 12); c.insert("pages".into(), p); }
    let mut em = db.rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END other_id, x.type, x.name, l.weight, l.pages FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='emailed' ORDER BY l.weight DESC LIMIT 100", &args![eid, eid, eid, eid]).map_err(e)?;
    for c in em.iter_mut() { let p = json_ids(c.get("pages").unwrap_or(&Value::Null), 8); c.insert("pages".into(), p); }
    en.insert("connections".into(), arr(conns)); en.insert("emailed".into(), arr(em));
    en.insert("profile".into(), obj(db.one("SELECT title, description, extract, url, category FROM profiles WHERE entity_id=? AND found=1", &args![eid]).map_err(e)?));
    en.insert("photos".into(), Value::from(db.count("SELECT COUNT(DISTINCT p.id) FROM mentions m JOIN pages p ON p.doc_id=m.doc_id WHERE m.entity_id=? AND p.photo=1", &args![eid]).map_err(e)?));
    Ok(Value::Object(en))
}

fn kind_of(q: &Q) -> &'static str { match ps(q, "kind") { "emailed" => "emailed", "paid" => "paid", _ => "co-page" } }

pub fn api_graph(st: &State, q: &Q) -> R {
    let db = &st.db;
    let depth = pi(q, "depth", 1).min(2); let minw = pi(q, "min", 1); let limit = pi(q, "limit", 120).min(400); let kind = kind_of(q);
    let types: Vec<String> = q.get("types").map(|s| s.as_str()).unwrap_or("PERSON,ORG,PLACE,REDACTION,EMAIL,PHONE,TAIL").split(',').filter(|t| !t.is_empty()).map(|s| s.to_string()).collect();
    let tsel = format!(" AND x.type IN ({})", qmarks(types.len()));
    let mut edges: BTreeMap<(i64, i64), i64> = BTreeMap::new(); let mut hop: HashMap<i64, i64> = HashMap::new();
    let ids: Vec<i64>;
    if let Some(c) = q.get("center").and_then(|c| c.parse::<i64>().ok()) {
        let mut seeds: HashSet<i64> = HashSet::from([c]); let mut nodes: HashSet<i64> = HashSet::from([c]); hop.insert(c, 0);
        for h in 0..depth {
            let mut frontier = HashSet::new();
            for s in seeds.iter().copied() {
                let mut a: Vec<Arg> = args![s, s, s, kind, minw]; a.extend(types.iter().map(Arg::from)); a.push(Arg::I(limit));
                for r in db.rows(&format!("SELECT l.a, l.b, l.weight, l.kind FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind=? AND l.weight>=?{tsel} ORDER BY l.weight DESC LIMIT ?"), &a).map_err(e)? {
                    let (ra, rb) = (gi(&r, "a"), gi(&r, "b")); let o = if ra == s { rb } else { ra };
                    edges.insert((ra.min(rb), ra.max(rb)), gi(&r, "weight")); frontier.insert(o); hop.entry(o).or_insert(h + 1);
                }
            }
            nodes.extend(frontier.iter()); seeds = frontier;
            if nodes.len() as i64 > limit * 3 { break; }
        }
        ids = nodes.into_iter().collect();
    } else {
        let mut a: Vec<Arg> = types.iter().map(Arg::from).collect(); a.push(Arg::I(limit));
        ids = db.rows(&format!("SELECT id FROM entities x WHERE 1=1{tsel} ORDER BY mentions DESC LIMIT ?"), &a).map_err(e)?.iter().map(|r| gi(r, "id")).collect();
    }
    let idset: HashSet<i64> = ids.iter().copied().collect();
    if !ids.is_empty() {
        let csv = ids_csv(ids.iter().copied());
        for r in db.rows(&format!("SELECT a, b, weight FROM links WHERE kind=? AND weight>=? AND a IN ({csv}) AND b IN ({csv})"), &args![kind, minw]).map_err(e)? {
            let (ra, rb) = (gi(&r, "a"), gi(&r, "b"));
            if idset.contains(&ra) && idset.contains(&rb) { edges.insert((ra, rb), gi(&r, "weight")); }
        }
    }
    let hid = hidden_ids(st); let ids: Vec<i64> = ids.into_iter().filter(|i| !hid.contains(i)).collect();
    let mut ents = if ids.is_empty() { vec![] } else { db.rows(&format!("SELECT e.id, e.type, e.name, e.mentions, e.docs, p.category, p.description FROM entities e LEFT JOIN profiles p ON p.entity_id=e.id AND p.found=1 WHERE e.id IN ({})", ids_csv(ids.iter().copied())), &[]).map_err(e)? };
    for en in ents.iter_mut() { let h = hop.get(&gi(en, "id")).map(|v| Value::from(*v)).unwrap_or(Value::Null); en.insert("hop".into(), h); }
    Ok(json!({"nodes": arr(ents), "edges": edges.iter().map(|((a, b), w)| json!({"a": a, "b": b, "w": w})).collect::<Vec<_>>(), "kind": kind}))
}

#[derive(PartialEq)]
struct HeapItem(f64, i64, i64);
impl Eq for HeapItem {}
impl PartialOrd for HeapItem { fn partial_cmp(&self, o: &Self) -> Option<Ordering> { Some(self.cmp(o)) } }
impl Ord for HeapItem { fn cmp(&self, o: &Self) -> Ordering { o.0.partial_cmp(&self.0).unwrap_or(Ordering::Equal).then(o.1.cmp(&self.1)).then(o.2.cmp(&self.2)) } }

pub fn api_path(st: &State, q: &Q) -> R {
    let db = &st.db; let (a, b) = (pi(q, "a", 0), pi(q, "b", 0)); let maxlen = pi(q, "max", 4).min(6); let kind = kind_of(q);
    if a == 0 || b == 0 { return Ok(json!({"error": "give a and b"})); }
    let mut best: HashMap<i64, (f64, i64)> = HashMap::from([(a, (0.0, 0))]); let mut prev: HashMap<i64, (i64, i64)> = HashMap::new();
    let mut heap = BinaryHeap::new(); heap.push(HeapItem(0.0, 0, a));
    while let Some(HeapItem(cost, hops, n)) = heap.pop() {
        if n == b { break; }
        if hops >= maxlen || cost > best.get(&n).map(|x| x.0).unwrap_or(1e9) { continue; }
        for r in db.rows("SELECT l.a, l.b, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE l.kind=? AND (l.a=? OR l.b=?) AND x.type IN ('PERSON','ORG','PLACE','REDACTION','EMAIL','PHONE','TAIL')", &args![n, kind, n, n]).map_err(e)? {
            let (ra, rb, w) = (gi(&r, "a"), gi(&r, "b"), gi(&r, "weight")); let o = if ra == n { rb } else { ra }; let c = cost + 1.0 / (1.0 + w as f64);
            if c < best.get(&o).map(|x| x.0).unwrap_or(1e9) { best.insert(o, (c, hops + 1)); prev.insert(o, (n, w)); heap.push(HeapItem(c, hops + 1, o)); }
        }
    }
    if !prev.contains_key(&b) && a != b { return Ok(json!({"path": [], "note": format!("no chain of shared pages within {maxlen} hops")})); }
    let mut chain = vec![]; let mut n = b;
    while n != a { let (pn, w) = prev[&n]; chain.push((pn, n, w)); n = pn; }
    chain.reverse();
    let mut out = vec![];
    for (x, y, w) in chain {
        let l = db.one("SELECT pages FROM links WHERE kind=? AND a=? AND b=?", &args![kind, x.min(y), x.max(y)]).map_err(e)?;
        let pages: Vec<i64> = l.map(|l| json_ids(l.get("pages").unwrap_or(&Value::Null), 6)).and_then(|v| v.as_array().map(|a| a.iter().filter_map(|p| p.as_i64()).collect())).unwrap_or_default();
        let mut ev = vec![];
        for pid in pages.iter().take(3) {
            let qx = db.one("SELECT quote FROM mentions WHERE entity_id=? AND page_id=? LIMIT 1", &args![x, *pid]).map_err(e)?; let qy = db.one("SELECT quote FROM mentions WHERE entity_id=? AND page_id=? LIMIT 1", &args![y, *pid]).map_err(e)?;
            let pg = db.one("SELECT p.pdf_page, d.docket FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.id=?", &args![*pid]).map_err(e)?.unwrap_or_default();
            ev.push(json!({"page_id": pid, "pdf_page": pg.get("pdf_page"), "docket": pg.get("docket"), "quote_a": qx.map(|r| gs(&r, "quote")).unwrap_or_default(), "quote_b": qy.map(|r| gs(&r, "quote")).unwrap_or_default()}));
        }
        out.push(json!({"from": obj(db.one("SELECT id, type, name FROM entities WHERE id=?", &args![x]).map_err(e)?), "to": obj(db.one("SELECT id, type, name FROM entities WHERE id=?", &args![y]).map_err(e)?), "shared_pages": w, "evidence": ev}));
    }
    Ok(json!({"path": out, "kind": kind}))
}

pub fn api_doc(st: &State, did: i64) -> R {
    let db = &st.db;
    let Some(mut d) = db.one("SELECT d.*, i.title item_title, i.url FROM documents d JOIN items i ON i.id=d.item WHERE d.id=?", &args![did]).map_err(e)? else { return Ok(json!({"error": "no such document"})) };
    d.insert("pages".into(), arr(db.rows("SELECT id, pdf_page, doc_page, chars FROM pages WHERE doc_id=? ORDER BY pdf_page", &args![did]).map_err(e)?));
    d.insert("entities".into(), arr(db.rows("SELECT e.id, e.type, e.name, COUNT(*) n FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE m.doc_id=? GROUP BY e.id ORDER BY n DESC LIMIT 300", &args![did]).map_err(e)?));
    Ok(Value::Object(d))
}

pub fn api_page(st: &State, pid: i64) -> R {
    let db = &st.db;
    let Some(mut pg) = db.one("SELECT p.*, d.docket, d.title doc_title, d.case_no FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.id=?", &args![pid]).map_err(e)? else { return Ok(json!({"error": "no such page"})) };
    pg.insert("mentions".into(), arr(db.rows("SELECT m.id, m.entity_id, e.type, e.name, m.start, m.end, m.surface FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE m.page_id=? ORDER BY m.start", &args![pid]).map_err(e)?));
    let item = gs(&pg, "item");
    let nb = db.one("SELECT id FROM pages WHERE id>? AND item=? ORDER BY id LIMIT 1", &args![pid, &item]).map_err(e)?; let pv = db.one("SELECT id FROM pages WHERE id<? AND item=? ORDER BY id DESC LIMIT 1", &args![pid, &item]).map_err(e)?;
    pg.insert("next_id".into(), nb.map(|r| Value::from(gi(&r, "id"))).unwrap_or(Value::Null)); pg.insert("prev_id".into(), pv.map(|r| Value::from(gi(&r, "id"))).unwrap_or(Value::Null));
    Ok(Value::Object(pg))
}

fn source_dir(st: &State, sd: &str) -> PathBuf { let p = Path::new(sd); if p.is_absolute() { p.to_path_buf() } else { st.root.join(p) } }

/// -> (path, content type): the page's own image file (a production's IMAGES/…), else a render of its PDF page (cached)
pub fn page_png(st: &State, pid: i64, dpi: u32, prefix: &str) -> Result<Option<(PathBuf, &'static str)>, String> {
    static CLEAN: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^A-Za-z0-9._-]").unwrap());
    let Some(pg) = st.db.one("SELECT p.item, p.pdf_page, p.pdf_path, p.image_path, i.source_dir, i.pdf FROM pages p JOIN items i ON i.id=p.item WHERE p.id=?", &args![pid]).map_err(e)? else { return Ok(None) };
    let sd = source_dir(st, &gs(&pg, "source_dir"));
    let img = gs(&pg, "image_path");
    if !img.is_empty() {
        let f = sd.join(&img); let low = img.to_lowercase();
        if !f.exists() { return Ok(None); }
        let ct = if low.ends_with(".jpg") || low.ends_with(".jpeg") { "image/jpeg" } else if low.ends_with(".png") { "image/png" } else { "image/tiff" };
        if prefix == "thumb-" && ct != "image/png" { return Ok(Some((f, ct))); }
        if prefix == "thumb-" { return Ok(Some((f, ct))); }
        return Ok(Some((f, ct)));
    }
    let pdf = { let p = gs(&pg, "pdf_path"); if p.is_empty() { gs(&pg, "pdf") } else { p } };
    if pdf.is_empty() { return Ok(None); }
    let page = gi(&pg, "pdf_page");
    let out = st.cache.join(format!("{}{}.png", prefix, CLEAN.replace_all(&format!("{}-{}-{}", gs(&pg, "item"), pdf, page), "_")));
    if !out.exists() {
        let _g = st.render.lock().unwrap();
        if !out.exists() {
            let stem = out.with_extension("");
            let status = std::process::Command::new("pdftoppm").args(["-f", &page.to_string(), "-l", &page.to_string(), "-r", &dpi.to_string(), "-png", "-singlefile"]).arg(sd.join(&pdf)).arg(&stem).status().map_err(e)?;
            if !status.success() { return Err("pdftoppm failed".into()); }
        }
    }
    Ok(Some((out, "image/png")))
}

pub fn api_redactions(st: &State) -> R {
    let db = &st.db;
    let mut red = db.rows("SELECT e.id, e.name, e.mentions, e.docs FROM entities e WHERE e.type='REDACTION' ORDER BY e.mentions DESC", &[]).map_err(e)?;
    for r in red.iter_mut() {
        let id = gi(r, "id");
        r.insert("documents".into(), arr(db.rows("SELECT d.id, d.docket, COUNT(*) n FROM mentions m JOIN documents d ON d.id=m.doc_id WHERE m.entity_id=? GROUP BY d.id ORDER BY n DESC LIMIT 20", &args![id]).map_err(e)?));
        r.insert("context".into(), arr(db.rows("SELECT x.id, x.type, x.name, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type<>'REDACTION' ORDER BY l.weight DESC LIMIT 25", &args![id, id, id]).map_err(e)?));
    }
    Ok(json!({"redactions": arr(red), "note": "Redacted parties are kept redacted: the studio shows the documents, pages and named context around each redaction and never proposes who a redacted person is."}))
}

pub fn api_timeline(st: &State, q: &Q) -> R {
    static YEAR: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b(19|20)\d\d\b").unwrap());
    let eid = pi(q, "entity", 0);
    let dates = st.db.rows("SELECT x.name date_text, l.weight, l.pages FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type='DATE' ORDER BY l.weight DESC LIMIT 300", &args![eid, eid, eid]).map_err(e)?;
    let mut out: Vec<(i64, String, Value)> = dates.iter().map(|d| { let t = gs(d, "date_text"); let y = YEAR.find(&t).and_then(|m| m.as_str().parse::<i64>().ok());
        (y.unwrap_or(9999), t.clone(), json!({"date": t, "year": y, "pages": json_ids(d.get("pages").unwrap_or(&Value::Null), 6), "weight": gi(d, "weight")})) }).collect();
    out.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
    Ok(json!({"entity": eid, "dates": out.into_iter().map(|x| x.2).collect::<Vec<_>>()}))
}

pub fn api_themes(st: &State) -> R {
    let mut out = vec![];
    for (name, q) in THEMES { let n = st.db.count("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH ?", &args![*q]).unwrap_or(-1); out.push(json!({"theme": name, "q": q, "pages": n})); }
    Ok(json!({"themes": out, "note": "Each lead is a saved full-text search. A matching page is a page that uses the words, nothing more: read the quotes and judge."}))
}

pub fn api_emails(st: &State, q: &Q) -> R {
    let db = &st.db; let qq = ps(q, "q").trim(); let who = ps(q, "who").trim().to_lowercase(); let limit = pi(q, "limit", 200).min(1000);
    let mut sql = "SELECT m.id, m.page_id, m.doc_id, d.docket, m.from_raw, m.to_raw, m.cc_raw, m.date_raw, m.subject, m.from_id, f.name from_name, m.to_ids FROM emails m JOIN documents d ON d.id=m.doc_id LEFT JOIN entities f ON f.id=m.from_id".to_string();
    let mut a: Vec<Arg> = vec![]; let mut wh: Vec<&str> = vec![];
    if !qq.is_empty() { wh.push("m.id IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ?)"); a.push(Arg::S(fts_query(qq))); }
    if !who.is_empty() { wh.push("(lower(m.from_raw) LIKE ? OR lower(m.to_raw) LIKE ? OR lower(m.cc_raw) LIKE ?)"); for _ in 0..3 { a.push(Arg::S(format!("%{who}%"))); } }
    if !wh.is_empty() { sql += " WHERE "; sql += &wh.join(" AND "); }
    sql += " ORDER BY m.id LIMIT ?"; a.push(Arg::I(limit));
    let mut em = match db.rows(&sql, &a) { Ok(r) => r, Err(er) => return Ok(json!({"emails": [], "error": er.to_string()})) };
    let mut ids: HashSet<i64> = HashSet::new();
    for x in &em { if let Value::Array(v) = json_ids(x.get("to_ids").unwrap_or(&Value::Null), 10_000) { ids.extend(v.iter().filter_map(|i| i.as_i64())); } }
    let names: HashMap<i64, String> = if ids.is_empty() { HashMap::new() } else { db.rows(&format!("SELECT id, name FROM entities WHERE id IN ({})", ids_csv(ids.iter().copied())), &[]).map_err(e)?.iter().map(|r| (gi(r, "id"), gs(r, "name"))).collect() };
    for x in em.iter_mut() {
        let tn: Vec<Value> = match json_ids(x.get("to_ids").unwrap_or(&Value::Null), 10_000) { Value::Array(v) => v.iter().filter_map(|i| i.as_i64()).filter_map(|i| names.get(&i).map(|n| Value::from(n.clone()))).collect(), _ => vec![] };
        x.insert("to_names".into(), Value::Array(tn));
    }
    Ok(json!({"emails": arr(em), "total": db.count("SELECT COUNT(*) FROM emails", &[]).map_err(e)?, "senders": arr(db.rows("SELECT e.id, e.name, COUNT(*) n FROM emails m JOIN entities e ON e.id=m.from_id GROUP BY e.id ORDER BY n DESC LIMIT 40", &[]).map_err(e)?)}))
}

pub fn api_photos(st: &State, q: &Q) -> R {
    let db = &st.db; let limit = pi(q, "limit", 120).min(600); let offset = pi(q, "offset", 0);
    let (pg, note) = if let Some(ent) = q.get("entity").and_then(|v| v.parse::<i64>().ok()) {
        (db.rows("SELECT DISTINCT p.id, p.pdf_page, p.doc_id, d.docket, p.bates FROM mentions m JOIN pages p ON p.doc_id=m.doc_id JOIN documents d ON d.id=p.doc_id WHERE m.entity_id=? AND p.photo=1 ORDER BY p.id LIMIT ? OFFSET ?", &args![ent, limit, offset]).map_err(e)?, "photo pages in the documents that mention this person (the picture itself is not read; the document's text is the only link)")
    } else if let Some(did) = q.get("doc").and_then(|v| v.parse::<i64>().ok()) {
        (db.rows("SELECT p.id, p.pdf_page, p.doc_id, d.docket, p.bates FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.doc_id=? AND p.photo=1 ORDER BY p.id LIMIT ? OFFSET ?", &args![did, limit, offset]).map_err(e)?, "")
    } else {
        (db.rows("SELECT p.id, p.pdf_page, p.doc_id, d.docket, p.bates FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.photo=1 ORDER BY p.id LIMIT ? OFFSET ?", &args![limit, offset]).map_err(e)?, "every page that is a picture (a stamp or no text), newest items last")
    };
    Ok(json!({"pages": arr(pg), "total": db.count("SELECT COUNT(*) FROM pages WHERE photo=1", &[]).map_err(e)?, "note": note}))
}

fn focus_id(st: &State) -> i64 { st.db.one("SELECT id FROM entities WHERE norm='PERSON:jeffrey epstein'", &[]).ok().flatten().map(|r| gi(&r, "id")).unwrap_or(0) }

pub fn figures_rows(st: &State, cat: &str) -> Result<Vec<Row>, String> {
    let fid = focus_id(st);
    let mut sql = "SELECT e.id, e.name, e.mentions, e.docs, p.category, p.description, p.url, p.extract, COALESCE(l.weight, 0) shared \
        FROM profiles p JOIN entities e ON e.id=p.entity_id LEFT JOIN links l ON l.kind='co-page' AND ((l.a=? AND l.b=e.id) OR (l.b=? AND l.a=e.id)) WHERE p.found=1".to_string();
    let mut a = args![fid, fid];
    if !cat.is_empty() { sql += " AND p.category=?"; a.push(Arg::from(cat)); }
    sql += " ORDER BY shared DESC, e.mentions DESC LIMIT 800";
    st.db.rows(&sql, &a).map_err(e)
}

pub fn api_figures(st: &State, q: &Q) -> R {
    let fig = figures_rows(st, ps(q, "category"))?;
    Ok(json!({"figures": arr(fig), "categories": arr(st.db.rows("SELECT category, COUNT(*) n FROM profiles WHERE found=1 GROUP BY category ORDER BY n DESC", &[]).map_err(e)?), "focus": "Jeffrey Epstein",
        "note": "A public figure here is a person named in the files whose name is the exact title of a Wikipedia article (a same-name person is possible; the files are the evidence). 'Shared' = pages on which both the figure and Jeffrey Epstein are mentioned."}))
}

pub fn api_dashboard(st: &State, q: &Q) -> R {
    if q.get("fresh").is_none() { if let Some((t, v)) = st.dash.lock().unwrap().as_ref() { if t.elapsed().as_secs() < 600 { return Ok(v.clone()); } } }
    let db = &st.db; let fid = focus_id(st);
    let mut d = Map::new();
    d.insert("stats".into(), api_stats(st)?); d.insert("themes".into(), api_themes(st)?["themes"].clone());
    d.insert("pairs".into(), arr(db.rows("SELECT a.name a_name, a.id a_id, b.name b_name, b.id b_id, l.weight FROM links l JOIN entities a ON a.id=l.a JOIN entities b ON b.id=l.b WHERE l.kind='co-page' AND a.type='PERSON' AND b.type='PERSON' \
        AND a.name LIKE '% %' AND b.name LIKE '% %' AND a.name NOT GLOB '*[A-Z][A-Z][A-Z]*' AND b.name NOT GLOB '*[A-Z][A-Z][A-Z]*' ORDER BY l.weight DESC LIMIT 40", &[]).map_err(e)?));
    d.insert("emailed".into(), arr(db.rows("SELECT a.name a_name, a.id a_id, b.name b_name, b.id b_id, l.weight FROM links l JOIN entities a ON a.id=l.a JOIN entities b ON b.id=l.b WHERE l.kind='emailed' ORDER BY l.weight DESC LIMIT 30", &[]).map_err(e)?));
    d.insert("correspondents".into(), arr(db.rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END id, x.name, x.type, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='emailed' ORDER BY l.weight DESC LIMIT 30", &args![fid, fid, fid, fid]).map_err(e)?));
    let mut bycat: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for f in figures_rows(st, "")? { let c = gs(&f, "category"); let v = bycat.entry(c).or_default(); if v.len() < 12 { v.push(Value::Object(f)); } }
    d.insert("figures".into(), Value::Object(bycat.into_iter().map(|(k, v)| (k, Value::Array(v))).collect()));
    d.insert("unknown".into(), arr(db.rows("SELECT e.id, e.name, e.mentions, e.docs, COALESCE(l.weight,0) shared FROM entities e LEFT JOIN profiles p ON p.entity_id=e.id LEFT JOIN links l ON l.kind='co-page' AND ((l.a=? AND l.b=e.id) OR (l.b=? AND l.a=e.id)) \
        WHERE e.type='PERSON' AND (p.found IS NULL OR p.found=0) AND e.name LIKE '% %' AND e.name NOT GLOB '*[A-Z][A-Z][A-Z]*' AND e.id<>? ORDER BY shared DESC, e.mentions DESC LIMIT 40", &args![fid, fid, fid]).map_err(e)?));
    let red = api_redactions(st)?; d.insert("redactions".into(), Value::Array(red["redactions"].as_array().cloned().unwrap_or_default().into_iter().take(12).collect()));
    d.insert("notebook".into(), arr(db.rows("SELECT id, kind, created, title, substr(body,1,240) body FROM notebook ORDER BY id DESC LIMIT 12", &[]).map_err(e)?));
    d.insert("items".into(), arr(db.rows("SELECT id, title, pages, mode, ingested FROM items ORDER BY ingested", &[]).map_err(e)?));
    d.insert("tails".into(), arr(db.rows("SELECT id, name, mentions, docs FROM entities WHERE type='TAIL' ORDER BY mentions DESC LIMIT 12", &[]).map_err(e)?));
    d.insert("money".into(), match api_money_summary(st) { Ok(ms) => json!({"total": ms["total"], "flags": ms["flags"], "pairs": take(&ms["pairs"], 10), "banks": take(&ms["banks"], 8), "structuring": take(&ms["structuring"], 6), "biggest": take(&ms["biggest"], 6)}), Err(_) => Value::Null });
    d.insert("participants".into(), db.rows("SELECT e.id, e.name, COUNT(DISTINCT m.page_id) n, COUNT(DISTINCT m.doc_id) docs FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='PERSON' AND e.name LIKE '% %' AND e.name NOT GLOB '*[A-Z][A-Z][A-Z]*' \
        AND e.norm NOT IN ('PERSON:jeffrey epstein','PERSON:ghislaine maxwell') AND e.id NOT IN (SELECT entity_id FROM profiles WHERE found=1) \
        AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?) GROUP BY e.id HAVING n>=4 ORDER BY n DESC LIMIT 40", &args![THEMES[THEMES.len() - 1].1]).map(arr).unwrap_or(Value::Array(vec![])));
    d.insert("places".into(), arr(db.rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END id, x.name, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type='PLACE' ORDER BY l.weight DESC LIMIT 20", &args![fid, fid, fid, fid]).map_err(e)?));
    let v = Value::Object(d);
    *st.dash.lock().unwrap() = Some((Instant::now(), v.clone()));
    Ok(v)
}
fn take(v: &Value, n: usize) -> Value { Value::Array(v.as_array().cloned().unwrap_or_default().into_iter().take(n).collect()) }

/// PATTERNS: connections that no one page shows, each with its evidence (cached 10 min)
pub fn api_insights(st: &State, q: &Q) -> R {
    if q.get("fresh").is_none() { if let Some((t, v)) = st.ins.lock().unwrap().as_ref() { if t.elapsed().as_secs() < 600 { return Ok(v.clone()); } } }
    static NONAZ: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^a-z ]").unwrap());
    let db = &st.db; let mut bulbs: Vec<(f64, Value)> = vec![];
    let npages = db.count("SELECT COUNT(*) FROM pages", &[]).map_err(e)?.max(1) as f64;
    let top = db.rows("SELECT id, name, mentions FROM entities WHERE type='PERSON' AND name LIKE '% %' AND name NOT GLOB '*[A-Z][A-Z][A-Z]*' AND name NOT LIKE \"%'s\" \
        AND lower(name) NOT GLOB '*death*' AND lower(name) NOT GLOB '*investigat*' AND lower(name) NOT GLOB '*report*' AND lower(name) NOT GLOB '*exhibit*' AND lower(name) NOT GLOB '*deposition*' \
        AND lower(name) NOT GLOB '* sent' AND lower(name) NOT GLOB '* cc' AND lower(name) NOT GLOB '* re' AND lower(name) NOT GLOB '* fw' ORDER BY mentions DESC LIMIT 600", &[]).map_err(e)?;
    let lawyers: HashSet<i64> = db.rows("SELECT entity_id FROM profiles WHERE found=1 AND category='law'", &[]).map_err(e)?.iter().map(|r| gi(r, "entity_id")).collect();
    let tid: HashMap<i64, Row> = top.iter().map(|t| (gi(t, "id"), t.clone())).collect();
    let toks: HashMap<i64, HashSet<String>> = top.iter().map(|t| (gi(t, "id"), NONAZ.replace_all(&gs(t, "name").to_lowercase(), "").split_whitespace().filter(|w| w.len() >= 4).map(|s| s.to_string()).collect())).collect();
    let order: Vec<i64> = top.iter().map(|t| gi(t, "id")).collect(); let ids = ids_csv(order.iter().copied());
    let pcount: HashMap<i64, i64> = db.rows(&format!("SELECT entity_id, COUNT(DISTINCT page_id) n FROM mentions WHERE entity_id IN ({ids}) GROUP BY entity_id"), &[]).map_err(e)?.iter().map(|r| (gi(r, "entity_id"), gi(r, "n"))).collect();
    let mut adj: HashMap<i64, HashMap<i64, i64>> = HashMap::new();
    for r in db.rows(&format!("SELECT a, b, weight FROM links WHERE kind='co-page' AND weight>=2 AND a IN ({ids}) AND b IN ({ids})"), &[]).map_err(e)? {
        let (a, b, w) = (gi(&r, "a"), gi(&r, "b"), gi(&r, "weight")); adj.entry(a).or_default().insert(b, w); adj.entry(b).or_default().insert(a, w);
    }
    let name = |i: i64| tid.get(&i).map(|t| gs(t, "name")).unwrap_or_default();
    let ent = |i: i64| tid.get(&i).map(|t| Value::Object(t.clone())).unwrap_or(Value::Null);
    let shares = |a: i64, b: i64| toks.get(&a).zip(toks.get(&b)).map(|(x, y)| !x.is_disjoint(y)).unwrap_or(false);
    // 1 surprising pairs
    let mut sp: Vec<(f64, f64, i64, i64, i64)> = vec![];
    for (a, nb) in &adj { for (b, w) in nb { if a < b && *w >= 6 && pcount.get(a).copied().unwrap_or(0) >= 20 && pcount.get(b).copied().unwrap_or(0) >= 20 && !shares(*a, *b) {
        let lift = *w as f64 * npages / (pcount[a] as f64 * pcount[b] as f64);
        if lift >= 20.0 { let pen = if lawyers.contains(a) && lawyers.contains(b) { 0.3 } else { 1.0 }; sp.push((*w as f64 * lift.ln() * pen, lift, *a, *b, *w)); }
    } } }
    sp.sort_by(|x, y| y.0.partial_cmp(&x.0).unwrap_or(Ordering::Equal));
    let mut kept = 0;
    for (score, lift, a, b, w) in sp.iter().take(80) {
        let nd = db.count("SELECT COUNT(DISTINCT m1.doc_id) FROM mentions m1 JOIN mentions m2 ON m2.page_id=m1.page_id WHERE m1.entity_id=? AND m2.entity_id=?", &args![*a, *b]).map_err(e)?;
        if nd < 3 { continue; }
        bulbs.push((*score, json!({"kind": "surprising pair", "a": ent(*a), "b": ent(*b), "why": format!("{} and {} share {} pages in {} documents, {:.0}× more often than their footprints predict ({} and {} pages each)", name(*a), name(*b), w, nd, lift, pcount[a], pcount[b]), "weight": w, "score": score.round()})));
        kept += 1; if kept >= 12 { break; }
    }
    // 2 hidden links
    let first: Vec<i64> = { let mut k: Vec<i64> = adj.keys().copied().collect(); k.sort_by_key(|i| order.iter().position(|o| o == i).unwrap_or(usize::MAX)); k.into_iter().take(300).collect() };
    let mut hl: Vec<(i64, usize, i64, i64, Vec<i64>)> = vec![];
    for a in &first { for b in &first { if a < b && !adj[a].contains_key(b) && !shares(*a, *b) {
        let common: Vec<i64> = adj[a].keys().filter(|c| adj[b].contains_key(c)).copied().collect();
        if common.len() >= 6 { let s: i64 = common.iter().map(|c| adj[a][c].min(adj[b][c])).sum(); let mut via = common.clone(); via.sort_by_key(|c| -(adj[a][c].min(adj[b][c]))); via.truncate(5); hl.push((s, common.len(), *a, *b, via)); }
    } } }
    hl.sort_by(|x, y| y.0.cmp(&x.0).then(y.1.cmp(&x.1)));
    for (s, n, a, b, via) in hl.iter().take(12) {
        bulbs.push((*s as f64, json!({"kind": "hidden link", "a": ent(*a), "b": ent(*b), "via": via.iter().map(|c| ent(*c)).collect::<Vec<_>>(), "why": format!("{} and {} never appear on the same page, yet share {} companions, most of all {}", name(*a), name(*b), n, via.iter().take(3).map(|c| name(*c)).collect::<Vec<_>>().join(", ")), "weight": n, "score": s})));
    }
    // 3 bridges
    let mut seen: HashSet<i64> = HashSet::new();
    for (t, label) in [("PHONE", "phone number"), ("EMAIL", "e-mail address"), ("TAIL", "aircraft")] {
        let mut cands = db.rows(&format!("SELECT x.id, x.name, COUNT(*) n FROM links l JOIN entities x ON x.id=l.a JOIN entities y ON y.id=l.b WHERE l.kind='co-page' AND l.weight>=2 AND x.type=? AND y.type='PERSON' AND y.id IN ({ids}) GROUP BY x.id HAVING n>=3 ORDER BY n DESC LIMIT 6"), &args![t]).map_err(e)?;
        cands.extend(db.rows(&format!("SELECT x.id, x.name, COUNT(*) n FROM links l JOIN entities x ON x.id=l.b JOIN entities y ON y.id=l.a WHERE l.kind='co-page' AND l.weight>=2 AND x.type=? AND y.type='PERSON' AND y.id IN ({ids}) GROUP BY x.id HAVING n>=3 ORDER BY n DESC LIMIT 6"), &args![t]).map_err(e)?);
        for r in cands {
            let id = gi(&r, "id"); if !seen.insert(id) { continue; }
            let people = db.rows(&format!("SELECT y.id, y.name, l.weight FROM links l JOIN entities y ON y.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND y.type='PERSON' AND y.id IN ({ids}) ORDER BY l.weight DESC LIMIT 6"), &args![id, id, id]).map_err(e)?;
            if people.len() >= 3 { let n = gi(&r, "n"); bulbs.push((n as f64, json!({"kind": "bridge", "a": {"id": id, "name": gs(&r, "name"), "type": t}, "via": arr(people.clone()), "why": format!("the {} {} shares pages with {}+ people: {}", label, gs(&r, "name"), people.len(), people.iter().take(4).map(|x| gs(x, "name")).collect::<Vec<_>>().join(", ")), "weight": n, "score": n}))); }
        }
    }
    // 4 across sources
    let nitems = db.count("SELECT COUNT(*) FROM items", &[]).map_err(e)?;
    for r in db.rows(&format!("SELECT m.entity_id id, COUNT(DISTINCT p.item) items, COUNT(DISTINCT m.doc_id) docs FROM mentions m JOIN pages p ON p.id=m.page_id WHERE m.entity_id IN ({ids}) GROUP BY m.entity_id HAVING items>=3 ORDER BY docs DESC LIMIT 15"), &[]).map_err(e)? {
        let id = gi(&r, "id"); let (it, docs) = (gi(&r, "items"), gi(&r, "docs"));
        bulbs.push(((it * 10) as f64, json!({"kind": "across sources", "a": ent(id), "why": format!("{} is named in {} of the {} releases ({} documents): a court file, a DOJ data set and a House production each have them", name(id), it, nitems, docs), "weight": docs, "score": it * 10})));
    }
    // 5 public figures on lead pages
    let figs: HashMap<i64, Row> = figures_rows(st, "")?.into_iter().take(150).map(|f| (gi(&f, "id"), f)).collect();
    if !figs.is_empty() {
        let fids = ids_csv(figs.keys().copied());
        for (lead, fq) in THEMES.iter().take(6) {
            let Ok(r2) = db.rows(&format!("SELECT m.entity_id id, COUNT(DISTINCT m.page_id) n FROM mentions m WHERE m.entity_id IN ({fids}) AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?) GROUP BY m.entity_id ORDER BY n DESC LIMIT 5"), &args![*fq]) else { continue };
            for x in r2 { let n = gi(&x, "n"); if n >= 3 { let f = &figs[&gi(&x, "id")];
                bulbs.push((n as f64, json!({"kind": "figure on lead pages", "a": {"id": gi(f, "id"), "name": gs(f, "name"), "type": "PERSON"}, "lead": lead, "q": fq, "why": format!("{} ({}) is mentioned on {} pages that use the words of the lead '{}' — read them before drawing anything", gs(f, "name"), gs(f, "category"), n, lead), "weight": n, "score": n}))); } }
        }
    }
    bulbs.sort_by(|x, y| y.0.partial_cmp(&x.0).unwrap_or(Ordering::Equal));
    let v = json!({"bulbs": bulbs.into_iter().map(|b| b.1).collect::<Vec<_>>(), "note": "A pattern in the mentions is not a finding: every one links to the pages it rests on. Read them; the notebook is for what you conclude."});
    *st.ins.lock().unwrap() = Some((Instant::now(), v.clone()));
    Ok(v)
}

pub fn api_money(st: &State, q: &Q) -> R {
    let (mn, mx) = (pf(q, "min", 0.0), pf(q, "max", 0.0)); let who = ps(q, "who").trim().to_lowercase(); let flag = ps(q, "flag"); let verb = ps(q, "verb"); let sort = ps(q, "sort"); let limit = pi(q, "limit", 200).min(1000);
    let rel = pi(q, "rel", 1); let press = ps(q, "press") == "1";
    let mut sql = "SELECT y.id, y.page_id, y.doc_id, y.amount, y.verb, y.payer_id, y.payee_id, y.payer_raw, y.payee_raw, y.flags, y.quote, y.item, p.pdf_page, p.bates, d.docket, a.name payer, b.name payee \
        FROM payments y JOIN pages p ON p.id=y.page_id JOIN documents d ON d.id=y.doc_id LEFT JOIN entities a ON a.id=y.payer_id LEFT JOIN entities b ON b.id=y.payee_id WHERE 1=1 AND y.relevance>=?".to_string();
    let mut a: Vec<Arg> = args![rel];
    if !press { sql += " AND y.press=0"; }
    if mn != 0.0 { sql += " AND y.amount>=?"; a.push(Arg::F(mn)); }
    if mx != 0.0 { sql += " AND y.amount<=?"; a.push(Arg::F(mx)); }
    if !who.is_empty() { sql += " AND (lower(a.name) LIKE ? OR lower(b.name) LIKE ? OR lower(y.payer_raw) LIKE ? OR lower(y.payee_raw) LIKE ? OR lower(y.quote) LIKE ?)"; for _ in 0..5 { a.push(Arg::S(format!("%{who}%"))); } }
    if !flag.is_empty() { sql += " AND (',' || y.flags || ',') LIKE ?"; a.push(Arg::S(format!("%,{flag},%"))); }
    if !verb.is_empty() { sql += " AND y.verb=?"; a.push(Arg::from(verb)); }
    sql += " ORDER BY "; sql += match sort { "page" => "y.page_id", "flags" => "length(y.flags) DESC, y.relevance DESC, y.amount DESC", _ => "y.relevance DESC, y.amount DESC" }; sql += " LIMIT ?"; a.push(Arg::I(limit));
    Ok(json!({"payments": arr(st.db.rows(&sql, &a).map_err(e)?), "total": st.db.count("SELECT COUNT(*) FROM payments", &[]).map_err(e)?, "relevant": st.db.count("SELECT COUNT(*) FROM payments WHERE relevance>=1 AND press=0", &[]).map_err(e)?}))
}

pub fn api_money_summary(st: &State) -> R {
    let db = &st.db; let mut out = Map::new();
    out.insert("total".into(), obj(db.one("SELECT COUNT(*) n, ROUND(SUM(amount)) s FROM payments", &[]).map_err(e)?));
    out.insert("verbs".into(), arr(db.rows("SELECT verb, COUNT(*) n, ROUND(SUM(amount)) s FROM payments GROUP BY verb ORDER BY n DESC", &[]).map_err(e)?));
    let mut flags: BTreeMap<String, i64> = BTreeMap::new();
    for r in db.rows("SELECT flags FROM payments", &[]).map_err(e)? { for f in gs(&r, "flags").split(',') { if !f.is_empty() { *flags.entry(f.to_string()).or_insert(0) += 1; } } }
    out.insert("flags".into(), json!(flags));
    out.insert("payers".into(), arr(db.rows("SELECT a.id, a.name, a.type, COUNT(*) n, ROUND(SUM(y.amount)) s FROM payments y JOIN entities a ON a.id=y.payer_id GROUP BY a.id ORDER BY n DESC LIMIT 30", &[]).map_err(e)?));
    out.insert("payees".into(), arr(db.rows("SELECT b.id, b.name, b.type, COUNT(*) n, ROUND(SUM(y.amount)) s FROM payments y JOIN entities b ON b.id=y.payee_id GROUP BY b.id ORDER BY n DESC LIMIT 30", &[]).map_err(e)?));
    out.insert("pairs".into(), arr(db.rows("SELECT a.id a_id, a.name a_name, b.id b_id, b.name b_name, l.weight n, l.docs s FROM links l JOIN entities a ON a.id=l.a JOIN entities b ON b.id=l.b WHERE l.kind='paid' AND length(a.name)>=5 AND length(b.name)>=5 AND a.name NOT GLOB '*[0-9]*' AND b.name NOT GLOB '*[0-9]*' AND l.docs>=100 ORDER BY l.weight DESC, l.docs DESC LIMIT 40", &[]).map_err(e)?));
    out.insert("banks".into(), arr(db.rows("SELECT name, COUNT(*) n, COUNT(DISTINCT doc_id) docs FROM bank_pages GROUP BY lower(name) ORDER BY n DESC LIMIT 25", &[]).map_err(e)?));
    out.insert("biggest".into(), arr(db.rows("SELECT y.id, y.amount, y.verb, y.payer_raw, y.payee_raw, y.flags, y.page_id, p.pdf_page, p.bates, substr(y.quote,1,220) quote FROM payments y JOIN pages p ON p.id=y.page_id WHERE y.relevance=2 AND y.press=0 AND y.amount<1e9 ORDER BY y.amount DESC LIMIT 25", &[]).map_err(e)?));
    out.insert("structuring".into(), arr(db.rows("SELECT y.id, y.amount, y.verb, y.payer_raw, y.payee_raw, y.page_id, p.pdf_page, p.bates, substr(y.quote,1,220) quote FROM payments y JOIN pages p ON p.id=y.page_id WHERE (','||y.flags||',') LIKE '%,structuring,%' AND y.press=0 ORDER BY y.relevance DESC, y.amount DESC LIMIT 40", &[]).map_err(e)?));
    out.insert("statements".into(), arr(db.rows("SELECT p.doc_id, d.docket, d.title, COUNT(*) n, ROUND(SUM(y.amount)) s, MIN(y.page_id) page_id FROM payments y JOIN pages p ON p.id=y.page_id JOIN documents d ON d.id=p.doc_id WHERE y.verb='statement-line' GROUP BY p.doc_id ORDER BY n DESC LIMIT 25", &[]).map_err(e)?));
    out.insert("repeated".into(), arr(db.rows("SELECT y.amount, y.payee_raw, COUNT(*) n, COUNT(DISTINCT y.doc_id) docs, MIN(y.page_id) page_id FROM payments y WHERE y.relevance>=1 AND y.press=0 AND y.amount>=1000 AND y.payee_raw<>'' GROUP BY y.amount, lower(y.payee_raw) HAVING n>=3 ORDER BY n DESC LIMIT 25", &[]).map_err(e)?));
    const SECRECY: &[&str] = &["VI", "VG", "KY", "BM", "CH", "LU", "LI", "MC", "BZ", "PA", "AE", "BS", "CY", "SC", "MU", "AG", "BB", "BL", "SX", "AI", "QA", "BH", "SG", "HK"];
    let mut jur = db.rows("SELECT g.country, COUNT(DISTINCT y.page_id) pages, COUNT(DISTINCT y.doc_id) docs, ROUND(SUM(y.amount)) s, MAX(e.name) name FROM payments y JOIN mentions m ON m.page_id=y.page_id JOIN geo g ON g.entity_id=m.entity_id JOIN entities e ON e.id=m.entity_id \
        WHERE y.relevance>=1 AND y.press=0 AND g.kind IN ('country','city') AND g.country<>'US' GROUP BY g.country ORDER BY pages DESC LIMIT 30", &[]).map_err(e)?;
    for j in jur.iter_mut() { let s = SECRECY.contains(&gs(j, "country").as_str()); j.insert("secrecy".into(), Value::Bool(s)); }
    out.insert("jurisdictions".into(), arr(jur));
    out.insert("note".into(), Value::from("An amount is a figure next to a money word on a page: a court filing's claim, an invoice, a statement line, a press figure. Payer and payee are read from the sentence; when it does not say, the raw words are kept and no one is named. Flags are patterns to look at, not findings."));
    Ok(Value::Object(out))
}

fn page_set(st: &State, q: &Q, a: &mut Vec<Arg>) -> (String, String) {
    if let Some(f) = q.get("focus").and_then(|v| v.parse::<i64>().ok()) {
        a.push(Arg::I(f));
        let n = st.db.one("SELECT name FROM entities WHERE id=?", &args![f]).ok().flatten().map(|r| gs(&r, "name")).unwrap_or("?".into());
        (" AND m.page_id IN (SELECT page_id FROM mentions WHERE entity_id=?)".into(), format!("the pages that mention {n}"))
    } else if let Some(tq) = theme_q(ps(q, "lead")) {
        a.push(Arg::from(tq)); (" AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?)".into(), format!("the pages of the lead '{}'", ps(q, "lead")))
    } else { (String::new(), "every page".into()) }
}

pub fn api_globe(st: &State, q: &Q) -> R {
    let mut keyv: Vec<(&String, &String)> = q.iter().collect(); keyv.sort(); let key = format!("{keyv:?}");
    if let Some((t, v)) = st.globe.lock().unwrap().get(&key) { if t.elapsed().as_secs() < 600 { return Ok(v.clone()); } }
    let db = &st.db; let minw = pi(q, "min", 2) as usize; let photos = ps(q, "photos") != "0";
    let kinds: &[&str] = match ps(q, "kind") { "places" => &["city", "state", "region"], "airports" => &["airport"], "countries" => &["country"], _ => &["country", "city", "state", "region", "airport"] };
    let mut a: Vec<Arg> = kinds.iter().map(|k| Arg::from(*k)).collect();
    let (whr, note) = page_set(st, q, &mut a);
    let rws = db.rows(&format!("SELECT m.page_id, m.entity_id, g.lat, g.lon, g.kind, g.country, e.name FROM mentions m JOIN geo g ON g.entity_id=m.entity_id JOIN entities e ON e.id=m.entity_id WHERE g.kind IN ({}){whr}", qmarks(kinds.len())), &a).map_err(e)?;
    struct Pt { id: i64, lat: f64, lon: f64, kind: String, country: String, pages: HashSet<i64>, names: HashMap<String, i64> }
    let mut pts: HashMap<i64, Pt> = HashMap::new(); let mut perpage: HashMap<i64, HashSet<i64>> = HashMap::new(); let mut alias: HashMap<(i64, i64), i64> = HashMap::new();
    for r in &rws {
        let (lat, lon) = (gf(r, "lat"), gf(r, "lon")); let spot = ((lat * 100.0).round() as i64, (lon * 100.0).round() as i64);
        let pid_e = *alias.entry(spot).or_insert(gi(r, "entity_id"));
        let d = pts.entry(pid_e).or_insert_with(|| Pt { id: pid_e, lat, lon, kind: gs(r, "kind"), country: gs(r, "country"), pages: HashSet::new(), names: HashMap::new() });
        *d.names.entry(gs(r, "name")).or_insert(0) += 1; d.pages.insert(gi(r, "page_id")); perpage.entry(gi(r, "page_id")).or_default().insert(pid_e);
    }
    let mut arcs: HashMap<(i64, i64), HashSet<i64>> = HashMap::new();
    for (pid, es) in &perpage {
        let mut es: Vec<i64> = es.iter().copied().collect(); es.sort(); if es.len() > 25 { continue; }
        for i in 0..es.len() { for j in i + 1..es.len() { let (p, r) = (&pts[&es[i]], &pts[&es[j]]); if (p.lat, p.lon) != (r.lat, r.lon) { arcs.entry((es[i], es[j])).or_default().insert(*pid); } } }
    }
    let mut order: Vec<i64> = pts.keys().copied().collect(); order.sort_by_key(|i| std::cmp::Reverse(pts[i].pages.len())); order.truncate(400);
    let keep: HashSet<i64> = order.iter().copied().collect();
    let mut out_arcs: Vec<Value> = arcs.iter().filter(|((a, b), v)| v.len() >= minw && keep.contains(a) && keep.contains(b)).map(|((a, b), v)| { let mut p: Vec<i64> = v.iter().copied().collect(); p.sort(); json!({"a": a, "b": b, "w": v.len(), "pages": &p[..p.len().min(5)]}) }).collect();
    out_arcs.sort_by_key(|x| std::cmp::Reverse(x["w"].as_i64().unwrap_or(0))); out_arcs.truncate(600);
    let points: Vec<Value> = order.iter().map(|i| { let d = &pts[i]; let mut nm: Vec<(&String, &i64)> = d.names.iter().collect(); nm.sort_by(|x, y| y.1.cmp(x.1).then(x.0.cmp(y.0))); let mut pg: Vec<i64> = d.pages.iter().copied().collect(); pg.sort();
        json!({"id": d.id, "name": nm[0].0, "lat": d.lat, "lon": d.lon, "kind": d.kind, "country": d.country, "n": d.pages.len(), "pages": &pg[..pg.len().min(6)], "aliases": nm.iter().take(6).map(|x| x.0.clone()).collect::<Vec<_>>()}) }).collect();
    let mut ph = vec![];
    if photos && !points.is_empty() {
        let ids = ids_csv(order.iter().take(150).copied()); let pa: Vec<Arg> = a[kinds.len()..].to_vec();
        for r in db.rows(&format!("SELECT m.entity_id, p.id page_id, p.pdf_page, p.bates FROM mentions m JOIN pages p ON p.doc_id=m.doc_id AND p.photo=1 WHERE m.entity_id IN ({ids}){whr} GROUP BY m.entity_id, p.id ORDER BY m.entity_id LIMIT 4000"), &pa).map_err(e)? {
            ph.push(json!({"entity_id": gi(&r, "entity_id"), "page_id": gi(&r, "page_id"), "pdf_page": r.get("pdf_page"), "bates": r.get("bates")}));
        }
    }
    let v = json!({"points": points, "arcs": out_arcs, "photos": ph, "note": note, "kinds": kinds});
    st.globe.lock().unwrap().insert(key, (Instant::now(), v.clone()));
    Ok(v)
}

pub fn api_flights(st: &State) -> R {
    static YEAR: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b(?:19|20)\d\d\b").unwrap());
    let db = &st.db; let mut byp: HashMap<i64, HashSet<String>> = HashMap::new();
    for r in db.rows("SELECT m.page_id, g.label FROM mentions m JOIN geo g ON g.entity_id=m.entity_id WHERE g.kind='airport'", &[]).map_err(e)? { byp.entry(gi(&r, "page_id")).or_default().insert(gs(&r, "label")); }
    if byp.is_empty() { return Ok(json!({"legs": []})); }
    let pids = ids_csv(byp.keys().copied());
    let mut dates: HashMap<i64, HashSet<String>> = HashMap::new();
    for r in db.rows(&format!("SELECT m.page_id, e.name FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='DATE' AND m.page_id IN ({pids})"), &[]).map_err(e)? { dates.entry(gi(&r, "page_id")).or_default().insert(gs(&r, "name")); }
    let mut people: HashMap<i64, HashMap<String, i64>> = HashMap::new();
    for r in db.rows(&format!("SELECT m.page_id, e.name FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='PERSON' AND e.name LIKE '% %' AND m.page_id IN ({pids})"), &[]).map_err(e)? { *people.entry(gi(&r, "page_id")).or_default().entry(gs(&r, "name")).or_insert(0) += 1; }
    let mut out: Vec<(String, i64, Value)> = vec![];
    for (pid, aps) in &byp {
        if aps.len() < 2 { continue; }
        let pg = db.one("SELECT p.pdf_page, p.bates, d.docket, p.item FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.id=?", &args![*pid]).map_err(e)?.unwrap_or_default();
        let ds = dates.get(pid).cloned().unwrap_or_default(); let mut years: Vec<String> = ds.iter().flat_map(|d| YEAR.find_iter(d).map(|m| m.as_str().to_string()).collect::<Vec<_>>()).collect::<HashSet<_>>().into_iter().collect(); years.sort();
        let mut dl: Vec<String> = ds.into_iter().collect(); dl.sort(); dl.truncate(6);
        let mut pp: Vec<(String, i64)> = people.get(pid).cloned().unwrap_or_default().into_iter().collect(); pp.sort_by(|x, y| y.1.cmp(&x.1).then(x.0.cmp(&y.0)));
        let mut ap: Vec<String> = aps.iter().cloned().collect(); ap.sort();
        let bates = { let b = gs(&pg, "bates"); if b.is_empty() { gs(&pg, "docket") } else { b } };
        out.push((years.first().cloned().unwrap_or("9999".into()), *pid, json!({"page_id": pid, "pdf_page": pg.get("pdf_page"), "bates": bates, "item": gs(&pg, "item"), "airports": ap, "years": years, "dates": dl, "people": pp.iter().take(12).map(|x| x.0.clone()).collect::<Vec<_>>()})));
    }
    out.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
    Ok(json!({"legs": out.into_iter().map(|x| x.2).collect::<Vec<_>>(), "note": "Each row is a page that names two or more airports (a flight-record page): the airports, the dates on that page and the people named on it. The pairing of a person with a leg is the page's, not the studio's."}))
}

pub fn api_timeline2(st: &State, q: &Q) -> R {
    static YEAR: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b(19[5-9]\d|20[0-2]\d)\b").unwrap());
    let mut a: Vec<Arg> = vec![]; let (whr, _) = page_set(st, q, &mut a);
    let mut years: BTreeMap<i64, i64> = BTreeMap::new(); let mut samples: HashMap<i64, Vec<(String, i64)>> = HashMap::new();
    for r in st.db.rows(&format!("SELECT e.name, m.page_id FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='DATE'{whr}"), &a).map_err(e)? {
        let name = gs(&r, "name");
        if let Some(y) = YEAR.find(&name).and_then(|m| m.as_str().parse::<i64>().ok()) {
            *years.entry(y).or_insert(0) += 1; let pid = gi(&r, "page_id"); let s = samples.entry(y).or_default();
            if s.len() < 40 && !s.iter().any(|x| x.1 == pid) { s.push((name.clone(), pid)); }
        }
    }
    let out: Vec<Value> = years.iter().map(|(y, n)| json!({"year": y, "n": n, "samples": samples.get(y).map(|s| s.iter().take(12).map(|(d, p)| json!({"date": d, "page_id": p})).collect::<Vec<_>>()).unwrap_or_default()})).collect();
    Ok(json!({"years": out, "note": "Pages by the year of the dates they carry (a date on a page is the page's, not an event date): the shape of the record, then the pages behind any year."}))
}

pub fn api_globe_point(st: &State, q: &Q) -> R {
    let db = &st.db; let eid = pi(q, "id", 0); let mut a: Vec<Arg> = args![eid]; let (whr, _) = page_set(st, q, &mut a);
    let ent = obj(db.one("SELECT e.id, e.name, e.type, e.mentions, e.docs, g.kind, g.country FROM entities e JOIN geo g ON g.entity_id=e.id WHERE e.id=?", &args![eid]).map_err(e)?);
    let people = db.rows(&format!("SELECT x.id, x.name, COUNT(DISTINCT m2.page_id) n FROM mentions m JOIN mentions m2 ON m2.page_id=m.page_id JOIN entities x ON x.id=m2.entity_id WHERE m.entity_id=? AND x.type='PERSON' AND x.name LIKE '% %'{whr} GROUP BY x.id ORDER BY n DESC LIMIT 30"), &a).map_err(e)?;
    let pages = db.rows(&format!("SELECT DISTINCT m.page_id, p.pdf_page, p.bates, d.docket, m.quote FROM mentions m JOIN pages p ON p.id=m.page_id JOIN documents d ON d.id=p.doc_id WHERE m.entity_id=?{whr} ORDER BY m.page_id LIMIT 12"), &a).map_err(e)?;
    let photos = db.rows("SELECT DISTINCT p.id page_id, p.pdf_page, p.bates FROM mentions m JOIN pages p ON p.doc_id=m.doc_id AND p.photo=1 WHERE m.entity_id=? ORDER BY p.id LIMIT 24", &args![eid]).map_err(e)?;
    Ok(json!({"place": ent, "people": arr(people), "pages": arr(pages), "photos": arr(photos)}))
}

/// a Wikipedia summary for EXACTLY this title (unverified: same-name people exist); fetched on the user's click, cached, never stored in the database
pub fn api_lookup(st: &State, q: &Q) -> R {
    static WS: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap()); static NONAN: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^a-z0-9]").unwrap());
    let name = WS.replace_all(ps(q, "name"), " ").trim().to_string();
    if name.is_empty() || name.len() > 80 { return Ok(json!({"found": false})); }
    if let Some(v) = st.look.lock().unwrap().get(&name) { return Ok(v.clone()); }
    let url = format!("https://en.wikipedia.org/api/rest_v1/page/summary/{}", percent_encoding::utf8_percent_encode(&name.replace(' ', "_"), percent_encoding::NON_ALPHANUMERIC));
    let out = match ureq::get(&url).set("User-Agent", "TheEpsteinFiles-LionStudios/1.0 (local research tool)").timeout(std::time::Duration::from_secs(15)).call().ok().and_then(|r| r.into_json::<Value>().ok()) {
        Some(d) => { let title = d["title"].as_str().unwrap_or(""); let same = NONAN.replace_all(&title.to_lowercase(), "") == NONAN.replace_all(&name.to_lowercase(), "");
            json!({"found": d["type"] == "standard" && same, "title": d["title"], "description": d["description"], "extract": d["extract"].as_str().map(|s| s.chars().take(900).collect::<String>()), "url": d["content_urls"]["desktop"]["page"]}) }
        None => json!({"found": false}),
    };
    st.look.lock().unwrap().insert(name, out.clone());
    Ok(out)
}

pub fn notebook_get(st: &State) -> R { Ok(json!({"entries": arr(st.db.rows("SELECT * FROM notebook ORDER BY id DESC", &[]).map_err(e)?)})) }
pub fn notebook_post(st: &State, body: &str) -> R {
    let d: Value = serde_json::from_str(if body.is_empty() { "{}" } else { body }).map_err(e)?;
    let s = |k: &str, n: usize| d[k].as_str().unwrap_or("").chars().take(n).collect::<String>();
    let refs = serde_json::to_string(&d.get("refs").cloned().unwrap_or(Value::Array(vec![]))).unwrap_or("[]".into()).chars().take(20000).collect::<String>();
    st.db.execute("INSERT INTO notebook(kind, created, title, body, refs) VALUES(?,?,?,?,?)", &args![if d["kind"].is_string() { s("kind", 40) } else { "note".into() }, chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string(), s("title", 200), s("body", 20000), refs]).map_err(e)?;
    Ok(json!({"ok": true}))
}
pub fn notebook_delete(st: &State, q: &Q) -> R { st.db.execute("DELETE FROM notebook WHERE id=?", &args![pi(q, "id", 0)]).map_err(e)?; Ok(json!({"ok": true})) }
pub fn api_documents(st: &State) -> R { Ok(json!({"documents": arr(st.db.rows("SELECT d.*, (SELECT COUNT(DISTINCT entity_id) FROM mentions m WHERE m.doc_id=d.id) entities FROM documents d ORDER BY d.first_page", &[]).map_err(e)?)})) }
