import { describe, expect, it } from "vitest";

import { safeExternalUrl, splitAnswer } from "./citations";
import { LFT_CITATION, dofSource, lftSource } from "./test/fakeApi";

describe("splitAnswer", () => {
  it("turns citations of verified sources into citation parts", () => {
    const parts = splitAnswer(`Ocho horas ${LFT_CITATION}. Y el decreto ${dofSource.citation}.`, [lftSource, dofSource]);
    expect(parts.map((p) => p.kind)).toEqual(["text", "citation", "text", "citation", "text"]);
    expect(parts[1]).toMatchObject({ kind: "citation", source: lftSource });
  });

  it("matches ignoring case and spacing, like the backend", () => {
    const parts = splitAnswer("Ver [ley federal del trabajo,  Art. 61, DOF 30/11/2012].", [lftSource]);
    expect(parts[1]).toMatchObject({ kind: "citation", source: lftSource });
  });

  it("leaves unknown brackets and Markdown links as text", () => {
    const text = "Texto [no es fuente] y [enlace](https://dof.gob.mx).";
    expect(splitAnswer(text, [lftSource])).toEqual([{ kind: "text", text }]);
  });
});

describe("safeExternalUrl", () => {
  it.each([
    ["https://dof.gob.mx/nota_detalle.php?codigo=1", "https://dof.gob.mx/nota_detalle.php?codigo=1"],
    ["http://www.diputados.gob.mx/x.pdf", "http://www.diputados.gob.mx/x.pdf"],
    ["javascript:alert(1)", null],
    ["data:text/html,<script>alert(1)</script>", null],
    ["/relative/path", null],
    [null, null],
  ])("%s -> %s", (input, expected) => {
    expect(safeExternalUrl(input)).toBe(expected);
  });
});
