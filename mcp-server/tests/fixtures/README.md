# Test fixtures

Synthetic SIDOF API payloads. Titles and texts are invented placeholders, not real DOF publications.

They copy the **structure** of real responses from `https://sidof.segob.gob.mx/dof/sidof/notas/{DD-MM-YYYY}` and `.../notas/nota/{codigo}`, as observed in November 2026: the key names, the edition grouping, and these quirks:

- `titulo` is missing on some notes.
- `tipoNota` is the literal string `"null"`.
- AVISO entries have no `codOrgaDos`, and their `pagina` is `0`.
- `cadenaContenido` holds a complete HTML 4.01 document with `<style>`, `Titulo_1` / `Titulo_2` / `Texto` / `ANOTACION` classes.
