// (c) 2026 Sunny Chase - Lion Studios. Source-available: see LICENSE.
//! db.rs — a pool of SQLite connections (WAL, 30 s busy timeout) and the two helpers the whole API is written with:
//! `rows(sql, args) -> Vec<Map>` and `one(sql, args) -> Option<Map>`, every column as a JSON value, so each query reads like the SQL.
use r2d2::Pool;
use r2d2_sqlite::SqliteConnectionManager;
use rusqlite::types::{ToSqlOutput, Value as Sv, ValueRef};
use rusqlite::{params_from_iter, ToSql};
use serde_json::{Map, Number, Value};
use std::path::Path;

pub type Row = Map<String, Value>;

#[derive(Clone)]
pub struct Db {
    pool: Pool<SqliteConnectionManager>,
}

/// A query argument: anything that turns into an SQLite value.
#[derive(Clone, Debug)]
pub enum Arg {
    I(i64),
    F(f64),
    S(String),
    Null,
}
impl ToSql for Arg {
    fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
        Ok(match self {
            Arg::I(v) => ToSqlOutput::Owned(Sv::Integer(*v)),
            Arg::F(v) => ToSqlOutput::Owned(Sv::Real(*v)),
            Arg::S(v) => ToSqlOutput::Owned(Sv::Text(v.clone())),
            Arg::Null => ToSqlOutput::Owned(Sv::Null),
        })
    }
}
impl From<i64> for Arg { fn from(v: i64) -> Self { Arg::I(v) } }
impl From<i32> for Arg { fn from(v: i32) -> Self { Arg::I(v as i64) } }
impl From<usize> for Arg { fn from(v: usize) -> Self { Arg::I(v as i64) } }
impl From<f64> for Arg { fn from(v: f64) -> Self { Arg::F(v) } }
impl From<&str> for Arg { fn from(v: &str) -> Self { Arg::S(v.to_string()) } }
impl From<String> for Arg { fn from(v: String) -> Self { Arg::S(v) } }
impl From<&String> for Arg { fn from(v: &String) -> Self { Arg::S(v.clone()) } }

#[macro_export]
macro_rules! args {
    () => { Vec::<$crate::db::Arg>::new() };
    ($($x:expr),+ $(,)?) => { vec![$($crate::db::Arg::from($x)),+] };
}

pub fn v2j(v: ValueRef<'_>) -> Value {
    match v {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(i) => Value::from(i),
        ValueRef::Real(f) => Number::from_f64(f).map(Value::Number).unwrap_or(Value::Null),
        ValueRef::Text(t) => Value::String(String::from_utf8_lossy(t).into_owned()),
        ValueRef::Blob(b) => Value::String(format!("<{} bytes>", b.len())),
    }
}

impl Db {
    pub fn open(path: &str) -> Db {
        let manager = SqliteConnectionManager::file(Path::new(path)).with_init(|c| {
            c.busy_timeout(std::time::Duration::from_secs(30))?;
            let _ = c.execute_batch("PRAGMA journal_mode=WAL");
            let _ = c.execute_batch(
                "CREATE TABLE IF NOT EXISTS profiles(entity_id INTEGER PRIMARY KEY, title TEXT, description TEXT, extract TEXT, url TEXT, category TEXT, checked TEXT, found INTEGER);
                 CREATE TABLE IF NOT EXISTS emails(id INTEGER PRIMARY KEY, page_id INTEGER, doc_id INTEGER, from_raw TEXT, to_raw TEXT, cc_raw TEXT, date_raw TEXT, subject TEXT, from_id INTEGER, to_ids TEXT);",
            );
            Ok(())
        });
        let pool = Pool::builder().max_size(12).build(manager).expect("sqlite pool");
        Db { pool }
    }

    pub fn conn(&self) -> r2d2::PooledConnection<SqliteConnectionManager> {
        self.pool.get().expect("sqlite connection")
    }

    pub fn rows(&self, sql: &str, args: &[Arg]) -> rusqlite::Result<Vec<Row>> {
        let c = self.conn();
        let mut st = c.prepare_cached(sql)?;
        let names: Vec<String> = st.column_names().iter().map(|s| s.to_string()).collect();
        let mut rs = st.query(params_from_iter(args.iter()))?;
        let mut out = Vec::new();
        while let Some(r) = rs.next()? {
            let mut m = Map::with_capacity(names.len());
            for (i, n) in names.iter().enumerate() {
                m.insert(n.clone(), v2j(r.get_ref(i)?));
            }
            out.push(m);
        }
        Ok(out)
    }

    pub fn one(&self, sql: &str, args: &[Arg]) -> rusqlite::Result<Option<Row>> {
        Ok(self.rows(sql, args)?.into_iter().next())
    }

    /// COUNT(*)-style scalar: the first column of the first row as i64 (0 when empty / null)
    pub fn count(&self, sql: &str, args: &[Arg]) -> rusqlite::Result<i64> {
        let c = self.conn();
        let mut st = c.prepare_cached(sql)?;
        let mut rs = st.query(params_from_iter(args.iter()))?;
        Ok(match rs.next()? {
            Some(r) => match r.get_ref(0)? {
                ValueRef::Integer(i) => i,
                ValueRef::Real(f) => f as i64,
                _ => 0,
            },
            None => 0,
        })
    }

    pub fn execute(&self, sql: &str, args: &[Arg]) -> rusqlite::Result<usize> {
        let c = self.conn();
        c.execute(sql, params_from_iter(args.iter()))
    }
}

/// helpers to read a Row the way the Python did with r["x"]
pub fn gi(r: &Row, k: &str) -> i64 {
    match r.get(k) {
        Some(Value::Number(n)) => n.as_i64().unwrap_or_else(|| n.as_f64().unwrap_or(0.0) as i64),
        Some(Value::String(s)) => s.parse().unwrap_or(0),
        _ => 0,
    }
}
pub fn gf(r: &Row, k: &str) -> f64 {
    match r.get(k) {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0),
        _ => 0.0,
    }
}
pub fn gs(r: &Row, k: &str) -> String {
    match r.get(k) {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) | None => String::new(),
        Some(v) => v.to_string(),
    }
}
pub fn ids_csv<I: IntoIterator<Item = i64>>(ids: I) -> String {
    let v: Vec<String> = ids.into_iter().map(|i| i.to_string()).collect();
    if v.is_empty() { "-1".to_string() } else { v.join(",") }
}
pub fn qmarks(n: usize) -> String {
    std::iter::repeat("?").take(n.max(1)).collect::<Vec<_>>().join(",")
}
