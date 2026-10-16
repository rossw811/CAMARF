# Git history rewrite, 2026-10-15

On 2026-10-15 the repository's history was rewritten with `git filter-repo` to remove every file ever committed under
`output/` (about 36,000 files: cached yfinance price data, IBKR market data, generated results) and `graphify-out/cache/`.
Market data from these vendors may not be redistributed, and the repository is public. No WRDS, CRSP or Compustat data
was ever committed (checked: no such path in the history).

- Every commit hash changed. Hashes cited in documents written before 2026-10-15 refer to the old history; look them up
  in [`commit_map_2026-10-15.csv`](commit_map_2026-10-15.csv) (old -> new). One commit touched only removed files and has
  no new counterpart (new hash all zeros).
- Commit messages, authors, dates and every other file are unchanged. The tree at the last commit differs from the old
  one only by three small result files under `output/` (re-added in the next commit).
- A full backup of the old history is kept offline by the author (git bundle, verified).
