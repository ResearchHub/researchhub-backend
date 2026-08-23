# ProseMirror schemas (vendored from ResearchHub/web)

Generated artifacts — **do not edit by hand**. The source of truth is the
[ResearchHub/web](https://github.com/ResearchHub/web) repo, which generates
these from the TipTap extension sets the editors actually run.

| File | Covers |
| --- | --- |
| `block-editor.json` | Notebook notes, posts (`components/Editor`) |
| `comment-editor.json` | Comments, incl. review mode (`components/Comment`) |

Load them via `utils.prosemirror.get_schema` / `parse_document`.

## Updating

When editor extensions change in the web repo (its schema export is
byte-deterministic, so a diff means a real schema change):

```bash
# in ResearchHub/web
npm run schema:export
cp schemas/prosemirror/*.json <backend>/src/utils/prosemirror/schemas/
```

Then run `utils` tests here. See `schemas/prosemirror/README.md` in the web
repo for what the export contains and its intentional deviations (DOM-only
fields stripped, permissive `doc` node, review-mode and AI-node supersets).
