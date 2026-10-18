-- Study vault: notes, PDF annotations, ink, cards and tasks as synced items,
-- plus the PDF files themselves (bytes live in R2, keyed by SHA-256).

-- One row per item. Clients pick ids. updated_at is the client's edit time
-- and decides last-write-wins. seq is assigned by the server on every
-- accepted write and is strictly increasing per account, so a client can
-- pull everything it has not seen with "seq > cursor".
CREATE TABLE vault_items (
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  id         TEXT NOT NULL,
  kind       TEXT NOT NULL,
  doc_id     TEXT,
  data       TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  deleted    INTEGER NOT NULL DEFAULT 0,
  seq        INTEGER NOT NULL,
  PRIMARY KEY (account_id, id)
);
CREATE INDEX vault_items_seq ON vault_items(account_id, seq);

-- PDF files uploaded by an account. The R2 key is pdf/<account_id>/<id>.
CREATE TABLE vault_files (
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  id         TEXT NOT NULL,
  size       INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (account_id, id)
);
